# Software Requirements Specification
## Self-Hosted Voice AI Orchestration Platform ("Project Vaani")

| Field | Value |
|---|---|
| Document ID | SRS-001 |
| Version | 1.0 |
| Date | 2026-08-23 |
| Status | Draft — awaiting sign-off (Gate G1) |
| Preceding document | FS-001 (Feasibility Study) |
| Succeeding documents | HLD-001, TP-001 |
| Standard | Structured after IEEE 830-1998 |

> **Gate notice.** In the V-model adopted for this programme, this document is the
> baseline against which System Testing and UAT are written. No implementation of a
> V-model module should begin before this document is signed off (Gate G1).

---

## 1. Introduction

### 1.1 Purpose

This document specifies the requirements for a self-hosted voice AI orchestration
platform that will replace Dograh as the execution environment for BS Wealth Finance's
outbound Indian-language voice agents.

It is written for the implementer, and it is the source for the Test Plan (TP-001).
Every requirement carries a unique identifier so that test cases can trace back to it.

### 1.2 Scope

**In scope for v1** (confirmed non-negotiable by the product owner):

- Outbound calling over the public telephone network
- Campaign management: contact lists, dialing, concurrency control, retries, reporting
- A conversation engine capable of tool calling and non-graph dialogue design
- A pluggable speech-recognition layer supporting third-party and self-hosted models
- Call observability: transcripts, latency metrics, outcomes, recordings
- An operator dashboard

**Explicitly out of scope for v1**, deferred to later releases:

| Item | Deferred to |
|---|---|
| Appointment booking and calendar integration | v2 |
| Visual agent-builder user interface | v2 |
| Inbound calling | v2 |
| Multi-tenancy, per-client logins, self-serve onboarding | Not planned |
| Usage metering and billing | Not planned |
| Self-hosted fine-tuned ASR model | v2 (Phase 4 workstream) |

**Rationale for the deferrals.** The platform is operated by its owner on behalf of
clients; clients do not log in. This removes approximately 60% of what an equivalent
commercial product would require. Appointment booking is deferred despite being a
motivating use case because v1 must first prove call quality parity; the tool-calling
foundation it needs is nonetheless required in v1 (FR-BRAIN-05).

### 1.3 Definitions and Abbreviations

| Term | Meaning |
|---|---|
| **Agent** | A configured voice persona: prompt, voice, model selection, and behaviour |
| **Turn** | One exchange: caller speaks, system responds |
| **Turn latency** | Elapsed time from end of caller speech to first audible system speech |
| **TTFB** | Time to first byte/token from a model |
| **Endpointing** | Deciding that the caller has finished speaking |
| **Barge-in** | Caller interrupting system speech; system must stop talking |
| **WER** | Word Error Rate — standard speech-recognition accuracy measure |
| **SIP** | Session Initiation Protocol — telephony signalling |
| **PSTN** | Public Switched Telephone Network |
| **DLT** | Distributed Ledger Technology registry — Indian regulatory regime for commercial communications |
| **DPDP** | Digital Personal Data Protection Act (India) |
| **Brain** | The conversation-control service: decides what the agent says and does |
| **Disposition** | The recorded outcome of a call |

### 1.4 References

| Ref | Document |
|---|---|
| R1 | FS-001 Feasibility Study |
| R2 | LiveKit Agents documentation — STT and speech pipeline |
| R3 | AI4Bharat IndicConformer (MIT licence) |
| R4 | Existing production measurements — `findings.md`, this repository |
| R5 | `workflows/gptoss120b_prompts.md` — tuned Telugu prompt corpus |

---

## 2. Overall Description

### 2.1 Product Perspective

The platform replaces Dograh in an existing operational context. It is not greenfield:
it must interoperate with an existing dashboard, existing contact data, existing
telephony arrangements, and an existing body of tuned Telugu prompts.

```
   Contact data ──▶ Campaign Engine ──▶ Dialer ──▶ Telephony (SIP) ──▶ PSTN ──▶ Customer
                          │                              │
                          │                              ▼
                          │                      Media Session (LiveKit)
                          │                              │
                          │                    ┌─────────┼─────────┐
                          │                    ▼         ▼         ▼
                          │                   STT      Brain      TTS
                          │                    │         │         │
                          ▼                    └────┬────┘         │
                   Observability ◀──────────────────┴──────────────┘
                          │
                          ▼
                     Dashboard
```

