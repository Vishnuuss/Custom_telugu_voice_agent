# Latency Engineering Plan
## Project Vaani — Sub-800ms Target

| Field | Value |
|---|---|
| Document ID | LAT-001 |
| Version | 1.0 |
| Date | 2026-08-23 |
| Status | Draft |
| Supersedes | FS-001 §3.1 conclusion; SRS-001 §4.1 targets |
| Preceding documents | FS-001, SRS-001, HLD-001, LLD-001, STT-001 |

> **This document revises the programme's latency position.** The earlier target —
> *parity with the incumbent at 1.95 s* — was anchored to the system being replaced
> rather than to the market. That was the wrong reference point. The sponsor was correct
> to reject it. The target is now **server-side p50 ≤ 800 ms**, and this document sets out
> whether that is achievable, how, and what blocks it.

---

## 1. What the numbers actually are

### 1.1 Measured reality on real phone calls

Independent benchmark, 500 production calls per platform, dual-channel recording, timed
from the caller's last word to the agent's first sound — that is, **what the caller
actually experiences**:

| Platform | p50 | p95 |
|---|---|---|
| Telnyx | **1,296 ms** | 1,856 ms |
| ElevenLabs | 1,424 ms | 1,768 ms |
| Bland AI | 1,520 ms | 2,248 ms |
| **Vapi** | **1,558 ms** | 2,008 ms |
| Retell AI | 1,740 ms | 2,259 ms |

**No platform achieved sub-second latency on real phone calls.**

### 1.2 The measurement gap that explains everything

> Vendor-reported figures run **≈490 ms lower** than caller-experienced figures, because
> vendors measure server-side while the caller additionally absorbs telephony transit,
> jitter buffering, codec conversion and carrier routing.

This single fact resolves the confusion around latency claims:

| Claim | What it is |
|---|---|
| "100 ms latency" | A **component** figure — e.g. OpenAI Realtime's 80–120 ms *processing* latency, or a vendor TTS time-to-first-audio claim. Not voice-to-voice. |
| "sub-500 ms" | **Server-side**, measured from the platform's own endpoint decision. |
| 1,296–1,740 ms | **Caller-experienced**, on real phone lines. The honest number. |

Voice-to-voice 100 ms over PSTN is below network round-trip. It is not achievable by
anyone, and planning against it guarantees the plan fails.

### 1.3 Where the incumbent actually sits

Dograh's measured 1.95 s is a **server-side** figure (`rtf-latency-measured`). Vapi's
caller-side 1,558 ms implies roughly **1,070 ms server-side**.

| | Server-side | Caller-experienced (est.) |
|---|---|---|
| Dograh today | 1,950 ms | ~2,440 ms |
| Vapi | ~1,070 ms | 1,558 ms |
| **Gap to close** | **~880 ms** | |

So the incumbent is not catastrophically behind — it is roughly 880 ms behind, and that
880 ms is identifiable and addressable. This is a tractable engineering problem, not a
wish.

### 1.4 Perception thresholds

| Latency | Caller behaviour |
|---|---|
| < 300 ms | Feels human |
| > 600 ms | Callers begin reverting to touch-tone behaviour |
| > 1,500 ms | Callers hang up |

Sub-500 ms *perceived* is described as the 2026 production standard. The incumbent's
~2.4 s caller-experienced latency sits above the hang-up threshold, which is a
sufficient reason to act on its own.

---

## 1.5 Is ≤800 ms feasible? Yes — with one condition

| Evidence | Reading |
|---|---|
| Budget in §3 closes 1,200 ms and lands at **790 ms** | Meets target with **10 ms** to spare — no slack |
| **OpenAI's flagship speech-to-speech model measures 820 ms** end-to-end | 800 ms is at the frontier, not beyond it |
| A well-engineered cascaded pipeline beats some end-to-end models | The architecture is not the limitation |
| Phases A–C reach ~1,200 ms with **no model training at all** | Most of the win is ordinary engineering |
| Every lever in §3 and §5 is independently measurable | No single point of failure |

**The condition: Telugu turn detection (§4).** Endpointing is 550 ms of the 1,200 ms, and
LiveKit's detector has no Telugu. Without that model the programme lands at ~1,200 ms —
still ahead of four of the five benchmarked platforms, but not at target.

| Outcome | Server-side | Caller hears | vs benchmark field |
|---|---|---|---|
| Phases A–C only | ~1,200 ms | ~1,690 ms | Beats 4 of 5 |
| **Phases A–D (target)** | **≤800 ms** | **~1,290 ms** | **Beats all 5** |

