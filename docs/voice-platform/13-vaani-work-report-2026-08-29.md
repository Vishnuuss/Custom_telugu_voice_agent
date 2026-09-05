# Vaani work report — 29 August 2026

## 1. The call that defined the day

Run 295. Forty-one seconds, then the caller hung up. His side of it, in order,
with timestamps from the run log:

| Time (UTC) | Caller |
|---|---|
| 07:53:28.6 | చెప్పండి. |
| 07:53:35.9 | ఆ మరి ఆ. |
| 07:53:40.1 | ఆ ప్లే లో. |
| 07:53:45.8 | 62 |
| 07:53:51.7 | **ఇంకా చెప్పలే కదా బిల్లు నేను ఇంకా ఇంకా బిల్లు చెప్పలే కదండి** |
| 07:53:53.8 | **అప్పుడే మీరు క్వశ్చన్** |
| 07:53:58.2 | ఏ. |
| 07:54:00.3 | **అసలు మిమ్మల్ని ఆన్సర్ చెప్పనియ్యరా మీరు?** |

*"I haven't even told you the bill yet." "You're already on the next question."*
*"Do you even let me answer?"*

Stored for the lead: `monthly_bill: 62`. He had been saying "60 … aaa … 70".

The agent asked for the bill three times running, then moved to the city
question while he was still answering the first one. Two of its own utterances
are truncated mid-word in the log — "మంచిది, మీరు ఏ" and
"సరే, మీరు own house, apartment" — because it started talking and he talked over
it. Two turns show a **negative** pre-LLM interval, meaning bot audio began
before the caller's turn was recorded as ended. The interruption is visible in
the numbers, not only in the transcript.

## 2. Root cause

Not the prompt. Not the model. Not the network. The stored workflow
configuration:

```
smart_turn_stop_secs: 0.2
```

and, hardcoded in `run_pipeline.py`:

```python
SileroVADAnalyzer(params=VADParams(stop_secs=0.2))
```

VAD declares the caller stopped after 200 ms of silence; the analyzer then
allows 200 ms more. **Nobody on that call was ever permitted to pause for more
than about 0.4 s.** Saying "60 … aaa … 70" out loud takes longer than that, so
the turn was cut at "60", and whatever fragment Sarvam had finalised by then
became the answer.

`latency_budget.yaml` in this repository declares
`min_endpoint_silence_ms_telugu: 600`. Production was running at a third of its
own stated floor.

### The design flaw underneath it

`TeluguTurnAnalyzer` had, as an explicit stated virtue in its own docstring:

> There is no path through this class that makes a turn slower than it already
> is.

The trained model was wired to one half of the decision. It could end a turn
**earlier** than the timer; it could never hold one **open**. So a caller
mid-sentence and a caller who had finished were handed the identical 200 ms.
The model knew the difference and was never asked.

## 3. What the rest of the industry does

| Source | Mechanism |
|---|---|
| LiveKit Agents | `min_endpointing_delay` **0.5 s**, `max_endpointing_delay` **6.0 s**. High confidence the turn ended, wait `min`. Low confidence, wait up to `max`. |
| AssemblyAI / Decagon / Cekura | "Setting the silence threshold too short — say, **200 milliseconds** — causes the system to cut users off during natural pauses, incomplete thoughts, or moments of hesitation." |
| ElevenLabs Conversational AI 2.0 | Hybrid VAD plus a model reading filler words, prosody and micro-pauses. Their test suite injects "umm", "ah" and throat clears specifically to check the endpointer does not read a filler as a finished sentence. |

The endpointing delay is **two-sided** everywhere it works, and it is driven by
the detector's probability. Vaani had the probability and spent it on one side
only. The 200 ms figure the industry names as the canonical mistake was, to the
digit, what was in production here.

## 4. What shipped

### 4.1 Two-sided endpointing — `telugu_turn.py`, `workflow_configurations.py`

The wait is now a function of how finished the caller sounds:

```
p >= bar            end the turn now                    (unchanged fast path)
p just under bar    endpoint_min_secs   0.05 s
p near zero         endpoint_max_secs   1.40 s
                    linear between, anchored on the trained threshold
```

Anchored on `bar` — the model's own trained threshold — rather than a fresh
constant, so it cannot drift away from the model the next time it is retrained.

