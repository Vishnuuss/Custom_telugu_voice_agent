# High-Level Design
## Self-Hosted Voice AI Orchestration Platform ("Project Vaani")

| Field | Value |
|---|---|
| Document ID | HLD-001 |
| Version | 1.0 |
| Date | 2026-08-23 |
| Status | Draft — awaiting sign-off (Gate G2) |
| Preceding documents | FS-001, SRS-001 |
| Succeeding documents | LLD-001, TP-001, DEP-001 |
| V-model pair | Verified by **System Testing** (TP-001 §5) |

---

## 1. Introduction

### 1.1 Purpose

This document defines the system architecture: how the platform is decomposed into
modules, how those modules communicate, what technology each uses and why, and how a
call flows through the system. It is the bridge between what the system must do
(SRS-001) and how each part is built (LLD-001).

### 1.2 Design Objectives

Derived from SRS-001 and ranked. Where objectives conflict, higher-ranked wins.

| Rank | Objective | Source |
|---|---|---|
| 1 | **Substitutability** — every external provider replaceable without touching other modules | FR-PIPE-03, FR-TEL-02, NFR-MAINT-02 |
| 2 | **Diagnosability** — a single operator must find the cause of a failure in minutes | NFR-USE-01, FR-OBS-05 |
| 3 | **Safe failure** — defects must not place wrong calls or lose campaign state | NFR-REL-01…04, FR-CMP-01 |
| 4 | **Conversation freedom** — no graph constraint; tools callable at any turn | FR-BRAIN-01, FR-BRAIN-05 |
| 5 | **Latency headroom** — every component in the turn path measurable and swappable | NFR-PERF-01…06 |
| 6 | Operational simplicity — fewest moving parts consistent with the above | C-06 |

> Objective 1 is ranked first deliberately. FS-001 concluded the entire justification
> for this project is *control*. An architecture that hard-codes a provider forfeits the
> reason for building it.

### 1.3 Design Principles

| # | Principle | Consequence |
|---|---|---|
| P1 | **Ports and adapters.** Every external system sits behind an interface owned by this codebase. | Providers are configuration, not architecture. |
| P2 | **The graph is dead.** Conversation control is a prompt plus tools plus state, never a node graph. | Directly answers FS-001 §3.2. |
| P3 | **Measure the turn, not the component.** Every turn emits a complete latency breakdown. | Prevents the TTFB misdiagnosis documented in SRS-001 §4.1. |
| P4 | **Provider faults are a first-class category.** Rate limits, credit exhaustion and auth failures are distinct from application errors. | Two multi-day outages were previously misdiagnosed as prompt defects. |
| P5 | **Dry run by default.** Any action with real-world effect requires explicit confirmation. | NFR-USE-02, NFR-USE-03. |
| P6 | **Agent config is data, in git.** Never edited in a UI as the source of truth. | FR-AGENT-02, FR-AGENT-05. |
| P7 | **Reuse before build.** The existing dashboard, analysis tools and eval harnesses are assets, not legacy. | FS-001 §3.6. |

---

## 2. System Context

```
                    ┌──────────────────────────────────────────┐
                    │            EXTERNAL ACTORS               │
                    └──────────────────────────────────────────┘

   Operator                Call recipient            Client system
  (Vishnu)                 (Telugu, mobile)         (CRM / sheet)
      │                          │                        ▲
      │ HTTPS                    │ PSTN                   │ signed webhook
      ▼                          ▼                        │
┌─────────────────────────────────────────────────────────┴──────────┐
│                        PROJECT VAANI                               │
└────────────────────────────────────────────────────────────────────┘
      │            │              │              │             │
      ▼            ▼              ▼              ▼             ▼
   SIP trunk     STT           LLM            TTS         Object store
   (Vobiz/       (Sarvam /     (Groq /        (Cartesia)   (MinIO)
    Plivo)        self-hosted)  OpenAI-compat)
```

---

