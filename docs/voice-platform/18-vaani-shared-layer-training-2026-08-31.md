# Training the shared layers — 31 August 2026

The client's framing was the right one:

> *"I'm focusing on Layer 1 and Layer 2. These must be for all clients same,
> right? Am I right?"*

Yes. Layers 1 (persona and voice), 2 (sales psychology) and 4 (mission) are
inherited **unchanged** by every agent this platform will ever run. Layer 3 —
the client's knowledge base — is the only per-client text, and
`api/tests/test_layers_are_reusable.py` enforces the separation on every test
run. So an hour spent on Layers 1 and 2 improves every client at once, and an
hour spent putting a solar example in the persona quietly costs the next one.

What was asked for: general sales, psychology, objection handling, **reacting**,
**understanding what was actually asked**, and real-world Telugu — *"how people
talk and how they form sentences"*.

## How it was done

Six categories, one agent each, each writing a standalone section that was
checked and then spliced in — rather than six agents editing two files.

| # | Category | Lands in | Lines |
|---|---|---|---|
| A | How a Telugu sentence is BUILT when it is spoken | Layer 1 | 255 |
| B | Reacting like a person — the feeling to react | Layer 1 | 219 |
| C | Comprehension — answer the question that was actually asked | Layer 2 | 272 |
| D | Sales craft — how to run the conversation | Layer 2 | 265 |
| E | Persuasion on an Indian phone call | Layer 2 | 321 |
| F | Objection handling — the method, then the catalogue | Layer 2 | 295 |

Layer 1: 174 → **650 lines**. Layer 2: 307 → **1,464 lines**.

## `tools/check_layer_section.py`

Written before the sections were, because six drafts going into two files that
every client inherits is exactly where a rule gets broken silently. It checks
industry vocabulary, client names, rupee figures, the mixed clock, the case
marker welded onto `o'clock`, stacked honorifics, digits inside spoken examples,
and literary Telugu that is being recommended rather than warned against.

**It earned its place immediately.** Section A had written, as a *correct*
example of Telugu word order:

    రేపు ఉదయం ten గంటలకు వస్తాను

— the exact mixed clock the client corrected twice. The word-order point was
right and the example carried the defect. Caught before it reached a layer.

The interesting part was teaching it to read a wrong/right table. The first
version skipped any two-cell row, which is too generous: a three-column table is
mostly right-hand column, so a mistake there would never be seen. It now reads
the table **header** to find which column holds the counter-example — these
layers carry `| wrong | right |`, `| pattern | natural | do not write |` and
`| said | means | reply |`, and guessing "the first cell" costs either a false
positive on every row or a blind spot down a whole column.

## Some of what landed

**Sentence architecture** (A). Telugu is verb-final, and the model writes
English word order in Telugu words:

| Wrong (English shape) | Right (Telugu shape) |
|---|---|
| నేను వస్తాను రేపు ఉదయం ten o'clock | రేపు ఉదయం ten o'clock వస్తాను |
| చెప్తాను మీకు డీటెయిల్స్ | మీకు డీటెయిల్స్ చెప్తాను |

Also: questions are made by lengthening the final vowel (`ఉందా`), not by word
order; negation lives *inside* the verb (`కాదు` / `లేదు` / `-లేను`), so an
English "not" bolted onto a Telugu clause is a whole error class; `కదా` only
attaches to information already shared — on something new it is how a machine
sounds pushy; one discourse particle per sentence, never two.

**Reacting** (B). The agent acknowledged everything with `మంచిది` regardless of
what was said. A generic acknowledgement is worse than none — it proves nobody
was listening. The rule is that **the reaction must contain the fact**:
`అది పెద్ద amount సార్` beats `మంచిది` because it repeats the thing back. With a
calibration scale, because over-reacting is as robotic as under-reacting:

| `మీరు చాలా మంచి ప్రశ్న అడిగారు.` | `మంచి పాయింట్ సార్.` or nothing |
| `అద్భుతం!` for an ordinary answer | *nothing* |