The ceiling is 1.40 s, not LiveKit's 6.0 s: 6 s is right for a general assistant
and wrong for a sales call, where a caller who really has stopped must not sit
in silence. With VAD's 0.2 s that is 0.25 s to 1.60 s of total tolerated pause.

### 4.2 The words, not only the sound — `completeness.py` (new)

Prosody cannot carry this alone, and the reason is structural rather than a
matter of model quality. **"అరవై" (sixty) and "సరే" (fine) are the same shape of
sound** — one word, falling pitch, same length, same trailing energy. No
acoustic feature separates them, because the difference is not acoustic: one is
a quantity whose unit has not been said yet.

So the transcript is read too, in grammatical **classes** rather than in the
phrases one caller happened to use:

| Class | Example | Why it cannot end a sentence |
|---|---|---|
| dangling quantity | "60", "అరవై", "పది" | the unit is still coming |
| open range | "పది నుంచి", "10 to" | the top of the range is still coming |
| connective | "కానీ", "ఎందుకంటే", "and" | the grammar promises another clause |
| hesitation | "ఆ", "uhh", "మ్మ్" | a word is still coming |

Either signal saying *wait* extends the turn, and any resumed speech resets the
silence timer — which is the entire mechanism. 17 of 17 phrases taken verbatim
from run 295 classify correctly.

For a **long, calm** utterance ending on a number, the acoustics genuinely do
say COMPLETE and would clear any reachable threshold. Raising the bar is not
enough there, so grammar does not argue with the probability: while the sentence
cannot end where it stands, the early path is shut outright and the turn ends on
the timed path instead, bounded by the fragment floor.

### 4.3 A caller may change his mind — `corrections.py` (new)

> "సారీ, పది కాదు — ఇరవై లక్షలు"

Previously dropped. Once a field was in `known`, nothing could overwrite it —
and that gate exists for a real reason: run 266 read "మూడు లక్షలు" (an answer
about money) as three o'clock and booked an appointment nobody had agreed to.

So the gate stays shut to bare later numbers and opens only to an explicit
repair that **also carries a new value**. Three grammatical moves cover
essentially every self-repair on these calls: negation of the prior value, an
apology opening a repair, an adversative correction. A "కాదు" with no new figure
unsets nothing — he is drawing breath, not retracting.

The new figure is then **said back**, because a correction the caller cannot
hear land is indistinguishable to him from one that was ignored.

### 4.4 62 rupees is not a monthly bill — `extractor.py`

`amounts.py` has known since run 286 what a monthly electricity bill can
credibly be (₹100 to ₹5 crore). That check sat on the synchronous path only.
The asynchronous extraction LLM wrote whatever it was handed, which is how
`monthly_bill: 62` reached the lead record.

Dropped rather than stored: a null is visibly missing, and 62 looks like an
answer.

### 4.5 Asking the question, not the schema description — run 298

    BOT   సరే, మీ నెలవారీ బిల్లు ఎంత?          how much is your monthly bill?
    USER  ఏం బిల్లు అండి                       what bill?
    BOT   మంచిది, మీ నెలవారీ బిల్లు ఎంత?       (asks the identical thing again)
    USER  అది ఏం బిల్లు?                       WHAT bill?
    BOT   అది మీ ఇంటి నెలవారీ విద్యుత్ బిల్లు   that is your HOUSE's monthly bill

Two failures in five lines, and neither is about solar.

**The words being spoken were never written to be spoken.** They came from
`extraction_variables[].prompt`, which Dograh's own DTO documents as the
**"Extraction Hint"** — `"Monthly electricity bill in rupees"`. Vaani handed
that English schema description to the model as the question; the model
translated it live and dropped "electricity", the one word the caller needed.

This is not a bill problem. Every field had it:

| Field | What the agent was told to ask |
|---|---|
| `property_type` | `own house / apartment / commercial` |
| `roof_available` | `Do they have their own roof space` |

A slash-separated English enum is not a question, and reading one to a Telugu
caller is how an agent ends up sounding like a form.

`ask` now carries the spoken question and `prompt` goes back to being a hint for
the extractor — two texts written for two different readers, neither improved by
being made to serve the other. `prompt` remains the fallback, so every workflow
predating the change behaves exactly as it does today. Live on workflow 2:

| Field | Spoken |
|---|---|
| `monthly_bill` | మీ కరెంట్ బిల్లు నెలకి ఎంత వస్తుంది? |
| `property_type` | మీది సొంత ఇల్లా, అపార్ట్‌మెంటా, లేదా కమర్షియల్ ప్లేసా? |
| `roof_available` | మీకు సొంత రూఫ్ లేదా టెర్రస్ ఉందా? |

"కరెంట్", not "విద్యుత్" — nobody on a phone in Telangana says విద్యుత్, and the
harvested transcripts agree. Options are offered wherever the answer is a
category, so the caller does not have to invent the format.

**And it invented the caller's situation.** `property_type` was null and had not
been asked; the man could have been ringing from a factory or a rented room. The
state block listed what was KNOWN and never said the rest was unknown — and a
model reading a list of facts does not infer the absence of the others, it
infers the most ordinary case, because a fluent sentence wants a noun there and
an invented one reads as fluent. The absence is now stated outright, for every
field rather than for property: the same failure would have put a city or a
budget into the agent's mouth just as readily.

## 5. Measured, not asserted

Holding a turn open is not free, and the obvious risk was that this hands back
the whole latency budget. The shipped forest was therefore scored on all 1,393
labelled clips and the new wait computed for each
(`tools/measure_endpoint_cost.py`):

| | n | ends early | wait p50 | vs the flat 0.2 s | held longer |
|---|---|---|---|---|---|
| **turn_end** — caller HAD finished | 1,125 | 46.6% | **0.057 s** | **−0.143 s** | 20.6% |
| **mid_turn** — caller had NOT finished | 268 | 0.4% | 0.938 s | **+0.738 s** | **95.5%** |

**It is not the trade-off it looked like.** A caller who has genuinely finished
is answered **0.14 s faster** at the median, because the model scores real
endings high and the interpolation lands near the 0.05 s floor. A caller
mid-sentence is held **0.74 s longer** in 95.5% of cases.

The flat constant was simply worse at both jobs — too slow for the people who
had finished, far too fast for the people who had not. One number was never
going to be right for both, and that is the whole argument for the change.

These clips carry no transcript, so this is the audio-only half. The text floor
can only *add* holding, so the mid-turn figure is a floor.

## 6. Preemptive generation: closed, with a reason

Run 295 recorded 8 speculation events, all `NO_SPECULATION`, `hits: 0
misses: 0`. Not a threshold problem and not a trigger problem this time:

```
user transcripts: 8 final, 0 INTERIM
```

**Sarvam emits no partial transcripts at all.** There is nothing to think ahead
*on*. Preemptive generation — the largest remaining lever in the 28 August
report — is unavailable with this STT, full stop. Changing STT is a Telugu
accuracy decision that needs its own benchmark, not a latency tweak.

## 6.1 Correction: the measurement tool was wrong, and it changes section 6

`vaani_runs.decompose()` zipped three independent ttfb lists together by index.
That is only correct while every turn emits exactly one of each, and it does
not — run 300 turn 15 emitted two STT and two LLM events (a retried hedge),
after which every later row was reading another turn's numbers. The TTS column
looked bimodal, alternating 0.06 s and 0.32 s turn after turn, and the
alternation was the lists sliding past each other.

Measured properly, Cartesia first-audio is **0.046–0.063 s on every single turn**
of run 300. It has never been a lever, and the "TTS 0.231 s, bimodal" reported
on 28 August came from the same bug. Turns are now grouped on
`rtf-latency-measured`, which is what a turn boundary actually is.

### Run 300, decomposed correctly

| Component | avg | share |
|---|---|---|
| **endpoint** (includes the STT wait) | **0.720 s** | **60%** |
| LLM first token | 0.410 s (0.336 excluding turn 1) | 34% |
| TTS first audio | 0.061 s | 5% |
| **TOTAL** | **1.191 s** (p50 1.109) | |
| *STT ttfb, inside endpoint* | *0.373 s* | |

0.2 s (VAD) + 0.373 s (STT) = 0.573 s against a measured endpoint of 0.720 s.
**The STT wait is sequential dead time after the caller stops speaking.**

## 6.2 The STT is on the wrong model, and it explains both open problems