## 3. Architecture Overview

### 3.1 Architectural style

**Modular service architecture with a per-call worker process.**

Two planes, separated because they have different failure and scaling characteristics:

| Plane | Contains | Nature |
|---|---|---|
| **Control plane** | Campaign Engine, Dialer, Agent Registry, API, Dashboard | Long-lived, stateful, transactional. Must survive restart (NFR-REL-02). |
| **Media plane** | Session Worker (one per active call): STT, Brain, TTS | Short-lived, ephemeral, latency-critical. One failure must not affect others (NFR-REL-03). |

The planes communicate only through the database and a job queue. A crash in a media
worker cannot corrupt campaign state; a control-plane restart cannot drop live calls.

### 3.2 Component diagram

```
┌───────────────────────── CONTROL PLANE ─────────────────────────┐
│                                                                  │
│  ┌────────────┐   ┌──────────────┐   ┌───────────────────────┐  │
│  │ Dashboard  │──▶│  Platform    │──▶│   Agent Registry      │  │
│  │ (Next.js)  │   │     API      │   │ (versioned configs)   │  │
│  └────────────┘   └──────┬───────┘   └───────────────────────┘  │
│                          │                                       │
│                   ┌──────▼────────┐    ┌──────────────────────┐ │
│                   │   Campaign    │───▶│   Suppression List   │ │
│                   │    Engine     │    └──────────────────────┘ │
│                   └──────┬────────┘                              │
│                          │ enqueue call jobs                     │
│                   ┌──────▼────────┐                              │
│                   │    Dialer     │  concurrency, hours, retries │
│                   └──────┬────────┘                              │
└──────────────────────────┼───────────────────────────────────────┘
                           │ dispatch
┌──────────────────────────▼──────── MEDIA PLANE ──────────────────┐
│   ┌───────────────────────────────────────────────────────────┐  │
│   │              Session Worker  (one per call)               │  │
│   │                                                            │  │
│   │   ┌──────────┐   ┌──────────┐   ┌──────────┐              │  │
│   │   │ Telephony│──▶│  Media   │──▶│  Brain   │              │  │
│   │   │ Adapter  │◀──│ Pipeline │◀──│ Service  │              │  │
│   │   └────┬─────┘   └────┬─────┘   └────┬─────┘              │  │
│   │        │              │               │                    │  │
│   └────────┼──────────────┼───────────────┼────────────────────┘  │
│            │              │               │                        │
│         SIP trunk    STT / TTS      LLM + Tools                    │
└────────────┼──────────────┼───────────────┼────────────────────────┘
             │              │               │
             └──────────────┴───────────────┴──▶ ┌──────────────────┐
                        telemetry events         │  Observability   │
                                                 │     Store        │
                                                 └──────────────────┘
                                                          │
                                             PostgreSQL + Object Storage
```

### 3.3 Module catalogue

| # | Module | Plane | Responsibility | Key SRS refs |
|---|---|---|---|---|
| M1 | **Telephony Adapter** | Media | Originate/manage SIP calls; normalise provider outcomes | FR-TEL-01…09 |
| M2 | **Media Pipeline** | Media | Audio transport, STT, endpointing, barge-in, TTS | FR-PIPE-01…17 |
| M3 | **Brain Service** | Media | Decide speech; execute tools; maintain call state | FR-BRAIN-01…13 |
| M4 | **Agent Registry** | Control | Store, validate, version, deploy agent configs | FR-AGENT-01…06 |
| M5 | **Campaign Engine** | Control | Lists, campaigns, lifecycle, per-contact state | FR-CAMP-01…04, 09…13 |
| M6 | **Dialer** | Control | Concurrency, calling hours, retry policy, suppression | FR-CAMP-05…08, 10 |
| M7 | **Observability** | Both | Transcripts, turn metrics, errors, recordings, reporting | FR-OBS-01…08 |
| M8 | **Platform API** | Control | Authenticated HTTP surface for dashboard and tools | FR-UI-*, EI-08 |
| M9 | **Dashboard** | Control | Operator UI (extends existing Next.js app) | FR-UI-01…08 |

