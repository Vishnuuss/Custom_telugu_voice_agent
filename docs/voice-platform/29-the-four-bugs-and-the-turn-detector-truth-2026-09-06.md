# The four bugs behind "worst agent", and the truth about turn detection

**6 September 2026 · Project Vaani**

The client tested MB Solar and reported five things: it loops, it skips
questions, it does not listen, it sounds robotic, and the latency is still
wrong. Two call logs — runs 803 and 804 — were read before any code was
touched. **Every complaint is reproduced in them, and the caller complains out
loud on both calls.**

Two of the client's own diagnoses were checked and are correct. They are quoted
here because they were better than the ones being worked from.

---

## 1. The evidence

### Run 804 — the skip
```
BOT : మీ నెల బిల్లు ఎంత వస్తుంది?        ask #1
USER: వచ్చేసి                             still assembling the sentence
BOT : మీరు ఏ ఏరియాలో ఉంటున్నారు?         MOVED ON
USER: ఏం బిల్ చెప్పలా ఏదో                 "I didn't say the bill"
BOT : సరే, మీ కరెంట్ బిల్లు నెలకి ఎంత?     ask #2
USER: నేను చెప్పలే కదా ఎందుకు ముందుకు పోతున్నావ్?
BOT : మీకు సొంత రూఫ్ ఉందా?                MOVED ON — bill abandoned
USER: బిల్లు తెలుసుకోలేదు కదా, మరి నెక్స్ట్ క్వశ్చన్ ఏమి పోయినారు?
```
Saved lead: `monthly_bill: null`, `location: null`, `customer_name: null`.
**Three of six fields lost on one call.**

### Run 803 — the loop
Seven byte-identical replies after the booking. The caller said goodbye four
times and finally asked *"బాయ్ బాయ్ కట్ చేస్తారా మీరు"* — will you hang up? —
because the agent would not. 187 s, the last minute pure loop.

---

## 2. One cause behind loop, skip and not-listening

The client: *"my question is not reaching the LLM, that is why it is looping and
why it is not answering."* Near enough, and here is the mechanism.

`StateInjector._refresh()` hands the model:

```
[system: personality + knowledge]
[... the conversation, including what the caller just said ...]
[system: A STATE BLOCK]        <-- appended LAST, AFTER the caller
```

His words *are* there — but an order is stapled on after them, and the model
obeys the order. **The state block outranks the caller.** And it is rebuilt from
the checklist every turn with **no memory of what it already did**, so the same
order produces the same reply however differently he answers.

| Complaint | The order responsible |
|---|---|
| **Loops** | `BOOKED for "X". Say those exact words back and END THE CALL.` — re-issued identically, forever |
| **Ignores me** | the same block says `Ask nothing further` |
| **Skips the bill** | the field leaves `STILL_NEED` after two asks and can never return |

Nothing hung up either: `EndCallBridge` fires on `must_end`, which only
`MODE: END` sets. The model delivered seven goodbyes without once emitting it.

### What shipped
- **`closings_said`** — the goodbye is an event, not a standing order. The
  second one sets `must_end`, which the bridge has been waiting for since it was
  written and which nothing was reaching.
- **`FAREWELL`** in triage — the caller can end his own call. Deliberately not
  matching *"ఉంటాను"*: it is the polite sign-off **and** the verb for "I live",
  and run 803's location answer was *"హైదరాబాద్‌లో ఉంటాను"*.
- **`NOT_YET_ANSWERED`** — there was a pattern for *"I already told you"*
  (run 218) and **none for its opposite**. He said it three ways and none was
  heard. It now refunds the ask, capped at one refund per field: replaying run
  804 with a cap of two produced **four** consecutive bill questions, and four
  is what made run 218's caller hang up.
- **The `_is_question` gate is gone** from the closing. Run 803 said
  *"బుధవారం చాలు"* — a statement carrying new information — so the gate missed
  it. Whatever he last said is now quoted into the instruction and answered
  first.
- **`REPAIR_LINE` no longer spends an ask.** An apology is not a question. The
  agent was spending the caller's question budget apologising for interrupting
  him.

Checked against 27 real caller lines from both calls: **no false hangups, no
false refunds.**

---

## 3. Why it sounded robotic — and it was never the prompt

`FillerPlayer` is built, wired into the pipeline, gated on the trained turn
detector, and covered by tests. **It had never once made a sound.**

`_clips` was empty on every call ever placed. The caller stops speaking, hears
0.5–1.0 s of nothing, then a fully formed sentence arrives. A human says
*"సరే…"* into that gap.

Nothing failed. The log said `Filler player inert` and no test asserted
otherwise, because every existing filler test constructs the player with a voice
of its own choosing.

Two reasons it was mute:

1. `render_fillers.py` only spoke to **Sarvam**, while the pipeline has run
   **Cartesia** since the cutover — so clips could never be keyed to the voice
   on the call.
2. `load_cached` preferred clips under the bare key `"harvested"`, reachable by
   **any** voice. Three cut on 28 Aug were still winning after the voice was
   rotated on 5 Sep. `fillers.py` already warned that changing the voice
   requires re-harvesting — but **a comment is not a mechanism.** The key now
   carries the voice.

