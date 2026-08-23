# Test Plan
## Self-Hosted Voice AI Orchestration Platform ("Project Vaani")

| Field | Value |
|---|---|
| Document ID | TP-001 |
| Version | 1.0 |
| Date | 2026-08-23 |
| Status | Draft |
| Preceding documents | FS-001, SRS-001, HLD-001, LLD-001 |
| Standard | Structured after IEEE 829 |

---

## 1. Introduction

### 1.1 Purpose

This document defines how the platform will be verified and validated. In the V-model
adopted for this programme, each specification document has a paired test level:

```
   FS-001  ─────────────────────────────────────▶  Acceptance / UAT      (§6)
      │                                                      ▲
      ▼                                                      │
   SRS-001  ────────────────────────────────────▶  System Testing        (§5)
      │                                                      ▲
      ▼                                                      │
   HLD-001  ────────────────────────────────────▶  Integration Testing   (§4)
      │                                                      ▲
      ▼                                                      │
   LLD-001  ────────────────────────────────────▶  Unit Testing          (§3)
      │                                                      ▲
      └──────────────▶  Implementation  ─────────────────────┘
```

### 1.2 The hybrid model in testing

FS-001 §7.1 established that the system has two parts of different character. This
carries directly into the test approach:

| Subsystem | Verification approach |
|---|---|
| Telephony, dialer, campaigns, data, API | **Deterministic.** Pass/fail assertions. Test-first where practical. |
| Conversation quality, Telugu ASR, latency | **Empirical.** Measured against a baseline on a fixed corpus, judged by threshold and by ear. |

> A pass/fail assertion cannot express "the agent sounded pushy." §7 defines how the
> empirical side is measured rigorously without pretending it is deterministic.

### 1.3 Guiding principle

> **No test may place a billed call unless the test's purpose is to place a billed call.**

The Simulator adapters (LLD §1.1, §1.2) exist so that the entire system can be exercised
end-to-end at zero cost and zero risk to real people. Real-call testing is a deliberate,
budgeted, small-N activity (§5.3), never a default.

---

## 2. Test Strategy

### 2.1 Scope of testing

| In scope | Out of scope |
|---|---|
| All v1 functional requirements (SRS §3) | v2/W-priority requirements |
| All v1 non-functional requirements (SRS §4) | Third-party provider internals |
| Regression against known production failures (§8) | Load beyond NFR-SCAL-01 (10 concurrent) |
| Compliance-critical behaviour (§9) | Penetration testing (deferred) |

### 2.2 Test environments

| Env | Telephony | STT/TTS/LLM | Database | Real calls |
|---|---|---|---|---|
| **LOCAL** | Simulator | Simulator / fixtures | Ephemeral | Never |
| **CI** | Simulator | Simulator | Ephemeral | Never |
| **STAGING** | Real trunk, **test numbers only** | Real providers | Staging DB | Operator's own numbers only |
| **PROD** | Real trunk | Real providers | Production DB | Yes — gated |

**Rule:** STAGING dials only an allow-list of operator-controlled numbers. The allow-list
is enforced as an additional dial gate (LLD §1.7), not as a convention.

### 2.3 Test data

| Asset | Purpose | Notes |
|---|---|---|
| **Telugu audio corpus** | ASR accuracy measurement (§7.2) | Held out; assembled from consented production recordings. **This is prerequisite RQ-5 and blocks Gate G4.** |
| Reference transcripts | WER ground truth | Human-verified |
| Entity list | Entity accuracy (§7.2) | Names, cities, amounts, product terms |
| Conversation scenario set | Brain behaviour (§5.2) | Derived from real transcripts |
| Contact list fixtures | Campaign tests | Synthetic numbers only |
| Failure fixtures | Provider-fault simulation (§8) | 429, 402, 401 responses |

> **RQ-5 must be actioned early.** Without an agreed, held-out audio set, "accuracy
> parity with the incumbent" cannot be demonstrated or disputed, and Gate G4 becomes a
> matter of opinion.

### 2.4 Tooling

| Need | Tool |
|---|---|
| Unit / integration | `pytest` |
| API contract | Schema validation against LLD §6 |
| Conversation evaluation | Existing `probe_chat.py`, `invest_train.py`, `loan_train.py` (adapted) |
| Call analysis | Existing `analyze_runs.py`, `recent_calls.py` |
| Model comparison | Existing `compare_models.py` |
| Real test calls | Existing `place_test_call.py` (adapted) |
| WER computation | Standard WER over the §2.3 corpus |

