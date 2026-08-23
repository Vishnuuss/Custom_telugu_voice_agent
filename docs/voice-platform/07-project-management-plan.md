# Project Management Plan
## Self-Hosted Voice AI Orchestration Platform ("Project Vaani")

| Field | Value |
|---|---|
| Document ID | PMP-001 |
| Version | 1.0 |
| Date | 2026-08-23 |
| Status | Draft |
| Preceding documents | FS-001, SRS-001, HLD-001, LLD-001, TP-001, DEP-001 |

---

## 1. Project Definition

### 1.1 Objective

Deliver a self-hosted voice AI orchestration platform capable of running outbound
Indian-language calling campaigns, replacing Dograh, with full control over the speech
recognition layer and unrestricted mid-conversation tool calling.

### 1.2 Success criteria

| # | Criterion | Measured at |
|---|---|---|
| SC-1 | One vertical runs live campaigns on the new platform | G7 |
| SC-2 | Latency and Telugu ASR accuracy at or above the Dograh baseline | G4 |
| SC-3 | The operator judges conversation quality acceptable for clients | G6 |
| SC-4 | Speech recognition is demonstrably substitutable (≥2 implementations) | G4 |
| SC-5 | Mid-conversation tool calling demonstrated working | G4 |
| SC-6 | Campaign capability at parity with Dograh | G5 |
| SC-7 | Rollback to Dograh rehearsed and proven | G7 |

> **SC-4 and SC-5 are the project's reason for existing** (FS-001 §10). A release that
> achieved SC-1, 2, 3 and 6 but not 4 and 5 would be a technically successful rebuild of
> something that already worked — that is, a failure.

### 1.3 Explicit non-goals

| Non-goal | Why |
|---|---|
| ~~Faster than Dograh in v1~~ **← REVERSED 2026-08-23** | Superseded. Latency is now a **primary goal**: server-side p50 ≤800 ms (LAT-001). The original reasoning anchored to the incumbent instead of the market. |
| Voice-to-voice 100 ms | Not achievable by anyone — it is below PSTN round-trip. That figure is a single-component TTS number (~40 ms time-to-first-audio), not conversational latency. Best measured platform on real calls: 1,296 ms. |
| A SaaS product | Operator-run only |
| Replacing Dograh in one step | Per-vertical migration (DEP-001 §7) |
| Appointment booking in v1 | v2; foundation built (FR-BRAIN-05) |
| Fine-tuned ASR in v1 | Phase 4 workstream |

---

## 2. Lifecycle Model

Hybrid, per FS-001 §7.1.

```
 ┌──── V-MODEL TRACK (infrastructure) ────────────────────────────┐
 │  SRS ─▶ HLD ─▶ LLD ─▶ Build ─▶ Unit ─▶ Integration ─▶ System   │
 │  Telephony · Dialer · Campaigns · Data · API · Dashboard        │
 └────────────────────────────────────────────────────────────────┘
                              │
                              ▼  (converge at gates)
 ┌──── AGILE TRACK (conversation quality) ────────────────────────┐
 │  Iterate: call ─▶ analyse ─▶ single fix ─▶ call ─▶ …            │
 │  Prompts · Endpointing · ASR · Latency tuning                   │
 └────────────────────────────────────────────────────────────────┘
```

**Agile track working agreement** — derived from established operating practice:

| Rule | Reason |
|---|---|
| One call at a time | Attribution is impossible otherwise |
| One change between calls | Two changes make the result uninterpretable |
| Analyse the transcript before the next call | The transcript is the fastest diagnostic |
| Never trim prompts for latency | Measured at ~0.1 s; objection handling is the payload |
| Diagnose the running system before redesigning | Most "prompt bugs" have been infrastructure or billing |

---

## 3. Work Breakdown Structure

Effort is in **engineering-days**, defined as one focused working day. These are
estimates for a single experienced engineer, and carry the ±50% uncertainty normal at
this stage. **Calendar duration is not asserted** — it depends entirely on operator
availability alongside live client work.