---

## 2. The Target

| ID | Metric | Target | Rationale |
|---|---|---|---|
| **LAT-T1** | **Server-side turn latency, p50, Telugu** | **≤ 800 ms** | Sponsor requirement; beats every benchmarked platform's implied server-side figure |
| LAT-T2 | Server-side turn latency, p95, Telugu | ≤ 1,200 ms | Tail control |
| LAT-T3 | Caller-experienced, p50 (derived) | ≤ 1,300 ms | Would place first against the benchmark table |
| LAT-T4 | Barge-in stop | ≤ 200 ms | Tightened from 300 ms |
| LAT-T5 | Perceived latency with backchannel | ≤ 400 ms | §6 — what the caller *feels* |
| LAT-T6 | English/Hindi server-side p50 | ≤ 600 ms | Turn detector already supports these |

**LAT-T1 is the gate.** LAT-T3 is derived, not independently engineered — the ~490 ms
telephony overhead is carrier physics and is not within the platform's control.

> **Honest framing to hold on to:** ≤800 ms server-side in Telugu would be genuinely
> ahead of the commercial field. It is achievable, but only if §4 is solved. It is not
> a matter of writing tighter code.

---

## 3. Latency Budget

Every millisecond allocated. Current figures are the incumbent's measured values.

> **Corrected 2026-08-23.** An earlier version of this table budgeted 60 ms for TTS on the
> strength of a **vendor claim** (~40 ms time-to-first-audio). The independent Coval
> benchmark, which parses container formats to detect when audio actually arrives rather
> than trusting vendor timestamps, measures the fastest production TTS at **155 ms P50**
> and Cartesia Sonic-3 at **188 ms P50**. The budget below uses the measured figures. This
> removes most of the headroom and is stated plainly rather than smoothed over.

| # | Component | Now | Target | Saving | Lever |
|---|---|---|---|---|---|
| 1 | **End-of-speech detection** | **800 ms** | **250 ms** | **−550 ms** | **Telugu semantic turn detector (§4)** |
| 2 | STT finalisation after endpoint | ~200 ms | 100 ms | −100 ms | Streaming partials; finalise on endpoint, don't re-decode |
| 3 | **LLM → first spoken token** | **~600 ms** | **200 ms** | **−400 ms** | **Non-reasoning model on LPU-class inference (§5.2)** |
| 4 | TTS time-to-first-audio | ~190 ms | 190 ms | 0 ms | Already near the measured floor — see correction above |
| 5 | Internal transport / queuing | ~200 ms | 50 ms | −150 ms | Co-location, in-process Brain |
| | **Server-side total** | **1,990 ms** | **790 ms** | **−1,200 ms** | |
| | *Headroom under LAT-T1* | | **10 ms** | | **None. The target is exactly met, not beaten** |
| | Telephony overhead (not controllable) | +490 ms | +490 ms | — | Carrier physics |
| | **Caller-experienced** | **~2,480 ms** | **~1,280 ms** | | Would rank **1st** vs §1.1 |

> **Consequence of the correction: there is no slack.** Every component must hit its
> number. If TTS cannot go below ~190 ms on Telugu, then endpointing, LLM and transport
> must each land on target for LAT-T1 to hold. Two mitigations exist and both are already
> in the plan: backchannel acknowledgement (§6), which decouples *perceived* latency from
> measured latency, and sentence-level streaming (§5.3), which overlaps TTS with
> generation rather than sequencing them.

> **Note on component 3.** The incumbent's `llm ttfb 0.09 s` is a decoy: on a reasoning
> model it times the first *reasoning* token, not the first token that becomes speech.
> Real time-to-first-spoken-token is roughly 600 ms because the model deliberates first.
> This is why the budget shows 600 ms, not 90 ms.

---

## 3A. The Reference Stack

The architecture keeps every provider behind a port (HLD ADR-04, LLD §1.2), so these are
**starting hypotheses to be measured, not decisions**. But a plan that says only
"pluggable" is not actionable, so this section names what v1 starts with and why.

### ⚠ 3A.0 The honest caveat that governs this whole section

**No public benchmark measures any of these providers on Telugu.**

- The Coval TTS benchmark covers English, French, German, Spanish and Portuguese. Its
  latency leader (Gradium, 155 ms) **supports only those five languages — not Telugu.**
