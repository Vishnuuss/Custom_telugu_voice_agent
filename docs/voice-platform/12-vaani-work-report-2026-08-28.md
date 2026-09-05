# Project Vaani — Engineering Report

**Date:** 28 August 2026
**Base:** open-source Dograh, forked at `fca8fc8`
**Deployed:** `vaani.bswealthfinance.com`
**Commits:** `daea349` … `5a7fda8` (eight, all deployed)

---

## Contents

1. The short version
2. Defect 1 — it asked the same question three times
3. Defect 2 — it ignored the caller's questions
4. Proof both are fixed
5. The call that looked broken and was not
6. Telugu fillers — hiding the silence
7. Appointment booking — a time somebody can act on
8. The endpoint: where the remaining latency actually is
9. Latency, honestly
10. What is done, what is blocked, what is next
11. Second session (evening) — fillers unblocked, endpoint cut, two negative results

---

# 1. The short version

Six changes went out today. Four are fixes to how the agent talks; two are new
capability. One thing that looked like a catastrophe turned out to be a phone on
speakerphone.

| # | What | Status |
|---|---|---|
| 1 | No question is ever asked a third time | Live, proven on a call |
| 2 | The caller's question is answered before the checklist continues | Live, proven on a call |
| 3 | Telugu fillers, at zero token cost | Live and **active** — clips cut from the agent's own voice (§11.1) |
| 4 | Appointment booking that stores a real date and time, and never double-books | Live, not yet seen on a call |
| 5 | Stronger Telugu turn detector, no new dependency | Live, not yet seen on a call |
| 6 | Crash fix: a missing `logger` import in `turn_taking.py` | Live |
| 7 | Slow endpoint path cut: 0.722 s → 0.588 s projected | Live, not yet seen on a call |
| 8 | Bug caught: fillers were keyed to the wrong TTS provider and would never have played | Fixed (§11.2) |

Test count went from 49 to **150** passing Vaani tests.

Two ideas were **measured and rejected** rather than shipped — deciding the turn
earlier, and training on all 651 recordings. Both would have made things worse.
See §11.3.

---

# 2. Defect 1 — it asked the same question three times

## What the client saw

Run 218, 28 August, 180 seconds, ended by the caller hanging up.

He gave his electricity bill on turn 2 — "టెన్ టు ట్వంటీ లాక్స్". He was asked
for it again on turns 3, 15 and 17. Property type: asked three times. His name:
asked three times.

His replies, in order:

| Turn | What he said | Meaning |
|---|---|---|
| 30 | చెప్పాను కదా అప్పుడే | I already told you |
| 32 | ఎన్ని సార్లు అడుగుతారు? | How many times will you ask? |
| 36 | మీరు చాలా ఇన్‌కన్సిస్టెంట్ గా ఉన్నారు | You are being very inconsistent |

Then he ended the call.

## Why it happened

Two independent causes, and **neither is fixed by rewording the prompt**:

1. **The part that remembers answers runs one turn behind.** It is deliberately
   asynchronous so it never delays a reply. So when the agent chose its next
   question, the checklist still said "we need the bill" — even though he had
   just given it.

2. **The old repeat-guard compared sentences.** "బిల్లు ఎంత?" and
   "బిల్లు సుమారు ఎంత?" are two different sentences asking one identical thing,
   so the guard saw no repeat.

## What was changed

Count the **field**, not the phrasing.

```
  Each detail now has a budget of TWO asks:
      ask 1  ->  the question
      ask 2  ->  one clarification ("sorry, could you repeat that")
      ask 3  ->  never happens; the field is abandoned and the call moves on
```

Because it counts the *thing being asked about*, rephrasing cannot dodge it.

Second guard, independent of the first: if the caller **says** they already
answered — "చెప్పాను కదా", "ఎన్ని సార్లు అడుగుతారు" — that field is dropped
immediately, on that turn, rather than a turn later.

One subtlety that mattered. The count is spent when the question is **spoken**,
not when the prompt is built. Run 218's caller interrupted constantly, and every
fragment — "హలో", a half word, a cough — rebuilds the prompt. Counting there
would have burned a field's whole budget on interjections and dropped questions
that were never actually put to him.