Run 300's ttfb payload says `"model": "saarika:v2.5"`. In pipecat's vendored
Sarvam service that model has **no partial-transcript path at all** —
`InterimTranscriptionFrame` is not even imported in `services/sarvam/stt.py`;
there is a single `push_frame(TranscriptionFrame(...))`, reached only on the
websocket's utterance-end message. It also declares
`supports_vad_params=False`, so the VAD settings in the Settings dataclass
cannot apply to it.

So **"Sarvam emits no interim transcripts", written up in section 6 as a fact
about the provider and used to close preemptive generation, is a fact about the
model we happen to be on.**

`saaras:v3-realtime` (docs.sarvam.ai) supports Telugu `te-IN`, a `transcribe`
mode, `stream_type: fast`, 8 kHz `linear16`/`mulaw` — and emits
`transcript.partial` as well as `transcript.final`. It is not present in
pipecat's `MODEL_CONFIGS` at the pinned revision.

Both open problems have one cause, and the arithmetic is not speculative:

| | |
|---|---|
| today | 1.109 s |
| − STT dead time (~0.22 s) | ~0.89 s |
| − LLM overlapped into the endpoint window (~0.33 s) | **~0.56 s** |

### Blocked, and the block is a live risk

The probe (`tools/probe_sarvam_realtime.py`, which replays a real caller
recording at wall-clock speed precisely to test whether text arrives *before*
the audio ends) returned:

```
0.48s  error  {"event": "error", "code": "quota_exceeded",
               "message": "Credits exhausted..."}
```

**The Sarvam account is out of credit.** Run 300 transcribed normally at
08:47 UTC, so the server had credit twenty minutes earlier. If the server uses
this same key, the next call loses transcription entirely — the agent will hear
nothing at all. This needs a top-up before anything else on this page matters.

## 6.3 The 800 ms target was met, by deleting a dead constant in our own code

Sections 6.1 and 6.2 chased latency into two vendors and got it wrong twice. The
number was ours all along.

Decomposing run 300 turn by turn, and putting `endpoint_secs` next to the
Sarvam STT ttfb for the same turn, the difference is not noise:

| endpoint | STT | gap |
|---|---|---|
| 0.578 | 0.328 | **0.250** |
| 0.667 | 0.417 | **0.249** |
| 0.576 | 0.326 | **0.250** |
| ... | | |
| 0.321 | 0.311 | 0.010 |
| 0.326 | 0.320 | 0.005 |

A dead constant of 0.250 s on 11 of 16 turns — and the two turns without it were
the two fastest of the entire call, at 0.734 s and 0.839 s.

The source is `pipecat/src/pipecat/turns/user_stop/turn_analyzer_user_turn_stop_strategy.py`,
in the branch commented *"Fallback: handle transcripts when no VAD stop was
received"*:

```python
timeout = max(0, self._stt_timeout - self._stop_secs)   # 0.45 - 0.2 = 0.25
```

A fallback meant for the case where voice-activity detection never fires was
running on **every** turn, waiting a quarter of a second for a transcript that
had already arrived. `stt_finalisation_budget_secs` was set from 0.45 to 0.20
(the schema floor) in workflow 2's stored configuration — a config change, no
deploy, revertible with one command.

**Measured on run 312**, the first call after the change:

| | before (run 300) | after (run 312) |
|---|---|---|
| endpoint p50 | 0.578 s | **0.383 s** |
| endpoint − STT | 0.250 s | **0.072 s** |
| **TOTAL p50** | **1.109 s** | **0.774 s** |
| best turn | 0.734 s | **0.640 s** |

The 700–800 ms target is met. It cost no quality: the endpointing hold, the
trained detector and the two-sided wait are all untouched — the only thing
removed was time spent waiting for something that had already happened.

## 6.4 Run 312 also lost the lead, and none of it was latency

The same call is a complete catalogue of one failure mode. Three times, Sarvam
returned a garbled word and a layer downstream recorded it as a fact rather than
asking about it.

| Caller said | Sarvam returned | Stored | Consequence |
|---|---|---|---|
| "2,000 rupees" | రెండు కోట్లు (2 crore) | `monthly_bill: 20000000` | agent congratulated him on it |
| "on the factory" | ఫ్యాక్టర్ పైన → మా ట్రాక్టర్ పైన | `roof_available: false` | **disqualified and hung up** |
| (a factory) | అది ఒక థర్డ్ సెంటర్ | `property_type: commercial` | guessed, never asked |