- STT benchmark sources state plainly that figures vary by audio condition and that
  Telugu-specific numbers require testing with your own audio.
- LLM TTFT figures are language-agnostic, but **Telugu tokenises expensively** (350–480
  completion tokens per reply on this workload), so throughput matters far more than it
  would for English.

Every number below is therefore an **English-derived estimate**. This is precisely why
STT-001 Level 0 (corpus + benchmark harness) is scheduled in Phase 1 and gates everything
else: **the stack must be selected on measurement against your own Telugu audio, not on
vendor pages.**

### 3A.1 Speech to text — budget 100 ms

| Candidate | Streaming latency | Telugu | Assessment |
|---|---|---|---|
| **Sarvam** (`saarika`) | Unpublished | **Native Indian focus** | **v1 baseline** — already in production here, known-good on Telugu |
| Deepgram Flux / Nova | Lowest measured; **phone-audio optimised** | Limited Telugu | Evaluate — phone-audio tuning matters on 8 kHz calls |
| ElevenLabs Scribe v2 Realtime | **<150 ms over WebSocket** | Broad coverage | Evaluate — strongest published streaming latency |
| Google Chirp | Higher | **125+ languages**, strong Indic | Evaluate — likely best coverage, not best latency |
| Reverie | Unpublished | 11+ Indian incl. Telugu | Evaluate — India-specialist |
| **Self-hosted IndicConformer** | Yours to tune | **Telugu-native, MIT** | **The v2 destination** (STT-001 L3) — marginal cost →0 |

**Decision: start on Sarvam, benchmark all six on the Level 0 corpus, switch on evidence.**
Deepgram's phone-audio optimisation and Scribe's sub-150 ms streaming make them the two
most likely challengers.

### 3A.2 Text to speech — budget 190 ms

Independent Coval benchmark, P50 TTFA, continuously re-tested, **English**:

| Model | P50 TTFA | IQR | Telugu |
|---|---|---|---|
| Gradium | **155 ms** | **2 ms** | ✗ 5 languages only |
| **Cartesia Sonic-3** | **188 ms** | 100 ms | ✓ in production here |
| ElevenLabs Turbo v2.5 | 264 ms | — | ✓ |
| ElevenLabs Flash v2.5 | 288 ms | 28 ms | ✓ |
| Deepgram Aura-2 | 313 ms | 68 ms | Limited |
| ElevenLabs Multilingual v2 | 1,232 ms | — | ✓ |
| OpenAI TTS-1-HD | 2,295 ms | — | ✓ |

**Two things to note.**

1. **Cartesia's 100 ms IQR is the widest in the table** — 50× Gradium's. A low median with
   a wide spread means most calls feel fast and a meaningful minority feel broken. For
   NFR-PERF-02 (p95 ≤1,200 ms), *consistency matters as much as the median*.
2. **Sarvam Bulbul v3** reportedly outperforms Cartesia Sonic-3 on quality evaluations and
   is India-focused, but publishes no latency figures.

**Decision: retain Cartesia Sonic-3 as v1 baseline** (in production, Telugu-capable);
**benchmark Sarvam Bulbul v3 head-to-head on Telugu for both TTFA and IQR.** Longer term,
AI4Bharat **Indic-TTS** is open source and covers Telugu — the route to owning TTS as
well as STT.

### 3A.3 Language model — budget 200 ms to first *spoken* token

| Provider | TTFT | Throughput (Llama 3.3 70B) | Note |
|---|---|---|---|
| **Groq** (LPU) | **~120 ms** | ~750 tok/s | Lowest TTFT; open-weights only; already in use here |
| **Cerebras** (WSE-3) | ~150 ms | **~2,100 tok/s** | 2.8× throughput — matters for Telugu |
| Others | Higher | Varies | — |

Voice requires TTFT under ~300 ms; both qualify.

**Why throughput matters unusually much here.** Telugu replies run 350–480 completion
tokens. At 750 tok/s a full reply takes ~530 ms; at 2,100 tok/s, ~190 ms. Sentence-level
streaming (§5.3) means only the *first sentence* gates speech, so:

```
  first spoken token  ≈  TTFT  +  (first sentence ÷ throughput)
  Groq:      120 ms + (~50 tok ÷ 750)   ≈ 187 ms   ✓ within budget
  Cerebras:  150 ms + (~50 tok ÷ 2,100) ≈ 174 ms   ✓ within budget
```

Both fit. Groq wins on TTFT, Cerebras on tail behaviour for long replies.