**Trade-off, stated plainly:** an abandoned field costs a follow-up call. Asking
a third time cost the entire call.

---

# 3. Defect 2 — it ignored the caller's questions

## What the client saw

Same call. He asked three real questions and was interrogated instead:

| Turn | He asked | It replied |
|---|---|---|
| 10 | మేము యాక్చువల్గా సిలికాన్ వ్యాలీ తెలుస్తదా? | asked about his roof |
| 13 | అక్కడ సోలార్ పెట్టాలనుకుంటున్నారా? | asked his property type |
| 18 | పాసిబుల్ అయి ఉంది యా… ఇట్స్ నాట్ ఏ స్మాల్ ప్లాట్ | **asked his name** |

At turn 36 he said it outright:

> నేను అడిగిన క్వశ్చన్ కి ఆన్సర్ ఇవ్వాలా ఫస్ట్ ఆఫ్ ఆల్… అతను సోలార్ పెట్టొచ్చా
> అని అడిగాను, మీరేమో పేరు అడుగుతున్నారు.
>
> *Shouldn't you answer my question first? I asked whether solar can be
> installed, and you're asking my name.*

## Why it happened — and it was not what it looked like

The obvious theory is that the agent failed to notice he was asking something.
**That theory is wrong.** The detector fired correctly on turns 10 and 13, and
the agent asked its own question anyway.

The actual cause was the shape of the instruction block:

```
  STILL_NEED: [monthly_bill, property_type, customer_name]     <- ask
  NEXT QUESTION TO ASK: "మీ పేరు?"                              <- ask
  THEY ASKED SOMETHING -- answer it first                       <- answer
  THEY SAID: "..." -- open with two words, then ask             <- ask
```

Three instructions telling it to interrogate, against one telling it to answer.
The checklist wins. `state.py` had already recorded this in its own notes:
listing the checklist at the end of the context makes the model ask for those
fields *even when the prose forbids it*.

## What was changed

**Prose does not beat the checklist. Removing the checklist does.**

The moment the caller asks something, the checklist is withdrawn for that one
turn:

```
  STILL_NEED: [] -- THE CALLER ASKED YOU SOMETHING. Answer THAT, and
  nothing else. Ask NO question this turn, not even a short one.
```

It cannot ask, so it must answer. The fields are still needed and return on the
next turn. This is the same mechanism already used when a call must end — the
only technique that has ever worked here.

Question detection was also widened to the two forms this caller actually used:

- the interrogative **"యా"** detached from the verb with the sentence running on
  past it ("పాసిబుల్ అయి ఉంది **యా** బికాజ్…")
- English question words inside a Telugu sentence ("possible", "how much")

Bare **"ఆ"** was deliberately **excluded**. He uses it as the filler "ah" and as
the demonstrative "that" — "ఆ కంపెనీ మీద పెట్టాలి" is a statement. Reading it as
a question would withdraw the checklist and stall the call outright.

---

# 4. Proof both are fixed

Run 262, 28 August, 130 seconds, a clean call.

| He asked | It did |
|---|---|
| మీ రేట్స్ ఎట్లా ఉంటాయి? సోలార్ రేట్స్, ప్యానెల్ రేట్స్? | **Answered** — pricing depends on usage, roof size, kW; vendor confirms exact figures |
| ఓకే లోన్స్ ఏమైనా వస్తాయా? | **Answered** — finance through vendor partners |
| అదే సోలార్ కోసమే లోన్ కావాలా? | **Answered** — yes, solar-specific plans exist |

Three off-script questions, three answers, no name-asking.

And on repeats: bill asked twice then dropped; location, property, roof, name —
**once each**. No third asks anywhere in the call.

---

# 5. The call that looked broken and was not

Run 261 came in looking catastrophic: every reply chopped after two words,
degenerating into "మంచిది, మంచిది, మంచిది". The reasonable conclusion was that
the day's changes had broken the agent.

They had not. Reading the transcript:

```
  AGENT   Namaskaram andi, MB Solar Hub nunchi Priya matladutunnanu...
  CALLER  ఎంబీ సోలార్ హబ్ నుంచి ప్రియా మాట్లాడుతున్నాను...   <- the same sentence
  AGENT   అవును, ఒక          CALLER  అవును.
  AGENT   సరే, మీ నెలవారీ     CALLER  సరే మీ నెలవారి
```

The "caller" was the agent's own voice coming back.

**Proved from the audio, not guessed.** The two recorded tracks were compared:
the caller track matches the agent track delayed by **300 milliseconds**, with a
correlation of **0.88** on the loudness envelope. (The raw waveforms look
different only because the phone codec re-encodes the sound.)

The loop: agent speaks → hears itself → believes the caller interrupted → cuts
its sentence dead → answers itself → hears that too.

Checked against the three previous calls — runs 216, 217, 218 — on the same code
path: **zero echo**. So it was specific to that call, almost certainly
speakerphone or a second device in the room.

**Action for the client:** handset to the ear, no speakerphone. A software guard
that recognises the agent's own voice is a sensible future hardening, since real
customers do use speakerphone.

---

# 6. Telugu fillers — hiding the silence

## The measurement that motivates it

Run 262:

```
  endpoint + STT   0.921 s      <- the caller hears nothing
  LLM              0.290 s
  TOTAL  p50       1.297 s
```

**The AI is no longer the wait.** Two thirds of every gap is spent deciding the
caller has finished and finalising their transcript, and the line is dead for
all of it. A human agent does not do that — they say "సరే..." the moment you
stop, and you never notice them thinking.

## The bank

Eight real Telugu call-centre fillers, not translations of English ones:

> సరే అండి · అలాగే · అర్థమైంది · ఒక్క నిమిషం · సరే సార్ · మంచిది · ఆc · చూద్దాం

Each is a **continuation** — it promises a sentence is coming. Words that could
stand as a complete reply are excluded on purpose: a bare "సరే." sounds like the
agent has finished, and the caller starts talking into the answer.

## Why it costs no tokens — the client's explicit requirement

The obvious implementation is to tell the model to open with a filler. That is
wrong twice over:

1. It is **billed on every single turn**.
2. It cannot be spoken until the model has already replied — which is the very
   thing being waited for. It would hide nothing.

So fillers never touch the prompt, the context, or the LLM. Each is synthesised
**once** by `tools/render_fillers.py`, cached on disk as raw PCM, and played
straight to the phone line.

**Marginal cost per call: one disk read. Zero tokens, zero TTS characters.**

## When it fires, and the safety argument

It triggers about 200 ms after the caller stops — *while* the endpoint decision
is still running, so it covers the whole 0.92 s rather than the last third.

Firing early is the entire risk. Speaking over a caller who was drawing breath
is worse than the silence, and the project caps false interruptions at 2%.

So it is gated on the **Telugu turn detector already trained on this agent's own
calls** — 1,393 clips from 396 real conversations — read at the moment of the
pause. The gate sits at **0.90**, deliberately *above* the 0.84 used to end a
turn: ending a turn early is recoverable because the caller's next words still
arrive; talking over them is not.

Every uncertain path produces silence: no clips, no detector, an unconfident
detector, a second pause in one turn. **There is no path through this feature
that makes a call worse than it is today.**

## Where it sits, and why that removes work

Placed between the speech engine and the phone line. The phone line plays audio
in the order it is queued, so the filler and the real reply play **in sequence,
never on top of each other** — which removes any need for ducking, mixing or
cancellation logic anywhere in the feature.

One detail: the instruction block also asks the model to open with
"సరే"/"మంచిది". Without care the caller would hear the same word twice, so the
reply's own opener is stripped when a filler has just said it.

## Status: **BLOCKED**

The audio clips are not rendered, because there is no Sarvam API key on the
build machine (`.env` is empty; the server holds its key in the database, not in
environment settings). Until they exist, fillers are **switched off and nothing
changes**.

To enable, from the `bswealthfinance` folder:

```
python tools/render_fillers.py --voice anushka
```

One-time cost: eight short words of speech synthesis.

---

# 7. Appointment booking — a time somebody can act on

## What run 262 actually did

