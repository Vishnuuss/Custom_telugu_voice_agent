# Latency plan — what shipped, what did not, and why

**5 September 2026 · Project Vaani · all five agents**

An audit of every item in `25-latency-plan-2026-09-05`, against what is actually
running. Nothing here is claimed without a measurement or a stated reason.

---

## Result

**Per-turn latency on a real call: 1,096 ms → 877 ms (p50).**
Measured on wf2, run 392 before against run 776 after, 14 turns.

| | run 392 | run 776 |
|---|---|---|
| **p50 TOTAL** | 1.096 s | **0.877 s** |
| endpoint (mean) | 0.523 | 0.473 |
| LLM | 0.527 | 0.351 |
| TTS first audio | 0.069 | 0.106 |

TTS first-audio *rising* while TOTAL falls is the signature of token streaming
working: it now covers a short opening chunk instead of being clocked from a
whole buffered sentence, so it measures less of the turn than before.

Run 776 also completed a full qualification — property type, bill (15,000),
location, roof, name, and a decision — so the speed did not cost the outcome.

---

## Phase 0 — COMPLETE

| Item | Status | Evidence |
|---|---|---|
| 0a `stt_finalisation_budget_secs` 0.45 → 0.2 | **No-op. Already 0.2 on all five.** | The 250 ms "dead timer" is `max(0, 0.2−0.2) = 0`. It never existed. **No saving claimed.** |
| 0b Cartesia token streaming | **SHIPPED, verified, now DEFAULT** | Run 776. `DEFAULT_TTS_TOKEN_STREAMING = True`, enabled on all five |
| 0c `llm_hedge` 2 → 3 | **SHIPPED on all five** | Measured wf3, 3 runs each way: 1.42/1.31/1.43 vs 1.34/1.35/1.40 — **~50 ms, inside noise.** Not the 328 ms the old bench claimed. Kept because it is the code's own default and the tail is better; **no p50 win claimed.** |

---

## Phase 1 — COMPLETE, and it immediately changed a conclusion

`text_aggregation_secs` now persists in `rtf-latency-breakdown`, and
`tools/vaani_runs.py` prints the endpoint distribution and any unaccounted time.

**The first thing it showed, on run 776:**

```
endpoint spread: min 0.378  p50 0.390  max 1.139   under 0.6s: 13/14
```

**The endpoint p50 is 0.390 s, not the 0.523 s mean quoted all week.** The mean
was dragged up entirely by turn 1. Thirteen of fourteen turns were under 0.6 s.

That reframes the remaining gap: **at p50 the server side is 877 ms against an
800 ms budget — 77 ms over, not 319 ms.** Most of the endpoint work the plan
contemplated is aimed at a problem that is smaller than the mean implied.

Turn 1 is the outlier (endpoint 1.139 s). That is **not** the cold prompt cache —
`prewarm.py` already handles the LLM side and turn 1's LLM was a normal 0.488 s.
It is `MIN_CONFIDENT_TURN_S = 0.65`: a one-word "హలో" is shorter than that, so
the detector demands near-certainty (0.995) before ending the turn. That is the
rule that stops callers being cut off mid-sentence. **It is a deliberate safety
cost on the shortest utterance, not a defect.**

---

## Phase 2

### 2b — Two landmines. SHIPPED.
- **`PartialResponder` pushed the promoted transcript UPSTREAM**, toward the
  STT, where nothing consumes it — and set `_promoted`, suppressing the genuine
  final. Fixed to always push DOWNSTREAM.
- **Speculation now FAILS CLOSED.** It generated from
  `compose_system_prompt_for_node` with `get_state_block=lambda: ""` — a hit
  would have spoken a reply with no answer-first rule, no two-ask cap and no
  repeat guard. It now refuses to build; the call site catches and logs.

### 2a — Realtime STT. ATTEMPTED, BROKE PRODUCTION, REVERTED.

Switched to `saaras:v3-realtime`. Runs 779 and 780 immediately after:

| run | result |
|---|---|
| 779 | **captured nothing** — no variables, no nodes visited |
| 780 | **p50 3.573 s**, one turn at **5.150 s**, LLM alone 3.668 s |