**Model choice is the open question, not the host.** The incumbent runs
`openai/gpt-oss-120b` — a *reasoning* model whose deliberation is the 600 ms in the
budget. A non-reasoning model is now viable (§5.2), but the candidates must be gated on
**Telugu conversation quality**, where `llama-3.3-70b` previously "muddled through".

**Decision: stay on Groq for v1** (in production, lowest TTFT); evaluate 2–3 non-reasoning
models against the STT-001 scenario set; **quality gates the choice, speed only breaks
ties**. Keep Cerebras as the fallback if long-reply tails hurt p95.

### 3A.4 v1 reference stack, summarised

| Layer | v1 choice | Rationale | v2 direction |
|---|---|---|---|
| Transport | **LiveKit** (self-host or Cloud) | ADR-01 | — |
| Endpointing | **Hybrid**, then fine-tuned Telugu detector | §4 — the blocker | Telugu turn-detector model |
| STT | **Sarvam** | Telugu-native, in production | Self-hosted IndicConformer |
| LLM | **Groq**, non-reasoning model TBD | Lowest TTFT; quality-gated | Cerebras if tails hurt |
| TTS | **Cartesia Sonic-3** | In production; benchmark vs Bulbul v3 | AI4Bharat Indic-TTS |
| Telephony | Vobiz or Plivo SIP | FS-001 §3.5 | — |

**This is deliberately the incumbent's stack, minus the reasoning model, plus a trained
endpointer.** That is not timidity — it means the ~1,200 ms saving comes from *how the
components are chosen, placed and sequenced*, not from swapping vendors and hoping. Every
substitution above must earn its place on the Level 0 corpus.

---

## 4. The Blocker: Telugu Turn Detection

**This is the single item on which the ≤800 ms target depends.** It is worth more than
everything else in §3 combined.

### 4.1 The problem

LiveKit Turn Detector v1 — fine-tuned from Qwen2.5-0.5B-Instruct, CPU-inferable, free on
LiveKit Cloud, and the framework default — supports **14 languages**:

> English, Spanish, French, German, Italian, Portuguese, Dutch, Chinese, Japanese,
> Korean, Indonesian, Turkish, Russian, **Hindi**.

**Telugu is not among them.**

Semantic turn detection is what collapses endpointing from a silence timer to a
prediction: rather than waiting to see whether the caller has stopped, the model decides
whether the utterance is *complete*. That is what buys the 550 ms.

Without it, Telugu is confined to silence-threshold endpointing, and that threshold
**cannot safely go below ~0.6 s** — documented, not theoretical: at 0.35 s callers on
this system repeatedly protested being cut off mid-sentence
("ఎందుకు కట్ చేస్తున్నావ్?").

> **0.6 s of endpointing alone consumes 75% of an 800 ms budget.** Sub-800 ms in Telugu
> is arithmetically impossible without solving this.

### 4.2 The consequence for the plan

| Language | Turn detector | ≤800 ms reachable? |
|---|---|---|
| English | Supported | Yes, ≤600 ms |
| Hindi | Supported | Yes, ≤600 ms |
| **Telugu** | **Not supported** | **Only after §4.3** |

### 4.3 The Telugu turn-detector workstream

**Precedent exists.** Published work (arXiv 2510.04016) built semantic end-of-turn
detection for **Thai**, likewise unsupported. The base model is small (0.5 B) and
fine-tuning is tractable.

**This work shares almost everything with the STT workstream (STT-001):** the same
recordings, the same consent filter, the same segmentation, the same annotation effort.
Building both from one corpus is materially cheaper than building either alone.

| Stage | Work |
|---|---|
| TD-1 | Extend the STT-001 corpus with **turn-boundary annotation** — for each utterance, was the speaker finished or pausing mid-thought? |
| TD-2 | Mine negatives from real failures: the mid-sentence pauses that caused false interruptions |
| TD-3 | Fine-tune the Qwen2.5-0.5B base on Telugu turn boundaries |
| TD-4 | Calibrate the per-language threshold (`languages.json`) for Telugu |
| TD-5 | Serve on CPU alongside the session worker; measure added inference latency |
| TD-6 | A/B against the silence-threshold endpointer on live calls, measuring **both** latency and false-interruption rate |

### 4.4 The tradeoff that must be measured, not assumed

Faster endpointing means more false interruptions. That is the trade that made 0.8 s the
right answer on the incumbent, and it is a real constraint, not timidity.