```
  AGENT   మీకు రేపు ఉదయం ten oclock లేదా ఈ రోజు afternoon two oclock…?
  CALLER  ఆ బాగుంటుంది, ఓకే నాకైతే ఓకే
  AGENT   సరే సుబ్బరాజు, రేపు ఉదయం ten oclockకి మా వేండర్ వస్తారు
```

The saved record for that call:

```json
{ "assessment_agreed": true }
```

**No day. No time.** Two separate defects, and the second is worse:

1. The agreed slot is never stored, so the vendor has nothing to act on.
2. The caller said "that's fine" to a menu of **two**, which names neither — and
   the agent silently chose the first and stated it as settled. That is not a
   booking, it is a guess presented as a fact, and the customer discovers it
   when somebody arrives on the wrong day.

## What was changed

**Agreement and selection are now different facts.**

| Caller says | Result |
|---|---|
| "సరే" / "ఓకే" / "బాగుంటుంది" | Consent — but **books nothing**. Asks *which of the two*. |
| "రేపు ఉదయం ten o clock" | Booked: `2026-08-29T10:00:00+05:30` |
| "ఎల్లుండి సాయంత్రం" | Booked: `2026-08-30T17:00:00+05:30` |
| "వద్దు, అవసరం లేదు" | Declined. Nothing booked. |

Other properties:

- **Two concrete slots, on different days.** Two times on one day are easy to
  mishear on a noisy line, and a mishearing is a wrong visit. Open questions
  ("when suits you?") make the caller invent a format nobody can parse.
- **Daylight hours only** (09:00–18:00) — a roof survey needs light.
- **Never in the past.**
- **Read back before closing**, so the caller can correct a misheard slot.
- The time is parsed from the caller's own words deterministically, **not** by
  the extraction AI — because the distinction that decides it (consenting versus
  choosing) is precisely the one run 262 got wrong.

A test asserts the agent can **parse back whatever it just offered**, so the two
halves cannot drift apart.

The booked time is merged into the saved lead record as `appointment_time`,
**without changing the client's agent settings**.

---

# 8. The endpoint: where the remaining latency actually is

Run 262's endpoint times are not one number. They are **two**:

```
  0.402  0.403  0.403  0.403  0.403     <- detector fired      (5 turns, 38%)
  0.783  0.793  0.850  0.856  0.892
  0.930  1.047  1.222                   <- timer ran out       (8 turns, 62%)
```

Nearly two thirds of turns are waiting on a **stopwatch, not a decision**. That
is the whole remaining latency gap.

## The model that was left on the shelf

A boosted-tree detector had already been trained on the same 1,393 clips. It
recognises **43.9%** of turn-endings against the shipped model's **33.9%**, at
the identical 2% false-cutoff bar.

It was never shipped, and the recorded reason was sound at the time:

> "Fourteen points of recall is not worth putting a new dependency on the call
> path." — `telugu_turn.py`

Scoring it needed scikit-learn inside the voice container.

## Why that trade was the wrong frame

A boosted forest **is** a pile of thresholds and constants. scikit-learn is only
the thing that *found* them. Exported as plain arrays, scoring is a walk down 250
short trees — a few hundred number comparisons.

So `tools/export_gbm_turn.py` writes the trees out, and the runtime scores them
with arithmetic on numpy, which the pipeline already depends on. **No new
dependency.**

This was verified rather than assumed:

| Check | Result |
|---|---|
| Exported arithmetic vs scikit-learn's own predictions, all 1,393 clips | max disagreement **5.6 × 10⁻¹⁶** (float rounding) |
| Four of those scores pinned as fixed values in the tests | a silent change is now a failing test |
| Cost on the live audio path | **0.44 ms**, against 2.34 ms for a step that already ran |

The old model remains the fallback. If the forest file is missing it falls back;
if both are missing the detector switches off and behaviour is exactly today's.

---

# 9. Latency, honestly

Where run 262 stands, and where the forest should take it:

| | Today | With the forest |
|---|---|---|
| Turns ending on a decision | 38% | ~44% |
| Mean endpoint | **0.722 s** | **~0.667 s** |
| TOTAL p50 | 1.297 s | — |

