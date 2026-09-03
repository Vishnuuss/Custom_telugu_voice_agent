# Deeper sales training at zero latency cost — just-in-time coaching

**3 September 2026 · Project Vaani · workflow 2 (MB Solar Hub)**

## The request

> "the persuasion and objection handling training also complete, but manage the
> latency to become same, and Telugu should be very good, how humans speak in
> general life."

Three things at once, and two of them had already been shown to fight each
other.

## Why they fight

On 31 August, Layers 1 and 2 were trained from 26,216 characters to 112,526.
The Telugu and the selling both got better. Run 336 then measured the LLM at
**1.884s against 0.337s**, and the client's reply was "you ruined the latency".

A bench with real conversation history reproduced it exactly: **1.070s →
2.099s**, with the model's hidden reasoning growing from 91 to 160 characters.
The mechanism is not mysterious. `openai/gpt-oss-120b` reads every instruction
before it answers, so instruction volume *is* latency. Compressing the layers
back under their original size recovered the speed and cost part of the depth.

That is the trap this work had to get out of: more training has always meant a
slower agent.

## The way out

**Almost all of a sales playbook is conditional.**

The line about what to do when a caller says the price is too high is worth a
great deal on the one turn they say it, and is dead weight on the other fifteen
— but it is read, and paid for, on all sixteen.

So the catalogue was moved out of the system prompt entirely, into
`api/services/vaani/coach.py`. One or two rows are selected by pattern against
the caller's own words and appended to the per-turn state block.

### Why the state block and not the prompt

`compiler.py` puts Layers 1+2 at the front precisely so they land in Groq's
cached prefix — byte-identical across every turn and every call. Anything that
varies per turn must not go there, or the cache misses on every turn.
`brain_processor._refresh` already appends the state block as a trailing system
message, which is both uncached anyway and the most authoritative position in
the context. That is where the coaching goes.

### What it costs

| | Characters |
|---|---|
| Catalogue, had it been written into Layer 2 | ~9,400 |
| What actually reaches the model, per matching turn | ~220 |
| What reaches the model on a turn with no match | 0 |
| Ceiling, enforced in code | 2 lines × 260 chars |

The catalogue can grow to any size without that last figure moving. That is the
whole point.

## What was added

**24 cues**, in three weighted groups.

**Tone — how they said it** (outranks everything, because content in the wrong
shape is worse than no content):

`bill_shock`, `angry`, `hurry`, `suspicious`, `confused`, `sad`, `joking`.

The client asked for this by name: *"it should catch the tones … see if cost
high it should react."* `bill_shock` fires when the caller themselves calls a
number large, and forces the fact into the reaction — Layer 1 already rules that
a reaction which does not contain the fact proves nobody was listening.

**Objections — 15 rows**, each carrying the part of the answer specific to that
objection: `too_expensive`, `no_money`, `not_interested`, `think_about_it`,
`call_later`, `whatsapp`, `ask_family`, `already_have`, `competitor`,
`who_are_you`, `too_many_calls`, `is_it_free`, `rented`, `guarantee`.

**Buying signals**: `come_and_see`, `how_does_it_work`, `price_question`.

### One rebuttal, never two — enforced by the prompt as well as in it

Layer 2 has always said a second push on the same objection loses the lead. A
cue already spent in a call is never injected again, so the prompt itself cannot
push twice. `CallState.coached` carries that across turns.

## Layer 2 got smaller, not bigger

The fifteen catalogue rows now delivered just-in-time were removed from Layer 2.
Five rows stayed inline because they are **policy, not tactics**, and must not
depend on a regex firing: a child answering, anger, polite non-commitment,
"are you a robot", and a language switch.

The freed budget bought four new always-on persuasion sections — the ones that
shape *every* turn and therefore cannot be conditional:

- **Name the feeling before you answer it.** Four or five words, then stop. A
  person who has been named correctly stops defending.
- **Every ask carries its reason** — why you need it and what they get.
- **Small yes before big yes.** Easy facts first; never open with the
  commitment.
- **Use their word, not yours.** If they said `షెడ్`, never "commercial
  establishment."

| | Before | After |
|---|---|---|
| Layer 2 | 10,356 chars | **10,104 chars** |
| Objection rows available to the agent | 17 | **24 + 5 policy rows** |