**Therefore every latency gate is paired with an interruption gate:**

| Metric | Target |
|---|---|
| Endpoint decision time, p50 | ≤ 250 ms |
| **False interruption rate** | **≤ incumbent at 0.8 s** |
| Caller complaints about interruption in UAT | **0** |

> A latency win purchased with interruptions is not a win. Callers on this system have
> already told us so, in Telugu, on a recorded line.

### 4.5 Interim position

Until TD-6 passes, Telugu runs a **hybrid endpointer**: the semantic model proposes,
a reduced silence threshold confirms. Expected interim endpointing ~450–550 ms, giving
server-side ~900–1,000 ms — already better than Vapi's implied server-side figure, while
the detector matures.

---

## 4A. Alternative Considered: Speech-to-Speech

**Question raised by the sponsor:** could a single realtime speech-to-speech (S2S) model —
audio in, audio out, no STT→LLM→TTS chain — reach the target more easily?

**Answer: no. It would make the target harder to hit and would cost two of the
programme's three justifications.**

### 4A.1 S2S is not automatically faster

| Model | Measured end-to-end TTFT |
|---|---|
| OpenAI `gpt-realtime-1.5` | **0.82 s** |
| OpenAI GPT-4o Realtime | 80–120 ms *processing only* — not voice-to-voice |
| Gemini 3.1 Flash Live | **2.98 s** |

> A well-engineered cascaded pipeline, with TTS streaming first audio in ~100–250 ms,
> **beats some end-to-end models on voice-to-voice latency.**

OpenAI's own flagship S2S model sits at **820 ms** — essentially identical to the 800 ms
cascaded target in §3. So S2S offers no latency advantage here, while removing every
component-level lever that makes the target reachable.

Note also the 80–120 ms figure: that is *processing* latency, the same category of
component number as Cartesia's 40 ms TTS. It is not voice-to-voice, and it is the likely
origin of the "100 ms" claims in circulation.

### 4A.2 S2S has essentially no Telugu

| Model | Indian language support |
|---|---|
| OpenAI Realtime | Not published for Telugu; quality unverified |
| Gemini Live | Not published for Telugu |
| Qwen3-TTS | 10 languages — **Telugu not included** |
| Moshi (open source, 7B, sub-200 ms, full-duplex) | English/French |

The one encouraging data point: **Hindi-Moshi** exists — the Moshi architecture adapted
into the first full-duplex spoken dialogue model for Hindi. That proves the adaptation
path is real for Indian languages, but it is a research programme, not a v1 decision.

### 4A.3 S2S destroys two of the three justifications

| Justification | Under cascaded | Under S2S |
|---|---|---|
| Architectural control (tool calling) | Full | Reduced — shallow tool surface |
| **Speech-recognition ownership** | **Full — the entire STT-001 ladder** | **GONE.** No STT to swap, boost, correct, race or fine-tune. There is no transcript stage to own |
| Latency leadership | Component-level control | Vendor's number, take it or leave it |
| Cost | $0.0095–$0.17/min, predictable | $0.00165–$0.30/min — OpenAI Realtime at **$0.30/min** |
| Vendor choice | 5+ STT, 7+ TTS, dozens of LLMs | **Two vendors: OpenAI and Google** |

> **This is the decisive point.** FS-001 §10 identifies Telugu ASR ownership as the
> primary justification for building this platform at all. S2S has no ASR stage to own.
> Adopting it would mean rebuilding the platform in order to surrender the capability the
> platform exists to provide — and returning to per-minute pricing set by one of two
> vendors, which is the position the project is escaping.

### 4A.4 What the market does

Cascaded dominates enterprise deployment for debuggability, compliance and provider
flexibility. S2S is growing for short conversational use cases where latency dominates
and the tool surface is shallow. Outbound sales qualification with tool calls, transfer,
extraction and compliance obligations is not that use case.

### 4A.5 Decision

**Remain cascaded.** Reasons, in order:

1. No latency advantage — OpenAI's best S2S is 820 ms against our 800 ms target
2. No usable Telugu
3. Eliminates the STT ownership that justifies the project
4. Restores per-minute vendor lock-in at up to $0.30/min
5. Weaker tool calling, which is justification #1

**Revisit when** a Telugu-capable full-duplex model exists that can be self-hosted. The
Hindi-Moshi precedent, plus AI4Bharat's open-source **Indic-TTS covering 13 Indian
languages including Telugu**, suggests that becomes plausible within a few years. Tracked
as a v3 research item, not a v1 option.