### WBS 1 — Foundations

| ID | Work package | Days | Depends on |
|---|---|---|---|
| 1.1 | Repository, environments, CI skeleton | 2 | — |
| 1.2 | Database schema + migrations (LLD §2) | 3 | 1.1 |
| 1.3 | Configuration and secret management (DEP §3) | 1 | 1.1 |
| 1.4 | Observability core: call/turn/event writers (M7) | 3 | 1.2 |
| 1.5 | **Simulator adapters** (telephony, STT, TTS) | 4 | 1.1 |
| | **Subtotal** | **13** | |

> 1.5 is scheduled early and deliberately. Every subsequent package is developed and
> tested against it; without it, development requires billed calls.

### WBS 2 — Media plane

| ID | Work package | Days | Depends on |
|---|---|---|---|
| 2.1 | LiveKit integration, session lifecycle | 4 | 1.5 |
| 2.2 | **STT Port + first real adapter** (SC-4) | 4 | 2.1 |
| 2.3 | TTS Port + adapter, incl. `cancel()` | 3 | 2.1 |
| 2.4 | Endpointer (hybrid, language floors) | 3 | 2.2 |
| 2.5 | Echo Guard | 2 | 2.2 |
| 2.6 | Barge-in wiring | 2 | 2.3 |
| 2.7 | Turn latency instrumentation (FR-OBS-02) | 2 | 1.4, 2.3 |
| 2.8 | Filler speech | 1 | 2.3 |
| | **Subtotal** | **21** | |

### WBS 3 — Brain

| ID | Work package | Days | Depends on |
|---|---|---|---|
| 3.1 | LLM Port + adapter | 2 | 1.3 |
| 3.2 | Call state and history management | 3 | 3.1 |
| 3.3 | Turn algorithm (LLD §1.6) | 4 | 3.2 |
| 3.4 | **Tool host — mid-conversation calling** (SC-5) | 4 | 3.3 |
| 3.5 | Intent pre-checks: opt-out, correction-vs-refusal | 3 | 3.3 |
| 3.6 | Extraction and disposition | 2 | 3.3 |
| 3.7 | Telugu prompt migration from existing corpus | 3 | 3.3 |
| | **Subtotal** | **21** | |

### WBS 4 — Telephony

| ID | Work package | Days | Depends on |
|---|---|---|---|
| 4.1 | Telephony Port definition | 1 | 1.5 |
| 4.2 | SIP adapter + LiveKit SIP bridging | 5 | 4.1, 2.1 |
| 4.3 | Outcome normalisation | 2 | 4.2 |
| 4.4 | Call progress, voicemail detection, max duration | 3 | 4.2 |
| | **Subtotal** | **11** | **Blocked by OI-1** |

> **WBS 4 is the only package blocked by the Vobiz SIP question.** WBS 1, 2, 3 and 5
> proceed against simulators regardless — which is why 1.5 is scheduled first.

### WBS 5 — Control plane

| ID | Work package | Days | Depends on |
|---|---|---|---|
| 5.1 | Agent Registry: schema, validation V1–V9, versioning | 4 | 1.2 |
| 5.2 | Deploy/dry-run/diff/rollback | 3 | 5.1 |
| 5.3 | Contact ingestion and validation | 2 | 1.2 |
| 5.4 | Campaign Engine + state machine | 4 | 5.3 |
| 5.5 | Dialer gate chain | 3 | 5.4 |
| 5.6 | Retry policy and scheduling | 2 | 5.5 |
| 5.7 | Suppression list | 1 | 1.2 |
| 5.8 | Result webhooks with signing and retry | 2 | 5.4 |
| 5.9 | Platform API (LLD §6) | 4 | 5.2, 5.4 |
| | **Subtotal** | **25** | |

### WBS 6 — Dashboard

