# AGENTS.md — Project Vaani

**Read this before writing a single line of code in this repository.**
This file is the contract. It applies to every contributor, human or AI.

---

# RULE 1 — 800 MILLISECONDS

> **Every turn must complete in ≤800 ms server-side.**
> Endpoint decision → first audio byte out.
> This is not a goal. It is a constraint. Code that breaks it does not ship.

If you are an AI agent and you take one thing from this file, take this:
**every design choice you make in this repository is subordinate to the 800 ms
budget.** Before you propose a library, a network hop, a model, a retry, a
serialization format, or an abstraction layer — ask what it costs in
milliseconds and where that time comes from.

There is no spare time. See Rule 2.

---

# RULE 2 — THE BUDGET IS FULLY ALLOCATED

`latency_budget.yaml` is the single source of truth. Current allocation:

| Component | Budget | Measured? |
|---|---|---|
| `endpoint_detection` | 250 ms | ✗ estimate |
| `stt_finalize` | 100 ms | ✗ estimate |
| `llm_first_spoken_token` | 200 ms | ✗ estimate |
| `tts_first_audio` | 190 ms | ✓ measured |
| `transport` | 50 ms | ✗ estimate |
| **Total** | **790 ms** | |
| **Headroom** | **10 ms** | **1.25%** |

**You cannot add work to the turn path without taking time from something
else.** CI enforces this: if component budgets sum above the target, the build
fails. There is nowhere to hide a slow call.

---

# RULE 3 — MEASURE EVERY SPAN

No component in the turn path runs unmeasured.

```python
from vaani import TurnBudget

turn = TurnBudget.begin(call_id=call.id, turn_index=n)

async with turn.aspan("endpoint_detection"):
    await endpointer.wait_for_turn_end()

async with turn.aspan("stt_finalize"):
    text = await stt.finalize()

async with turn.aspan("llm_first_spoken_token"):
    sentence = await brain.first_sentence(text)

async with turn.aspan("tts_first_audio"):
    await tts.first_chunk(sentence)

record = turn.finish()   # raises in dev/CI if the turn blew the budget
```

Spans must name a component declared in `latency_budget.yaml`. An undeclared
span name raises immediately — you cannot invent a new stage of the pipeline
without giving it a budget.

In `dev` and `ci`, overruns **raise `BudgetExceeded`**.
In `staging` and `prod`, they log a violation. **Never break a live call over a
budget breach** — a caller is on the line.

---

# RULE 4 — NEVER CONFLATE THE TWO LATENCY NUMBERS

| Number | Meaning |
|---|---|
| **Server-side** | Endpoint decision → first audio out. **This is the 800 ms.** |
| **Caller-experienced** | Server-side **+ ~490 ms** of carrier transit, jitter buffer, codec. |

The caller hears **~1,290 ms**. That 490 ms is carrier physics. It is measured,
never optimised, and never engineered away.

**Reporting one as the other is a defect.** Every report shows both.

For calibration — real phone-call measurements of commercial platforms
(caller-experienced p50): Telnyx 1,296 ms · ElevenLabs 1,424 ms · Bland
1,520 ms · Vapi 1,558 ms · Retell 1,740 ms. **No platform is sub-second.**
Hitting 800 ms server-side means matching the best measured system in the
industry — in Telugu, which none of them do.

---

# RULE 5 — TTFB IS NOT RESPONSIVENESS

Never report model time-to-first-byte as latency.

On a reasoning model, TTFB times the first **reasoning** token, not the first
token that becomes speech. On the incumbent system this read 0.09 s against a
real 1.95 s turn — wrong by more than an order of magnitude, and it cost days
of misdirected debugging.

Measure `llm_first_spoken_token`. Nothing else.

**Corollary:** a reasoning model cannot fit a 200 ms budget. Use a
non-reasoning model. The old objection — that fast models couldn't handle node
transitions — was a defect of the *graph* execution model, and this framework
has no graph.

---

# RULE 6 — A LATENCY WIN BOUGHT WITH INTERRUPTIONS IS NOT A WIN

Faster endpointing causes the agent to cut callers off.

