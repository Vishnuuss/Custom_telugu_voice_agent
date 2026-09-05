# "It is not listening" — run 324, 30 August 2026

WR-TEL-OUT-08276281, 64 seconds, four of six fields saved as null. The client's
description of it was precise enough to be a specification:

> *"it is not listening, it is just doing its work fastly... it has a time
> bound; if I answer in that time bound it replies, if past that time it moves
> to the next question or interrupts me."*

That is the code. The transcript, with seconds:

    16.52  USER  అదే ఇప్పుడైతే ఏం రాదు కానీ నెక్స్ట్ 2010.
    17.99  USER  3 లాక్స్ ఎట్లా వస్తాది?                  he asks a question
    18.00  BOT   మంచిది సార్, మీరు                        10 ms later
    ...
    38.20  BOT   సరే, మీరు ఏ ఏరియా లేదా సిటీలో ఉంటున్నారు?
    40.58  USER  నేను చెప్తే వినండి.                      LISTEN TO WHAT I SAY
    43.02  BOT   సరే, మీరు ఏ ఏరియా లేదా సిటీలో ఉంటారు?      asks it again
    45.68  USER  నేను చెప్పేది మాకు                       cut off mid-sentence
    49.48  BOT   మంచిది సార్, మీది సొంత ఇల్లా ...            moves on regardless
    53.35  USER  కాదు.
    57.52  BOT   సార్, మీరు రూఫ్ లేదా టెర్రస్ కలిగి లేకపోతే
                 మేము కొనసాగించలేము. థాంక్యూ.               hangs up

He says *listen to me* twice, in as many words, and is asked the same question
and then a different one. `location` saved null. Then the call is ended on a
roof he was never asked about — `roof_available` is null in the record.

**The 10 milliseconds at 18.00 is the whole diagnosis.** No model answers in
10 ms. That reply was generated for his *previous* utterance and was already in
flight; his question arrived 1.5 s after the turn had been declared over. He was
still talking, and the agent had stopped listening.

---

## 1. The floor, and why "don't break latency" is not in tension with it

The patience floor only applied when the model was **unsure** (score within 5%
of the trained threshold). That is what makes it free — the median turn scores
above it and takes the fast path untouched.

It is also the exact failure mode here. A caller who pauses mid-thought produces
a clean falling tail: high energy decay, falling pitch, everything the prosody
model reads as *finished*. **He scores high, so he gets the minimum wait — 0.05 s.
The longer he thinks, the faster the agent cuts in.** A static threshold cannot
see that it is wrong about a particular person.

So the threshold stops being static. If the caller starts speaking again within
**1 second** of us ending his turn, we did not end it — we interrupted it. Nobody
answers a question, hears the reply begin, and starts a fresh sentence inside a
second; a resume that fast is the back half of a sentence cut in two. After two
of those, this caller gets the floor on **every** turn, however confident the
model sounds about him.

Measured on the same 1,393 labelled clips the forest was trained on:

| | ends early | wait p50 | vs the old flat 0.2 s |
|---|---|---|---|
| **A caller we never interrupt** | 46.6% | **0.057 s** | −0.143 s |
| **A caller we have cut off twice** | 46.6% | 0.300 s | +0.100 s p50, **−0.018 s mean** |

**The median wait for everybody else does not move at all.** The caller who is
being interrupted pays 0.24 s — and even he is still faster on the mean than the
flat timeout this replaced. A call where nobody is talked over never reaches the
second row.

Per call by construction: the analyzer is built per pipeline, so one impatient
caller cannot make the next one slower.

## 2. Sentences that cannot end where they stopped

`sounds_unfinished` reads the transcript because half of what makes a Telugu
answer unfinished is inaudible. It missed every fragment in this call.

Three new classes, each a grammatical rule rather than a phrase somebody
happened to say, and **each measured against 2,754 utterances that really were
turn ends before being kept**:

| Class | Example | False positives |
|---|---|---|
| Topic/conditional `-అయితే` | `ఇప్పుడైతే` (as for now) | **0 / 2,754** |
| Bare postposition | `దేని గురించి`, `మా ఇంటి కోసం` | 3 / 2,754 |
| Discourse connective | `వచ్చేసి` (that is to say) | 1 / 2,754 |

Total **7.73% → 8.02%**, at 0.45 s each. That is the cost in full.

One trap worth recording. `-అయితే` matched **nothing** at first, including the
utterance it was written for. Telugu agglutinates: `ఇప్పుడు + అయితే` surfaces as
`ఇప్పుడైతే`, where the initial అ is absorbed into the preceding consonant as a
vowel sign — so the literal string `అయితే` is no longer anywhere in the word. The
suffix has to be matched in its sandhi form `ైతే` as well. Same family as the
`\b`-against-Telugu trap this project has now hit four times.

