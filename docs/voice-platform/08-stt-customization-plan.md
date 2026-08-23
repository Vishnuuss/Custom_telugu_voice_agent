# Speech Recognition Customization Workstream
## Project Vaani — Telugu ASR Ownership Plan

| Field | Value |
|---|---|
| Document ID | STT-001 |
| Version | 1.0 |
| Date | 2026-08-23 |
| Status | Draft |
| Preceding documents | FS-001 §3.3, SRS-001, HLD-001 ADR-04, LLD-001 §1.2, TP-001 §7.2 |
| Workstream owner | Engineering |

---

## 1. Why this workstream exists

FS-001 concluded that the entire justification for building this platform is **control**,
and that the most valuable form of that control is ownership of the speech recognition
layer. The originating complaint was blunt and correct:

> *"for Telugu all are trash"*

That is a true statement about **generic** Telugu ASR. It is not a permanent condition.
It is a solvable engineering problem, and it is solvable **only** by owning the pipeline.
On Vapi or Dograh it is unsolvable at any price, because neither lets you replace or
train the recognition model.

This document turns that from a paragraph in a feasibility study into a planned
workstream with requirements, a data pipeline, an evaluation method, effort estimates and
risks.

### 1.1 Why Telugu ASR fails on these calls specifically

Four compounding causes, each with a different remedy:

| # | Cause | Remedy | Level |
|---|---|---|---|
| C1 | Generic models are trained on read/broadcast speech, not spontaneous telephone speech | Domain fine-tuning | 3 |
| C2 | **Entities** — customer names, city names, amounts, product terms — are rare tokens the model has barely seen | Vocabulary boost, then entity-dense training | 1 → 3 |
| C3 | Telephone audio is 8 kHz, narrowband, noisy, often speakerphone | Train on real call audio at real bandwidth | 3 |
| C4 | Code-mixing — Telugu with English loanwords (loan, EMI, subsidy, interest) | Mixed-script training data | 3 |

> C2 is the highest-leverage. Overall word error rate can look acceptable while the words
> that actually decide the call outcome — *whose* name, *which* city, *how much* — are
> wrong. Published Indic ASR work reports the gap concentrates precisely on entity-dense
> audio, which matches what these calls show.

---

## 2. The Four-Level Ladder

Levels are cumulative and independently valuable. **Each level ships and is measured on
its own** — the workstream is not a single bet on level 3.

| Level | Capability | Release | Marginal STT cost | Effort |
|---|---|---|---|---|
| **L0** | **Measure** — corpus, baseline, entity metric | **v1, Phase 1** | — | 6 d |
| **L1** | **Tune** — vocabulary boost, provider selection | **v1** | unchanged | 4 d |
| **L2** | **Correct** — LLM transcript repair, engine racing | **v1** | small increase | 7 d |
| **L3** | **Own** — self-hosted fine-tuned IndicConformer | **v2** | **→ near zero** | 28 d |

```
   L0  measure ──▶ L1  tune ──▶ L2  correct ──▶ L3  own
    │              │            │               │
  WER +          keyword      LLM repair     fine-tuned
  entity         boost        + racing       IndicConformer
  baseline                                   on your own audio
    │              │            │               │
    └──── every level judged against the L0 baseline ────┘
```

**Design rule:** every level plugs into the same `SttPort` interface (LLD §1.2). No level
requires changes to any other module. That is the whole point of ADR-04.

---

## 3. Requirements

New requirements, to be merged into SRS-001 §3.2 and §4.2.

### 3.1 Functional

