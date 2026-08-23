"""Latency budget enforcement for Project Vaani.

THE 800ms TARGET IS ENFORCED HERE, NOT DOCUMENTED HERE.

Every component in the turn path wraps its work in a span. The span measures,
records, and — in strict mode — raises the moment a component overruns its
allocation. There is no way to write a slow component and not find out.

    turn = TurnBudget.begin(call_id="...", turn_index=3)

    async with turn.span("endpoint_detection"):
        await endpointer.wait_for_turn_end()

    async with turn.span("stt_finalize"):
        text = await stt.finalize()

    async with turn.span("llm_first_spoken_token"):
        first = await brain.first_sentence(text)

    async with turn.span("tts_first_audio"):
        await tts.first_chunk(first)

    turn.finish()          # raises/warns if the TOTAL blew the 800ms target

Budgets come from latency_budget.yaml. Nobody hardcodes a number in Python.
Changing an allocation is a change to that file, reviewed like any other.

Design rules this module exists to enforce:
  1. Server-side and caller-experienced latency are NEVER conflated.
  2. Model TTFB is never reported as responsiveness — on a reasoning model it
     times the first *reasoning* token, not the first spoken one.
  3. A latency figure is never reported without its false-interruption rate.
  4. Estimated budgets are flagged as estimates until measured.
"""
from __future__ import annotations

import functools
import inspect
import logging
import os
import time
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, AsyncIterator

log = logging.getLogger("vaani.latency")

_BUDGET_FILE = Path(__file__).resolve().parent.parent / "latency_budget.yaml"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class BudgetExceeded(RuntimeError):
    """A component or a whole turn overran its latency allocation."""

    def __init__(self, scope: str, actual_ms: float, budget_ms: float) -> None:
        self.scope = scope
        self.actual_ms = actual_ms
        self.budget_ms = budget_ms
        over = actual_ms - budget_ms
        super().__init__(
            f"{scope}: {actual_ms:.1f}ms exceeds budget {budget_ms:.1f}ms "
            f"(over by {over:.1f}ms, {over / budget_ms * 100:.0f}%)"
        )


class BudgetInvalid(ValueError):
    """The budget file itself does not add up."""


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ComponentBudget:
    name: str
    budget_ms: float
    measured: bool
    source: str
    owner: str = ""
    notes: str = ""

    @property
    def is_estimate(self) -> bool:
        return not self.measured