Run 780's user transcript is the word **"హలో" repeated twenty-two times.** The
caller said it once. The realtime model emits a partial per fragment; each was
becoming its own turn, and the LLM was re-reading a context full of duplicates.

**The ordering in the plan was right and my reasoning about it was wrong.** 2b
before 2a was correct — but before that fix, `PartialResponder` pushed upstream
into a dead end. **It was harmless because it was broken.** Fixing it made it
live, in the same session that first gave it partials to act on. Two changes
each defensible alone; together they turned every partial into a turn.

Reverted with `set_stt_config.py --model "saarika:v2.5" --apply`. With no
interims the partial path is inert again, so the code fix is harmless where it
sits.

**Before this is attempted again, all three must hold:**
1. `PartialResponder` must promote **at most once per turn**. Its logic assumes
   an STT emitting one final, not twenty partials.
2. `SarvamRealtimeSTTService` sets `frame.finalized = True`, opening a different
   branch in `TurnAnalyzerUserTurnStopStrategy._handle_transcription`. Unexamined,
   and a second candidate for the 22 turns.
3. **It cannot be piloted.** STT is an ORGANISATION-level setting, not
   per-workflow — the plan assumed otherwise. Any retry moves all five agents at
   once, so it needs a test call booked in advance and an immediate revert ready.

### 2c — LLM turn completion. NOT DONE. BLOCKED BY 2a.
The architecture from the client's transcript — the LLM polled while the caller
is still speaking, emitting ✓ / ○ / ◐ instead of a reply — requires interim
transcripts to poll against. `saarika:v2.5` emits none. **2c cannot be built
until 2a works.** Building it now would produce untestable code sitting behind a
switch that is off.

### 2d — Throttle the detector's CPU. NOT DONE, and RECOMMENDED AGAINST for now.
`_probability()` costs ~5–7 ms and runs on every 20 ms frame during silence —
~53 ms per turn of event-loop occupancy. The plan already said this is a
**concurrency** win, not a p50 win.

Phase 1 removed most of its remaining case: the endpoint p50 is 0.390 s, which
is close to its 250 ms budget, and current call volume is a handful per day, so
event-loop contention is not the binding constraint. It touches the one
component that stops callers being cut off. **Marginal benefit against real
risk — not worth doing now.** Revisit when concurrent call volume rises.

---

## Where the remaining 77 ms sits

At p50, on a real call: endpoint 0.390 + LLM ~0.35 + TTS ~0.106 ≈ 0.85 s against
the 800 ms budget.

- **TTS** is 106 ms against a 190 ms budget — under, nothing to win.
- **Endpoint** is 390 ms against 250 ms. Closing it means the realtime STT path
  (2a) or a faster detector verdict — and the repo's own sweep shows deciding
  earlier makes calls *slower* on average and spends against the 2 %
  false-interruption floor.
- **LLM** is ~350 ms against 200 ms. Closing it needs a non-reasoning model,
  which this Groq account does not offer, or 2c.

**Both remaining routes run through 2a.** That is the honest bottleneck.

## And the number that does not move
`telephony_overhead_ms: 490`, marked *"NOT engineerable"* in
`latency_budget.yaml`. At the measured 877 ms the caller hears about **1.37 s**.
At a perfect 800 ms they would hear 1.29 s. **700 ms at the caller's ear is not
available on a phone line**, and no amount of the work above changes that.

---

## Regression — nothing destroyed

Checked after **every** change, by diffing the failure list before and after:

- **414 tests pass, zero new failures.** The 10 failures in
  `test_vaani_filler_cover` are pre-existing and fail identically with every
  change reverted.
- `vaani_eval` wf2: **18/25, 9 hard — twice, identical.**
- Behaviour probes on all five agents: answers the caller's question, then asks
  its own; answers off-topic questions; remembers across turns; no false repair
  lines.

Two suites can only run in CI on this machine: `test_partial_response.py` needs
`pytest-asyncio` and the Cartesia factory tests need `google.genai`. Neither is
installed here, and that gap is part of why the 2a failure was not caught before
a live call.