| ID | Requirement | Priority | Release |
|---|---|---|---|
| FR-STT-01 | The system shall maintain a held-out Telugu evaluation corpus of real call audio with human-verified reference transcripts. | M | v1 |
| FR-STT-02 | The system shall compute and report Word Error Rate against that corpus for any configured STT implementation. | M | v1 |
| FR-STT-03 | The system shall compute and report **entity accuracy** separately from WER, over a defined entity list (person names, place names, monetary amounts, product terms). | M | v1 |
| FR-STT-04 | The system shall support supplying a per-agent vocabulary/keyword-boost list to STT implementations that accept one, and shall degrade cleanly where they do not. | M | v1 |
| FR-STT-05 | The system shall support an optional transcript correction stage between STT and the Brain, configurable per agent, with a bounded latency budget. | S | v1 |
| FR-STT-06 | The correction stage shall be a no-op when disabled and shall never increase turn latency beyond its configured budget. | M | v1 |
| FR-STT-07 | The system shall support dispatching one audio stream to two STT implementations concurrently and selecting a result by confidence and/or arrival order. | C | v2 |
| FR-STT-08 | The system shall support an STT implementation backed by a self-hosted model server reachable over HTTP/WebSocket. | M | v1 |
| FR-STT-09 | The system shall export a training corpus of call audio and transcripts, restricted to recordings where `training_use_permitted` is true. | M | v1 |
| FR-STT-10 | The training export shall exclude or mask personal data not required for acoustic training, per the consent basis recorded. | M | v1 |
| FR-STT-11 | The system shall support A/B routing of live calls between two STT implementations at a configurable ratio. | S | v2 |
| FR-STT-12 | The system shall record, per turn, which STT implementation and model version produced the transcript. | M | v1 |

> **FR-STT-08, FR-STT-09 and FR-STT-12 are the v1 obligations that make level 3 possible
> later.** If v1 ships without them, level 3 is not merely deferred — it is blocked
> behind a retrofit. This is the single most important scheduling point in this document.

### 3.2 Non-functional

| ID | Requirement | Target |
|---|---|---|
| NFR-STT-01 | WER on the held-out corpus, L1 | ≤ L0 baseline |
| NFR-STT-02 | WER on the held-out corpus, L2 | < L0 baseline |
| NFR-STT-03 | WER on the held-out corpus, L3 | **materially better than baseline** — target set after L0 |
| NFR-STT-04 | Entity accuracy, L3 | **primary success metric** — target set after L0 |
| NFR-STT-05 | Correction stage added latency | ≤ 120 ms p95 |
| NFR-STT-06 | Self-hosted model server STT latency | ≤ hosted provider p95 |
| NFR-STT-07 | Model server availability during calls | ≥ hosted provider, with automatic failover to a hosted STT |
| NFR-STT-08 | Corpus size for L3 training | ≥ 20 hours verified, ≥ 100 hours weakly-labelled (working assumption, revised at L0) |

> **No numeric WER target is asserted for NFR-STT-03/04.** Setting one before the baseline
> exists would be fabrication. The targets are defined as an output of L0 and approved
> before L3 work begins.

---

## 4. Level 0 — Measure (v1, Phase 1)

**Nothing else in this workstream can be judged without this.** It is also already
required by TP-001 as TPR-1/TPR-2, so it is shared work, not additional work.

### 4.1 Corpus construction

```
  MinIO recordings
        │
        ▼
  ┌─────────────────┐   training_use_permitted = true only  (FR-CMP-04)
  │  Consent filter │
  └────────┬────────┘
           ▼
  ┌─────────────────┐   VAD split into utterances; drop bot channel
  │  Segmentation   │
  └────────┬────────┘
           ▼
  ┌─────────────────┐   stratify: vertical × dialect × audio quality × entity density
  │   Sampling      │
  └────────┬────────┘
           ▼
  ┌─────────────────┐   best available ASR draft, then HUMAN correction
  │  Transcription  │
  └────────┬────────┘
           ▼
  ┌─────────────────┐   frozen; never used for training  ← critical
  │ HELD-OUT SET    │
  └─────────────────┘
```

**Held-out discipline.** The evaluation set is frozen and never enters training. A model
evaluated on data it trained on will look excellent and perform badly on real calls. This
is the most common way ASR projects fool themselves.

### 4.2 Corpus specification

| Property | Target |
|---|---|
| Held-out evaluation set | 2–3 hours, human-verified |
| Utterance count | ≥ 1,000 |
| Coverage | All live verticals |
| Audio conditions | Include speakerphone, poor network, background noise — deliberately, not by accident |
| Entity annotation | Names, cities, amounts, product terms marked |
| Reference format | Verbatim, including code-mixed English tokens as spoken |

### 4.3 Metrics