| ID | Work package | Days | Depends on |
|---|---|---|---|
| 6.1 | Assess coupling to Dograh's data model (DR-4) | 1 | — |
| 6.2 | Campaign management screens | 3 | 5.9, 6.1 |
| 6.3 | Call review: transcript, audio, latency, events | 4 | 5.9 |
| 6.4 | Agent version visibility, test-call UI | 2 | 5.9 |
| 6.5 | Confirmation and dry-run UX (NFR-USE-02/03) | 1 | 6.2 |
| | **Subtotal** | **11** | |

### WBS 7 — Test assets

| ID | Work package | Days | Depends on |
|---|---|---|---|
| 7.1 | **Held-out Telugu audio corpus + transcripts** (TPR-1) | 4 | — |
| 7.2 | **Dograh baseline measurement** (TPR-2) | 2 | 7.1 |
| 7.3 | Conversation scenario set | 2 | — |
| 7.4 | Provider failure fixtures | 1 | 1.5 |
| 7.5 | Regression suite REG-01…12 | 4 | 2.*, 3.* |
| 7.6 | Latency + WER benchmark harnesses | 3 | 7.1, 2.7 |
| | **Subtotal** | **16** | |

> **7.1 and 7.2 have no dependencies and long lead times, and they block Gate G4.**
> They must start in the first phase. Deferring them is the most likely cause of a
> stalled G4.

### WBS 8 — Deployment and operations

| ID | Work package | Days | Depends on |
|---|---|---|---|
| 8.1 | Container builds and CI/CD pipeline | 3 | 1.1 |
| 8.2 | Staging environment incl. dial allow-list gate | 2 | 8.1, 5.5 |
| 8.3 | Health checks and metrics | 2 | 1.4 |
| 8.4 | Alerting (DEP §9) | 2 | 8.3 |
| 8.5 | Runbook authoring and rehearsal | 2 | 8.4 |
| 8.6 | Backup verification and restore test | 1 | 8.2 |
| 8.7 | Cut-over execution, first vertical | 3 | All gates |
| | **Subtotal** | **15** | |

### WBS 9 — Speech recognition customization

Detailed in **STT-001 §8**. Summarised here.

| ID | Work package | Days | Release |
|---|---|---|---|
| 9.1 | **Level 0 — measure**: corpus, entity annotation, benchmark harness, Dograh baseline | 9 (≈3 net) | v1 P1 |
| 9.2 | **Level 1 — tune**: vocabulary boosting, provider comparison | 5 | v1 |
| 9.3 | **Level 2 — correct**: transcript corrector, hallucination metric (racing → v2) | 5 of 8 | v1 |
| 9.4 | **Level 3 — own**: corpus export, synthetic entity-dense audio, NeMo fine-tuning, model server, A/B rollout | 32 | **v2** |
| | **Added to v1** | **~13 net** | |
| | **v2 workstream** | **35** | |

> WBS 9.1 largely overlaps WBS 7.1/7.2 — the corpus needed to prove ASR accuracy is the
> same corpus needed to prove latency and quality parity. Roughly 6 of its 9 days are
> shared, not additional.

> **Level 3 is deliberately kept off the v1 critical path.** Gating the first release on
> a model-training project risks never shipping. What keeps it viable is that v1 ships
> FR-STT-08, FR-STT-09 and FR-STT-12, so L3 becomes configuration rather than a retrofit.
> STT-001 §8.2 sets out the alternative if the sponsor prefers L3 in v1.

### 3.1 Effort summary

| WBS | Area | Days |
|---|---|---|
| 1 | Foundations | 13 |
| 2 | Media plane | 21 |
| 3 | Brain | 21 |
| 4 | Telephony | 11 |
| 5 | Control plane | 25 |
| 6 | Dashboard | 11 |
| 7 | Test assets | 16 |
| 8 | Deployment and operations | 15 |
| **9** | **STT customization (v1 portion — L0/L1/L2)** | **13** |
| **10** | **Latency engineering — ≤800 ms target (LAT-001)** | **42** |
| | **Total (v1)** | **188 engineering-days** |
| | **+30% contingency** | **~244 engineering-days** |
| | *WBS 9.4 — STT Level 3, v2* | *32 (planned, not in v1)* |