**That is roughly one turn in ten dropping half a second. It is real, it is
measured, and it is not enough for 0.7 s on its own.**

The target is not reached. The honest position:

- The LLM is **not** the problem — 0.290 s, and hedging already fixed it.
- The endpoint is the problem — 0.722 s of a 1.297 s turn.
- The forest shaves it. **Fillers hide it**, which is worth more to the caller
  than shaving it, because the caller experiences silence rather than a metric.
- **TTS time has still never been directly measured.** There is no TTS
  time-to-first-byte metric in the run log — only the LLM's. That is a real gap
  in the instrumentation and the next thing worth closing.

---

# 10. What is done, what is blocked, what is next

## Done and deployed

- No question asked a third time — **proven on run 262**
- Caller's questions answered before the checklist — **proven on run 262**
- Appointment booking with a stored date and time — not yet exercised on a call
- Boosted turn detector, no new dependency — not yet exercised on a call
- Crash fix: `turn_taking.py` used `logger` without importing it. The only path
  reaching it is the Telugu weights failing to load, which would have turned a
  graceful fallback into a crash mid-call.

## Blocked

- **Telugu fillers** — need the Sarvam API key to render eight audio clips.
  Currently inert; the call behaves exactly as it does today.

## Known gaps, stated rather than buried

- **The web chat window does not apply the instruction block at all.** Verified
  by sending it a do-not-call request — an old, unrelated safety rule — which it
  ignored and carried on asking for the electricity bill. Phone calls apply it
  correctly. Consequence: **the automated test battery cannot verify any of this
  work**, and only a real call can. This is a genuine bug in its own right.
- **TTS time is unmeasured**, so a portion of every turn is unaccounted for.
- Echo has no software defence. Run 261 collapsed because of it, and real
  customers do use speakerphone.

## Next, in order of value

1. Render the filler clips (needs the key) — hides the whole 0.92 s
2. Measure TTS time-to-first-byte — closes the last unmeasured part of a turn
3. Echo guard — so a speakerphone call degrades instead of collapsing
4. Apply the instruction block in web chat — restores the test battery


---

# 11. Second session, 28 August (evening)

Five items were asked for. All five were worked; two produced negative results
that are more useful than the change would have been.

## 11.1 Fillers — unblocked without the key

Fillers were built but inert, waiting on a Sarvam API key.

**The voice was already on disk.** Every call keeps a separated recording of the
agent, and most turns open with exactly the word wanted. `tools/harvest_fillers.py`
cuts them out of run 262:

| Word | Length |
|---|---|
| సరే | 0.21 s |
| అవును | 0.25 s |
| మంచిది | 0.37 s |
| అర్థమైంది | 0.72 s |

This is **better than a fresh render**, not a workaround. The clips are already
at 8 kHz, already through the phone codec, already carrying the line character
of a real call. A studio-clean render would audibly not match the sentence that
follows it.

Finding the words without per-word timings: split the recording on silence, then
**refuse to cut unless the number of loud regions equals the number of logged
utterances** — so the Nth region is provably the Nth sentence. Then take each
utterance up to its first internal pause, because Telugu speakers leave a real
gap after the opening acknowledgement. Clips outside 0.18–1.10 s are rejected as
not-a-word, and both ends are faded 5 ms because a hard cut is an audible click.

## 11.2 A bug that would have made all of that silent

The clips were keyed to the voice `anushka`, on the belief the pipeline runs
Sarvam. **Run 262's usage record says Cartesia `sonic-3.5`.**

The key would have matched nothing at runtime and the fillers would have stayed
off — with no error, on every call.

Harvested clips are now stored under a fixed name and used **whatever voice is
configured**. That is correct by construction: a clip cut from the agent's own
call *is* the live voice. The consequence is written into the code so it is not
forgotten: **changing the agent's voice requires re-harvesting.**

## 11.3 Turn detection — two negative results

The plan was to make the detector commit earlier. The fast path is a hard floor
of 0.403 s, and the reason is structural: the analyzer is fed "still speaking"
until VAD reports a stop at 0.2 s, so its own 120 ms silence counter only starts
then. **It waits for silence it has already had.**