| Metric | Definition |
|---|---|
| **WER** | Standard word error rate, normalised for punctuation and casing |
| **Entity accuracy** | Correctly recognised annotated entities ÷ total annotated entities |
| **CER** | Character error rate — more informative than WER for agglutinative Telugu |
| Per-condition WER | Broken out by audio condition, so a good average cannot hide a bad case |
| Latency | STT finalisation time, per implementation |

> **CER is included deliberately.** Telugu is agglutinative; a single wrong morpheme
> marks a whole word wrong under WER, which overstates degradation and understates
> improvement. CER tracks real progress more honestly.

### 4.4 Baseline capture

Measure **the current Dograh stack** on this corpus before anything is built. Every later
"better" or "parity" claim references this recorded number, not memory.

### 4.5 Deliverables

- Frozen held-out corpus with verified transcripts and entity annotations
- Baseline report: WER, CER, entity accuracy, per-condition breakdown
- Reusable benchmark harness (`stt_bench.py`)
- **Approved numeric targets for NFR-STT-03 and NFR-STT-04**

---

## 5. Level 1 — Tune (v1)

Cheap, immediate, no infrastructure.

### 5.1 Vocabulary boosting

Per-agent keyword lists supplied to the STT where supported (FR-STT-04):

| Category | Examples |
|---|---|
| Product terms | లోన్, ఈఎంఐ, వడ్డీ, సబ్సిడీ, సోలార్, ప్యానెల్ |
| Amount forms | లక్ష, వేల, కోటి |
| Cities | vertical-specific place-name lists |
| Company / agent names | BS Wealth, శ్రేయ, దీప్తి |
| Code-mixed English | loan, EMI, interest, subsidy, tenure |

The `SttCapabilities` declaration (LLD §1.2) governs behaviour: implementations without
boost support ignore the list, and the capability is recorded so evaluation can attribute
results correctly.

### 5.2 Provider selection

Evaluate available Telugu-capable STT providers against the L0 corpus and pick on
evidence rather than reputation. Reuse `compare_models.py`.

### 5.3 Deliverables

- Vocabulary lists per agent, in the agent artefact (`stt.vocabulary`)
- Provider comparison report against the L0 corpus
- L1 measurement vs baseline

---

## 6. Level 2 — Correct (v1 correction, v2 racing)

### 6.1 Transcript correction

A small, fast model repairs the transcript before the Brain sees it.

```
  raw transcript ──▶ Corrector ──▶ corrected ──▶ Brain
                        │
                     bounded: ≤120 ms p95, else pass through unchanged
```

| Design point | Decision |
|---|---|
| Model | Small/fast; correction is not reasoning |
| Prompt | Domain glossary + entity list; instruct minimal edits only |
| Budget | Hard timeout; on expiry the **raw transcript passes through** (FR-STT-06) |
| Safety | Corrector may never introduce content absent from the audio — measured as a hallucination rate |
| Observability | Both raw and corrected text stored on the turn record |

> **The hallucination guard matters more than the accuracy gain.** A corrector that
> invents a plausible amount or name is far worse than one that leaves a garbled word
> alone. Both versions are stored so this is auditable rather than assumed.

### 6.2 Engine racing (v2)

Dispatch one stream to two engines; select by confidence, with arrival order as
tie-breaker (FR-STT-07). STT is a small fraction of per-call cost, so paying twice for it
is usually rational.

Composite `RacingStt` satisfies the same `SttPort` — no other module changes.

### 6.3 Deliverables

- `TranscriptCorrector` with bounded budget and pass-through fallback
- Hallucination-rate measurement
- L2 measurement vs baseline
- (v2) `RacingStt` composite

---

## 7. Level 3 — Own (v2)

Self-hosted, fine-tuned Telugu ASR. This is the level that makes the capability
permanent and drives marginal STT cost toward zero.

### 7.1 Base model

**AI4Bharat IndicConformer** — hybrid CTC-RNNT conformer, all 22 official Indian
languages, **MIT licensed** (commercial use permitted), fine-tunable via AI4Bharat NeMo.

| Property | Value |
|---|---|
| Licence | MIT — no commercial restriction |
| Languages | 22, including Telugu |
| Architecture | Hybrid CTC + RNNT |
| Fine-tuning | Supported, tooling published |
| Deployment | Self-hosted; GPU for training, CPU/GPU for inference |