## Telugu, in code rather than in the prompt

`speech_register.py` already rewrites generated speech into the spoken register
after the model produces it — a dictionary lookup on a string already in hand,
adding nothing to the prompt and impossible for the model to ignore.

Nineteen general-life pairs were added. None is industry vocabulary; these are
the Sanskrit-derived nouns the model reaches for in *any* conversation, because
the written Telugu corpus is full of them and spoken Telugu is not:

| Bookish | Spoken |
|---|---|
| మీకు అనుకూలమైన సమయంలో | మీకు కుదిరే టైమ్‌లో |
| ఏమైనా సందేహాలు | ఏమైనా డౌట్స్ |
| వివరాలు | డీటెయిల్స్ |
| సమాచారం | ఇన్ఫర్మేషన్ |
| నిర్ణయం | డిసిషన్ |
| ప్రయోజనం | బెనిఫిట్ |
| పరిమాణం | సైజ్ |
| అనుమతి | పర్మిషన్ |
| సంప్రదించండి | కాంటాక్ట్ చేయండి |
| తదుపరి | నెక్స్ట్ |
| ప్రస్తుతం | ఇప్పుడు |
| నివాసం | ఇల్లు |
| వ్యయం | ఖర్చు |
| ఆసక్తి | ఇంట్రెస్ట్ |

## Measurement

### Latency

`bench/ab_layers.py` was written for this, because the bench that cleared the
31 August training was the reason that regression shipped: it used a two-message
toy conversation on a warmed cache, and a reasoning model has nothing to
reconcile with two messages. This one carries eight turns of Telugu history, the
real trailing state block, interleaved arms with alternating order, and measures
**time to first speakable token** — the first byte on this model is the start of
hidden reasoning, which the caller cannot hear.

Measured on the **worst case**: a turn where two cues fire at once.

| Run | before (mean) | after (mean) | delta |
|---|---|---|---|
| 1 (n=16) | 0.648s | 0.661s | +0.013s |
| 2 (n=16) | 0.656s | 0.559s | −0.097s |

**The two runs disagree in sign, and the swing between runs is larger than the
difference between the arms.** The honest reading is that there is no
measurable latency change — which is what was asked for. Anyone reporting this
as a speed-up from run 2 alone would be repeating the 31 August error in the
opposite direction.

### Correctness

| | |
|---|---|
| New tests | 44, all passing (`api/tests/test_coach.py`) |
| Full suite | **2,539 passed**, up from 2,495 |
| New failures vs baseline | **none** — the 51 failures and 98 errors are identical before and after, and are Docker not running locally |

The baseline was taken by stashing the change, re-running the identical command,
and comparing failure lists by name.

The 26 cues are each tested against the caller's real words, and eight ordinary
answers (`సరే`, `హా`, `విజయవాడ`, `కాంక్రీట్ రూఫ్ ఉంది`) are tested to produce
**no** coaching — the expensive failure mode is coaching an objection that was
never raised. Four of the cues were misses on the first pass and were found this
way: `మా దగ్గర already ఉంది` (an English adverb on a Telugu verb),
`మీ నంబర్ ఎక్కడిది?` (మీ, not నా), `ఏంటి catch?`, and a bare `ఎంత అవుతుంది?`.

## Files

| File | Change |
|---|---|
| `api/services/vaani/coach.py` | new — the catalogue and the selection |
| `api/services/vaani/state.py` | `coached` field; `render` appends the lines |
| `api/services/vaani/layers/02_psychology/core.md` | 15 rows out, 4 persuasion sections in |
| `api/services/vaani/speech_register.py` | 19 general-life register pairs |
| `api/tests/test_coach.py` | new — 44 tests |
| `bench/ab_layers.py` | new — the A/B that does not lie |

## What is still open

- **No real call has exercised this.** Every number above is a bench. The
  `saaras:v3-realtime` STT switch made on 31 August is also still unverified by
  a live call.
- **Recall is unmeasured.** The 26 cues are tested against utterances chosen
  when the patterns were written. How often they fire on real callers can only
  be counted from transcripts, and should be, after the next few calls.
- Telephony cost per minute is still unknown; the stack is ₹2.71/min.