> **Adjacent finding worth acting on later:** AI4Bharat Indic-TTS is open source and
> covers Telugu. That is a route to owning the **TTS** layer as well as STT, driving
> another per-minute cost toward zero. Recorded in STT-001's successor scope, not v1.

---

## 5. The Other Levers

### 5.1 Co-location (−150 ms, high confidence)

If STT, LLM and TTS providers are served from outside India, each round trip carries
150–250 ms of avoidable transit — and there are three of them per turn.

| Action | Detail |
|---|---|
| Audit provider regions | Determine where Sarvam, Groq and Cartesia actually serve from |
| Prefer Indian regions | Where offered |
| Co-locate the platform | Same region as the majority of providers |
| Measure per-provider RTT | Recorded per turn, per LAT-M2 |

This is the cheapest large win in the plan and requires no model work.

### 5.2 Non-reasoning LLM (−400 ms) — unlocked by the new architecture

The incumbent runs `openai/gpt-oss-120b`, a **reasoning** model that emits hundreds of
hidden deliberation tokens before its first spoken word.

A faster non-reasoning model was previously **rejected** — `llama-3.3-70b-versatile`
could not perform Dograh node transitions, emitting tool calls as literal speech.

> **That objection no longer applies.** It was a defect of the *node-graph* execution
> model. Project Vaani has no graph (HLD ADR-03) and uses native tool calling. The
> constraint that forced a reasoning model is removed by the architecture change.

| Action | Detail |
|---|---|
| Re-evaluate fast non-reasoning models | Against the STT-001 scenario set |
| Gate on quality, not speed alone | Conversation evaluation must not regress |
| Keep the LLM Port abstraction | Model choice stays configuration (LLD §1.6) |
| Retain a reasoning model as fallback | Per-agent, if quality demands it |

### 5.3 Streaming and sentence-level TTS (−200 ms perceived)

| Technique | Effect |
|---|---|
| Synthesise and speak the **first sentence** while the model still generates | Removes full-generation wait |
| Stream TTS audio chunk-by-chunk | Already required (FR-PIPE-16) |
| Cancel synthesis mid-stream on barge-in | Required (LLD §1.3) |
| Shorten spoken Telugu lines | Telugu tokenises expensively; TTS time scales with output length |

> Shortening *spoken output* is the one prompt-side latency lever that pays. Shortening
> *instructions* is worth ~0.1 s and costs objection-handling quality. That distinction
> stands.

### 5.4 TTS selection (0 ms saving — but protects the p95)

**No latency saving is available here.** The measured floor for production TTS is ~155 ms
(Gradium, English-only) and Cartesia Sonic-3 is already at 188 ms. The earlier ~40 ms
figure was a vendor claim and has been withdrawn from the budget.

What *is* available is **consistency**. Cartesia's 100 ms IQR is the widest of the
benchmarked models — 50× the tightest. A wide spread means a meaningful minority of calls
feel broken even when the median looks good, which is exactly what NFR-PERF-02 (p95)
exists to catch.

| Action | Purpose |
|---|---|
| Benchmark Sarvam Bulbul v3 vs Cartesia Sonic-3 on **Telugu**, for TTFA **and IQR** | Neither is measured on Telugu publicly |
| Judge on voice quality first, latency second | A fast voice nobody wants to listen to is worthless |
| Track AI4Bharat Indic-TTS | Open source, covers Telugu — route to owning TTS |

### 5.5 Speculative execution (−100 ms, opportunistic)

Begin LLM inference on the partial transcript **before** the endpoint fires; discard if
the caller continues. Costs tokens, saves wall-clock. Measure the discard rate before
committing — if callers frequently continue, this is waste rather than saving.

---

## 6. Perceived Latency

Measured latency and felt latency are different, and the caller only experiences the
second.

| Technique | Effect | Requirement |
|---|---|---|
| **Backchannel** — a natural "అవునండి" / "సరే" within ~200 ms | Caller hears immediate acknowledgement; real response follows behind | New: FR-PIPE-18 |
| Filler speech before slow tool calls | "ఒక్క సెకను, చూస్తాను…" | FR-PIPE-17 |
| Begin speaking on first sentence | §5.3 | FR-PIPE-16 |

**LAT-T5 targets ≤400 ms perceived.** Backchannelling is not a trick to hide a slow
system — it is how humans actually hold turns in conversation, and its absence is part
of why agents sound mechanical.

---