### 2.2 Product Functions (summary)

| Module | Code | Responsibility |
|---|---|---|
| Telephony Adapter | TEL | Originate and manage PSTN calls via SIP |
| Media Pipeline | PIPE | Audio in/out, STT, endpointing, TTS, barge-in |
| Conversation Engine (Brain) | BRAIN | Decide what to say; execute tools |
| Agent Configuration | AGENT | Define, version and publish agents |
| Campaign & Dialer | CAMP | Contact lists, scheduling, concurrency, retries |
| Observability | OBS | Transcripts, metrics, recordings, dispositions |
| Operator Dashboard | UI | Human control and review surface |
| Data & Storage | DATA | Persistence, retention, access |
| Compliance | CMP | Consent, opt-out, disclosure, retention enforcement |

### 2.3 User Characteristics

| User | Description | Implication |
|---|---|---|
| **Operator** (Vishnu) | Sole builder and operator. Technically capable but not a full-time platform engineer; time-constrained. | The system must be diagnosable quickly and must fail safely without supervision. Operational simplicity outweighs feature richness. |
| **Client** | Business owner receiving leads. No system access. | Outputs must be presentable without exposing internals. |
| **Call recipient** | Telugu-speaking member of the public, often on a low-quality mobile connection, frequently on speakerphone. | Audio robustness, echo tolerance, and interruption handling are functional requirements, not polish. |

### 2.4 Constraints

| ID | Constraint |
|---|---|
| C-01 | The platform is self-hosted on existing Coolify infrastructure |
| C-02 | Telephony access is limited to what the provider offers; SIP trunking availability is an open item (FS-001 §3.5) |
| C-03 | Primary language is Telugu; the system must not assume English-language behaviour anywhere |
| C-04 | Dograh remains live throughout development and must not be disrupted |
| C-05 | Live campaigns call real customers; defects have monetary and reputational cost |
| C-06 | Single operator — no on-call rotation exists |
| C-07 | Indian regulatory regime (DLT/TRAI, DPDP) applies to all outbound calling |

### 2.5 Assumptions and Dependencies

| ID | Assumption | If false |
|---|---|---|
| A-01 | The telephony provider offers SIP trunking with G.711 | Migrate provider, or fall back to FS-001 §A3 |
| A-02 | LiveKit self-hosting is viable on existing infrastructure | Use LiveKit Cloud for v1 |
| A-03 | Existing MinIO recordings are usable for later ASR work | Phase 4 STT workstream is descoped |
| A-04 | Existing Supabase/Next.js dashboard can be extended | Dashboard cost increases materially |
| A-05 | Groq (or equivalent) remains available at usable rates and limits | Model abstraction (FR-BRAIN-02) absorbs the change |

---

## 3. Functional Requirements

Priority uses MoSCoW: **M**ust, **S**hould, **C**ould, **W**on't (this release).

### 3.1 Telephony Adapter (TEL)

| ID | Requirement | Priority | Release |
|---|---|---|---|
| FR-TEL-01 | The system shall originate outbound PSTN calls to Indian mobile numbers via a SIP trunk. | M | v1 |
| FR-TEL-02 | The telephony layer shall be implemented behind a provider-agnostic interface such that a provider can be substituted without changes to any other module. | M | v1 |
| FR-TEL-03 | The system shall detect and record call-progress outcomes distinctly: answered, busy, no-answer, failed, rejected, invalid number. | M | v1 |
| FR-TEL-04 | The system shall detect answering machines / voicemail and terminate or branch according to agent configuration. | S | v1 |
| FR-TEL-05 | The system shall enforce a configurable maximum call duration and terminate calls exceeding it. | M | v1 |
| FR-TEL-06 | The system shall present a configured caller line identity (CLI) on outbound calls. | M | v1 |
| FR-TEL-07 | The system shall transfer a live call to a human agent, warm or cold, preserving the caller's audio session without a perceptible gap. | **M** | **v1** |
| FR-TEL-10 | Transfer shall be invocable **as a tool by the Brain**, at any point in the conversation. | M | v1 |
| FR-TEL-11 | On warm transfer, the system shall deliver a spoken or textual call summary to the receiving human. | S | v1 |
| FR-TEL-12 | If no human is available, the system shall fall back to a configured path (callback capture or voicemail) and shall never drop the caller. | M | v1 |
| FR-TEL-13 | Transfer outcome shall be recorded as a disposition identifying the receiving party. | M | v1 |
| FR-TEL-08 | The system shall accept inbound calls. | W | v2 |
| FR-TEL-09 | The system shall record, per call, the provider-side identifiers necessary to reconcile against provider billing records. | S | v1 |

