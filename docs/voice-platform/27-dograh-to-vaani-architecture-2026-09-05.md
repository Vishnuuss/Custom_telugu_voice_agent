# From Dograh to Vaani — how the agent was rebuilt

**5 September 2026 · Project Vaani · the complete architecture**

What was inherited, what was replaced, what runs today, and every technique and
model in the live system. Numbers in this document are measured on real calls
and cited by run number.

---

## 1. The starting point, and the structural bug

Dograh drives a conversation with a **node graph**. Each node carries a prompt;
each edge carries a condition; the caller's utterance is matched against the
edges to choose a transition.

The failure is structural, not a tuning problem, and it is written into
`state.py` as the reason the rewrite happened:

> A node graph makes the state machine GENERATE the reply, which is backwards:
> when the caller says something no edge matches, there is no transition and the
> agent goes silent.

A caller who says something unanticipated falls off the graph. On a phone call
that is dead air, and it is the one failure a caller will not forgive.

There was a second cost. Swapping the system prompt at every node destroys the
provider's prompt cache, so every transition paid a full uncached prefill.

---

## 2. The inversion that defines Vaani

**The state machine no longer generates. It only constrains.**

The model always generates, so there is never an edge to fall off. State is
injected as a compact block — roughly 80 tokens, rebuilt every turn — that tells
the agent where it is and what it still owes, without ever preventing it from
answering what was actually said.

| | Dograh | Vaani |
|---|---|---|
| Who produces the reply | the graph picks a node prompt | the model, always |
| What the state does | decides the transition | constrains and records |
| Unmatched utterance | no edge → silence | answered normally |
| Prompt cache | destroyed at every node | one stable prefix per call |
| Node count in production | many | **one** (`startCall`) |

The live agents are single-node. `wf2` carries one `startCall` node; the BS
Wealth agents carry `startCall` plus a `webhook` node that is not a
conversational step. **The graph was not tuned away — it was removed.**

## 3. What was deliberately NOT rebuilt

Rewriting the audio engine was tried once and was a mistake. From
`pipeline.py`:

> On real calls that gate threw the caller's voice away while the agent was
> speaking — the agent talked over the caller and never heard them. Real-time
> audio is not a place to guess.

The division that stands:

| Layer | Owns |
|---|---|
| **Dograh** | UI, campaigns, Redis, Postgres, telephony, dashboard |
| **Pipecat** (Daily's framework) | the audio engine, serializers, VAD, turn-model plumbing |
| **Vaani** | the conversation, and the *definition* of the pipeline — which processors exist, in what order, and why |

---

## 4. The prompt: four layers

`compiler.py` assembles one system prompt per call, constants first so they land
in the provider's cached prefix.

| Layer | File | Size | Scope |
|---|---|---|---|
| 1 — Persona | `layers/01_persona/te-IN.md` | 8,850 chars | **Shared, every client** |
| 2 — Psychology | `layers/02_psychology/core.md` | 11,980 chars | **Shared, every client** |
| 3 — Business knowledge | per workflow, in the node | 1,890–9,811 chars | **Per client** |
| 4 — Mission | `layers/04_mission/outbound.md` | 3,320 chars | Shared per agent type |

Layers 1, 2 and 4 are inherited unchanged by every agent, so they are held to a
hard rule enforced by tests: **no industry vocabulary, no client names, no
figures.** `test_layers_are_reusable.py` and
`test_coach.py::test_the_catalogue_carries_no_industry_vocabulary` fail the
build if a trade word appears. Layer 3 is the only place a trade word belongs.

Assembly order is a latency decision, not an aesthetic one: persona and
psychology are byte-identical on every turn of every call, so they sit at the
front and stay cached; the varying state block is appended **last**, after the
history, where it is both uncached anyway and the most authoritative position in
the context.

---

## 5. The brain — three objects on the live path

```
transport → stt → [partial responder] → StateInjector → aggregator
          → llm → ReplyFilter → tts → transport
```

`StateInjector` sits **before** the aggregator so the state block is current
when the LLM fires. `ReplyFilter` sits **after** the LLM so nothing unspeakable
is ever spoken. Both positions were paid for with real calls.

### CallState — what replaces the graph
`state.py`, 897 lines. Tracks phase, what is known, what is still needed, what
has been asked and how often, objections raised, booking state, and the
end-of-call flags. Two rules in it do most of the work:

- **`MAX_ASKS_PER_FIELD = 2`** — one ask, one clarification, then the field is
  abandoned. Better an unknown than a caller hanging up.
- **Answer first, then ask** — when the caller asks something, the checklist is
  withdrawn for that turn and a single ordered instruction takes its place. Run
  218 is why: the caller asked whether solar was possible on his plot and was
  asked his name instead, and by turn 36 he said so out loud.

### ReplyFilter — the last gate before speech
Repetition detection, guardrail substitution, register correction and mode
parsing, all on the streaming reply, all decided on the first chunk **before a
word is emitted** — because half a sentence is worse than the mistake it
prevents.

---

## 6. Machine learning in the live system

### 6.1 The Telugu turn detector — trained here, because nothing else exists
**No vendor turn detector supports Telugu.** Smart Turn v3 covers 23 languages,
LiveKit 14, Deepgram Flux 10, AssemblyAI 4–6. Telugu is in none of them.

| | |
|---|---|
| Model | Gradient-boosted forest, **250 trees**, `models/audio_turn_gbm.json` (176,933 bytes) |
| Features | Prosody over the final 1.5 s: autocorrelation f0 track, polynomial contour fits, FFT band energy |
| Training data | **2,754 real Telugu utterances**, 651 callers |
| Labelling | A complete utterance is a positive; a **prefix** of one is, by construction, a negative — the standard construction used by LiveKit and Smart Turn |
| Split | By **utterance**, never by example, or prefixes of one sentence leak across the split and the score becomes fiction |
| Optimised for | **Not accuracy.** The threshold is set where false cut-offs stay under 2%, because cutting a Telugu caller off is the failure they complain about |
| Result | Ends **33.9–43.9%** of turns early at that operating point |

It also adapts within a call: after `CUTOFFS_BEFORE_ADAPTING = 2` mid-sentence
cut-offs it becomes permanently more patient **with that caller**, because the
forest is right about most people and wrong about some in a way that is obvious
within two turns and invisible to a static threshold.

Safety rules layered on top: a turn under `MIN_CONFIDENT_TURN_S = 0.65` needs
near-certainty (0.995) before it may end, because a one-word fragment
prosodically resembles an ending.

### 6.2 Supervised datasets, harvested automatically
`vaani_harvest.py` / `vaani_dataset.py` mine every completed call:

| Dataset | Rows | Purpose | Status |
|---|---|---|---|
| `sft.jsonl` | 3,810 | Distillation / fine-tuning | **READY, unused** |
| `dpo.jsonl` | preference pairs | Preference tuning | **READY, unused** |
| `turnstops.jsonl` | 2,759 | Turn detector | **In use** |

Preference pairs are free: every reply that fails `hard_rules` is a labelled
rejection. **Nothing trains on them yet** — the data half of preference learning
exists and the learning half does not.

### 6.3 What is deliberately NOT machine learning
`coach.py` selects rules by regex on the caller's words. `triage.py`,
`negation.py`, `amounts.py`, `completeness.py` are deterministic. This is a
design decision, stated repeatedly in the code: **prose loses to a gate.** A
compliance rule that must never fail is not a thing to learn probabilistically.

**Reinforcement learning is not present**, and it would not reduce latency: RL
changes word choice; it cannot make the system notice a caller stopped talking.

---

## 7. The models in production

| Stage | Provider / model | Measured |
|---|---|---|
| STT | Sarvam `saarika:v2.5`, te-IN | ~0.37 s speech-end → transcript |
| LLM | Groq `openai/gpt-oss-120b`, `reasoning_effort=low` | ~0.35 s first token |
| TTS | Cartesia `sonic-3.5`, Telugu | ~0.10 s first audio |
| Turn detection | Local GBM forest (above) | ~5–7 ms per score |

`reasoning_effort=low` is not cosmetic: measured TTFT p50 **631 ms with the
parameter against 1,699 ms without**, and speech on 5/5 requests instead of 2/5.
Groq rejects `"none"` for this model, so `low` is the floor.

---

## 8. Every latency technique in the live system

The budget lives in `latency_budget.yaml` and is **loaded at runtime, enforced
per turn, and validated in CI** — not documentation.

| Technique | Mechanism | Measured effect |
|---|---|---|
| **Single-prompt architecture** | One stable prefix per call | Cache survives the whole call; **97.5%** of tokens cached by call 3 |
| **Layer ordering** | Constants first, state block last | Keeps the prefix byte-identical |
| **Prompt-cache prewarm** | Send the prompt during the greeting, 1-token cap | First-turn TTFT **0.674 s → ~0.281 s** |
| **LLM hedging** | Fire N completions, speak the first | p50 0.517 → 0.355 s, p90 1.132 → 0.390 s |
| **TTS token streaming** | Cartesia `TextAggregationMode.TOKEN` | **p50 1.096 s → 0.877 s** (run 392 → 776) |
| **Trained turn detector** | Prosody forest instead of a silence timer | Ends 33.9–43.9% of turns early |
| **Just-in-time coaching** | Catalogue outside the prompt, 1–2 rows per turn | ~220 chars/turn vs 86,310 in-prompt |
| **Register correction in code** | Post-generation dictionary, not prompt text | Zero tokens, cannot be ignored |
| **Reply bounds** | Stop sequences, token cap | Prevents the paragraph that costs a turn |

### Techniques evaluated and rejected, with the measurement
Honesty about what did *not* work is part of the architecture:

- **Trimming prompts.** Controlled sweep, cache-warmed and interleaved: the
  across-tier effect (0.339 s) sits **inside** the within-tier noise (0.786 s).
  Reasoning output was flat at every size. **Cancelled** — and the standing rule
  "never trim prompts for latency" stands.
- **Deciding the endpoint earlier.** 0.10 s earlier moved early-ended turns
  33.2% → 21.1% and mean endpoint **up** 0.718 → 0.753 s. **Deciding sooner
  makes calls slower**, and spends against the 2% false-interruption floor.
- **Moving vendors to India.** Already there: Groq 30.8 ms, Cartesia 21.1 ms,
  Sarvam 37.8 ms RTT. Closed.
- **Speculative generation.** Now **fails closed**: it generated from the wrong
  prompt with an empty state block, so a hit would have spoken a reply with no
  answer-first rule, no ask cap and no repeat guard.
- **Fillers.** Machinery sound, disabled after two live failures — a spliced
  clip does not sound like the sentence it precedes.

---

## 9. Where latency stands

Measured on real telephony, wf2 run 776, 14 turns:

| | Before | Now | Budget |
|---|---|---|---|
| **p50 TOTAL** | 1,096 ms | **877 ms** | 800 ms |
| endpoint (p50) | — | **390 ms** | 250 ms |
| LLM first token | 527 ms | 351 ms | 200 ms |
| TTS first audio | 69 ms | 106 ms | 190 ms ✓ |

**13 of 14 turns were under 0.6 s on the endpoint.** The mean is misleading; the
first turn is the outlier, and by design — a one-word "హలో" is shorter than
`MIN_CONFIDENT_TURN_S`, so the detector demands near-certainty before ending it.
That is the rule that stops callers being cut off.

**The number that does not move:** `telephony_overhead_ms: 490`, marked *"NOT
engineerable"*. At 877 ms server-side the caller hears about **1.37 s**. At a
perfect 800 ms they would hear 1.29 s. **A 700 ms experience is not available on
a phone line.**

---

## 10. Honest status — this is not "everything perfect"

Working and verified:
- Answers the caller's question, then asks its own
- Answers off-topic questions ("have you eaten?" → *"లేదు, ఇంకా తినలేదు"*)
- Remembers across turns; the two-ask cap and repeat guard both bite
- Website questions answered from the ontology
- Telugu register: "dot" not *chukka*, phone numbers in English
- 421 tests pass, zero new failures at every step

**Open defects, all observed on run 783:**
1. **The booking offer repeated word for word.** The repeat guard did not catch
   it. Not yet fixed.
2. **The greeting is romanised Telugu** — *"Namaskaram andi, MB Solar Hub nunchi
   Priya matladutunnanu"* — while everything else is Telugu script. The speech
   engine pronounces the two differently. Model-chosen; not in any prompt.
3. **Latency regressed on that call**: p50 1.012 s against 0.877 s, STT 0.616 s
   against 0.436 s, and only 6 of 10 turns under 0.6 s endpoint.

**Blocked, needing one live call:**
- Realtime STT (`saaras:v3-realtime`, ~0.37 s → ~0.11 s). Enabled once, broke
  production — it emits a `final` per stabilised segment, so one "హలో" became
  22 turns. Both root causes are now fixed and tested; it ships dark.
- **Semantic turn detection** — the LLM polled mid-utterance, answering
  ✓ / ○ / ◐ instead of a reply. Written and tested; the marker-versus-`MODE`
  collision is resolved. It needs interim transcripts, so it is blocked behind
  realtime STT.

---

## 11. Summary

Dograh's node graph was **removed**, not tuned. What replaced it is a single
compiled four-layer prompt, a state block that constrains rather than generates,
a trained Telugu turn detector that exists because no vendor ships one, and a
set of deterministic gates that run before any audio reaches the caller.

Dograh keeps the campaigns, the telephony and the dashboard. Pipecat keeps the
audio engine. Vaani owns the conversation — and the measured result is
**1,096 ms → 877 ms per turn**, with the qualification data still captured in
full.