---

## 4. Module Design

### 4.1 M1 — Telephony Adapter

**Purpose.** Turn "call this number with this agent" into a live audio session, and
normalise every provider's outcome vocabulary into one internal vocabulary.

**Interface (conceptual).**

| Operation | Direction |
|---|---|
| `originate(number, cli, session_ref)` → `call_handle` | out |
| `hangup(call_handle)` | out |
| `on_call_progress(event)` | in |
| `on_media_ready(session)` | in |

**Design notes.**

- Implemented as a **port with per-provider adapters** (P1). v1 ships one real adapter
  plus a simulator (NFR-MAINT-02, NFR-MAINT-03).
- Provider-specific outcome strings are mapped to the internal enum at the adapter
  boundary. No provider vocabulary leaks past M1 (FR-TEL-03).
- A **Simulator adapter** is a first-class deliverable, not a test afterthought: it
  allows the whole system to run end-to-end without placing billed calls, which is the
  only way a single operator can develop safely against a live-cost system (C-05).

> **Open dependency.** This module cannot be completed until FS-001 OI-1 (SIP
> availability) is answered. The interface above is deliberately provider-neutral so
> that design and downstream modules proceed regardless.

### 4.2 M2 — Media Pipeline

**Purpose.** Everything between the audio and the text, in both directions.

**Built on LiveKit Agents**, which supplies transport, barge-in and the turn-detector
model. This module is the configuration and extension of that framework, not a
reimplementation.

**Sub-components.**

| Sub | Responsibility | Substitutable |
|---|---|---|
| Transport | WebRTC/SIP audio in and out | via LiveKit |
| **STT Port** | Streaming speech → text with confidence | **Yes — required (FR-PIPE-03)** |
| Vocabulary Booster | Inject domain terms where the provider supports it | FR-PIPE-04 |
| Transcript Corrector | Optional sub-100ms LLM cleanup pass | FR-PIPE-05 |
| Endpointer | Decide the caller has finished | FR-PIPE-07, 08 |
| Echo Guard | Reject transcripts matching recent system speech | FR-PIPE-12 |
| **TTS Port** | Text → streaming audio | Yes (FR-PIPE-14) |
| Filler Emitter | Speak a holding phrase past a latency threshold | FR-PIPE-17 |

**Key design decisions.**

- The **STT Port is the single most important abstraction in the system.** It is defined
  so that a hosted API, a self-hosted model server, and a future fine-tuned
  IndicConformer all satisfy the same contract. FS-001 identified this as the primary
  justification for the entire project; the architecture must not compromise it.
- **Echo Guard is an explicit component, not a provider setting.** A previous production
  call was entirely lost to the agent transcribing and answering its own speech. The
  guard compares incoming transcripts against a short window of recently synthesised
  text and suppresses matches, independent of whatever acoustic cancellation the
  transport provides.
- **Endpointing is a strategy, not a constant.** The model-based turn detector runs
  alongside a silence threshold; the threshold has a language-aware floor (0.6s for
  Telugu) enforced in configuration validation (FR-PIPE-08).
- **Every stage emits a timestamp** into the turn record (P3, FR-OBS-02).

### 4.3 M3 — Brain Service

**Purpose.** Decide what the agent says and does. This module is the answer to
FS-001 §3.2.

**Structure.**

```
   transcript in
        │
        ▼
  ┌─────────────┐     ┌──────────────┐
  │ Call State  │◀───▶│  Tool Host   │──▶ external systems
  │  (per call) │     └──────────────┘
  └─────┬───────┘
        │  history + state + tool schema
        ▼
  ┌─────────────┐
  │  LLM Port   │  ◀── model/provider by configuration
  └─────┬───────┘
        │
        ├──▶ speech out
        ├──▶ tool invocation
        └──▶ state update / extraction / disposition
```