### 3.2 Media Pipeline (PIPE)

| ID | Requirement | Priority | Release |
|---|---|---|---|
| FR-PIPE-01 | The system shall stream call audio bidirectionally in real time between the PSTN leg and the processing pipeline. | M | v1 |
| FR-PIPE-02 | The system shall transcribe caller speech to text in the configured language using a streaming speech-recognition service. | M | v1 |
| FR-PIPE-03 | The speech-recognition component shall be abstracted behind an interface permitting substitution of any provider or self-hosted model without changes to other modules. *(Traces FS-001 §3.3 — primary justification.)* | M | v1 |
| FR-PIPE-04 | The system shall support supplying a domain vocabulary / keyword-boost list to the speech-recognition component where the provider supports it. | S | v1 |
| FR-PIPE-05 | The system shall support an optional post-transcription correction pass before the transcript is passed to the Brain. | C | v1 |
| FR-PIPE-06 | The system shall support routing the same audio to two speech-recognition engines concurrently and selecting a result by confidence. | C | v2 |
| FR-PIPE-07 | The system shall determine end-of-speech (endpointing) using a configurable strategy, and shall support a semantic/model-based turn detector in addition to silence-duration thresholds. | M | v1 |
| FR-PIPE-08 | The end-of-speech silence threshold shall be configurable per agent and shall not be settable below 0.6 seconds for Telugu without an explicit override acknowledgement. *(Traces R4: callers audibly protested being cut off at 0.35s.)* | M | v1 |
| FR-PIPE-09 | The system shall register caller utterances of a single word as a valid turn. *(Traces R4: Telugu one-word replies అవును / వద్దు / ఆ were previously not registered at all.)* | M | v1 |
| FR-PIPE-10 | The system shall support barge-in: when the caller begins speaking during system speech, system audio shall stop within 300 ms. | M | v1 |
| FR-PIPE-11 | Barge-in shall be enable/disable-able per conversation stage. | S | v1 |
| FR-PIPE-12 | The system shall apply acoustic echo suppression such that system speech returning through the caller's device is not transcribed as caller speech. *(Traces R4: a full call was previously lost to the agent transcribing and answering itself.)* | M | v1 |
| FR-PIPE-13 | The system shall synthesise system speech in the configured language and voice via a streaming text-to-speech service. | M | v1 |
| FR-PIPE-14 | The text-to-speech component shall be abstracted behind an interface permitting provider substitution. | M | v1 |
| FR-PIPE-15 | Speech synthesis speed and volume shall be configurable per agent. | S | v1 |
| FR-PIPE-16 | The system shall begin speaking as soon as the first synthesised audio chunk is available, rather than waiting for complete synthesis. | M | v1 |
| FR-PIPE-17 | The system shall emit configurable filler speech when a Brain response or tool call is expected to exceed a threshold. | S | v1 |
| FR-PIPE-18 | The system shall emit a natural backchannel acknowledgement (e.g. "అవునండి", "సరే") within 200 ms of the endpoint decision, ahead of the substantive response. | M | v1 |
| FR-PIPE-19 | The system shall begin speech synthesis on the first complete sentence of a response rather than waiting for full generation. | M | v1 |
| FR-PIPE-20 | The endpointing strategy shall support a semantic/model-based turn detector for languages where one is available, and shall be extensible to a self-hosted turn-detection model. | M | v1 |

#### 3.2.1 Speech recognition customization (STT)

The STT requirements above are elaborated into a full workstream in **STT-001**, which
defines a four-level ladder (measure → tune → correct → own) and adds requirements
**FR-STT-01…12** and **NFR-STT-01…08**. Those requirements form part of this
specification by reference.