Reuse is deliberate (HLD ADR-06): these harnesses already encode hard-won evaluation
practice.

---

## 3. Unit Testing — verifies LLD-001

### 3.1 Approach

Test-first for deterministic modules. Every external dependency replaced by a double.
No unit test touches a network.

### 3.2 Coverage requirements

| Module | Must-test |
|---|---|
| TelephonyPort adapters | Outcome mapping incl. unknown → `FAILED` + event; `originate` idempotency per `session_ref` |
| SttPort adapters | Streaming assembly; `capabilities` honesty; vocabulary pass-through |
| TtsPort adapters | First-chunk latency; `cancel()` aborts mid-stream |
| **HybridEndpointer** | Threshold logic; `max_silence_s` floor; **`min_words=1` accepts one-word turns** |
| **EchoGuard** | Detects echo within window; does **not** suppress genuine repetition outside it; emits event on every suppression |
| **Brain turn algorithm** | Opt-out pre-check fires before the model; **correction ≠ refusal**; re-prompt cap; closing statement emitted exactly once; tool round cap of 2 |
| **Dial gates** | Order; first non-ALLOW wins; suppression is `DENY`; reason persisted |
| Config validator | Every rule V1–V9 (LLD §3.1), each with a positive and a negative case |
| State machines | Every legal transition; every illegal transition rejected |
| Retry policy | Per-fault behaviour incl. credit-exhausted → **pause, not retry** |

### 3.3 Exit criteria

- All unit tests pass in CI
- Every LLD §3.1 validation rule has both a passing and a failing case
- Every event type in LLD §5.1 is emitted by at least one test

---

## 4. Integration Testing — verifies HLD-001

### 4.1 Approach

Real modules, simulated externals. Verifies that the seams in HLD §4 hold.

### 4.2 Test cases

| ID | Case | Verifies |
|---|---|---|
| IT-01 | Dialer → Telephony → Session: gates pass, call originates, session starts | HLD §5.1 |
| IT-02 | Full simulated call: greeting → 3 turns → closing → records written | HLD §5.1 |
| IT-03 | Turn record contains all five timestamps and a computed latency | FR-OBS-02 |
| IT-04 | Barge-in: caller speaks during TTS; synthesis cancelled ≤300 ms | FR-PIPE-10 |
| IT-05 | Echo: system speech fed back as caller audio; suppressed, not answered | FR-PIPE-12 |
| IT-06 | One-word Telugu reply registers as a turn | FR-PIPE-09 |
| IT-07 | Unhandled input → re-prompt, then capped; never silence | FR-BRAIN-12/13 |
| IT-08 | Opt-out → suppression row written → subsequent dial denied | FR-BRAIN-10, FR-CMP-01 |
| IT-09 | **Correction ("personal loan కాదండి, home loan") is not treated as refusal** | FR-BRAIN-09 |
| IT-10 | Provider 429 → typed event, contact returns to `pending`, not `failed` | LLD §5.2 |
| IT-11 | Provider 402 → campaign **paused**, critical alert, no further dialling | LLD §5.3 |
| IT-12 | Tool call mid-conversation; filler speech emitted past threshold | FR-BRAIN-05/06, FR-PIPE-17 |
| IT-13 | Control-plane restart mid-campaign → resumes, no contact re-dialled | FR-CAMP-10, NFR-REL-02 |
| IT-14 | Two workers claim contacts concurrently → no double dial | LLD §7 |
| IT-15 | Agent deploy dry-run reports changes and writes nothing | FR-AGENT-06 |
| IT-16 | Agent deploy does not alter fields absent from the payload | FR-AGENT-05 |
| IT-17 | Campaign pinned to version N unaffected by deploying version N+1 mid-run | LLD §2.2 |
| IT-18 | Webhook signed correctly; retried on failure; `WEBHOOK_FAILED` raised | FR-CAMP-12/13 |
| IT-19 | Session crash affects one call only | NFR-REL-03 |
| IT-20 | Calling-window gate defers outside permitted hours | FR-CAMP-06 |

### 4.3 Exit criteria

All IT cases pass on CI against simulators. IT-08, IT-09, IT-11 and IT-16 are
**blocking** — each corresponds to a defect that has already caused real harm.

---

## 5. System Testing — verifies SRS-001

### 5.1 Approach