`tools/sweep_turn_lead.py` retrained the detector to commit 0.1 s, 0.2 s and
0.3 s sooner — which is also what lowering the VAD window would amount to:

| Decide | Turns ending early | Mean endpoint |
|---|---|---|
| now | 33.2% | **0.718 s** |
| 0.10 s earlier | 21.1% | 0.753 s |
| 0.20 s earlier | 5.5% | 0.837 s |
| 0.30 s earlier | 13.6% | 0.769 s |

**Recall collapses faster than the time saved. Deciding sooner makes the call
slower on average.** The idea is dead, and it is better to know that than to
ship it.

**Second negative result, found on the way:** the training set is poisoned past
400 calls. On the first 400 recordings recall is 33.2%; on all 651 it falls to
**0.6%**. More data made it strictly worse, so the extra recordings are a
different distribution and must not be added blindly.

## 11.4 What could be cut instead

The slow path — 0.78–0.93 s on the 62% of turns the detector is unsure about —
is 0.2 s of VAD plus **the 0.6 s transcript budget**, almost exactly. That
constant is what the caller is waiting out.

Lowered to **0.45 s**. Not lower: Sarvam's measured p50 flush-to-final is
438 ms, so about half the finals still arrive in time and the rest fall back to
the newest partial, which for a two-word Telugu answer is usually the whole
answer. Going below the p50 would trade transcript accuracy for milliseconds —
the wrong trade for a client complaining about quality.

| | Slow path | Mean endpoint |
|---|---|---|
| Before | 0.874 s | 0.722 s |
| After | 0.680 s | **0.588 s** |

## 11.5 Appointments must not collide

Two customers promised the same slot both wait in, and one is stood up. That
costs the client the customer, not just the visit.

- Offers now skip any time already booked, walking forward up to 14 days.
- A caller who names an already-taken slot is **asked again**, not double-booked.
- The two offers are forced to differ in **day and hour**. "రేపు ఉదయం ten"
  against "ఎల్లుండి ఉదయం ten" is one mishearing apart, and a misheard slot is a
  vendor at the wrong door.

## 11.6 LLM cost — measured, not guessed

Run 262, 130 seconds, 13 turns:

| | Tokens |
|---|---|
| Input | 258,792 |
| — of which cached | 219,648 (85%) |
| Output | 2,274 |

Output is negligible. **The bill is input tokens, and the largest multiplier is
that every turn is sent three times** — the hedging added earlier to cut the
slow tail. Roughly 6,600 tokens per request, tripled.

So "make it cheaper" has three levers, in order of size:

1. **Hedging 3 → 2** — cuts input tokens by a third. Costs latency; the hedge
   was worth −0.33 s at the median when it was added.
2. **A smaller model** (`gpt-oss-20b`) — cheaper per token and likely *faster*
   to first token, so this is the one lever that helps both. Needs a quality
   comparison before it ships.
3. Prompt size — already 85% cached, so the remaining gain is small.

**Not changed yet.** Cutting the hedge would undo a measured latency win, and
swapping the model without a quality comparison is exactly the kind of change
that produces another angry call. Recommended next step: run the 25-case battery
against `gpt-oss-20b` and compare quality and TTFB before deciding.

## 11.7 Where latency stands

| Term | Value | Note |
|---|---|---|
| Endpoint (projected) | 0.588 s | was 0.722 s |
| LLM | 0.290 s | hedging already fixed this |
| TTS | **unmeasured** | still no metric in the run log |

Total p50 was 1.297 s. The endpoint cut should take roughly 0.13 s off it.
**That is not 0.7 s, and I will not claim it is.** The fillers now hide the
remaining gap, which is what the caller actually experiences — but the honest
engineering position is that TTS time has never been measured, so part of every
turn is still unaccounted for. That is the next thing to close.


---

# 12. 29 August — the latency number was wrong

## 12.1 The finding

One line in `realtime_feedback_observer.py`:

```python
if metric_data.processor and "LLM" in metric_data.processor:
```

Every timing whose processor name did not contain "LLM" was **discarded before
it reached the run log**. Cartesia's processor is `CartesiaTTSService#1`, so the
speech engine's time has never been recorded on this project.