> Alternatives (Whisper-family, other Indic models) are evaluated at L0 as baselines.
> IndicConformer is the planned base because of licence, Telugu nativeness and
> fine-tuning support together — not any one of those alone.

### 7.2 Training data pipeline

```
   Consented recordings          Synthetic entity-dense audio
   (real, weakly labelled)       (TTS-generated, exactly labelled)
            │                              │
            ├──── human-verified subset    │
            │                              │
            ▼                              ▼
      ┌──────────────────────────────────────────┐
      │            Training corpus                │
      │   real spontaneous speech + entity mass   │
      └────────────────────┬─────────────────────┘
                           ▼
                  Fine-tune IndicConformer
                           ▼
                  Evaluate on FROZEN L0 held-out set
```

**Why synthetic data is in the plan.** Real recordings supply authentic telephone
acoustics and spontaneous speech, but they under-represent the rare tokens that matter —
each customer name appears once. Published work indicates the Indic ASR gap closes
substantially when training data is deliberately **entity-dense**. Generating TTS audio
over your real name/city/amount/product lists produces exactly-labelled, entity-saturated
data cheaply, and combining it with real audio addresses C2 and C4 together.

**Neither source alone is sufficient**: synthetic-only produces a model that fails on real
telephone acoustics; real-only produces a model that still misses entities.

### 7.3 Data governance — gating condition

| Requirement | Detail |
|---|---|
| Consent | Only `training_use_permitted = true` recordings (FR-CMP-04, FR-STT-09) |
| Secondary purpose | ASR training is a **secondary processing purpose** and must be covered by the consent obtained — this is FS-001 open item **OI-4** |
| Minimisation | Export excludes personal data not needed for acoustic training (FR-STT-10) |
| Storage | Training corpora held under the same retention controls as recordings |
| Deletion | A deletion request must remove source audio from the corpus; retraining is not required retrospectively but the corpus must not be reused |

> **OI-4 gates L3 entirely.** No training may begin until the consent basis is confirmed
> in writing. L0/L1/L2 are unaffected — they process audio for the call's own purpose.

### 7.4 Training approach

| Aspect | Plan |
|---|---|
| Compute | Rented GPU hours, not owned hardware |
| Strategy | Fine-tune from the multilingual checkpoint; do not train from scratch |
| Curriculum | Real verified data first, then synthetic entity augmentation, then mixed |
| Validation | A validation split distinct from both training and the frozen held-out set |
| Versioning | Every model version tagged, with its training corpus manifest recorded |
| Stop criterion | Improvement on the held-out set, not on training loss |

### 7.5 Serving

```
  Session Worker ──▶ SelfHostedStt ──▶ Model Server ──▶ fine-tuned IndicConformer
        │                                    │
        └── automatic failover ──▶ hosted STT provider  (NFR-STT-07)
```

| Concern | Design |
|---|---|
| Interface | `SelfHostedStt` implements `SttPort` (FR-STT-08); nothing else changes |
| Failover | Model server unavailable or slow → hosted provider, automatically, logged |
| Rollout | A/B at a configurable ratio (FR-STT-11), starting low |
| Attribution | Every turn records the implementation and model version (FR-STT-12) |
| Rollback | Configuration change; ≤5 min, same mechanism as agent rollback |

> Automatic failover to a paid hosted provider is deliberate. A self-hosted model must
> never be able to take down live client campaigns; that would trade a quality problem
> for an availability problem.

### 7.6 Deliverables

- Training corpus export tooling (consent-filtered)
- Synthetic entity-dense generation tooling
- Fine-tuning pipeline and model registry
- Model server + `SelfHostedStt` adapter
- A/B routing and failover
- L3 evaluation vs baseline and vs L2

---

## 8. Work Breakdown

Appended to PMP-001 as **WBS 9**. Effort in engineering-days, same basis and uncertainty
as PMP §3.

### WBS 9.1 — Level 0 (v1, Phase 1)