This is not hypothetical. At 350 ms endpointing, real callers on the incumbent
system repeatedly protested: *"ఎందుకు కట్ చేస్తున్నావ్?"* — "why do you keep
cutting me off?"

**Every latency figure is reported with its false-interruption rate.** A change
that improves latency and worsens interruptions is a regression, and CI treats
it as one.

Hard floors in `quality_floor`:
- Silence-threshold endpointing: **never below 600 ms for Telugu** without a
  semantic turn detector
- `min_turn_words`: **1** — one-word Telugu replies (అవును, వద్దు, ఆ) must
  register as turns

---

# RULE 7 — HONEST NUMBERS ONLY

`latency_budget.yaml` marks each component `measured: true` or `false`.

**Right now, 600 ms of the 790 ms allocation is estimated, not measured.** Only
`tts_first_audio` is backed by independent measurement of a real system.

If you measure a component on our own audio, update `source:` and set
`measured: true`. **Do not set `measured: true` for a vendor's published
number.** Vendor figures are systematically optimistic — the TTS budget in this
file moved from 60 ms to 190 ms when a vendor claim of ~40 ms was replaced with
an independent measurement of 188 ms.

Run `python -m vaani.check --confidence` to see how much of the budget is
currently guesswork.

---

# RULE 8 — THE TELUGU CONSTRAINT

This framework's target language is **Telugu**, and that changes the engineering:

- **LiveKit's turn detector does not support Telugu.** It covers 14 languages
  including Hindi. A Telugu turn detector must be fine-tuned. Until it exists,
  endpointing runs hybrid and the realistic floor is ~1,000 ms, not 800 ms.
- **Telugu tokenises expensively** — 350–480 completion tokens per reply.
  Throughput matters more than it would for English. Shortening *spoken output*
  pays; shortening *instructions* does not.
- **No public benchmark measures Telugu latency for any provider.** Every
  vendor figure in this repo is English-derived. Measure on our own corpus.
- **Never assume English behaviour.** Pauses, turn-taking and phrasing differ.

---

# RULE 9 — DESIGN RULES THAT PROTECT THE BUDGET

| Do | Don't |
|---|---|
| Stream everything — start speaking on the first sentence | Wait for full generation |
| Keep the Brain in-process | Add a network hop to the turn path |
| Overlap TTS with generation | Sequence them |
| Emit a backchannel within 200 ms | Let the caller hear silence |
| Put providers behind ports | Hardcode a vendor |
| Co-locate with providers | Cross an ocean three times per turn |
| Cancel TTS mid-stream on barge-in | Let the agent talk over the caller |

Any new network call in the turn path needs an explicit budget line and time
taken from another component. Say so in the PR.

---

# RULE 10 — SAFETY RULES THAT OUTRANK LATENCY

Latency never justifies breaking these:

1. **Never dial a suppressed number.** Every origination path passes the dial
   gate chain — including manual test calls.
2. **Dry-run is the default** for anything with real-world effect. Campaigns
   place real, billed calls to real people.
3. **Secrets live in environment variables**, never in code, config artefacts,
   or git.
4. **Provider faults are their own error class.** A 429/402/401 is never
   recorded as a call outcome — that mistake cost days of misdiagnosis twice.
5. **Never train on recordings without `training_use_permitted`.**

---

## Layout

```
latency_budget.yaml     THE constraint. Single source of truth.
vaani/latency.py        Runtime enforcement. Read before writing pipeline code.
tests/                  CI gates, including budget validation.
docs/voice-platform/    Full SDLC set. Doc 09 is the latency plan.
tools/                  Operational scripts for the incumbent system.
```

## Before you open a PR

- [ ] Every new turn-path stage has a span and a budget line
- [ ] `pytest tests/` passes, including `test_latency_budget.py`
- [ ] Latency claims quote server-side **and** caller-experienced
- [ ] Latency claims are paired with a false-interruption figure
- [ ] No vendor number marked `measured: true`
- [ ] No secrets, no customer phone numbers

---

**If a change makes the agent faster but worse, it is not an improvement.
If a change makes it faster but interrupts callers, it is a regression.
The 800 ms exists to make the agent feel human — not to win a benchmark.**