**The bill.** `MAX_PLAUSIBLE` was 5 crore, so 2 crore sat inside the bound and
the `doubted` path — which exists for exactly this and has worked since run 286
— never fired. The old comment justified that generous ceiling by saying
rejecting a real large bill is worse than accepting a silly one. That premise
was simply wrong about what the gate does: **it does not reject anything.** An
implausible figure costs one turn of "did you mean thousands or crores?"

The ceiling is now ₹50 lakh a month, derived from what rooftop solar actually
serves — roughly 860 kW drawn continuously at the industrial HT tariff, already
the top of what any rooftop array can carry. And the question is now specific:
"వేలా, లక్షలా, కోట్లా?" A generic "are you sure?" gets the same misheard
syllable back a second time; naming the scales gets a different word.

**The roof.** Nothing in "ఎక్కడండి ట్రాక్టర్ పైన మా ట్రాక్టర్ పైన" is a *no*.
`మా X పైన` — "on our X" — is an affirmative; he was saying *where* the roof is.
The extractor is instructed "never infer or guess" and inferred anyway, because
a boolean field invites it: two of the three honest answers (yes / no /
did-not-say) look alike to a model that wants to be helpful. Prose cannot fix
that, so a gate does: **a negative fact now requires an actual negation in the
caller's own words** (`api/services/vaani/negation.py`).

Asymmetric on purpose. A wrongly recorded *yes* costs a site visit that finds no
roof. A wrongly recorded *no* ends the call, and nobody ever finds out.

**The hang-up.** That disqualification landed on the turn immediately after the
agent had itself said *"మీరు చెప్పినది బాగా వినిపించలేదు"* — I could not hear
you. It did not hear the answer, said so out loud, and ended the call on it. A
disqualifier is the one decision in a call that cannot be walked back, so it now
requires an utterance the agent actually parsed.

One further correction, found while fixing this: the ceiling test asserted
`MAX_PLAUSIBLE >= 10_000_000` while its own failure message read *"10 lakhs a
month must remain credible"*. Ten lakh is 1,000,000. The test had been enforcing
a bound ten times looser than the reason it gave for itself, which is why
nothing caught the 2-crore figure. Rewritten to assert the intent.

## 6.5 Run 314: "Mr. Um Bhaskar", and a warm lead pushed until he cooled

Run 314 (WR-TEL-OUT-70031484) is the first call where nothing went wrong with
the speed and the call was still lost. p50 was **0.829 s**. The caller gave his
bill, his roof, his name, and asked two unprompted questions about the company —
by every mechanical measure a good lead.

### "um" became part of his name

    BOT  : మంచిది, మీ పేరు చెప్పగలరా?
    USER : ఉమ్ భాస్కర్.                     ← "um... Bhaskar"
    BOT  : మంచిది, ఉమ్ భాస్కర్ గారు. ...     ← "Mr. Um Bhaskar"

Stored as `customer_name: "ఉమ్ భాస్కర్"`, and spoken back to him twice.

`completeness.py` has known what a filler is since run 295 — "ఉమ్" was missing
from the set because Sarvam writes English fillers in Telugu script, but "um",
"uhh" and a dozen others were already there. The vocabulary had simply never
been consulted anywhere except the turn-taking decision. It now runs on every
extracted value on its way into the record.

Edges only, never the middle: a filler between two words was said inside a
phrase the caller meant, and cutting there splices two halves of a sentence
into something he never said. And "ఉమ్" carries a virama, so it ends on a bare
consonant and is not a Telugu word — the name **Uma** ("ఉమ"/"ఉమా") is
deliberately excluded, because stripping that would be the identical bug
pointed the other way.

### Then it pestered him until he stopped being warm

    USER : ఆ చెప్తాం మేము మళ్ళీ చెప్తాం.        we'll tell you, we'll tell you again
    BOT  : రేపు ఉదయం ten oclock లేదా ... ఏ సమయం మీకు బాగుంటుంది?
    USER : మేము చెప్తాం ఆలోచన చెప్తాం.          we'll think and tell you
    BOT  : రేపు ఉదయం ten oclock లేదా ... **దయచేసి** ... చెప్పండి.
    USER : అంటే మేము ఆలోచించి చెప్తాం ... డిసైడ్ అవ్వలేం ఇంకా