Whole system, staging environment, real providers. Two sub-phases: simulated telephony
first (§5.2), then a small number of real calls (§5.3).

### 5.2 Functional system tests (simulated telephony, real AI providers)

| ID | Case | Requirement |
|---|---|---|
| ST-01 | Upload 500-contact CSV; validation rejects malformed and de-duplicates | FR-CAMP-01/02 |
| ST-02 | Create, start, pause, resume, stop a campaign | FR-CAMP-03/04 |
| ST-03 | Concurrency never exceeds configured maximum | FR-CAMP-05 |
| ST-04 | Retry policy honoured per outcome | FR-CAMP-07 |
| ST-05 | Suppressed numbers never dialled — including via the test-call endpoint | FR-CMP-01 |
| ST-06 | Full conversation scenario set produces correct dispositions | FR-BRAIN-08 |
| ST-07 | Extraction schema populated correctly across scenarios | FR-BRAIN-07 |
| ST-08 | Campaign report aggregates match underlying call records | FR-OBS-07 |
| ST-09 | Operator identifies cause of a seeded failure from dashboard in ≤2 min | NFR-USE-01 |
| ST-10 | Campaign start requires confirmation and states the dial count | NFR-USE-02 |
| ST-11 | Rollback to previous agent version completes in ≤5 min | NFR-REL-05 |
| ST-12 | Retention job deletes expired recordings | FR-DATA-03 |
| ST-13 | Recording URLs expire; unauthenticated access refused | NFR-SEC-05 |
| ST-14 | 10 concurrent simulated calls sustained | NFR-SCAL-01 |
| ST-15 | Contact list of 50,000 accepted and dialled through | NFR-SCAL-03 |

### 5.3 Real-call system tests — **budgeted and gated**

Real calls cost money and reach real people. This suite is deliberately small and
requires explicit operator authorisation per run.

| ID | Case | N | Target |
|---|---|---|---|
| RT-01 | End-to-end call to operator's own number completes | 1 | Gate **G3** |
| RT-02 | Telugu conversation, all turn types exercised | 3–5 | G4 |
| RT-03 | Barge-in behaviour on a real mobile connection | 2 | G4 |
| RT-04 | Speakerphone echo condition | 2 | G4 |
| RT-05 | Poor-network condition | 2 | G4 |
| RT-06 | Small live campaign, real contacts | 10–20 | Gate **G5** |

**Protocol for every real-call run** — derived from established operating practice:

1. Dry-run the deployment first; confirm the diff
2. Confirm the intended target numbers explicitly
3. **One call at a time.** Analyse the transcript and latency before the next
4. Fix one thing between calls, not several — otherwise attribution is impossible
5. Record findings before proceeding

> Step 3 and 4 are not bureaucracy. Batch-calling and multi-fixing is how the incumbent
> accumulated undiagnosed defects.

### 5.4 Exit criteria

All ST cases pass; RT-01 passes for G3; RT-02…05 pass for G4; RT-06 passes for G5.

---

## 6. Acceptance Testing (UAT) — validates FS-001

### 6.1 Approach

Performed by the operator (Vishnu), on real calls, judged partly **by ear**. This is
validation — "did we build the right thing" — not verification.

### 6.2 Acceptance criteria

| ID | Criterion | Basis |
|---|---|---|
| UAT-01 | Turn latency is no worse than the incumbent baseline | NFR-PERF-01 |
| UAT-02 | Telugu transcription is no worse than the incumbent | NFR-QUAL-01 |
| UAT-03 | The agent does not interrupt the caller mid-sentence | FR-PIPE-08 |
| UAT-04 | The agent does not answer itself | NFR-QUAL-03 |
| UAT-05 | No call ends in silence | NFR-QUAL-05 |
| UAT-06 | A caller correcting themselves is not treated as opting out | NFR-QUAL-06 |
| UAT-07 | The closing statement is spoken once | NFR-QUAL-07 |
| UAT-08 | A campaign can be run start to finish without engineering intervention | FR-CAMP-* |
| UAT-09 | The cause of any failed call is determinable from the dashboard | NFR-USE-01 |
| UAT-10 | **The operator judges the conversation acceptable to put in front of a client** | NFR-QUAL-08 |

> **UAT-10 is the real gate.** Every other criterion can pass while the agent still
> sounds wrong. Metric parity is necessary and insufficient; this has already occurred
> on the incumbent, which passed automated gates and was never verified by ear.