## 7. Live Human Transfer

Promoted from v2 "Could" to **v1 Must** at sponsor request.

| ID | Requirement | Priority | Release |
|---|---|---|---|
| FR-TEL-07 | The system shall transfer a live call to a human agent, warm or cold, preserving the caller's audio session without a perceptible gap. | **M** | **v1** |
| FR-TEL-10 | Transfer shall be invocable **as a tool by the Brain**, at any point in the conversation. | M | v1 |
| FR-TEL-11 | On warm transfer, the system shall deliver a spoken or textual summary of the call to the receiving human. | S | v1 |
| FR-TEL-12 | If no human is available, the system shall fall back to a configured path (callback capture or voicemail) and never drop the caller. | M | v1 |
| FR-TEL-13 | Transfer outcome shall be recorded as a disposition with the receiving party identified. | M | v1 |
| NFR-LAT-T7 | Time from transfer decision to human connection | ≤ 3 s, with continuous audio (music or speech) |

> FR-TEL-10 is only possible because of ADR-03. On a node graph, transfer must be a node
> the conversation is routed to — the same structural limitation that blocks appointment
> booking. With native tool calling, the model can hand off the moment the caller asks
> for a human.

---

## 8. Measurement

Targets are meaningless without a measurement method that cannot flatter itself.

| ID | Rule |
|---|---|
| **LAT-M1** | Report **server-side and caller-experienced separately**, always. Never quote one as the other. |
| **LAT-M2** | Record every component boundary per turn (LLD §2.1 `turn`): endpoint decision, STT final, LLM first token, LLM first *spoken* token, TTS first audio. |
| **LAT-M3** | Caller-experienced latency is validated by **dual-channel recording of real calls**, timed from the audio — the method used in §1.1 — not from platform timestamps. |
| **LAT-M4** | **Never report model TTFB as responsiveness.** On reasoning models it measures the first reasoning token. Any report headlining TTFB is defective. |
| **LAT-M5** | Every latency figure is reported alongside the **false-interruption rate** from the same run. |
| **LAT-M6** | Report p50 **and** p95. A good median with a bad tail is a bad agent. |

---

## 9. Work Breakdown — WBS 10

| ID | Package | Days | Release |
|---|---|---|---|
| 10.1 | Latency instrumentation to component granularity (extends 2.7) | 2 | v1 |
| 10.2 | Dual-channel real-call measurement harness (LAT-M3) | 3 | v1 |
| 10.3 | Provider region audit and co-location | 3 | v1 |
| 10.4 | Non-reasoning LLM evaluation and switch | 4 | v1 |
| 10.5 | Sentence-level streaming TTS + Sonic 4 upgrade | 3 | v1 |
| 10.6 | Backchannel implementation (FR-PIPE-18) | 3 | v1 |
| 10.7 | **Telugu turn-boundary annotation** (extends STT-001 9.1.3/9.1.4) | 4 | v1 |
| 10.8 | **Telugu turn-detector fine-tune (TD-3/TD-4)** | 8 | v1 |
| 10.9 | **Turn-detector serving + hybrid endpointer (TD-5)** | 4 | v1 |
| 10.10 | **A/B latency vs interruption evaluation (TD-6)** | 3 | v1 |
| 10.11 | Speculative execution (opportunistic) | 3 | v2 |
| 10.12 | Live human transfer (§7) | 5 | v1 |
| | **v1 subtotal** | **42** | |
| | *v2* | *3* | |

### 9.1 Revised programme effort

| | Previous | Revised |
|---|---|---|
| v1 base | 133 d | 133 d |
| WBS 9 — STT (v1 portion) | 13 d | 13 d |
| **WBS 10 — Latency (v1)** | — | **42 d** |
| **v1 total** | 146 d | **188 d** |
| **v1 with 30% contingency** | ~190 d | **~244 d** |

> The ≤800 ms target adds roughly **42 engineering-days**, of which **19 days
> (10.7–10.10) are the Telugu turn detector alone**. That is the price of the target, and
> it should be paid knowingly. Without those 19 days the target is unreachable in Telugu
> and the rest of the latency work delivers ~1,200 ms rather than ~800 ms.

---

## 10. Gates