Also found: `cache_path` was case-sensitive on the voice, and a mismatch fails
as a cache miss, which is silence — indistinguishable from the bug being fixed.

**Latency cost: at most `LEAD_MS` = 60 ms**, against 0.5–1.0 s of dead air
removed. Pinned by a test, because it is the whole argument for shipping it.

*"అవును"* (yes) was removed from the bank. A filler is chosen **before** the
model has read the turn, so it cannot know what it is agreeing to.

---

## 4. Turn detection — measured, not argued

The client: *"pipecat already has a turn detector naa, why are you training
one"*, and *"turn detection not detected with intent, it is like fixed
seconds"*. Both fair. Both now answered with numbers.

### The vendor bake-off
| Detector | Telugu |
|---|---|
| Deepgram Flux (10 languages) | **not supported** |
| LiveKit multilingual (14 languages) | **not supported** |
| pipecat `smart-turn-v3.2` | **tested — does not work** |

`smart-turn-v3.2` is bundled, offline, and carries no language metadata, so it
was an empirical question. Replayed over **200 recorded calls** it produced
**255 verdicts and every one came from its 2-second timeout fallback. Zero ML
predictions.** Its wait p50 is 2.18 s against our 0.30 s. It is a two-second
timer on this language.

### The real baseline
**200 calls, 999 speech bursts: 35.9% of bursts cut off, against a 2% target.**

`tools/turn_detector_monitor.py` reports **1.6%** for the same fleet. It is
wrong by more than twenty times and must not be quoted — including in
[28-mlops-for-vaani](28-mlops-for-vaani-2026-09-05.md) §4, which does.

### No parameter fixes it
Ten settings over 589 bursts. The best moves 33.3% → 27.8% while doubling p90
wait. The reason is structural: **when the forest scores above the bar the turn
ends immediately and no floor applies at all** — and that is where the cut-offs
are. `frac` reaches 1.0 on that path so `_wait_secs` collapses to
`min_endpoint_secs` = 0.05 s, which is why refusing the branch alone moved the
rate by *exactly nothing* at four different settings.

### The actual cause
At the moment the decision is taken:

| | |
|---|---|
| text for **this** utterance has arrived | **31.2%** |
| only **older** text available | **44.7%** |
| no text at all | **24.1%** |

`_clear()` wipes `_text` at the end of each turn and STT delivers hundreds of
milliseconds later, so what is in hand mid-turn **is the previous sentence**.
The text half of the decision is reading the wrong utterance on more than two
thirds of turns — and not symmetrically: a finished earlier sentence does not
read as unfinished, so it leaves the early-end path **open**. It does not merely
fail to help; it pushes toward cutting the caller off. That is why raising
`fragment_floor` to 0.80 s moved 33.3% to 32.8% and nothing more.

**The client's description was exact.** The intent detection works; the reaction
to it is a stopwatch, because the intent signal is usually not there yet.

### What was NOT shipped, and why
`blind_min_silence_ms` makes the blind turns wait. Measured on the same bursts
it trades one for one — 33.3% at 0.30 s becomes 24.1% at 0.78 s. **Buying
cut-offs with latency is not a fix**, and it ships **inert at 0.0**, pinned by a
test.

**The conclusion the evidence supports:** no timer, threshold or vendor swap
fixes this. The semantic signal has to be *available when the decision is made*,
which means partial transcripts **during** speech rather than a final one after
it. That is the next piece of work, and it is the first time it has been an
evidence-backed conclusion rather than a guess.

---

## 5. Latency — the honest arithmetic

| | run 804 | run 803 | needed for 700 ms |
|---|---|---|---|
| endpoint | 0.514 | 0.627 | ~0.25 |
| **LLM first token** | **0.541** | 0.436 | ~0.35 |
| TTS first byte | 0.106 | 0.137 | ~0.10 |
| **p50 total** | **1.049** | 0.966 | 0.70 |
| worst turn | 2.54 | 3.49 | — |

`service_factory.py` records that `gpt-oss-120b` at `reasoning_effort=low` has a
**TTFT floor of ~631 ms**. **700 ms is not reachable while the LLM is a
reasoning model.** TTS and the endpoint are already near their limits; the
remaining work is a measured bake-off of non-reasoning models, scored for Telugu
quality as well as speed.

---

## 6. Where it stands

| Complaint | Status |
|---|---|
| Robotic | **fixed** — six clips now render in the live voice |
| Loops | **fixed** — run 803 ends at reply 2, not reply 7 |
| Skips questions | **fixed** — the bill gets three attempts, not zero |
| Does not listen | **fixed** — the caller's words reach the instruction |
| Interruption | **root-caused and measured**, not yet fixed |
| 700 ms | **blocked on the LLM**, arithmetic above |

All of it is in shared code, so every agent gets it — wf2, wf3, wf4, wf5, wf6
and every future one.

Suite: **577 pass, 3 pre-existing failures, none new.** Replay at defaults is
identical to before the change: 33.3%, wait p50 0.30 s.