**Design decisions.**

- **Single instruction set, no graph** (P2). Conversation shape lives in the prompt and
  in call state, not in a topology. This removes edge-loss, edge-condition brittleness,
  and the routing dead-ends that produced silent calls.
- **Tools are callable at any turn** (FR-BRAIN-05). The Tool Host exposes a declared set
  per agent; the model chooses when. This is the capability the incumbent cannot provide
  at all.
- **Tool execution is concurrent with speech** (FR-BRAIN-06). Long tool calls trigger
  filler speech rather than silence — the design compensation for the latency a Brain
  service adds (SRS-001 §4.1).
- **Intent classification is explicit for two cases** that previously caused real harm:
  opt-out detection (FR-BRAIN-10) and correction-versus-refusal (FR-BRAIN-09). These are
  not left to prompt phrasing alone.
- **The Brain runs in-process with the Media Pipeline** in v1, not as a network hop, to
  avoid adding avoidable latency. It remains a separate module with a clean interface so
  it *can* be extracted later.

> **Alternative rejected.** Running the Brain as a remote OpenAI-compatible endpoint —
> which would allow it to be used from Dograh as well (FS-001 §A3) — was considered.
> Rejected for v1 because it adds a network round trip to every turn on a system already
> at its latency budget. The interface is kept compatible so the option survives.

### 4.4 M4 — Agent Registry

**Purpose.** An agent is a versioned artefact. This module owns its lifecycle.

| Concern | Design |
|---|---|
| Source of truth | Files in git (P6, FR-AGENT-02) |
| Validation | Schema validation plus semantic rules — e.g. rejecting a Telugu endpoint threshold below 0.6s (FR-PIPE-08), or a closing statement appearing more than once (NFR-QUAL-07) | 
| Deployment | Explicit version pin; dry-run default (P5, FR-AGENT-06) |
| Partial update safety | Deployment writes only submitted fields; never replaces whole configuration objects (FR-AGENT-05) |
| Rollback | Redeploy a prior version; ≤5 min (NFR-REL-05) |

> FR-AGENT-05 exists because the incumbent's write semantics silently destroyed a model
> override in production. The registry treats "what did this change?" as a first-class
> question, answerable before the change is applied.

### 4.5 M5 — Campaign Engine

**Purpose.** Own contact lists, campaigns and per-contact state.

| Concern | Design |
|---|---|
| Ingestion | CSV with declared schema; validated and de-duplicated on upload (FR-CAMP-02) |
| Binding | A campaign pins a contact list to a **specific agent version**, never "latest" — so a mid-campaign deployment cannot change agent behaviour halfway through |
| State | Per-contact state machine, persisted (§4.9) |
| Restart safety | State is in the database, not in memory (NFR-REL-02, FR-CAMP-10) |
| Results | Signed webhook per call, with retry and visible failures (FR-CAMP-12, 13) |

### 4.6 M6 — Dialer

**Purpose.** Decide *whether and when* a given contact may be called. This module is the
system's principal safety boundary.

Four gates, evaluated in order, all of which must pass:

| Order | Gate | Source |
|---|---|---|
| 1 | **Suppression** — number is not opted out | FR-CAMP-08, FR-CMP-01 |
| 2 | **Calling window** — within permitted hours/days | FR-CAMP-06 |
| 3 | **Retry policy** — attempt cap and backoff satisfied | FR-CAMP-07 |
| 4 | **Concurrency** — per-campaign and global limits | FR-CAMP-05 |

> **Gate 1 applies to every origination path, including manual test calls** (FR-CMP-01).
> This is deliberately enforced in the Dialer rather than the Campaign Engine, so no
> caller can bypass it by originating a call through another route.

### 4.7 M7 — Observability

**Purpose.** Make the system diagnosable by one person (Objective 2).

**Three record types:**