| Gate | Criterion |
|---|---|
| **L-G1** | Instrumentation live; incumbent baseline captured **server-side and caller-side** |
| **L-G2** | Co-location + non-reasoning LLM + streaming TTS delivered → server-side p50 ≤ 1,200 ms, no quality regression |
| **L-G3** | Telugu turn detector beats the silence endpointer on latency **at equal or better false-interruption rate** |
| **L-G4** | **Server-side p50 ≤ 800 ms in Telugu** (LAT-T1) with zero interruption complaints in UAT |
| **L-G5** | Caller-experienced p50 ≤ 1,300 ms verified by dual-channel real-call measurement |
| **L-G6** | Live transfer works end to end within NFR-LAT-T7 |

**L-G4 supersedes the former "quality parity" gate G4.** Parity is no longer the
standard.

---

## 11. Risks

| ID | Risk | P | I | Score | Response |
|---|---|---|---|---|---|
| **LR-1** | **Telugu turn detector does not reach usable accuracy** | 3 | 5 | **15** | Hybrid endpointer (§4.5) delivers ~900–1,000 ms as a floor; Thai precedent suggests feasibility; corpus shared with STT-001 |
| **LR-2** | Faster endpointing raises interruptions and callers complain | 3 | 5 | 15 | Every latency gate paired with an interruption gate (§4.4); UAT judged by ear |
| **LR-3** | Non-reasoning model degrades conversation quality | 3 | 4 | 12 | Gate on the scenario set; LLM Port keeps reversal to configuration |
| **LR-4** | Providers offer no Indian region; co-location saving unavailable | 2 | 3 | 6 | Re-evaluate provider mix; treat as a selection criterion |
| **LR-5** | 800 ms proves unreachable in Telugu even after TD work | 2 | 4 | 8 | Publish the achieved figure honestly; ~1,000 ms still beats every benchmarked platform |
| **LR-6** | Latency work crowds out campaign delivery | 3 | 3 | 9 | WBS 10 is 42 d; sequence 10.1–10.6 first (cheap wins) before 10.7–10.10 |
| **LR-7** | Team optimises the metric rather than the experience | 3 | 4 | 12 | LAT-M5 and LAT-T5; UAT acceptance is by ear (NFR-QUAL-08) |

---

## 12. Sequencing

Cheap and certain first; expensive and uncertain second.

```
  Phase A  (10.1-10.3)   instrument + co-locate      →  ~1,600 ms   low risk
  Phase B  (10.4-10.5)   non-reasoning LLM + TTS     →  ~1,200 ms   L-G2
  Phase C  (10.6, 10.12) backchannel + transfer      →  ~400 ms perceived
  Phase D  (10.7-10.10)  Telugu turn detector        →  ≤800 ms     L-G4
```

**Phases A–C reach ~1,200 ms server-side (~1,690 ms caller-side) without any model
training** — already better than four of the five benchmarked platforms. Phase D is what
buys the last 400 ms, and it is where the difficulty and the differentiation both live.

---

## 13. Changes to Preceding Documents

| Document | Change |
|---|---|
| FS-001 §3.1 | Conclusion revised: latency **is** a valid objective, via component replacement rather than orchestration rewrite |
| FS-001 §10 | Third justification added: latency leadership |
| SRS-001 §4.1 | NFR-PERF-01/02/03 replaced by LAT-T1…T6 |
| SRS-001 §3.1 | FR-TEL-07 promoted to **Must, v1**; FR-TEL-10…13 added |
| SRS-001 §3.2 | FR-PIPE-18 (backchannel) added |
| TP-001 §7.1 | Measurement rules replaced by LAT-M1…M6; dual-channel method added |
| PMP-001 §3 | WBS 10 added; v1 effort 146 → 188 d |
| STT-001 §4 | Corpus extended with turn-boundary annotation |

---

## Appendix A — What changed and why

The original plan concluded that orchestration overhead was <5% of turn latency and
therefore that rebuilding for speed was unjustified. **That analysis was correct and its
conclusion was wrong**, because it answered the wrong question.

Orchestration overhead is indeed negligible. But the platform does not merely *host* the
components — it **chooses** them, **places** them, and decides **when to stop listening**.
Those three decisions are where the 1,290 ms lives:

| Decision | Saving |
|---|---|
| When to stop listening (turn detection) | 550 ms |
| Which model reasons | 400 ms |
| Where components run, and how output streams | 340 ms |

None of those are available on a managed platform. So latency belongs on the
justification list after all — not because the orchestrator is slow, but because
**owning the orchestrator is what makes the component decisions yours.**

The sponsor was right to insist. The correction is recorded here rather than quietly
patched, because the earlier reasoning is referenced elsewhere in the document set.
