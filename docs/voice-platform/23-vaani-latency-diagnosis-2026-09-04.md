# Where the latency actually goes — measured on real calls

**4 September 2026 · Project Vaani · all agents**

The client: *"latency is the main thing, people will leave, I need 700ms, it has
3 sec latency in loan."*

This is the measurement. No estimates.

---

## The measurement exists already — no audio needed

Every run record carries a per-turn breakdown. `python tools/vaani_runs.py
--run <id>` prints it. Earlier attempts to measure latency used
`true_latency.py`, which needs separated `user.wav` / `bot.wav` recordings and
fails on recent runs — but that whole detour was unnecessary. The numbers were
in the run log all along.

`TOTAL = endpoint + LLM + TTS`. STT is shown in brackets because it runs inside
the endpoint window, not after it.

---

## Real calls, real numbers

### wf2 — MB Solar, run 392, a 167-second call, 19 turns

| | avg | budget | verdict |
|---|---|---|---|
| **TOTAL** | **1.119 s** | 800 ms | **319 ms over** |
| endpoint | 0.523 s | 250 ms | **2.1x over** |
| LLM | 0.527 s | 200 ms | **2.6x over** |
| TTS | 0.069 s | 190 ms | **121 ms UNDER** |
| (STT, inside endpoint) | 0.415 s | 100 ms | **4.2x over** |

p50 TOTAL **1.096 s**, max 1.495 s.

### wf3 — Loan, run 377, 5 turns

| | avg |
|---|---|
| TOTAL | **1.006 s** |
| endpoint | 0.411 s |
| LLM | 0.530 s |
| TTS | 0.065 s |
| (STT) | 0.359 s |

p50 TOTAL **1.078 s**, max 1.277 s.

### wf4 — Solar campaign, run 400, 4 turns

| turn | TOTAL | endpoint | LLM | TTS |
|---|---|---|---|---|
| 1 | **2.094** | 1.443 | 0.587 | 0.064 |
| 2 | 0.656 | 0.385 | 0.204 | 0.067 |
| 3 | 1.258 | 0.653 | 0.534 | 0.071 |
| 4 | 1.301 | 0.686 | 0.542 | 0.073 |

---

## What this says

**1. It is not 3 seconds, and it is not 700 ms either.**
Server-side p50 is **1.0–1.1 s** on every agent measured. Add the carrier's
490 ms, which `latency_budget.yaml` marks *"NOT engineerable"*, and the caller
hears about **1.5 s**.

**The 3-second experience is real, but it is the FIRST turn.** Run 400's opening
turn was 2.094 s server-side — 2.6 s to the caller — because the first endpoint
decision took 1.443 s against a 0.4–0.7 s steady state. First impressions are
made on exactly that turn.

**2. All agents are the same.** MB Solar 1.096, loan 1.078, solar campaign
similar. Confirmed: all five workflows carry identical latency configuration
(`llm_hedge 2`, `smart_turn_stop_secs 0.2`, `turn_start_min_words 3`,
`turn_stop_strategy turn_analyzer`). There is no per-agent latency bug. **This
is a platform problem, and a platform fix reaches every agent.**

**3. TTS is not the problem and never was.** 69 ms against a 190 ms budget.
Cartesia is giving back 121 ms. Leave it alone.

**4. The two things over budget are the LLM and the endpoint** — and inside the
endpoint, it is STT.

---

## The real culprit: STT finalisation

The endpoint window averages 523 ms, and **415 ms of it is STT finalisation**
against a 100 ms budget. Waiting for the final transcript is the single largest
hidden cost in the system.

The config asks for `stt_finalisation_budget_secs: 0.2`. The measurement is
0.415. **The budget is not being honoured** — that gap alone is 215 ms.

---

## The path to target, in milliseconds

| Component | now | budget | saving |
|---|---|---|---|
| LLM | 527 | 200 | **−327** |
| endpoint (mostly STT) | 523 | 250 | **−273** |
| TTS | 69 | 190 | +0 (already under) |
| **TOTAL** | **1,119** | **800** | **−600 available** |

Land both and the server side is about **520 ms — comfortably inside the 800 ms
target**, with the caller hearing roughly **1.0 s** instead of 1.5 s, and the
first turn dropping from 2.6 s to about 1.2 s.

### Lever 1 — the LLM, −327 ms
`latency_budget.yaml` states the requirement outright: *"Requires a
NON-REASONING model. A reasoning model cannot fit this."* The system runs
`openai/gpt-oss-120b`, a reasoning model, at `reasoning_effort=low`. Hedging
already rescued the p90 (0.355 s p50 hedged vs 0.517 s single), so the remaining
saving needs a different model, not more tuning of this one.

The route is **distillation** — fine-tune a small non-reasoning model on the
agent's own calls. The harvest already reports `distillation / SFT — 3,810 —
READY`. The data is collected.

**This is NOT reinforcement learning.** RL trains word choice; it cannot make
the system notice a caller stopped talking, and it will not reduce latency. The
313 preference pairs are worth using for QUALITY, separately.

**The loan agent has 1,095 runs — by far the largest corpus. Train there first,
not on MB Solar's 50.**

### Lever 2 — STT finalisation, −273 ms
Find out why 0.2 s is configured and 0.415 s is measured, and close it. Options
worth measuring before choosing: a faster realtime STT path
(`probe_sarvam_realtime.py` exists for this), endpointing on the partial
transcript rather than waiting for the final, and cutting the first-turn
endpoint outlier specifically.

### Not a lever
`speculation_enabled` and `context_compaction_enabled` are both off. The record
says speculation *"has never replayed a single response"*. Do not expect a win
there.

---

## About the 700 ms number

Your own budget targets **800 ms server-side**, and records
`caller_p50_ms: 1290` as what the caller hears when that target is met, because
490 ms belongs to the phone network.

So **700 ms as the caller experiences it is not physically available** on a
phone call. 700 ms server-side is below the system's own design target and
would require beating the budget in every component simultaneously.

What IS available, and what should be committed to: **caller-perceived latency
from ~1.5 s down to ~1.0 s, and the first turn from ~2.6 s to ~1.2 s.** That is
the difference people actually hang up over.

---

## Order of work

1. **STT finalisation** — biggest gap against its own budget (4.2x), and it is
   configuration and code, not training. Fastest win.
2. **The first-turn endpoint outlier** — 1.443 s against a 0.4–0.7 s steady
   state. It is one turn, and it is the one that decides the call.
3. **Distil a non-reasoning model** on the loan agent's 1,095 calls.
4. Re-measure after each, from the run records.

Everything here is platform-level. Every agent, including every future one,
gets it.