### WBS 10 — Latency engineering

Detailed in **LAT-001 §9**. Added 2026-08-23 when the sponsor rejected the parity target.

| ID | Package | Days |
|---|---|---|
| 10.1–10.3 | Instrumentation, dual-channel measurement, provider co-location | 8 |
| 10.4–10.5 | Non-reasoning LLM switch, sentence-level streaming TTS, Sonic 4 | 7 |
| 10.6 | Backchannel acknowledgement | 3 |
| **10.7–10.10** | **Telugu turn detector: annotation, fine-tune, serving, A/B** | **19** |
| 10.12 | Live human transfer | 5 |
| | **v1 subtotal** | **42** |

> **19 of these 42 days are the Telugu turn detector alone**, and they are what make the
> ≤800 ms target reachable. LiveKit's turn detector supports 14 languages including Hindi
> but **not Telugu**, and silence-based endpointing cannot go below ~0.6 s safely — 75%
> of the budget. Without those 19 days the programme lands at ~1,200 ms, not 800 ms.
> That is still better than four of the five benchmarked commercial platforms.

> **Sequencing matters here.** LAT-001 §12 orders the work cheap-and-certain first:
> phases A–C reach ~1,200 ms with no model training at all. Phase D buys the last 400 ms.

**Estimating assumptions**, stated so they can be challenged:

| # | Assumption |
|---|---|
| EA-1 | One experienced engineer, no team coordination overhead |
| EA-2 | LiveKit behaves as documented; no framework-level workarounds needed |
| EA-3 | SIP trunking is available (OI-1 favourable). If not, add provider migration effort |
| EA-4 | The existing dashboard is extensible (DR-4 assessed at 6.1) |
| EA-5 | Existing Telugu prompts transfer with adaptation, not rewriting |
| EA-6 | Conversation-quality iteration is **not** fully captured here — it is empirical and open-ended by nature. WBS 3.7 covers migration, not perfection |
| EA-7 | Estimates carry ±50% uncertainty at this stage |

> **EA-6 deserves emphasis.** The Agile track has no fixed end. Historically, tuning a
> single agent to production quality took months of iteration on the incumbent. The 133
> days buys a *platform*; reaching a great Telugu sales agent on it is continuous work.

---

## 4. Phases and Milestones

| Phase | Contents | Gate | Exit |
|---|---|---|---|
| **P0 — Approval** | Documents signed off; OI-1 answered | **G0/G1/G2** | Specs approved, SIP answer received |
| **P1 — Foundations** | WBS 1, 7.1, 7.2, 7.3, 8.1, **9.1 (STT Level 0)** | **S-G0** | Simulators work; **corpus frozen, baseline captured, ASR targets approved** |
| **P2 — First conversation** | WBS 2, 3, **9.2 (Level 1)** | **S-G1** | Simulated call converses end to end |
| **P3 — First real call** | WBS 4, 8.2 | **G3** | RT-01 passes |
| **P4 — Quality parity** | WBS 2.4–2.8, 3.5, 3.7, 7.5, 7.6, **9.3 (Level 2)** | **G4, S-G2** | Latency + ASR at baseline; SC-4, SC-5 shown |
| **P5 — Campaigns** | WBS 5, 6 | **G5** | Full campaign runs; RT-06 passes |
| **P6 — Operations** | WBS 8.3–8.6 | — | Alerts live; runbooks rehearsed |
| **P7 — Acceptance** | UAT | **G6** | Operator accepts in writing |
| **P8 — Cut-over** | WBS 8.7 | **G7** | One vertical live; rollback rehearsed |
| **P9+ — Expansion** | Remaining verticals; v2 features; ASR fine-tuning | — | Per-vertical criteria |