Three of them are **Must in v1** even though the self-hosted fine-tuned model itself is
v2, because without them level 3 becomes a retrofit rather than a configuration change:

| ID | Requirement | Priority | Release |
|---|---|---|---|
| FR-STT-08 | The system shall support an STT implementation backed by a self-hosted model server reachable over HTTP/WebSocket. | M | v1 |
| FR-STT-09 | The system shall export a training corpus of call audio and transcripts, restricted to recordings where `training_use_permitted` is true. | M | v1 |
| FR-STT-12 | The system shall record, per turn, which STT implementation and model version produced the transcript. | M | v1 |

> These three are the difference between speech-recognition ownership being *scheduled*
> and being *hypothetical*. FS-001 §10 identifies that ownership as the primary
> justification for the programme.

### 3.3 Conversation Engine — Brain (BRAIN)

> This module addresses FS-001 §3.2, the structural limitation of the incumbent system.

| ID | Requirement | Priority | Release |
|---|---|---|---|
| FR-BRAIN-01 | The system shall generate agent responses from a single instruction set (prompt) plus conversation history, without requiring a predefined node graph. | M | v1 |
| FR-BRAIN-02 | The language model shall be abstracted behind an interface permitting provider and model substitution by configuration. | M | v1 |
| FR-BRAIN-03 | The system shall maintain full conversation history for the duration of a call and make it available to the model, subject to a configurable context strategy. | M | v1 |
| FR-BRAIN-04 | The system shall support conversation-state variables that persist across turns within a call (e.g. captured name, loan type, qualification answers). | M | v1 |
| FR-BRAIN-05 | The system shall support model-invoked tool calls at any point in the conversation, with the tool set defined per agent. *(Traces FS-001 §3.2 — the capability the incumbent architecture cannot provide.)* | M | v1 |
| FR-BRAIN-06 | Tool execution shall be asynchronous with respect to speech, such that the agent can speak while a tool call is in progress. | S | v1 |
| FR-BRAIN-07 | The system shall support a structured data-extraction schema, populated during or at the end of the call. | M | v1 |
| FR-BRAIN-08 | The system shall classify and record a call disposition on completion. | M | v1 |
| FR-BRAIN-09 | The system shall distinguish a correction from a refusal when classifying caller intent. *(Traces R4: a caller correcting their loan type was wrongly treated as opting out and was told they would not be called again.)* | M | v1 |
| FR-BRAIN-10 | The system shall detect an explicit opt-out request and record it in a suppression list. | M | v1 |
| FR-BRAIN-11 | The system shall terminate the call gracefully on completion, refusal or opt-out, delivering a closing statement exactly once. | M | v1 |
| FR-BRAIN-12 | The system shall recover from a caller utterance that matches no anticipated path by re-prompting, and shall never produce silence as a result of an unhandled input. *(Traces R4: the classic incumbent failure was a routing dead end, not latency.)* | M | v1 |
| FR-BRAIN-13 | A re-prompt for the same unanswered question shall be permitted at most a configurable number of times, default once. | M | v1 |
| FR-BRAIN-14 | The system shall support appointment scheduling via calendar tools. | W | v2 |

### 3.4 Agent Configuration (AGENT)

| ID | Requirement | Priority | Release |
|---|---|---|---|
| FR-AGENT-01 | An agent shall be defined by a versioned configuration artefact containing: instruction set, language, model selection, STT selection, TTS voice, turn-taking parameters, tool set, extraction schema, and disposition vocabulary. | M | v1 |
| FR-AGENT-02 | Agent configurations shall be stored in version control as the source of truth. | M | v1 |
| FR-AGENT-03 | The system shall support deploying a specific agent version, and rolling back to a previous version. | M | v1 |
| FR-AGENT-04 | The system shall validate an agent configuration before deployment and reject invalid configurations with a specific error. | M | v1 |
| FR-AGENT-05 | Deployment of an agent configuration shall not silently alter any field not present in the submitted artefact. *(Traces R4: the incumbent replaces whole configuration objects on write, which destroyed a model override in production.)* | M | v1 |
| FR-AGENT-06 | The system shall support a dry-run mode that reports what a deployment would change without applying it. | M | v1 |
| FR-AGENT-07 | The system shall provide a visual agent-builder interface. | W | v2 |