That is not a missing chart. `rtf-latency-measured` reports TOTAL, and on run
273 that total equals endpoint + LLM **to three decimals on all seven turns**:

```
  TOTAL 2.111 = endpoint 0.503 + LLM 1.608
  TOTAL 0.691 = endpoint 0.454 + LLM 0.237
  TOTAL 1.253 = endpoint 0.901 + LLM 0.352
```

The number stops at the model's **first token**. Everything between that and the
first sound reaching the caller was invisible. The client reported three seconds
on a turn the log recorded as 2.111s, and the missing second had nowhere to
appear.

**So every latency claim on this project — including mine — was measured against
a number that excluded one of the three components.** That is the real reason
the 0.7 s target kept being missed: two terms were being optimised and the third
could not be seen.

## 12.2 Fixed

The filter is removed. Pipecat already measures TTS; nothing new is computed.
The breakdown now carries:

| Field | Meaning |
|---|---|
| `endpoint_secs` | deciding the caller finished, plus transcription |
| `llm_secs` | model's first token |
| `tts_secs` | **speech engine — never recorded before** |
| `heard_secs` | what the caller actually waits |

Components are reported separately because a single total cannot be acted on.

## 12.3 Fillers: off, and staying off

Two designs, two live failures.

| | What happened |
|---|---|
| v1 (run 267) | one clip at the pause, then 1.0–1.8 s of silence before the reply — "that aaa in the middle" |
| v2 (run 273) | continuous paced cover, stopping on the reply's first audio |

v2 **fixed** the hole, and its tests still pass. But run 273 exposed something
upstream of timing. The caller heard the clip as a stray word and asked what it
was:

> **ఆ ఏంది మంచిది ఏంది అది?** — *what is this "మంచిది"?*

A pre-recorded word spliced in front of a sentence does not sound like that
sentence. It has different prosody and leads nowhere. Covering a gap
convincingly is a **TTS-level** change, not a playback one.

The machinery is kept behind a flag — the measurement behind it stands — but it
does not go back on a live client call without a way to hear it first.

## 12.4 The seven techniques, assessed

Required by the standing operating mode. Stated including what was skipped.

| # | Technique | Status here |
|---|---|---|
| 1 | Retrieval over prompt-stuffing | **Not applied.** The prompt is ~7,000 tokens and 85% provider-cached, so retrieval would cut tokens that are already nearly free and add a lookup to the critical path. Revisit when the FAQ bank grows past what fits. |
| 2 | Semantic embeddings | **Not applied — and this is the one worth doing next.** Objection and question matching is still regex. Embeddings would replace `_is_question`, the echo guard and the money/time disambiguation with one measured model. |
| 3 | Model routing/cascading | **Partly.** One fast model with 3× hedging. The real form — pre-recorded audio for the ~7 fixed checklist questions, skipping LLM *and* TTS — is designed but not built. On the numbers this is the only route to 0.7 s. |
| 4 | Classical ML | **Applied.** Telugu turn detector, gradient-boosted, 43.9% of turns ended early at a 2% false-cutoff bar, exported to plain arrays so no new dependency ships. |
| 5 | Bandits | **Correctly skipped.** There is no outcome signal yet — no booked/not-booked data at volume. Wiring a bandit now would optimise noise. |
| 6 | Eval harness | **Exists but is blind.** 25 cases, and they run over text chat, which does not apply the state block at all. It cannot verify any of this work. Needs rebuilding against the voice path. |
| 7 | Observability | **This session's work.** §12.1 is exactly the failure this technique exists to prevent. |

## 12.5 Where the 0.7 s actually comes from

On the numbers now visible:

```
  endpoint + STT   0.63 - 0.76 s     the largest term
  LLM              0.26 - 0.35 s
  TTS              unmeasured until today
```

Deciding the turn earlier was measured and **rejected** — recall collapses
faster than the time saved (§11.3). So the remaining route is technique 3: for
the fixed checklist questions, play pre-recorded audio and skip both the model
and the speech engine. That removes roughly 0.6 s from a routine turn and puts
it under 0.7 s.

**Not built yet, and not claimed.** The next step is one call with the new
instrumentation, to see the TTS number for the first time and size it properly.