### 4.1 Critical path

```
 1.1 ─▶ 1.2 ─▶ 1.4 ─▶ 1.5 ─▶ 2.1 ─▶ 2.2 ─▶ 3.1 ─▶ 3.3 ─▶ 4.2 ─▶ G3
                                                              │
                          7.1 ─▶ 7.2 ────────────────────────┤
                                                              ▼
                                        2.4/2.5 ─▶ 7.6 ─▶ G4 ─▶ 5.* ─▶ G5 ─▶ G6 ─▶ G7
```

Two critical-path observations:

1. **1.5 (simulators) gates almost everything.** Build it first.
2. **7.1/7.2 (corpus and baseline) run in parallel but gate G4.** They have no technical
   dependency and are therefore easy to postpone — and postponing them is the single
   most likely cause of schedule slip.

---

## 5. Risk Register

Scored: Probability × Impact, each 1–5.

| ID | Risk | P | I | Score | Response | Owner |
|---|---|---|---|---|---|---|
| **R-01** | **Vobiz offers no SIP trunking** | 3 | 5 | **15** | **Mitigate/Transfer.** Ask before starting (FS §9.1). Provider-agnostic adapter (ADR-02). Fallback: Plivo. Contingency: FS §A3 (Brain-only via Dograh) | Vishnu |
| **R-02** | Conversation quality never reaches acceptable on the new stack | 2 | 5 | 10 | **Mitigate.** Migrate tuned prompts (3.7); text eval before calls; per-vertical cut-over; Dograh retained | Eng |
| **R-03** | Latency materially worse than Dograh after Brain insertion | 3 | 3 | 9 | **Mitigate.** In-process Brain (ADR-05); filler speech; component attribution; G4 blocks progress | Eng |
| **R-04** | Operator unavailable — client work takes priority | 4 | 3 | 12 | **Accept + mitigate.** No calendar commitment; phases independently shippable; Dograh keeps running | Vishnu |
| **R-05** | Live campaign incident during migration | 2 | 5 | 10 | **Mitigate.** Per-vertical, lowest-value first; rehearsed rollback; auto-pause on critical alerts | Vishnu |
| **R-06** | Corpus/baseline (7.1/7.2) deferred; G4 unassessable | 4 | 4 | **16** | **Mitigate.** Schedule in P1; treat as blocking; no G4 attempt without it | Eng |
| **R-07** | Self-hosting LiveKit exceeds operational capacity | 3 | 3 | 9 | **Mitigate.** LiveKit Cloud for v1 (A-02); self-host later | Eng |
| **R-08** | Provider quota exhaustion during testing or campaigns | 3 | 4 | 12 | **Mitigate.** Pre-flight credit checks; auto-pause; capacity review (DEP §12); simulators for most testing | Eng |
| **R-09** | Regulatory gap found late (DLT/DPDP) | 2 | 5 | 10 | **Mitigate.** Start OI-3/OI-4 in parallel with P1; blocks G7 only, not design | Vishnu |
| **R-10** | Dashboard more coupled to Dograh than expected | 3 | 2 | 6 | **Mitigate.** Assess at 6.1, early and cheaply | Eng |
| **R-11** | Scope creep — booking, agent builder, multi-tenancy pulled into v1 | 4 | 3 | 12 | **Mitigate.** SRS §1.2 deferrals are explicit; changes go through §7 | Vishnu |
| **R-12** | Simulator diverges from real telephony behaviour | 3 | 3 | 9 | **Mitigate.** Periodic real-call validation; simulator is never the only gate | Eng |
| **R-13** | Economic case unverified; project may not pay back | 3 | 3 | 9 | **Mitigate.** Gather E1–E6 before committing beyond P1. Note SC-4/SC-5 are unobtainable at any price elsewhere | Vishnu |
| **R-14** | Cost of AI providers during iteration exceeds expectation | 3 | 2 | 6 | **Mitigate.** Text evaluation over calls; small gate suites; simulators by default | Eng |