### 3.5 Campaign and Dialer (CAMP)

| ID | Requirement | Priority | Release |
|---|---|---|---|
| FR-CAMP-01 | The system shall accept a contact list by CSV upload with a defined schema. | M | v1 |
| FR-CAMP-02 | The system shall validate contact lists on upload, rejecting or flagging malformed and duplicate numbers. | M | v1 |
| FR-CAMP-03 | The system shall create a campaign binding a contact list to an agent version. | M | v1 |
| FR-CAMP-04 | The system shall start, pause, resume and stop a campaign. | M | v1 |
| FR-CAMP-05 | The system shall enforce a configurable maximum number of concurrent calls per campaign and globally. | M | v1 |
| FR-CAMP-06 | The system shall enforce configurable permitted calling hours and days, and shall not dial outside them. | M | v1 |
| FR-CAMP-07 | The system shall retry unsuccessful calls according to a configurable policy (attempt cap, backoff interval, per-outcome rules). | M | v1 |
| FR-CAMP-08 | The system shall never dial a number present in the suppression list. | M | v1 |
| FR-CAMP-09 | The system shall record per-contact call state and make campaign progress visible in real time. | M | v1 |
| FR-CAMP-10 | The system shall resume a campaign correctly after a platform restart, without re-dialling completed contacts. | M | v1 |
| FR-CAMP-11 | The system shall support scheduling a campaign to begin at a future time. | S | v1 |
| FR-CAMP-12 | The system shall emit per-call results to a configurable webhook. | M | v1 |
| FR-CAMP-13 | Webhook delivery shall be retried on failure and failures shall be visible to the operator. | S | v1 |

### 3.6 Observability (OBS)

| ID | Requirement | Priority | Release |
|---|---|---|---|
| FR-OBS-01 | The system shall record, per call, the full transcript with speaker attribution and per-utterance timestamps. | M | v1 |
| FR-OBS-02 | The system shall record, per turn: end-of-speech time, STT completion time, model first-token time, first-audio-out time, and total turn latency. *(These are the measurements on which FS-001 §3.1 and NFR-PERF are judged.)* | M | v1 |
| FR-OBS-03 | The system shall record per-call token consumption and estimated cost by component. | S | v1 |
| FR-OBS-04 | The system shall store call audio recordings, subject to retention policy. | M | v1 |
| FR-OBS-05 | The system shall record structured error events with sufficient context to distinguish provider faults (rate limits, credit exhaustion, authentication) from application faults. *(Traces R4: two multi-day production outages were provider billing failures misdiagnosed as prompt defects.)* | M | v1 |
| FR-OBS-06 | The system shall raise an operator alert when provider errors exceed a threshold. | M | v1 |
| FR-OBS-07 | The system shall expose aggregate reporting per campaign: connection rate, average duration, disposition distribution, latency distribution. | M | v1 |
| FR-OBS-08 | The system shall allow export of transcripts and results. | S | v1 |

### 3.7 Operator Dashboard (UI)

| ID | Requirement | Priority | Release |
|---|---|---|---|
| FR-UI-01 | The dashboard shall allow upload of contact lists and creation of campaigns. | M | v1 |
| FR-UI-02 | The dashboard shall allow start, pause, resume and stop of campaigns. | M | v1 |
| FR-UI-03 | The dashboard shall display live campaign progress. | M | v1 |
| FR-UI-04 | The dashboard shall allow review of an individual call: transcript, audio, latency, disposition, extracted data. | M | v1 |
| FR-UI-05 | The dashboard shall allow placing a single test call to a specified number with a selected agent version. | M | v1 |
| FR-UI-06 | The dashboard shall display which agent version is deployed. | M | v1 |
| FR-UI-07 | The dashboard shall require authentication. | M | v1 |
| FR-UI-08 | The dashboard shall support a text-based conversation preview against an agent without placing a call. | S | v1 |

### 3.8 Data and Storage (DATA)