| Record | Grain | Contents |
|---|---|---|
| **Call record** | per call | identifiers, agent version, outcome, duration, disposition, extracted data, cost |
| **Turn record** | per turn | the full latency breakdown of FR-OBS-02, transcripts both directions, token counts |
| **Event record** | per event | typed errors, provider faults, state transitions |

**Design decisions.**

- **Provider faults are a distinct event class** (P4, FR-OBS-05). Rate limiting, credit
  exhaustion and authentication failure each get their own type and alert. This is the
  single highest-value observability requirement: it directly prevents the multi-day
  misdiagnoses that have already occurred twice.
- **The turn record is the performance contract.** NFR-PERF is judged on it, and it is
  designed so that no single component can hide inside an aggregate.
- **Existing tools are the starting point**, not replaced: `analyze_runs.py`,
  `recent_calls.py`, `compare_models.py` (P7, FS-001 §3.6).

### 4.8 M8/M9 — Platform API and Dashboard

The existing Next.js + Supabase dashboard is extended rather than rebuilt (P7).

| Concern | Design |
|---|---|
| API | Authenticated HTTP; the only route to control-plane actions |
| Auth | Existing Supabase auth (NFR-SEC-03) |
| Confirmations | Destructive actions state real-world consequence, explicitly including that real billed calls will be placed (NFR-USE-02) |
| Diagnosis | Call review shows transcript, audio, per-turn latency and typed errors on one screen — the 2-minute target of NFR-USE-01 |

### 4.9 Data architecture

**PostgreSQL (existing Supabase)** for structured data; **S3-compatible object storage
(existing MinIO)** for audio.

Principal entities and relationships:

```
  agent ──< agent_version
                  │
                  ▼
  contact_list ──< contact          campaign ──< campaign_contact
       │                                │              │
       └────────────────────────────────┘              ▼
                                                      call ──< turn
                                                       │
                                                       ├──< event
                                                       └──── recording (object store ref)

  suppression_list  (independent, permanent)
```

| Decision | Rationale |
|---|---|
| `campaign_contact` is a join with its own state | Same contact may appear in several campaigns with different outcomes |
| `agent_version` is immutable once deployed | Reproducibility — a call can always be explained by the exact config that ran it |
| Recordings referenced, not stored, in Postgres | FR-DATA-02; keeps the database small and retention independently enforceable |
| `suppression_list` is independent of campaigns | Must outlive any campaign (FR-DATA-04) |
| Schema evolves by ordered migrations | FR-DATA-05 |

> **Retention** (FR-DATA-03) is enforced per data class, with recordings carrying a
> `training_use_permitted` flag set from consent (FR-CMP-04). The Phase 4 ASR workstream
> may only export recordings where that flag is true.

---

## 5. Call Flow

### 5.1 Outbound call lifecycle

```
 Dialer                Telephony        Media Pipeline        Brain           Obs
   │                       │                  │                 │              │
   │ 4 gates pass          │                  │                 │              │
   ├──────────────────────▶│ originate        │                 │              │
   │                       ├─── SIP INVITE ───────────▶ PSTN    │              │
   │                       │◀── answered ─────────────           │              │
   │                       ├─────────────────▶│ session up      │              │
   │                       │                  ├────────────────▶│ greeting     │
   │                       │                  │◀──── text ──────┤              │
   │                       │                  ├─ TTS ─▶ caller  │              │
   │                       │                  │                 │              │
   │                       │        ┌─────────┴──── TURN LOOP ──┴──────┐       │
   │                       │        │ caller speaks                     │       │
   │                       │        │  → STT (streaming)                │       │
   │                       │        │  → Echo Guard                     │       │
   │                       │        │  → Endpointer decides turn end  ──┼──────▶│ t0
   │                       │        │  → Brain: history + state         │       │
   │                       │        │      ├─ tool call? → Tool Host    │       │
   │                       │        │      │   └─ filler speech if slow │       │
   │                       │        │      └─ response text           ──┼──────▶│ t1
   │                       │        │  → TTS first chunk              ──┼──────▶│ t2
   │                       │        │  → audio to caller                │       │
   │                       │        │  → barge-in may interrupt         │       │
   │                       │        └───────────────────────────────────┘       │
   │                       │                  │                 │              │
   │                       │                  │  end condition  │              │
   │                       │◀─────────────────┤◀────────────────┤ disposition  │
   │                       ├─ hangup ─▶       │                 │              │
   │◀── outcome ───────────┤                  │                 │              │
   │ update campaign_contact                  │                 │  turn+call records
   │ → webhook to client                      │                 │              │
```