### 6.3 Exit criteria

All UAT criteria accepted by the operator in writing. Gate **G6**.

---

## 7. Specialised Voice Testing

### 7.1 Latency benchmark

**Method.** Over a fixed scenario set, compute the distribution of `turn_latency_s` from
the `turn` table (LLD §2.1).

| Metric | Parity target | Stretch |
|---|---|---|
| p50 | ≤ 1.95 s | ≤ 1.50 s |
| p95 | ≤ 3.00 s | ≤ 2.50 s |
| Barge-in stop | ≤ 300 ms | — |

**Component attribution is mandatory.** Each run reports the breakdown across
`speech_end → stt_final → brain_first_token → brain_complete → tts_first_audio`.

> **Model TTFB must not be reported as responsiveness.** On reasoning models it measures
> the first *reasoning* token, not the first spoken word, and was previously wrong by an
> order of magnitude (0.09 s TTFB against a 1.95 s turn). Any report quoting TTFB as the
> headline latency figure is defective.

### 7.2 ASR accuracy benchmark

| Metric | Definition | Target |
|---|---|---|
| **WER** | Word error rate over the held-out corpus | ≤ incumbent baseline |
| **Entity accuracy** | Correct recognition of names, cities, amounts, product terms | Measured and reported separately |
| Turn registration | Proportion of caller utterances registered as turns | 100% incl. one-word |

**Entity accuracy is reported separately and deliberately.** Overall WER can improve
while the words that actually determine call outcome — a customer's name, a city, an
amount — get worse. Published Indic ASR work indicates entity-dense audio is precisely
where the gap sits, and it is the metric the Phase 4 fine-tuning workstream will be
judged on.

### 7.3 Conversation quality evaluation

Text-based evaluation against the scenario set, using the existing eval harnesses. Runs
without placing calls, so it is cheap enough for every change.

| Dimension | Method |
|---|---|
| Goal completion | Did the agent reach a correct disposition |
| Objection handling | Scenario set includes refusals, corrections, hesitation, questions |
| Instruction adherence | No improvised content outside the instruction set |
| Language quality | Natural spoken Telugu; not stilted or over-formal |
| Turn economy | Reasonable number of turns to outcome |

> **Cost note.** The operator is cost-sensitive about evaluation tokens. The default is a
> small gate suite run per change; the full battery is run at gates only.

### 7.4 Regression baseline

Before any migration, the incumbent is measured on the same corpus and scenario set. All
"parity" claims are against that recorded baseline, not against memory.

**This baseline capture is a prerequisite for Gate G4 and must be scheduled explicitly.**

---

## 8. Regression Suite — Known Production Failures

Every case below reproduces a defect that has already occurred in production. This is
the highest-value section of this document: these are not hypothetical.

| ID | Historical failure | Test |
|---|---|---|
| REG-01 | Turn threshold set to 3 words; one-word Telugu replies never heard | Assert one-word turns register; assert validator rejects `min_words > 1` |
| REG-02 | Endpointing too aggressive; callers cut off mid-sentence | Assert Telugu `max_silence_s` floor of 0.60 enforced at config load |
| REG-03 | Agent transcribed and answered its own speech (speakerphone echo) | IT-05 plus real-call RT-04 |
| REG-04 | A caller's correction matched a refusal condition; told they would not be called again | IT-09, UAT-06 |
| REG-05 | Closing statement spoken twice | Validator rule V3; assert single emission |
| REG-06 | Silent call from an unhandled input with no exit | IT-07; assert zero `SILENT_CALL` events |
| REG-07 | Daily LLM token cap presented as ordinary call failure for days | IT-10; assert typed event and retry, not `outcome=failed` |
| REG-08 | TTS credit exhaustion killed every call at 0 s | IT-11; assert campaign pauses and alerts |
| REG-09 | Config write replaced the whole object and destroyed a model override | IT-16; assert absent fields untouched |
| REG-10 | Deployment silently reverted live tuning from a stale local file | IT-15; assert dry-run diff shown before apply |
| REG-11 | Multiple edges collapsed on persistence, stranding callers with no exit | N/A by design — no graph (HLD ADR-03). Assert every end condition has a path |
| REG-12 | Turn-taking parameter drifted back to a default | Assert deployed config matches the artefact after deploy; periodic drift check |

> REG-11 is included to record that an entire class of incumbent defect is eliminated by
> the architecture rather than tested against. That is the point of ADR-03.

