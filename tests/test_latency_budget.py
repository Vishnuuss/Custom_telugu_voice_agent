"""CI gates for the 800ms latency budget.

These tests are the reason the target is a constraint rather than an aspiration.
If they pass, the budget adds up and enforcement works. If someone inflates a
component allocation to make their slow code fit, the build fails here.
"""
from __future__ import annotations

import asyncio
import time

import pytest

from vaani.latency import (
    BudgetExceeded,
    BudgetInvalid,
    LatencyBudget,
    TurnBudget,
    budgeted,
)


@pytest.fixture(scope="module")
def budget() -> LatencyBudget:
    return LatencyBudget.load()


# ---------------------------------------------------------------------------
# The budget file itself
# ---------------------------------------------------------------------------
def test_target_is_800ms(budget):
    """The number. If this changes, it was a deliberate decision."""
    assert budget.target_p50_ms == 800


def test_components_fit_inside_the_target(budget):
    """You cannot give one component more time without taking it from another."""
    assert budget.allocated_ms <= budget.target_p50_ms, (
        f"components total {budget.allocated_ms}ms, target is "
        f"{budget.target_p50_ms}ms"
    )


def test_inflating_a_component_fails_validation(tmp_path):
    """Proves the gate actually bites."""
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "target:\n"
        "  p50_ms: 800\n"
        "  p95_ms: 1200\n"
        "  telephony_overhead_ms: 490\n"
        "components:\n"
        "  endpoint_detection:\n"
        "    budget_ms: 700\n"
        "    measured: false\n"
        "  tts_first_audio:\n"
        "    budget_ms: 400\n"
        "    measured: true\n",
        encoding="utf-8",
    )
    with pytest.raises(BudgetInvalid, match="over by"):
        LatencyBudget.load(bad)


def test_every_component_declares_whether_it_is_measured(budget):
    for c in budget.components.values():
        assert isinstance(c.measured, bool)
        assert c.source, f"{c.name} has no source — where did the number come from?"


def test_tts_budget_reflects_measurement_not_vendor_claim(budget):
    """Regression guard.

    This budget was once 60ms, taken from a vendor claim of ~40ms TTFA.
    Independent measurement puts Cartesia Sonic-3 at 188ms. If someone drops
    this back toward the vendor number, they must justify it here.
    """
    tts = budget.get("tts_first_audio")
    assert tts.measured is True
    assert tts.budget_ms >= 150, (
        "TTS budget below the measured floor of ~155ms. Vendor claims are not "
        "measurements — see AGENTS.md Rule 7."
    )


def test_caller_experienced_is_not_the_server_side_number(budget):
    """Rule 4. The two numbers must never collapse into one."""
    assert budget.telephony_overhead_ms > 0
    assert budget.caller_experienced_ms == pytest.approx(
        budget.target_p50_ms + budget.telephony_overhead_ms
    )


def test_telugu_silence_floor_is_protected(budget):
    """Rule 6. Callers protested at 350ms. 600ms is the floor."""
    assert budget.quality_floor["min_endpoint_silence_ms_telugu"] >= 600


def test_one_word_telugu_turns_must_register(budget):
    """అవును / వద్దు / ఆ are complete answers."""
    assert budget.quality_floor["min_turn_words"] == 1


# ---------------------------------------------------------------------------
# Runtime enforcement
# ---------------------------------------------------------------------------
def test_span_within_budget_passes(budget):
    turn = TurnBudget.begin("call-1", 0, budget=budget, env="dev")
    with turn.span("transport"):
        pass
    assert not turn.violations


def test_span_over_budget_raises_in_dev(budget):
    turn = TurnBudget.begin("call-2", 0, budget=budget, env="dev")
    with pytest.raises(BudgetExceeded) as e:
        with turn.span("transport"):          # 50ms budget
            time.sleep(0.12)
    assert e.value.scope == "transport"
    assert e.value.actual_ms > 50


def test_span_over_budget_only_warns_in_prod(budget):
    """A caller is on the line. Never break a live call over a budget breach."""
    turn = TurnBudget.begin("call-3", 0, budget=budget, env="prod")
    with turn.span("transport"):
        time.sleep(0.12)
    assert len(turn.violations) == 1
    assert turn.violations[0].scope == "transport"


def test_undeclared_span_is_rejected(budget):
    """You cannot add a pipeline stage without giving it a budget."""
    turn = TurnBudget.begin("call-4", 0, budget=budget, env="dev")
    with pytest.raises(KeyError, match="Unknown component"):
        with turn.span("some_new_thing_i_invented"):
            pass


def test_turn_total_is_checked_on_finish(budget):
    turn = TurnBudget.begin("call-5", 0, budget=budget, env="prod")
    for name in ("endpoint_detection", "stt_finalize", "llm_first_spoken_token",
                 "tts_first_audio", "transport"):
        with turn.span(name):
            pass
    record = turn.finish()
    assert record["within_budget"] is True
    assert record["turn_latency_ms"] < 800


def test_unclosed_span_is_an_error(budget):
    turn = TurnBudget.begin("call-6", 0, budget=budget, env="dev")
    turn._open_span("transport")
    with pytest.raises(RuntimeError, match="unclosed spans"):
        turn.finish()


def test_turn_record_matches_the_turn_table_shape(budget):
    turn = TurnBudget.begin("call-7", 3, budget=budget, env="prod")
    with turn.span("stt_finalize"):
        pass
    rec = turn.to_turn_record()
    for key in ("call_id", "turn_index", "turn_latency_ms",
                "caller_experienced_ms", "within_budget", "components"):
        assert key in rec
    assert rec["caller_experienced_ms"] > rec["turn_latency_ms"]


def test_async_span(budget):
    async def run():
        turn = TurnBudget.begin("call-8", 0, budget=budget, env="dev")
        async with turn.aspan("stt_finalize"):
            await asyncio.sleep(0)
        return turn

    turn = asyncio.run(run())
    assert not turn.violations
    assert turn.spans[0].name == "stt_finalize"


def test_budgeted_decorator_async(budget):
    class FakeStt:
        def __init__(self, turn):
            self.turn = turn

        @budgeted("stt_finalize")
        async def finalize(self):
            return "అవును"

    async def run():
        turn = TurnBudget.begin("call-9", 0, budget=budget, env="dev")
        stt = FakeStt(turn)
        text = await stt.finalize()
        return turn, text

    turn, text = asyncio.run(run())
    assert text == "అవును"
    assert [s.name for s in turn.spans] == ["stt_finalize"]


# ---------------------------------------------------------------------------
# Honesty
# ---------------------------------------------------------------------------
def test_confidence_report_names_the_estimates(budget):
    """Rule 7. We stay honest about how much of this is guesswork."""
    report = budget.confidence_report()
    assert "ESTIMATED" in report
    assert budget.estimated_ms > 0, (
        "If nothing is estimated any more, that is excellent — update this test."
    )
    for c in budget.estimated_components:
        assert c.name in report


def test_endpoint_detection_is_flagged_as_the_biggest_unknown(budget):
    """The single largest risk in the budget must not be silently marked done."""
    ep = budget.get("endpoint_detection")
    if ep.measured:
        pytest.skip("Telugu turn detector now measured — update this gate")
    assert ep.budget_ms == max(c.budget_ms for c in budget.estimated_components)