**Turn latency = t2 − t0** (NFR-PERF-01). Every intermediate timestamp is retained so
that a regression can be attributed to a component rather than guessed at.

### 5.2 End conditions

| Condition | Handling |
|---|---|
| Goal achieved | Closing statement (once), disposition, hangup |
| Caller refuses | Closing statement, disposition, hangup |
| **Caller opts out** | Closing statement, **write to suppression list**, disposition, hangup |
| Caller hangs up | Disposition from state at hangup |
| Max duration exceeded | Forced hangup, disposition `timeout` |
| Unhandled input | **Re-prompt, capped** (FR-BRAIN-13) — never silence |
| Provider fault | Typed event, alert, disposition `platform_error`, contact eligible for retry |

> The last two rows encode the incumbent's two most damaging behaviours: silent dead
> ends, and provider faults recorded as if the call had simply failed.

---

## 6. Technology Decisions

Recorded in decision-record form. Each states what was chosen, what was rejected, and
what would reverse the decision.

### ADR-01 — LiveKit as media and agent framework

- **Decision:** Build on LiveKit (self-hosted; LiveKit Cloud acceptable for early phases).
- **Rejected:** Pipecat (would require building SIP bridging, call lifecycle and barge-in
  in-house, and forfeits the turn-detector model — rebuilding the incumbent's foundation
  in order to escape its graph); building from first principles (2–3 months of
  undifferentiated work).
- **Why:** Supplies transport, SIP, barge-in, tool calling and an open-source
  **multilingual turn-detector model** — the last of which attacks the largest single
  latency component (SRS-001 §4.1).
- **Reversal trigger:** LiveKit SIP proves unable to interoperate with the chosen trunk,
  or self-hosting exceeds available operational capacity.

### ADR-02 — Provider-agnostic telephony adapter

- **Decision:** All telephony behind M1's port; ship one real adapter plus a simulator.
- **Why:** FS-001 OI-1 is unresolved. The architecture must not be blocked by, or bet
  on, the answer.
- **Reversal trigger:** None foreseen; this is cheap insurance.

### ADR-03 — Prompt-plus-tools conversation control (no graph)

- **Decision:** Conversation shape lives in an instruction set, call state and a tool
  set.
- **Rejected:** Any node-graph representation.
- **Why:** FS-001 §3.2 — graphs cannot express mid-conversation tool use, lose edges on
  persistence, and evaluate nuanced conditions unreliably.
- **Reversal trigger:** None. This is the project's reason for existing.

### ADR-04 — STT behind a first-class port

- **Decision:** A single STT contract satisfied by hosted APIs, self-hosted servers and
  future fine-tuned models alike.
- **Why:** FS-001 §3.3 — the primary justification. AI4Bharat IndicConformer is MIT
  licensed and fine-tunable, and the organisation holds in-domain Telugu audio.
- **Reversal trigger:** None.

### ADR-05 — Brain in-process for v1

- **Decision:** Brain runs inside the session worker, not as a network service.
- **Rejected:** Remote OpenAI-compatible Brain service (which would also be usable from
  Dograh, per FS-001 §A3).
- **Why:** Avoids a network round trip on every turn, on a system already at its latency
  budget.