## 3. "Listen to what I say" is a class of its own

Not a refusal and not a deferral. Both of those mean **stop**; this one means
**wait, I have not finished**. Treating it as a refusal would end the call on a
caller who is trying to buy; treating it as nothing produced the transcript
above.

`WANTS_THE_FLOOR` covers `నేను చెప్తే...`, `నేను చెప్పేది...`, `వినండి మీరు`,
`ఆగండి`, `ఒక్క నిమిషం`, plus the Hindi and English equivalents. It does two
things, and the second matters more:

- **Ask nothing this turn.** The checklist is suppressed for exactly one turn,
  the same mechanism as for a question — because prose telling the model to wait
  does not beat a list of fields at the end of the context. Removing the list
  does.
- **Do not spend the ask.**

## 4. An interrupted question is not a question he declined to answer

This is the half that actually fixes `location: null`, and it answers the
client's second point — *"it needs to get answers for ALL lead questions, how
can it skip."*

`location` was asked twice: once normally, once over the top of him. The two-ask
budget was spent, `location` dropped off the checklist, and the call ended
without it. The budget exists to stop **interrogation** — run 218, where the
caller was asked the same thing four times and said *"ఎన్ని సార్లు అడుగుతారు?"*
— not to charge the caller for our own impatience.

So an ask is refunded when the caller was talked over: he asked for the floor,
or his final transcript stops mid-sentence. At most one refund per ask, cleared
once used, so a caller who is cut off repeatedly cannot earn a field an
unbounded budget — which would be run 218 rebuilt out of refunds.

## 5. The agent may not hang up on a fact it never asked for

    49.48  BOT   మీది సొంత ఇల్లా, అపార్ట్‌మెంటా, లేదా కమర్షియల్ ప్లేసా?
    53.35  USER  కాదు.
    57.52  BOT   ...రూఫ్ లేదా టెర్రస్ కలిగి లేకపోతే మేము కొనసాగించలేము.

He said **"no"** to a three-way question about his property type. The extractor
read it as *no roof*, disqualified him and ended the call.

The first version of this gate was too strict — it required the turn to have
filled a field, which would have blocked *"మాకు ఇప్పటికే సోలార్ ఉంది"* (we already
have solar), a perfectly good disqualifier that fills no field. The rule that
survives is narrower and sharper:

> **A bare denial cannot disqualify.** One or two tokens, all of them negations,
> with no field filled. It is an answer to whatever was last asked and it does
> not say what is being denied.

`కాదు` is blocked. `మాకు ఇప్పటికే సోలార్ ఉంది` is not. Hanging up is the one move
in this call that cannot be walked back.

## 6. It read an equation out loud

    ... 2 kW + + 1 kW = = 3 kW మొత్తం 78,000 రూపాయల వరకు ...

Doubled operators and all, down a phone line. Arithmetic is written, not spoken:
`+` becomes "plus" and `=` becomes `అంటే`, both of which a code-mixing speaker
really says, and the doubling — an artefact of the model laying the sum out as
it worked — is collapsed first so it is not said twice.

---

## Run 324 replayed against the fixed code

| He says | Then | Now |
|---|---|---|
| `3 లాక్స్ ఎట్లా వస్తాది?` | next lead question | `ASKED YOU SOMETHING. Answer THAT, and nothing else` |
| `చెప్పండి వినండి మీరు` | asks anyway | `HE ASKED YOU TO LISTEN. Ask NOTHING this turn` |
| `నేను చెప్తే వినండి` | re-asks the same question | same, and the ask is refunded |
| `నేను చెప్పేది మాకు` | moves to the next field | still listening |
| `కాదు` | **disqualified, hung up at 64 s** | call continues, 5 fields still on the checklist |

`location` is never dropped from `STILL_NEED` at any point in the replay.

## Verification

- **476 passing, 13 failing** across the Vaani subset. Baseline, measured by
  stashing the work and re-running the identical command: **446 passing, 13
  failing** — the same thirteen, by name. **+30, no regressions.**
- The thirteen are pre-existing and unrelated: nine in `test_vaani_filler_cover.py`
  and three others need async fixtures from a `conftest.py` that cannot load
  without a database; one is the known wording drift in `test_reply_sanitizer.py`.
- New file `api/tests/test_run324_listening.py`, 30 cases.
- `tools/measure_endpoint_cost.py` now reports both columns — the ordinary
  caller and the interrupted one — so the trade cannot be claimed without being
  shown.

## Still open

- Not yet exercised by a live call.
- `monthly_bill` was saved as the string `"2010"` from *"నెక్స్ట్ 2010"*, which
  was never a bill figure. The synchronous money parser did not claim it, so the
  extractor's guess stood.
- `location` is still normalised inconsistently between Telugu and English.
- Token usage is still not instrumented.