---

## 9. Compliance Testing

| ID | Case | Requirement |
|---|---|---|
| CT-01 | Suppressed number never dialled by any path, including test calls | FR-CMP-01 |
| CT-02 | Opt-out during a call writes suppression before the call ends | FR-BRAIN-10 |
| CT-03 | Calling-window enforcement across timezone boundaries | FR-CAMP-06 |
| CT-04 | Disclosure statement delivered when configured | FR-CMP-03 |
| CT-05 | `training_use_permitted` defaults false; export excludes non-consented audio | FR-CMP-04, FR-DATA-06 |
| CT-06 | Retention deletes both database rows and stored objects | FR-DATA-03 |
| CT-07 | Contact provenance and consent basis recorded on every list | FR-CMP-02 |
| CT-08 | Audit log records every campaign start/stop and agent deploy | FR-CMP-05 |

> CT-05 is deliberately a test and not merely a default. An export that quietly includes
> non-consented audio would be a regulatory breach discoverable only afterwards.

---

## 10. Defect Management

| Severity | Definition | Action |
|---|---|---|
| **S1 Critical** | Places wrong calls, breaches compliance, or loses campaign state | Stop; fix before any further testing |
| **S2 Major** | A requirement fails; no safe workaround | Blocks the current gate |
| **S3 Minor** | Requirement partially met; workaround exists | Fix before the next gate |
| **S4 Cosmetic** | No functional impact | Backlog |

Every S1 and S2 defect must gain a regression test in §8 before closure.

---

## 11. Gate Entry and Exit Criteria

| Gate | Entry | Exit |
|---|---|---|
| **G3 First call** | Unit + IT pass on simulators | RT-01 passes; a real call completes end to end |
| **G4 Quality parity** | G3; §7.4 baseline captured; §2.3 corpus assembled | §7.1 and §7.2 at or above baseline; RT-02…05 pass; REG-01…06 pass |
| **G5 Campaign parity** | G4 | ST-01…15 pass; RT-06 passes; REG-07…12 pass |
| **G6 UAT** | G5 | All §6.2 criteria accepted in writing, incl. UAT-10 |
| **G7 Cut-over** | G6 | §9 compliance suite passes; rollback rehearsed (NFR-REL-06); regulatory items OI-3/OI-4 cleared |

---

## 12. Traceability Summary

| Requirement group | Verified by |
|---|---|
| FR-TEL-* | Unit §3.2; IT-01; RT-01 |
| FR-PIPE-* | Unit §3.2; IT-04/05/06/12; §7.1; §7.2; RT-02…05 |
| FR-BRAIN-* | Unit §3.2; IT-07/08/09/12; §7.3; ST-06/07 |
| FR-AGENT-* | Unit §3.2; IT-15/16/17; ST-11 |
| FR-CAMP-* | IT-13/14/18/20; ST-01…04; RT-06 |
| FR-OBS-* | IT-03; ST-08/09 |
| FR-UI-* | ST-09/10; UAT-08/09 |
| FR-DATA-* | ST-12; CT-05/06 |
| FR-CMP-* | CT-01…08 |
| NFR-PERF-* | §7.1 |
| NFR-QUAL-* | §7.2; §7.3; UAT-01…07/10 |
| NFR-REL-* | IT-10/11/13/19; ST-11 |
| NFR-SCAL-* | ST-14/15 |
| NFR-SEC-* | ST-13; CT-08 |
| NFR-MAINT-* | Simulator adapters; §2.2 LOCAL env |
| NFR-USE-* | ST-09/10; UAT-09 |

---

## Appendix A — Test Prerequisites

| ID | Prerequisite | Blocks |
|---|---|---|
| TPR-1 | Held-out Telugu audio corpus with verified transcripts (SRS RQ-5) | **G4** |
| TPR-2 | Incumbent baseline measured on that corpus (§7.4) | **G4** |
| TPR-3 | Conversation scenario set derived from real transcripts | §5.2, §7.3 |
| TPR-4 | Staging allow-list of operator-controlled numbers | §2.2 |
| TPR-5 | Provider failure fixtures (429, 402, 401) | IT-10/11 |
| TPR-6 | Simulator adapters delivered | All of §3, §4, §5.2 |

> TPR-1 and TPR-2 have long lead times and are frequently deferred until they block a
> gate. They should be started in the first phase of implementation, not the last.