- **Reversal trigger:** A need to serve the Brain to another platform, or to scale it
  independently. The interface is kept compatible so this remains available.

### ADR-06 — Reuse the existing dashboard and analysis tooling

- **Decision:** Extend the Next.js/Supabase dashboard and the existing Python analysis
  and evaluation tools.
- **Why:** ~30% of the platform already exists, concentrated in the observability and
  evaluation layers greenfield projects usually lack (FS-001 §3.6).
- **Reversal trigger:** Dashboard coupling to Dograh's data model proves deeper than
  anticipated.

### ADR-07 — PostgreSQL + object storage on existing infrastructure

- **Decision:** Supabase Postgres for structured data, MinIO for audio.
- **Why:** Already operated; no new operational surface (C-01, C-06, NFR-PORT-02).

### ADR-09 — Cascaded pipeline, not speech-to-speech

- **Decision:** Keep the cascaded STT → Brain → TTS pipeline. Do not adopt a realtime
  speech-to-speech (S2S) model.
- **Rejected:** OpenAI Realtime, Gemini Live, Moshi.
- **Why:**
  1. **No latency advantage.** OpenAI `gpt-realtime-1.5` measures **820 ms** end-to-end
     against this programme's 800 ms cascaded target. Gemini 3.1 Flash Live measures
     2.98 s. A well-engineered cascaded pipeline beats some end-to-end models outright.
  2. **No usable Telugu.** Qwen3-TTS covers 10 languages, excluding Telugu; Moshi is
     English/French; the hosted S2S vendors do not publish Telugu support.
  3. **It eliminates the STT stage** — and with it the entire STT-001 ladder, which
     FS-001 §10 identifies as the primary justification for the platform. There is no
     transcript stage to boost, correct, race or fine-tune.
  4. **Vendor lock-in returns.** Two vendors exist (OpenAI, Google), at up to $0.30/min,
     versus $0.0095–$0.17/min cascaded across 5+ STT, 7+ TTS and dozens of LLMs.
  5. Shallower tool surface, weakening ADR-03.
- **Reversal trigger:** a Telugu-capable, self-hostable full-duplex model. **Hindi-Moshi**
  (Moshi adapted to Hindi) shows the path is real for Indian languages; AI4Bharat's
  open-source **Indic-TTS** already covers Telugu. Tracked as v3 research.

### ADR-10 — Endpointing is a trainable model, not a timer

- **Decision:** Treat end-of-turn detection as a first-class model to be fine-tuned for
  Telugu, on the same corpus as the STT workstream.
- **Rejected:** Silence-threshold endpointing as the permanent strategy.
- **Why:** Endpointing is the largest single latency component (800 ms measured). LiveKit's
  turn detector covers 14 languages including Hindi but **not Telugu**, and silence
  thresholds cannot safely go below ~0.6 s for Telugu — 75% of an 800 ms budget. Precedent
  exists (Thai, arXiv 2510.04016); the base is Qwen2.5-0.5B, CPU-inferable.
- **Reversal trigger:** LiveKit adds Telugu to the supported set, making the fine-tune
  unnecessary. Worth checking before committing the 19 days.

### ADR-08 — Two-plane separation

- **Decision:** Control plane and media plane share only the database and a queue.
- **Why:** NFR-REL-02 and NFR-REL-03 — a media crash must not corrupt campaign state,
  and a control restart must not drop live calls.

---

## 7. Cross-Cutting Concerns

### 7.1 Error handling

| Class | Examples | Handling |
|---|---|---|
| **Provider fault** | 429 rate limit, 402 credit exhausted, 401 auth | Typed event, alert, call marked `platform_error`, contact retried. **Never** recorded as a call outcome. |
| **Transient** | Timeout, dropped socket | Bounded retry within the call where safe |
| **Conversation** | Unhandled input | Capped re-prompt; never silence |
| **Configuration** | Invalid agent artefact | Rejected at deploy, before any call |
| **Fatal** | Unrecoverable session error | Terminate one call only; other calls unaffected |