The same closing question twice, near-verbatim, the second time with *"please"*
attached. Three deferrals to get one warm goodbye.

**A deferral is not a refusal.** He has not said no; he has said not now. The
existing machinery only knew about refusals, and gave those a deliberate second
gentle probe. That is right for "not interested" and wrong here, because the
second ask *is* the irritation — there is no version of asking again that
converts a "let me think".

One deferral, once slots have actually been offered, now ends the call warmly
by name. Gated on `offered` so that "I'll tell you later" earlier in the call —
about a question rather than an appointment — does not hang up on him.

### Two more from the same transcript

**It apologised for mishearing, then changed the subject.**

    BOT : సారీ, మీరు ఏ **ఏరియా లేదా సిటీలో** ఉన్నారో వినిపించలేదు.
          మీది **సొంత ఇల్లా, అపార్ట్‌మెంటా,** లేదా కమర్షియల్ ప్లేసా?

It apologised for not hearing the **city** and asked about the **property** in
the same breath. He never got to re-answer, and `location` was stored as
**"సంతై"** — a fragment of a later sentence — while he had said
**"మంచిర్యాల్"** (Mancherial) twice. The repair line the code owns is only
reached when the repetition guard fires; this apology the model wrote itself,
so it matched nothing. It now raises the same flag, and the state block carries
one line, on that turn only, telling it to re-ask the same question.

**"ten oclock" is now "ten గంటలకు".** The English *number* stays — Telugu
callers say the hour in English and the client asked for it that way. "oclock"
is not a number; it is a bare English word dropped into a Telugu sentence, and
the Telugu case suffix was ending up glued onto it ("four oclockకి", run 300).

### What was NOT a defect

Turn 5 shows a 6.3 s total, endpoint 5.9 s. That is the caller pausing after
"ఉమ్" and the agent waiting for him to finish — the two-sided endpointing from
section 4.1 doing exactly its job. It looks alarming in the latency table and
it is the behaviour that was asked for.

## 7. Verification

- `api/tests/test_endpoint_hold.py` — 13 cases, each written from a specific
  logged failure (run 295's hesitation, run 287's "మాది.", the dangling number).
- `api/tests/test_correction_and_plausibility.py` — 17 cases, including a
  regression guard that run 266's phantom booking stays fixed.
- `test_telugu_turn.py` 30, `test_vaani_amounts.py` 34, `test_vaani_booking.py`
  31, `test_vaani_echo_guard.py` 17, `test_vaani_no_third_ask.py` 9 — unchanged.
- `api/tests/test_run312_defects.py` — 26 cases replaying run 312's exact
  transcript: the 2-crore figure, both garbled roof answers, the negation
  vocabulary, and the one-turn limit on the post-repair grace period.
- `api/tests/test_run314_defects.py` — 39 cases: the name with the filler in
  it, the name Uma that must survive it, all three deferrals verbatim, the two
  bookings that must not be read as deferrals, and the clock phrasing.
- **400 passing** across the synchronous Vaani suite after sections 6.4 and 6.5.
- Pre-existing local failures (speculation, filler cover, reply sanitizer) were
  confirmed identical **before and after** by stashing this work and re-running,
  rather than assumed unrelated. The async suites cannot run locally at all —
  `--noconftest` is required to get past a missing `DATABASE_URL`, and that
  disables `pytest-asyncio`. That is an environment limit, not a result.

## 8. Still open

- **Nothing in sections 6.4 or 6.5 has been exercised by a real call yet.** Both
  are deployed (`992b10d`, app healthy) but deployed is not verified.
- One supervised call to confirm: a scale question instead of a congratulation
  on 2 crore; no hang-up after a "could not hear" turn; no filler in a stored
  name; a warm goodbye on the first "we'll think about it"; "ten గంటలకు".
- `saaras:v3-realtime` remains deployed but unselected. Section 6.2's case for
  it was built on a mismeasurement (6.1); section 6.3 removed the latency that
  motivated it. It should not be revisited without a fresh measurement.
- The repository is still **public**; the Coolify token, the Dograh API key and
  the Sarvam key all still need rotating; the unused `vaani-storage` DNS record
  still needs removing.

### Closed today

- Latency: **0.774 s p50, best turn 0.640 s** (run 312), against a 700–800 ms
  target. Met — see section 6.3.
- Sarvam credits — a new key was supplied and is live.