| ID | Requirement | Priority | Release |
|---|---|---|---|
| FR-DATA-01 | The system shall persist contacts, campaigns, calls, turns, transcripts, dispositions, extracted data and agent versions. | M | v1 |
| FR-DATA-02 | The system shall store call recordings in object storage separately from structured data. | M | v1 |
| FR-DATA-03 | The system shall apply configurable retention periods per data class and delete data on expiry. | M | v1 |
| FR-DATA-04 | The system shall maintain a persistent suppression list surviving campaign and platform lifecycle. | M | v1 |
| FR-DATA-05 | Database schema changes shall be applied by versioned, ordered migrations. | M | v1 |
| FR-DATA-06 | The system shall support export of a call corpus (audio plus transcript) for speech-model training. *(Enables the Phase 4 STT workstream, FS-001 §3.3.)* | S | v1 |

### 3.9 Compliance (CMP)

| ID | Requirement | Priority | Release |
|---|---|---|---|
| FR-CMP-01 | The system shall not dial numbers on the suppression list under any circumstance, including manual test calls. | M | v1 |
| FR-CMP-02 | The system shall record, per contact, the basis and source of the contact record. | M | v1 |
| FR-CMP-03 | The system shall support an agent-configurable automated-caller disclosure statement. | M | v1 |
| FR-CMP-04 | The system shall record whether recording consent applies to each call, and shall mark recordings usable or not usable for model training accordingly. *(Traces FS-001 §6.4 — training on recordings is a secondary processing purpose.)* | M | v1 |
| FR-CMP-05 | The system shall provide an audit trail of campaign start/stop actions and agent deployments, with actor and timestamp. | S | v1 |
| FR-CMP-06 | The system shall enforce DLT-related constraints where applicable. | M | v1 |

---

## 4. Non-Functional Requirements

### 4.1 Performance (PERF)

> **REVISED 2026-08-23 — supersedes the earlier parity targets.** The previous targets
> anchored to the incumbent (1.95 s) rather than to the market, which was the wrong
> reference point. Full analysis, budget and method are in **LAT-001**.
>
> Measured industry reality on real phone calls: the best commercial platform achieves
> **1,296 ms caller-experienced**; Vapi 1,558 ms. Vendor-reported figures run ~490 ms
> lower because they measure server-side. The incumbent's 1.95 s is a server-side
> figure, so the real gap to close is ~880 ms — identifiable and addressable.

| ID | Requirement | Target |
|---|---|---|
| **NFR-PERF-01** | **Server-side turn latency (endpoint decision → first system audio), p50, Telugu** | **≤ 800 ms** |
| NFR-PERF-02 | Server-side turn latency, p95, Telugu | ≤ 1,200 ms |
| NFR-PERF-03 | Caller-experienced turn latency, p50 (derived; +≈490 ms telephony) | ≤ 1,300 ms |
| NFR-PERF-04 | Barge-in stop time | ≤ 200 ms |
| NFR-PERF-05 | Time from campaign start to first call initiated | ≤ 10 s |
| NFR-PERF-06 | Every turn shall have latency components recorded per FR-OBS-02 | 100% of turns |
| NFR-PERF-07 | Filler speech emitted when a response is expected to exceed | 1.2 s |
| NFR-PERF-08 | Perceived latency with backchannel acknowledgement | ≤ 400 ms |
| NFR-PERF-09 | Server-side turn latency, p50, English/Hindi | ≤ 600 ms |
| **NFR-PERF-10** | **False-interruption rate at the target endpointing speed** | **≤ incumbent at 0.8 s** |
| NFR-PERF-11 | Transfer decision → human connected, with continuous audio | ≤ 3 s |

> **NFR-PERF-10 is not optional and is reported with every latency figure.** Faster
> endpointing buys interruptions. Callers on the incumbent already protested being cut
> off in Telugu at 0.35 s. A latency win purchased with interruptions is not a win.

> **Dependency.** NFR-PERF-01 is unreachable in Telugu without a Telugu turn-detection
> model. LiveKit's turn detector supports 14 languages including Hindi but **not
> Telugu**, and silence-threshold endpointing cannot safely go below ~0.6 s — which alone
> consumes 75% of an 800 ms budget. See LAT-001 §4.

> **Measurement note.** Model TTFB shall not be used as a proxy for responsiveness.
> On reasoning models it measures the first *reasoning* token, not the first spoken
> word, and was previously misleading by an order of magnitude. Turn latency per
> FR-OBS-02 is the governing metric.

### 4.2 Accuracy and Quality (QUAL)