> The first row is the highest-value rule in this document's error model. Both prolonged
> production outages to date were provider billing faults presented as ordinary call
> failures, which sent diagnosis to the prompts for days.

### 7.2 Configuration

Three layers, most specific winning: platform defaults → agent version → campaign
override. Secrets live only in environment configuration (NFR-SEC-01) and are never
written into agent artefacts, which are in git.

### 7.3 Security

| Concern | Approach |
|---|---|
| Credentials | Environment only; never in git or agent config |
| Transport | TLS on all external interfaces |
| Dashboard | Authenticated; no unauthenticated data route |
| Webhooks | Signed so recipients can verify origin |
| Recordings | Non-public; authorised, time-limited access only |
| Data minimisation | Only call-necessary personal data reaches any provider |

### 7.4 Observability and alerting

Alerts are deliberately few, so that they are read:

| Alert | Condition |
|---|---|
| Provider fault | Any credit/auth failure; rate limits above threshold |
| Call failure rate | Platform-fault calls exceed 1% (NFR-REL-01) |
| Latency regression | p50 turn latency exceeds the parity target |
| Campaign stalled | Running campaign with no completed call in an interval |
| Silent call | Any call completing with no system speech (NFR-QUAL-05) |

---

## 8. Deployment View (summary)

Detailed in DEP-001.

| Component | Deployment |
|---|---|
| Control-plane services | Containers on existing Coolify host |
| Session workers | Scaled by concurrent-call demand |
| LiveKit server | Self-hosted container, or LiveKit Cloud in early phases (A-02) |
| Database | Existing Supabase Postgres |
| Object storage | Existing MinIO |
| Dashboard | Existing deployment pipeline |
| Dograh | **Retained and running throughout** (C-04); decommissioned only after G7 |

---

## 9. Traceability

| HLD element | Satisfies |
|---|---|
| M1 + ADR-02 | FR-TEL-01…09, EI-01, NFR-MAINT-02 |
| M2 STT Port + ADR-04 | FR-PIPE-02…06, NFR-QUAL-01/02 |
| M2 Echo Guard | FR-PIPE-12, NFR-QUAL-03 |
| M2 Endpointer | FR-PIPE-07/08/09, NFR-QUAL-04 |
| M3 + ADR-03 | FR-BRAIN-01…13, NFR-QUAL-06/07 |
| M4 | FR-AGENT-01…06, NFR-REL-05 |
| M5 | FR-CAMP-01…04, 09…13, NFR-REL-02 |
| M6 four gates | FR-CAMP-05…08, FR-CMP-01 |
| M7 + §7.1 | FR-OBS-01…08, NFR-PERF-06, NFR-REL-04, NFR-USE-01 |
| M8/M9 + ADR-06 | FR-UI-01…08, NFR-SEC-03, NFR-USE-02 |
| §4.9 | FR-DATA-01…06, FR-CMP-04 |
| ADR-08 | NFR-REL-02, NFR-REL-03, NFR-SCAL-02 |

---

## Appendix A — Design Risks

| ID | Risk | Mitigation |
|---|---|---|
| DR-1 | SIP trunking unavailable (FS-001 OI-1) | ADR-02 adapter; provider migration; FS-001 §A3 fallback |
| DR-2 | Brain adds latency beyond budget | ADR-05 in-process; filler speech (FR-PIPE-17); measured at G4 |
| DR-3 | LiveKit turn detector underperforms on Telugu | Endpointer is a strategy; silence threshold retained as fallback |
| DR-4 | Dashboard coupled to Dograh's data model | Assess early; ADR-06 reversal trigger |
| DR-5 | Self-hosting LiveKit exceeds operator capacity | A-02: LiveKit Cloud for v1, self-host later |
| DR-6 | Simulator diverges from real telephony behaviour | Periodic real-call validation; simulator is not the only gate |