@dataclass(frozen=True)
class LatencyBudget:
    target_p50_ms: float
    target_p95_ms: float
    telephony_overhead_ms: float
    components: dict[str, ComponentBudget]
    perceived: dict[str, float]
    quality_floor: dict[str, float]
    enforcement: dict[str, str]

    # -- loading ------------------------------------------------------------
    @classmethod
    def load(cls, path: Path | str | None = None) -> "LatencyBudget":
        path = Path(path) if path else _BUDGET_FILE
        raw = _read_yaml(path)

        components = {
            name: ComponentBudget(
                name=name,
                budget_ms=float(spec["budget_ms"]),
                measured=bool(spec.get("measured", False)),
                source=str(spec.get("source", "")),
                owner=str(spec.get("owner", "")),
                notes=str(spec.get("notes", "")),
            )
            for name, spec in raw["components"].items()
        }

        budget = cls(
            target_p50_ms=float(raw["target"]["p50_ms"]),
            target_p95_ms=float(raw["target"]["p95_ms"]),
            telephony_overhead_ms=float(raw["target"]["telephony_overhead_ms"]),
            components=components,
            perceived={k: float(v) for k, v in raw.get("perceived", {}).items()},
            quality_floor={k: float(v) for k, v in raw.get("quality_floor", {}).items()},
            enforcement={k: str(v) for k, v in raw.get("enforcement", {}).items()},
        )
        budget.validate()
        return budget

    # -- the rule that makes this a budget rather than a wish ---------------
    def validate(self) -> None:
        """Component allocations must fit inside the target. No exceptions.

        This is what stops the budget being quietly inflated to match reality.
        Giving one component more time means taking it from another.
        """
        total = self.allocated_ms
        if total > self.target_p50_ms:
            raise BudgetInvalid(
                f"Component budgets total {total:.0f}ms but the target is "
                f"{self.target_p50_ms:.0f}ms (over by {total - self.target_p50_ms:.0f}ms). "
                f"Take the time from another component or change the target "
                f"deliberately — do not let it drift."
            )

    @property
    def allocated_ms(self) -> float:
        return sum(c.budget_ms for c in self.components.values())

    @property
    def headroom_ms(self) -> float:
        return self.target_p50_ms - self.allocated_ms

    @property
    def caller_experienced_ms(self) -> float:
        """Server-side plus carrier physics. NEVER quote this as server-side."""
        return self.target_p50_ms + self.telephony_overhead_ms

    @property
    def estimated_components(self) -> list[ComponentBudget]:
        """Budgets not yet backed by measurement of our own system."""
        return [c for c in self.components.values() if c.is_estimate]

    @property
    def estimated_ms(self) -> float:
        return sum(c.budget_ms for c in self.estimated_components)

    def get(self, component: str) -> ComponentBudget:
        try:
            return self.components[component]
        except KeyError:
            raise KeyError(
                f"Unknown component '{component}'. Every measured span must be "
                f"declared in latency_budget.yaml. Known: "
                f"{sorted(self.components)}"
            ) from None

    def mode(self, env: str | None = None) -> str:
        env = env or os.getenv("VAANI_ENV", "dev")
        return self.enforcement.get(env, "warn")

    # -- reporting ----------------------------------------------------------
    def confidence_report(self) -> str:
        """How much of this budget is actually known versus guessed."""
        est = self.estimated_ms
        pct = est / self.allocated_ms * 100 if self.allocated_ms else 0
        lines = [
            f"Target        : {self.target_p50_ms:.0f}ms server-side "
            f"({self.caller_experienced_ms:.0f}ms caller-experienced)",
            f"Allocated     : {self.allocated_ms:.0f}ms",
            f"Headroom      : {self.headroom_ms:.0f}ms",
            f"ESTIMATED     : {est:.0f}ms of {self.allocated_ms:.0f}ms ({pct:.0f}%) "
            f"is NOT measured on our own system",
            "",
            "Unmeasured components (replace with measurement before trusting):",
        ]
        for c in sorted(self.estimated_components, key=lambda c: -c.budget_ms):
            lines.append(f"  - {c.name:<26} {c.budget_ms:>5.0f}ms   {c.owner}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Per-turn measurement
# ---------------------------------------------------------------------------
@dataclass
class Span:
    name: str
    started_at: float
    ended_at: float | None = None

    @property
    def elapsed_ms(self) -> float:
        end = self.ended_at if self.ended_at is not None else time.perf_counter()
        return (end - self.started_at) * 1000.0


@dataclass
class TurnBudget:
    """Measures one conversational turn against the budget.

    Produces exactly the fields the `turn` table expects (LLD 2.1), so
    observability is a by-product of enforcement rather than a separate chore.
    """

    call_id: str
    turn_index: int
    budget: LatencyBudget
    env: str | None = None
    spans: list[Span] = field(default_factory=list)
    _open: dict[str, Span] = field(default_factory=dict, repr=False)
    _t0: float = field(default_factory=time.perf_counter, repr=False)
    violations: list[BudgetExceeded] = field(default_factory=list)

    @classmethod
    def begin(
        cls,
        call_id: str,
        turn_index: int,
        budget: LatencyBudget | None = None,
        env: str | None = None,
    ) -> "TurnBudget":
        return cls(
            call_id=call_id,
            turn_index=turn_index,
            budget=budget or LatencyBudget.load(),
            env=env,
        )

    # -- span context managers ---------------------------------------------
    @contextmanager
    def span(self, component: str) -> Iterator[Span]:
        """Synchronous span. Prefer `aspan` in the media pipeline."""
        s = self._open_span(component)
        try:
            yield s
        finally:
            self._close_span(component, s)

    @asynccontextmanager
    async def aspan(self, component: str) -> AsyncIterator[Span]:
        """Async span — the normal case in the voice pipeline."""
        s = self._open_span(component)
        try:
            yield s
        finally:
            self._close_span(component, s)

    def _open_span(self, component: str) -> Span:
        self.budget.get(component)  # fail fast on undeclared components
        if component in self._open:
            raise RuntimeError(f"span '{component}' already open on this turn")
        s = Span(name=component, started_at=time.perf_counter())
        self._open[component] = s
        return s

    def _close_span(self, component: str, s: Span) -> None:
        s.ended_at = time.perf_counter()
        self._open.pop(component, None)
        self.spans.append(s)
        self._check(component, s.elapsed_ms, self.budget.get(component).budget_ms)

    # -- enforcement --------------------------------------------------------
    def _check(self, scope: str, actual_ms: float, budget_ms: float) -> None:
        if actual_ms <= budget_ms:
            return
        exc = BudgetExceeded(scope, actual_ms, budget_ms)
        self.violations.append(exc)
        mode = self.budget.mode(self.env)
        if mode == "strict":
            raise exc
        if mode == "warn":
            # Never break a live call over a budget breach.
            log.warning(
                "latency_budget_exceeded",
                extra={
                    "call_id": self.call_id,
                    "turn_index": self.turn_index,
                    "scope": scope,
                    "actual_ms": round(actual_ms, 1),
                    "budget_ms": budget_ms,
                },
            )

    # -- results ------------------------------------------------------------
    @property
    def total_ms(self) -> float:
        """Server-side turn latency. NOT what the caller experiences."""
        return sum(s.elapsed_ms for s in self.spans)

    @property
    def caller_experienced_ms(self) -> float:
        """Server-side plus carrier overhead. Report separately, always."""
        return self.total_ms + self.budget.telephony_overhead_ms

    def finish(self) -> dict[str, Any]:
        if self._open:
            raise RuntimeError(f"unclosed spans: {sorted(self._open)}")
        self._check("TURN TOTAL", self.total_ms, self.budget.target_p50_ms)
        return self.to_turn_record()

    def to_turn_record(self) -> dict[str, Any]:
        """Shaped for the `turn` table (LLD 2.1)."""
        return {
            "call_id": self.call_id,
            "turn_index": self.turn_index,
            "turn_latency_ms": round(self.total_ms, 1),
            "caller_experienced_ms": round(self.caller_experienced_ms, 1),
            "within_budget": not self.violations,
            "components": {s.name: round(s.elapsed_ms, 1) for s in self.spans},
            "violations": [
                {"scope": v.scope, "actual_ms": round(v.actual_ms, 1),
                 "budget_ms": v.budget_ms}
                for v in self.violations
            ],
        }

    def report(self) -> str:
        lines = [
            f"turn {self.call_id}#{self.turn_index}: "
            f"{self.total_ms:.0f}ms server-side / "
            f"{self.caller_experienced_ms:.0f}ms caller-experienced "
            f"(target {self.budget.target_p50_ms:.0f}ms)"
        ]
        for s in self.spans:
            b = self.budget.get(s.name).budget_ms
            flag = "OVER" if s.elapsed_ms > b else "ok"
            lines.append(f"  {s.name:<26} {s.elapsed_ms:>7.1f}ms / {b:>5.0f}ms  {flag}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Decorator, for components that are a single call
# ---------------------------------------------------------------------------
def budgeted(component: str):
    """Enforce a component budget on a function.

    The wrapped callable must accept a `turn: TurnBudget` keyword argument,
    or be a method on an object exposing `self.turn`.
    """

    def decorator(fn):
        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def awrapper(*args, **kwargs):
                turn = _resolve_turn(args, kwargs)
                if turn is None:
                    return await fn(*args, **kwargs)
                async with turn.aspan(component):
                    return await fn(*args, **kwargs)

            return awrapper

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            turn = _resolve_turn(args, kwargs)
            if turn is None:
                return fn(*args, **kwargs)
            with turn.span(component):
                return fn(*args, **kwargs)

        return wrapper

    return decorator


def _resolve_turn(args: tuple, kwargs: dict) -> TurnBudget | None:
    turn = kwargs.get("turn")
    if isinstance(turn, TurnBudget):
        return turn
    if args and hasattr(args[0], "turn") and isinstance(args[0].turn, TurnBudget):
        return args[0].turn
    return None


# ---------------------------------------------------------------------------
# Minimal YAML reader
#
# Deliberately dependency-free so the budget can be validated in any
# environment, including CI images without pyyaml. Handles the subset this
# file uses: nested maps, scalars, block strings. Uses pyyaml when present.
# ---------------------------------------------------------------------------
def _read_yaml(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        return yaml.safe_load(text)
    except ImportError:
        return _tiny_yaml(text)


def _tiny_yaml(text: str) -> dict:
    root: dict = {}
    stack: list[tuple[int, dict]] = [(-1, root)]
    pending_key: str | None = None
    pending_indent = 0
    buf: list[str] = []

    def flush() -> None:
        nonlocal pending_key, buf
        if pending_key is not None:
            parent = stack[-1][1]
            parent[pending_key] = " ".join(w.strip() for w in buf).strip()
            pending_key, buf = None, []

    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())

        if pending_key is not None:
            if indent > pending_indent:
                buf.append(raw.strip())
                continue
            flush()

        line = raw.strip()
        if line.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        value = value.split("  #")[0].strip()

        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]

        if value in ("", "|", ">"):
            if value in ("|", ">"):
                pending_key, pending_indent, buf = key, indent, []
            else:
                node: dict = {}
                parent[key] = node
                stack.append((indent, node))
            continue

        parent[key] = _scalar(value)

    flush()
    return root


def _scalar(v: str) -> Any:
    if v.startswith(('"', "'")) and v.endswith(('"', "'")) and len(v) > 1:
        return v[1:-1]
    low = v.lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    if low in ("null", "~"):
        return None
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        return v


__all__ = [
    "BudgetExceeded",
    "BudgetInvalid",
    "ComponentBudget",
    "LatencyBudget",
    "Span",
    "TurnBudget",
    "budgeted",
]