| **R-15** | **Telugu corpus never assembled — no ASR claim provable** (= STT-001 SR-1; same root cause as R-06) | 4 | 5 | **20** | **Mitigate.** WBS 9.1 scheduled in P1 as blocking; shares ~6 d with WBS 7.1/7.2; S-G0 gates G4 | Eng |
| **R-16** | **Consent basis does not cover ASR training (OI-4)** (= STT-001 SR-2) | 3 | 5 | **15** | **Mitigate.** Start the review now. Gates Level 3 only; L0–L2 unaffected. If refused, L3 falls back to synthetic plus newly-consented audio | Vishnu |
| **R-17** | Level 3 slips indefinitely; the primary justification is never realised (= STT-001 SR-9) | 3 | 4 | 12 | **Mitigate.** v1 ships FR-STT-08/09/12 so L3 stays configuration, not a retrofit; S-G0 targets make progress measurable | Eng |

> R-15, R-16 and R-17 are carried up from STT-001 §10 because they affect the programme,
> not only the workstream. The full STT risk set is in that document.

### 5.1 Top risks requiring action now

| Rank | Risk | Action | When |
|---|---|---|---|
| 1 | **R-15 / R-06** (20 / 16) | Schedule corpus + baseline into P1 as blocking work — it gates G4 *and* every ASR claim | P1 |
| 2 | **R-01** (15) | Send the Vobiz enquiry (FS §9.1) | **Before P1** |
| 3 | **R-16** (15) | Start the consent review for ASR training (OI-4) | P0–P1 |
| 4 | R-04 / R-08 / R-11 / R-13 / R-17 (12) | Availability, quota pre-flight, scope discipline, cost inputs, L3 enablers in v1 | P0–P1 |

---

## 6. Governance

### 6.1 Roles

| Role | Who | Responsibility |
|---|---|---|
| Sponsor / Product Owner | Vishnu | Scope, priority, gate approval, acceptance |
| Engineer | Vishnu (with AI assistance) | Design, build, test |
| Operator | Vishnu | Campaigns, incidents, cut-over |
| Regulatory advisor | External | OI-3, OI-4 |

> The concentration of every role in one person is itself risk R-04, and is why gates are
> written down: they substitute for the challenge a second person would otherwise provide.

### 6.2 Gate approval

Each gate requires: exit criteria demonstrably met (TP-001 §11), open defects at S1/S2
reviewed, risk register updated, and explicit written approval.

**A gate may be failed.** Failing G4 and iterating is a correct outcome; passing it on
optimism is not.

### 6.3 Change control

| Change | Process |
|---|---|
| New v1 requirement | Amend SRS; re-estimate; explicit approval — **default answer is v2** |
| Design change | Amend HLD/LLD; assess test impact |
| Scope reduction | Record what is deferred and why |
| Gate criterion change | Requires sponsor approval and a written reason |

---

## 7. Cost Model

### 7.1 Structure

| Category | Item | Status |
|---|---|---|
| One-time | Engineering effort (~133–173 days) | Estimated §3.1 |
| One-time | Telephony migration, if R-01 materialises | Contingent |
| Recurring | Compute (existing Coolify) | Marginal |
| Recurring | Telephony per minute | **E4/E5 required** |
| Recurring | STT per minute | **E1 required** — trends to ~0 with self-hosting |
| Recurring | LLM per call | **E1 required** |
| Recurring | TTS per minute | **E1 required** |
| Deferred | GPU hours for ASR fine-tuning | **E6 required** |
| Avoided | Managed platform per-minute fee | **E3 required** |

### 7.2 Outstanding inputs