---

# 13. 29 August — researching the latency, and killing three theories

The operating mode requires measured claims. This section is what that produced:
three plausible explanations for the LLM's ~0.4 s, each tested on the live
server with real calls, and each **rejected**.

## 13.1 What the industry actually does

From [LiveKit's latency guide](https://livekit.com/blog/understand-and-improve-agent-latency),
[Future AGI's 12-technique breakdown](https://futureagi.com/blog/how-to-optimize-livekit-latency-2026/)
and [Sarvam's LiveKit production notes](https://docs.sarvam.ai/api/integration/livekit-production-best-practices):

A default pipeline lands at **1.2–1.4 s p95** — almost exactly our 1.135–1.29 s.
Optimised ones reach **500–650 ms on the same providers**. The gap is not the
models. It is four techniques:

1. **Preemptive generation** — start the LLM on a stable partial *while*
   endpointing is still running
2. **Stream LLM tokens into TTS at the first sentence boundary** — 200–500 ms
3. **Endpointing delay tuned to 0.3–0.5 s**
4. **Co-locate the orchestrator with the providers**

## 13.2 Theory 1 — the server is far from the LLM. REJECTED

The geography looked damning:

| | Location |
|---|---|
| Server | Mumbai, India |
| Sarvam (STT) | Pune, India |
| Cartesia (TTS) | Singapore |
| **Groq (LLM)** | **Toronto, Canada** |

Measured from the server, subtracting Groq's self-reported timings from the wall
clock:

| Run | Network |
|---|---|
| 279 | 0.081 s |
| 281 | 0.350 s |
| 283 | 0.073 s |
| 284 | **0.044 s** |

**Typically 44–81 ms.** A transcontinental hop that costs 60 ms is not the
problem, and a region migration is off the table. One outlier at 0.350 s remains
unexplained and is worth watching, but it is not the median case.

## 13.3 Theory 2 — a smaller model would be faster. REJECTED

| Model | Provider time |
|---|---|
| gpt-oss-120b (live) | 0.399 s |
| **gpt-oss-20b** | **0.414 s** |

The smaller model is **not faster**. `llama-3.3-70b` and `llama-3.1-8b` are not
available to this account.

## 13.4 Theory 3 — the 28,850-character prompt is the cost. REJECTED

Same model, same server, seconds apart:

| Prompt chars | Provider time |
|---|---|
| 28,850 | **0.080 s** |
| 28,850 | **0.413 s** |
| 14,425 | 0.074 s |
| 7,212 | 0.149 s |
| 1,442 | 0.072 s |

**Length predicts nothing.** The same prompt varies 5× between two calls seconds
apart. Retrieval or prompt-trimming would not have moved this number, and would
have cost the psychology layer that makes the agent worth using.

## 13.5 What is left

Not distance, not model size, not prompt length — **variance**. The provider
figure was being reported as `queue_time + total_time` summed together, which
cannot distinguish waiting for a worker from working. They are now measured
apart, and the sweep repeats one prompt size five times rather than walking four
sizes, because the question changed from *how long* to *how unstable*.

If the variance is queue, hedging is already the correct answer and is at 3.
If it is compute, the route is preemptive generation — overlapping the LLM with
the 0.63 s endpoint window, which is technique 1 above and the largest single
win still available.

## 13.6 What shipped alongside

- **English/Telugu amounts understood.** 18/18 real caller phrases parse,
  including run 274's "వన్ లాక్ అండి" which was asked three times and stored as
  null. Two Unicode traps caused it: `\w` excludes Telugu vowel marks, so the
  tokeniser split "లక్షలు"; and `` fails after them, so every range collapsed
  to its upper figure.
- **It reacts to the size of the bill.** Proven live on run 276:
  *"మీ బిల్లు ఒక లక్షలుగా ఉంటే, ఆదా కూడా పెద్దది అవుతుంది."*
- **Parsed facts survive the extractor's nulls** — run 279 saved
  `monthly_bill: 100000` where run 276 had saved null for the same answer.
- Run 279 was a **clean call**: every field captured, nothing asked twice, and a
  booking made.