| ID | Package | Days | Notes |
|---|---|---|---|
| 9.1.1 | Consent-filtered export from MinIO | 1 | Also serves FR-STT-09 |
| 9.1.2 | Segmentation and stratified sampling | 1 | |
| 9.1.3 | Draft transcription + **human verification** | 3 | The slow part; largely manual |
| 9.1.4 | Entity annotation and entity list | 1 | |
| 9.1.5 | Benchmark harness (WER / CER / entity / per-condition) | 2 | |
| 9.1.6 | Dograh baseline capture | 1 | |
| | **Subtotal** | **9** | *Overlaps TP-001 TPR-1/TPR-2 — ~6 d is shared, not additional* |

### WBS 9.2 — Level 1 (v1)

| ID | Package | Days |
|---|---|---|
| 9.2.1 | Vocabulary boost plumbing + capability degradation | 2 |
| 9.2.2 | Per-agent vocabulary lists | 1 |
| 9.2.3 | Provider comparison against L0 corpus | 2 |
| | **Subtotal** | **5** |

### WBS 9.3 — Level 2

| ID | Package | Days | Release |
|---|---|---|---|
| 9.3.1 | `TranscriptCorrector` with bounded budget + pass-through | 3 | v1 |
| 9.3.2 | Hallucination-rate measurement | 1 | v1 |
| 9.3.3 | Raw + corrected storage on turn record | 1 | v1 |
| 9.3.4 | `RacingStt` composite | 3 | v2 |
| | **Subtotal** | **8** (5 in v1) | |

### WBS 9.4 — Level 3 (v2)

| ID | Package | Days |
|---|---|---|
| 9.4.1 | Training corpus export at scale | 2 |
| 9.4.2 | Synthetic entity-dense audio generation | 4 |
| 9.4.3 | NeMo fine-tuning pipeline setup | 4 |
| 9.4.4 | Training runs and iteration | 8 |
| 9.4.5 | Model registry and versioning | 2 |
| 9.4.6 | Model server deployment | 4 |
| 9.4.7 | `SelfHostedStt` adapter + failover | 3 |
| 9.4.8 | A/B routing and canary rollout | 3 |
| 9.4.9 | L3 evaluation and sign-off | 2 |
| | **Subtotal** | **32** |

### 8.1 Summary and effect on the programme

| Level | Days | Release | In v1 critical path? |
|---|---|---|---|
| L0 | 9 (≈3 net of TP overlap) | v1 Phase 1 | **Yes — gates G4** |
| L1 | 5 | v1 | Yes |
| L2 | 5 of 8 | v1 | Partly |
| L3 | 32 | **v2** | **No** |
| | **~13 net added to v1** | | |
| | **35 for v2 (L2 racing + L3)** | | |

**Revised PMP totals:**

| | Before | After |
|---|---|---|
| v1 effort | 133 d | **~146 d** |
| v1 with 30% contingency | ~173 d | **~190 d** |
| v2 STT workstream | *(unplanned)* | **35 d, now planned** |

### 8.2 The one decision you can overrule

**L3 is planned as v2 and deliberately kept off the v1 critical path.**

| | If L3 stays v2 (recommended) | If L3 moves into v1 |
|---|---|---|
| v1 ships | ~146 d | ~178 d |
| v1 depends on a model training project succeeding | No | **Yes** |
| Blocked by OI-4 consent review | No | **Yes** |
| Telugu quality improves in v1 | Yes — via L1 + L2 | Yes, more |
| Risk of never shipping | Low | Elevated |

**Recommendation: keep L3 in v2.** Model training has genuinely open-ended timelines and
a real chance of needing several iterations. Gating your first release on it risks the
platform never reaching production — and L1+L2 deliver measurable Telugu improvement in
v1 regardless.

**What makes this safe** is that v1 still ships FR-STT-08, FR-STT-09 and FR-STT-12 — the
self-hosted adapter, the consent-filtered export, and per-turn model attribution. L3 then
becomes configuration and training, not a retrofit. That is the difference between
"deferred" and "abandoned", and it is why those three requirements are Must in v1.

> If you want L3 in v1, say so and I will re-cut the plan. It is your call and the
> argument for it — that Telugu quality *is* the product — is not unreasonable.

---

## 9. Evaluation and Gates