| ID | Requirement | Target |
|---|---|---|
| NFR-QUAL-01 | Telugu transcript Word Error Rate on a held-out set of real call audio shall be no worse than the incumbent | Parity at G4 |
| NFR-QUAL-02 | Entity accuracy (names, cities, amounts, product terms) shall be measured and reported separately from overall WER | Measured, baselined at G4 |
| NFR-QUAL-03 | System speech shall not be transcribed as caller speech | 0 occurrences in the acceptance set |
| NFR-QUAL-04 | Single-word caller replies shall register as turns | 100% |
| NFR-QUAL-05 | Calls ending with no system speech ("silent calls") | 0 |
| NFR-QUAL-06 | Corrections misclassified as opt-outs | 0 |
| NFR-QUAL-07 | Closing statement delivered more than once per call | 0 |
| NFR-QUAL-08 | Operator acceptance by ear on live calls | Required at G6 |

> **NFR-QUAL-08 is deliberate.** Metric parity is necessary but not sufficient. The
> incumbent has previously passed automated gates while sounding wrong on a real call.

### 4.3 Reliability and Availability (REL)

| ID | Requirement | Target |
|---|---|---|
| NFR-REL-01 | Calls lost to platform fault, as a proportion of calls attempted | < 1% |
| NFR-REL-02 | A platform restart shall not lose campaign state | Guaranteed |
| NFR-REL-03 | A single call failure shall not affect other in-flight calls | Guaranteed |
| NFR-REL-04 | Provider faults (rate limit, credit exhaustion, auth failure) shall be surfaced as distinct, alertable events rather than as generic call failures | Guaranteed |
| NFR-REL-05 | Rollback to the previous agent version | ≤ 5 minutes |
| NFR-REL-06 | Rollback to Dograh for a migrated vertical | ≤ 30 minutes, documented runbook |

### 4.4 Scalability (SCAL)

| ID | Requirement | Target |
|---|---|---|
| NFR-SCAL-01 | Concurrent calls supported on v1 infrastructure | ≥ 10 |
| NFR-SCAL-02 | Architecture shall permit horizontal scaling of call handling without redesign | Design property |
| NFR-SCAL-03 | Contacts per campaign | ≥ 50,000 |

### 4.5 Security (SEC)

| ID | Requirement |
|---|---|
| NFR-SEC-01 | All credentials and API keys shall be held in environment configuration, never in source control or agent artefacts. |
| NFR-SEC-02 | All external interfaces shall be served over TLS. |
| NFR-SEC-03 | The dashboard shall be authenticated; no unauthenticated route shall expose call data. |
| NFR-SEC-04 | Webhook deliveries shall be signed so recipients can verify origin. |
| NFR-SEC-05 | Call recordings and transcripts shall not be publicly addressable; access shall require authorisation and be time-limited. |
| NFR-SEC-06 | Personal data shall not be transmitted to any provider not required for the call. |
| NFR-SEC-07 | Access to production credentials shall be logged. |

### 4.6 Maintainability (MAINT)

| ID | Requirement |
|---|---|
| NFR-MAINT-01 | Each module shall be independently testable, with external dependencies replaceable by test doubles. |
| NFR-MAINT-02 | Provider integrations (telephony, STT, LLM, TTS) shall each sit behind an interface with at least two implementations, or one implementation plus a test double, to prove the abstraction. |
| NFR-MAINT-03 | A developer shall be able to run the system end-to-end locally without placing a real call. |
| NFR-MAINT-04 | Every production failure mode listed in R4 shall have a documented diagnostic procedure. |
| NFR-MAINT-05 | Configuration shall be declarative and version-controlled. |

### 4.7 Usability (USE)

| ID | Requirement |
|---|---|
| NFR-USE-01 | An operator shall be able to determine why a specific call failed within 2 minutes, from the dashboard alone. |
| NFR-USE-02 | Destructive actions (start campaign, deploy agent) shall require explicit confirmation and shall state their real-world consequence, including that real calls will be placed. |
| NFR-USE-03 | Dry-run shall be the default for any deployment command. |

> **NFR-USE-02 and NFR-USE-03** encode existing operating practice: deploy scripts in
> this environment default to dry run because publishing places real, billed calls.