Enthusiasm for a pin code is the clearest fake in the call. And the client's own
example — *"it should be able to handle even 'did you eat'"* —
`భోజనం అయిందా?` → `అయ్యో, నేను తినను సార్. మీరు తిన్నారా?`

**Comprehension** (C). Eleven shapes a Telugu question takes, including the ones
with no question mark and no wh-word. Then the question behind the question:
`ఎంత అవుతుంది?` is rarely a request for a number, it is *can I afford this*;
`మీరు ఎవరు?` is *should I trust you*. Plus the discriminators the model gets
wrong — `ఖరీదు ఎక్కువ` (objection) against `ఎంత ఖరీదు?` (question), and `సరే` as
a backchannel rather than agreement.

**Sales craft** (D). Qualifying by conversing rather than collecting; a
categorical question must name its options; the two-slot next step; ask once
then stop talking; a `సరే` that books nothing.

**Persuasion** (E). Trust from an unknown number in the first fifteen seconds,
which in India is presumed to be a fraud. Each classical lever written as the
sentence to say, with its failure mode. Manufactured scarcity is banned outright
with the phone-specific reason it also backfires; anchoring is constrained to
costs the caller stated themselves; and honesty is named as the strongest lever
on the page — *"I don't know, our team will confirm"* builds more than a
confident guess.

**Objections** (F). The method first, because Layer 3 cannot list them all:
hear → acknowledge → is it real or reflex → answer → one question. A reflex
carries no reason, and rebutting a reflex is what marks you as a telecaller.
`కానీ` is banned outright. One rebuttal, never two. And explicit permission to
agree when the objection is simply correct. Then thirteen objections not already
in Layer 2.

## The measurement that decides whether this ships

The compiled prompt went **34,409 → 114,909 characters** (~10,700 → ~35,900
tokens). The standing rule in this project is *never trim prompts for latency*,
and its stated justification is that trimming buys nothing — measured on 29
August across 1.4k–28.8k chars. Three times further out, that justification
needed re-testing rather than assuming.

**The first measurement said the rule was broken.** Six interleaved reps:
p50 0.725s → 1.726s, **+1.0s**. That would be unshippable.

It was noise. Two further runs of fourteen interleaved reps each:

| run | old prompt (34k) | new prompt (115k) |
|---|---|---|
| 1 — mean | 0.852 s | **0.852 s** |
| 2 — mean | 0.512 s | **0.518 s** |

**28 samples each; mean difference +0.003 s.** The medians move in opposite
directions between the two runs (−0.168 s, then +0.150 s), which is what noise
looks like rather than an effect. A size sweep across 30k / 45k / 60k / 80k /
115k was likewise non-monotonic — 80k measured *faster* than 45k.

The reason is prefix caching. The system prompt contains no per-call value, so
the whole ~36k-token prefix is identical across every turn and every call, and
Groq serves it from cache. Prefill on a cached prefix is close to free.

**Two things this does cost, stated plainly:**

- **Input tokens roughly tripled** — ~36k per request against ~11k, at two
  hedged requests per turn. Cached tokens are half price, so this is a real but
  modest increase in spend per call, not a threefold one.
- **Instruction-following over a 1,464-line layer is not measured.** A very long
  instruction set can dilute attention, and no bench here tests that. It is the
  reason to place a call rather than trust the test suite.

## Verification

- **476 passing, 13 failing** across the Vaani subset — the same thirteen
  pre-existing failures as the baseline established earlier today.
- `test_layers_are_reusable.py`: 11 passed. All three shared layers are clean
  under `check_layer_section.py`, including the `₹3,000` that had been sitting
  in Layer 1 since before this work.
- A date-dependent assertion introduced yesterday in `test_run323_booking.py`
  was caught by this run and fixed: it asserted the literal `2026-09-01` for
  "ఎల్లుండి" and therefore passed for exactly one day. It now asserts two days
  from today.

## Still open

- **Not exercised by a live call.** That is the only test that matters for
  whether the model actually follows a layer this long.
- Whether any of the six sections contradict each other in practice, as opposed
  to passing a lint. The clock rule and the honorific rule are checked
  mechanically; tone consistency is not.