Carried from FS-001 §4.5. **No break-even is asserted until these are supplied** — a
fabricated number here would produce a real decision.

| # | Input |
|---|---|
| E1 | Current monthly spend: Vobiz, Sarvam, Groq, Cartesia |
| E2 | Current and projected monthly call minutes per vertical |
| E3 | Vapi published per-minute pricing |
| E4 | Vobiz SIP rates (combine with the R-01 enquiry) |
| E5 | Plivo India outbound + DLT charges |
| E6 | GPU hourly rate for fine-tuning |

### 7.3 Commercial note

The strategic argument is not the per-minute saving. It is that an agency cannot price
client outcomes predictably on a rate set by a third party. Converting a variable
per-minute cost into a largely fixed infrastructure cost is the correct shape for this
business — and self-hosted ASR drives the largest recurring per-minute component toward
zero, which compounds with volume.

---

## 8. Communication and Reporting

| Artefact | Cadence | Contents |
|---|---|---|
| Gate report | Per gate | Criteria met, defects, risks, decision |
| Progress log | Per working session | What changed, what was learned, what is next |
| Call analysis note | Per real-call batch | Transcript findings, latency, the single change made |
| Risk review | Per phase | Register updated, top-3 actions |
| Cost review | Monthly once live | Actual vs modelled |

---

## 9. Dependency Summary

| ID | Dependency | Type | Blocks | Owner |
|---|---|---|---|---|
| D-1 | Vobiz SIP answer (OI-1) | External | WBS 4, G3 | Vishnu |
| D-2 | Provider accounts and quota | External | Real-call testing | Vishnu |
| D-3 | Regulatory review (OI-3, OI-4) | External | **G7 only** | External |
| D-4 | Consented recordings for corpus | Internal | 7.1, Phase 4 ASR | Vishnu |
| D-5 | Cost inputs E1–E6 | Internal | Economic sign-off | Vishnu |
| D-6 | LiveKit hosting decision (A-02) | Internal | 2.1 | Eng |

---

## 10. Immediate Next Actions

| # | Action | Owner | Blocks |
|---|---|---|---|
| 1 | **Send the Vobiz SIP enquiry** (FS-001 §9.1) | Vishnu | Everything in WBS 4 |
| 2 | Review and sign off FS-001, SRS-001, HLD-001, LLD-001 | Vishnu | G0–G2 |
| 3 | Gather cost inputs E1–E6 | Vishnu | Economic sign-off |
| 4 | Initiate regulatory review (OI-3, OI-4) | Vishnu | G7 |
| 5 | Confirm MinIO recording volume and retention | Eng | 7.1, Phase 4 |
| 6 | **Apply the missing `Reasoning: low` fix to Dograh WF6** | Eng | Nothing — independent ~1.6 s win on the live system today |

> Action 6 is unrelated to this project's success and should not wait for it.

---

## Appendix A — Deferred Scope Ledger

Recorded so deferrals are decisions rather than omissions.

| Item | Deferred to | Foundation laid in v1? |
|---|---|---|
| Appointment booking | v2 | Yes — FR-BRAIN-05 tool calling |
| Calendar integration | v2 | Interface declared (LLD App. A) |
| Inbound calling | v2 | Session entry point extensible |
| Human transfer | v2 | Interface declared |
| Racing STT | v2 | STT Port supports composition |
| **Fine-tuned Telugu ASR** | v2 — **fully planned in STT-001 §7, WBS 9.4, 32 d** | **Yes — FR-STT-08 self-hosted adapter, FR-STT-09 consented export, FR-STT-12 version attribution, all Must in v1** |
| Visual agent builder | v2 | Config artefact is the data model |
| Multi-tenancy / billing | Not planned | No |

> The ASR row is the one to protect. It is the project's primary justification
> (FS-001 §10, SC-4), and although the model itself is v2 work, **v1 must deliver the
> port and the consented corpus export** or the justification is deferred indefinitely.