| Gate | Criterion | Blocks |
|---|---|---|
| **S-G0** | Corpus frozen, baseline captured, targets approved | G4, all later STT work |
| **S-G1** | L1 measured; WER ≤ baseline; entity accuracy improved | v1 STT sign-off |
| **S-G2** | L2 measured; WER < baseline; hallucination rate acceptable | v1 STT sign-off |
| **S-G3** | OI-4 consent confirmed in writing | **All L3 work** |
| **S-G4** | L3 model beats L2 on the frozen held-out set | L3 rollout |
| **S-G5** | L3 A/B on live calls at parity or better; failover proven | L3 default |

**Every gate is measured on the frozen held-out set from L0.** No exceptions — a model
promoted on training-set numbers is the standard failure mode of this kind of work.

---

## 10. Risks

| ID | Risk | P | I | Score | Response |
|---|---|---|---|---|---|
| **SR-1** | Corpus never assembled; nothing can be judged | 4 | 5 | **20** | Schedule L0 in Phase 1 as blocking; shares work with TPR-1/TPR-2 |
| **SR-2** | Consent basis does not cover training (OI-4) | 3 | 5 | **15** | Start the review now; L0–L2 unaffected; if refused, L3 relies on synthetic + newly-consented audio only |
| SR-3 | Insufficient verified data volume for L3 | 3 | 4 | 12 | Synthetic augmentation; measure the volume early (NFR-STT-08 revised at L0) |
| SR-4 | Fine-tuned model beats baseline on the corpus but not on live calls | 3 | 4 | 12 | A/B rollout (FR-STT-11); live measurement, not corpus-only promotion |
| SR-5 | Corrector hallucinates entities | 3 | 4 | 12 | Minimal-edit prompting; hallucination-rate metric; store raw + corrected |
| SR-6 | Self-hosted serving hurts availability | 2 | 5 | 10 | Automatic failover to hosted (NFR-STT-07); A/B ratio starts low |
| SR-7 | Human transcription effort underestimated | 3 | 3 | 9 | Draft-then-correct; 2–3 h held-out is deliberately modest |
| SR-8 | GPU cost exceeds expectation | 2 | 3 | 6 | Rent, don't own; fine-tune, don't pre-train; E6 input |
| SR-9 | L3 slips indefinitely and the justification is never realised | 3 | 4 | 12 | v1 ships FR-STT-08/09/12 so L3 stays configuration; S-G0 targets make progress visible |

> **SR-1 and SR-9 are the ones to watch.** Both are failure-by-postponement rather than
> failure-by-difficulty, and both are prevented by the same thing: doing L0 in Phase 1
> and shipping the three enabling requirements in v1.

---

## 11. Traceability

| Element | Source / target |
|---|---|
| §1 justification | FS-001 §3.3, §10 |
| §2 ladder | FS-001 §3.3 levels 1–3 |
| FR-STT-01…03 | TP-001 §7.2, SRS NFR-QUAL-01/02 |
| FR-STT-04 | SRS FR-PIPE-04 |
| FR-STT-05/06 | SRS FR-PIPE-05 |
| FR-STT-07 | SRS FR-PIPE-06 |
| FR-STT-08 | HLD ADR-04, LLD §1.2 |
| FR-STT-09/10 | SRS FR-DATA-06, FR-CMP-04 |
| FR-STT-12 | LLD §2.1 `turn` |
| §4 corpus | TP-001 TPR-1, TPR-2 |
| §7.3 governance | FS-001 OI-4 |
| §8 WBS 9 | PMP-001 §3 |
| §10 risks | PMP-001 §5 |

---

## Appendix A — v1 obligations that keep Level 3 alive

If nothing else from this document survives scope pressure, these three must:

| ID | Requirement | Consequence if dropped |
|---|---|---|
| **FR-STT-08** | Self-hosted STT adapter | L3 needs new integration work, not configuration |
| **FR-STT-09** | Consent-filtered training export | No corpus accumulates; L3 starts from zero whenever it starts |
| **FR-STT-12** | Per-turn STT implementation and version recorded | No way to A/B or attribute quality changes |

Each is small. Together they are the difference between Level 3 being **scheduled** and
Level 3 being **hypothetical** — and Level 3 is why this platform is being built.