### 4.8 Portability (PORT)

| ID | Requirement |
|---|---|
| NFR-PORT-01 | The platform shall run on the existing container infrastructure. |
| NFR-PORT-02 | No component shall depend on a managed service that cannot be self-hosted, except third-party model and telephony providers. |

---

## 5. External Interface Requirements

| ID | Interface | Requirement |
|---|---|---|
| EI-01 | Telephony provider | SIP trunk; G.711 (PCMU/PCMA) audio; outbound origination from a customer-hosted media server. *Contingent on FS-001 §3.5.* |
| EI-02 | Speech recognition | Streaming audio in, incremental transcript out, with confidence; must accommodate both hosted APIs and a self-hosted model endpoint. |
| EI-03 | Language model | Chat-completion style interface with tool-calling support; OpenAI-compatible endpoints shall be usable by base-URL configuration. |
| EI-04 | Text to speech | Streaming synthesis; first-chunk delivery before completion. |
| EI-05 | Object storage | S3-compatible (existing MinIO). |
| EI-06 | Database | PostgreSQL-compatible (existing Supabase). |
| EI-07 | Outbound webhook | Signed HTTP POST of call results to a client-configured endpoint. |
| EI-08 | Dashboard API | Authenticated HTTP API consumed by the existing Next.js application. |

---

## 6. Requirement Traceability

| Source | Requirements produced |
|---|---|
| FS-001 §3.2 — no mid-call tool calling | FR-BRAIN-01, FR-BRAIN-05, FR-BRAIN-06 |
| FS-001 §3.3 — STT customization | FR-PIPE-03, FR-PIPE-04, FR-PIPE-05, FR-PIPE-06, FR-DATA-06, NFR-QUAL-01, NFR-QUAL-02 |
| FS-001 §3.1 — latency evidence | NFR-PERF-01…07, FR-OBS-02 |
| FS-001 §3.5 — Vobiz SIP gate | FR-TEL-02, EI-01, A-01 |
| FS-001 §5.3 — single-operator risk | NFR-REL-05, NFR-REL-06, NFR-USE-01…03, NFR-MAINT-04 |
| FS-001 §6.2 — regulatory | FR-CMP-01…06, FR-DATA-03, NFR-SEC-05 |
| R4 — production incident history | FR-PIPE-08, FR-PIPE-09, FR-PIPE-12, FR-BRAIN-09, FR-BRAIN-11, FR-BRAIN-12, FR-AGENT-05, FR-OBS-05, NFR-QUAL-03…07 |

> The final row is the most valuable in this document. Each of those requirements
> exists because the behaviour it mandates was previously absent and caused a real,
> diagnosed production failure. They are not speculative.

---

## 7. Acceptance Criteria Summary (Gate Mapping)

| Gate | Requirements that must pass |
|---|---|
| G3 — First call | FR-TEL-01/03, FR-PIPE-01/02/07/13, FR-BRAIN-01, FR-OBS-01 |
| G4 — Quality parity | NFR-PERF-01/02, NFR-QUAL-01…07, FR-PIPE-08/09/10/12 |
| G5 — Campaign parity | FR-CAMP-01…12, FR-OBS-07, NFR-REL-02 |
| G6 — UAT | NFR-QUAL-08, NFR-USE-01…03, FR-UI-01…07 |
| G7 — Cut-over | FR-CMP-01…06, NFR-REL-06, NFR-SEC-01…05 |

---

## Appendix A — Open Requirement Items

| ID | Item | Blocks |
|---|---|---|
| RQ-1 | Confirm SIP and codec support (FS-001 OI-1) | EI-01, FR-TEL-01 |
| RQ-2 | Confirm DLT obligations applicable to CLI and disclosure | FR-CMP-03, FR-CMP-06 |
| RQ-3 | Confirm consent basis permits ASR training use | FR-CMP-04, FR-DATA-06 |
| RQ-4 | Confirm required retention periods per data class | FR-DATA-03 |
| RQ-5 | Define the held-out Telugu audio set for WER measurement | NFR-QUAL-01, NFR-QUAL-02 |

> RQ-5 is an engineering prerequisite for Gate G4 and should be assembled early: without
> an agreed measurement set, "accuracy parity" cannot be demonstrated or disputed.
