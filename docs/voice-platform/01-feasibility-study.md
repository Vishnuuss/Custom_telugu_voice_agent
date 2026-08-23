# Feasibility Study
## Self-Hosted Voice AI Orchestration Platform ("Project Vaani")

| Field | Value |
|---|---|
| Document ID | FS-001 |
| Version | 1.0 |
| Date | 2026-08-23 |
| Author | Engineering |
| Owner | Vishnu (BS Wealth Finance / Tonerun) |
| Status | Draft — awaiting sign-off |
| Preceding document | None (this is the entry gate) |
| Succeeding document | SRS-001 |

---

## 1. Executive Summary

### 1.1 Purpose

This study assesses whether BS Wealth Finance should build and operate a self-hosted
voice AI orchestration platform to replace its current dependency on Dograh, and as a
lower-cost alternative to commercial platforms such as Vapi.

### 1.2 Recommendation

**PROCEED — conditionally.**

The project is technically feasible, economically justified, and operationally
manageable, **provided one blocking unknown is resolved first**: whether the incumbent
telephony provider (Vobiz) offers SIP trunking. This is a single question to a vendor
and gates the entire programme.

**Critically, the project must be justified on the correct grounds.** The originally
stated motivation — that Dograh's orchestrator causes unacceptable latency — is **not
supported by measurement** and is rejected in §3.1. The valid justification is
**architectural control**: the ability to customize speech recognition for Telugu and to
perform mid-conversation tool calls. Those two capabilities are structurally impossible
on both Dograh and Vapi, and they are what determine whether a sales and
appointment-booking agent works at all.

### 1.3 Summary of Findings

| Dimension | Verdict | Confidence |
|---|---|---|
| Technical feasibility | **Feasible** | High |
| Economic feasibility | **Favourable** | Medium — pricing needs verification (§4.5) |
| Operational feasibility | **Feasible with caveats** | Medium — single-operator risk (§5.3) |
| Legal / regulatory feasibility | **Feasible, obligations unchanged** | Medium — DLT/TRAI review required (§6) |
| Schedule feasibility | **Feasible** | Medium |
| **Overall** | **PROCEED, gated on §3.5** | — |

---

## 2. Background and Problem Statement

### 2.1 Current State

BS Wealth Finance operates outbound Indian-language (primarily Telugu) voice agents on a
**self-hosted Dograh instance** at `voice.bswealthfinance.com`, running on Coolify with
MinIO object storage. Four verticals exist or are planned: loan qualification, solar,
investing, and real estate. Workflow 1 (loan, agent "Shreya") is live and places real,
billed calls to real customers.

The current stack per call: Vobiz telephony → Dograh (Pipecat-based) → Sarvam STT →
Groq `openai/gpt-oss-120b` → Cartesia `sonic-3` TTS.

### 2.2 Stated Problems

Three distinct complaints have been raised. They are separated here because they have
different causes and different remedies:

| # | Complaint | Assessment |
|---|---|---|
| P1 | "Dograh latency is too high" | **Partly invalid.** See §3.1 — the orchestrator contributes <5% of turn latency. |
| P2 | "It can't handle sales, high reasoning, or appointment booking" | **Valid and structural.** See §3.2. |
| P3 | "Telugu speech recognition is unusable" | **Valid and solvable only by owning the pipeline.** See §3.3. |

P2 and P3 constitute a sound business case. P1 does not, and building a platform to
solve P1 would fail.

### 2.3 Objective

Deliver a platform that (a) removes the graph-shaped constraint on conversation design,
(b) permits arbitrary customization of the speech-recognition layer including
self-hosted and fine-tuned models, and (c) keeps per-minute cost under the operator's
control, while preserving existing outbound-campaign capability.

---

## 3. Technical Feasibility

### 3.1 Rejection of the latency premise

Measured on production calls (runs 1103/1104, and the 175–189 series):

| Component | Measured | Share of turn |
|---|---|---|
| LLM time-to-first-token | 0.09–0.10s (p50) | ~5% |
| STT + turn detection + TTS | ~1.85s | ~95% |
| **Total turn latency (p50)** | **1.95s** | 100% |

Orchestration overhead — the code that would be replaced — is a small fraction of the
5%. A perfect reimplementation would recover well under 0.1 second.

Furthermore, the largest single component is the **end-of-speech wait**
(`smart_turn_stop_secs`, currently 0.8s), which is set high **deliberately**: at 0.35s,
callers audibly complained of being interrupted mid-sentence. Telugu speakers pause
within sentences. This is a genuine quality/latency trade-off that follows the language,
not the vendor.

**Conclusion: a new orchestrator will not, by itself, be faster.** Any latency
improvement must come from changing components (turn-detection model, STT, TTS,
non-reasoning LLM) — and §3.3 shows the new platform makes those changes *possible*.

> ### ⚠ REVISED 2026-08-23 — this section's conclusion was wrong
>
> The analysis above is correct; the conclusion drawn from it was not. It originally
> recommended targeting **latency parity (1.95 s)**, which anchored to the system being
> replaced rather than to the market. The sponsor rejected that, correctly.
>
> Measured reality on real phone calls: the best commercial platform reaches **1,296 ms**
> caller-experienced, Vapi **1,558 ms**, and vendor-reported figures run ~490 ms lower
> because they are measured server-side. The incumbent's 1.95 s is server-side, so the
> genuine gap is **~880 ms**, and it decomposes into three decisions the platform owns:
>
> | Decision | Recoverable |
> |---|---|
> | When to stop listening (turn detection) | 550 ms |
> | Which model reasons | 400 ms |
> | Where components run, and how output streams | 340 ms |
>
> **Revised target: server-side p50 ≤ 800 ms** (≈1,300 ms caller-experienced), which
> would lead the benchmarked field. The orchestrator is not slow — but *owning* it is
> what makes those three component decisions yours. Latency therefore belongs on the
> justification list after all.
>
> The blocker is that LiveKit's turn detector covers 14 languages including Hindi but
> **not Telugu**, and silence-based endpointing cannot safely go below ~0.6 s. A Telugu
> turn-detection model is consequently required, not optional.
>
> **Full analysis, latency budget, workstream and risks: LAT-001.**

### 3.2 The structural limitation (valid justification #1)

Inspection of the live workflow definitions confirms Dograh exposes six node types:
`startCall`, `agentNode`, `qa`, `webhook`, `endCall`, `globalNode`.

Three consequences make sales and appointment booking infeasible:

1. **No mid-conversation tool calling.** External integration exists only as a
   `webhook` *node* — a fixed position on the graph that must be routed to. Booking an
   appointment therefore requires the graph author to predict *at which turn* the caller
   will ask about availability. A sales conversation cannot be predicted; a caller may
   raise scheduling at turn 3 or turn 20.
2. **Edge loss on persistence.** Workflow 3 lost 4 of 11 edges in a single canvas
   round-trip — every edge sharing an End Call target but one was discarded. Objection
   handling requires substantially more edges than the point at which this degradation
   begins.
3. **Conditions must be short observable literals.** Prose conditions are evaluated
   conservatively by the reasoning model. The judgement sales depends on — "hesitant but
   not refusing" — is inexpressible.

A directed graph models a decision tree. Sales dialogue is not a decision tree. This
limitation is architectural and cannot be remedied by prompt engineering.

### 3.3 Speech-recognition customization (valid justification #2)

This is the strongest technical argument for the project, because it is the one
capability that no managed platform can provide.

**Verified: LiveKit permits STT customization at three levels.**

| Level | Capability | Effort |
|---|---|---|
| 1 | Swap among official plugins (Deepgram, AssemblyAI, Gladia, Speechmatics, Google, …) | Configuration |
| 2 | Implement the STT node directly — stream audio to any HTTP/WebSocket service, return `SpeechEvent` objects. Officially supported. OpenAI-compatible endpoints may reuse `base_url`. | Days |
| 3 | Self-host and fine-tune a Telugu-native model | Weeks (Phase 4 workstream) |

**Level 3 is credible, not aspirational.** AI4Bharat's **IndicConformer** is an
open-source hybrid CTC-RNNT ASR covering all 22 official Indian languages, released
under the **MIT licence** (commercial use permitted), with fine-tuning tooling published
via AI4Bharat NeMo.

BS Wealth possesses an asset no competitor has: **hundreds of hours of real Telugu
sales-call audio** already stored in MinIO. Recent published research indicates the
Indic ASR accuracy gap narrows substantially when models are trained on *entity-dense*
audio — personal names, place names, monetary amounts, product terms. That is precisely
the content on which generic Telugu STT currently fails on these calls.

Four customization levers become available, none of which exist on Vapi or Dograh:

- Running two STT engines concurrently and selecting the higher-confidence result
  (STT cost is marginal relative to LLM and TTS)
- Domain vocabulary boosting (లోన్, ఈఎంఐ, సోలార్, సబ్సిడీ, customer and city names)
- A sub-100ms LLM transcript-correction pass before the reasoning layer
- Fine-tuning on proprietary in-domain audio

### 3.4 Proposed technology base

**LiveKit** (open source, self-hostable) is selected as the media and agent framework.

| Provides | Consequence |
|---|---|
| WebRTC + SIP transport | The hardest and least differentiated engineering is not rebuilt |
| Barge-in / interruption handling | Known failure mode handled by maintained code |
| Open-source multilingual turn-detector model | Directly addresses the 0.8s end-of-speech wait — the largest latency component |
| Native tool calling | Removes the §3.2 blocker |
| Pluggable STT/LLM/TTS | Enables all of §3.3 |

Alternatives considered:

- **Pipecat** — lighter and more flexible, and almost certainly what Dograh itself uses
  (its TTS errors name `CartesiaTTSService`, a Pipecat class). **Rejected**: SIP
  bridging, call lifecycle and barge-in would be built in-house, and the turn-detector
  model would be lost. This amounts to rebuilding Dograh's foundation in order to escape
  Dograh's graph.
- **Build from first principles** (raw RTP/SIP stack) — **rejected**: 2–3 months of
  undifferentiated work with high defect risk, for no capability gain.

### 3.5 ⚠ BLOCKING UNKNOWN — Vobiz SIP availability

LiveKit SIP bridges PSTN calls into LiveKit rooms **via a SIP trunk**. It does not
remove the telephony-provider dependency; it changes the requirement from *websocket
media streams* (uncommon) to *SIP trunking* (industry standard). This materially lowers
the risk but does not eliminate it.

Dograh exposes only ring and hangup callbacks for Vobiz, which is characteristic of a
click-to-call API rather than a media integration. **If Vobiz does not offer SIP
trunking, no amount of platform engineering grants access to the audio.**

| | |
|---|---|
| **Gate** | Confirm Vobiz SIP trunking availability before any implementation begins |
| **Method** | Direct written enquiry to Vobiz (see §9.1 for the text to send) |
| **Cost** | Nil |
| **Fallback** | Plivo — documented SIP trunking, India DLT support. Cost: new account, new numbers, possible number-porting delay |
| **Design mitigation** | The telephony layer is specified as a provider-agnostic adapter regardless of the answer (see HLD) |

### 3.6 Existing reusable assets

Approximately **30%** of the platform already exists in this repository, concentrated in
the layers greenfield projects usually lack:

| Asset | Location | Reuse |
|---|---|---|
| Next.js + Supabase dashboard | `AI-Voice-Agent-Dashboard/` | Campaign UI, call review |
| Call and transcript analysis | `tools/analyze_runs.py`, `recent_calls.py` | Observability |
| Automated test-call harness | `tools/place_test_call.py` | System testing |
| Agent evaluation harnesses | `tools/invest_train.py`, `loan_train.py`, `probe_chat.py` | Quality gates |
| Model comparison | `tools/compare_models.py` | Vendor benchmarking |
| Tuned Telugu prompt corpus | `workflows/gptoss120b_prompts.md` | Brain module seed |

Equally valuable is the accumulated operational knowledge — echo-as-caller
misdetection, one-word Telugu turn registration, correction-versus-refusal intent,
safe end-of-speech thresholds. This is encoded as requirements in the SRS rather than
rediscovered.

### 3.7 Technical feasibility verdict

**FEASIBLE.** The differentiating work (brain, dialer, STT customization) is within
demonstrated competence. The hardest components are delegated to a maintained
open-source framework. One blocking unknown (§3.5) is cheap to resolve and has a viable
fallback.

---

## 4. Economic Feasibility

### 4.1 Cost structure comparison

| Cost element | Vapi (managed) | Dograh (current) | Proposed platform |
|---|---|---|---|
| Platform / orchestration fee | Per-minute, vendor-set | Nil (self-hosted) | Nil (self-hosted) |
| Telephony | Pass-through + margin | Direct (Vobiz) | Direct |
| STT | Pass-through | Direct (Sarvam) | Direct, **or self-hosted → near-zero marginal** |
| LLM | Pass-through | Direct (Groq) | Direct |
| TTS | Pass-through | Direct (Cartesia) | Direct |
| Compute | Included | VPS (existing) | VPS + optional GPU |
| Engineering | Nil | Nil | **Principal cost — see §4.3** |

### 4.2 The economic argument

The saving is **not** primarily the platform fee. It is that a client-services business
cannot price predictably on a per-minute rate set by a third party it does not control.
Owning the stack converts a variable per-minute cost into a largely fixed
infrastructure cost, which is the correct shape for an agency selling outcomes.

The second economic effect is larger and less obvious: **a self-hosted, fine-tuned
Telugu STT model has near-zero marginal cost per minute**, whereas every managed
platform charges for STT on every minute of every call, forever. At sufficient call
volume this dominates.

### 4.3 Cost of the project

The dominant cost is engineering time, not infrastructure.

| Item | Basis | Notes |
|---|---|---|
| Engineering effort | See PMP-001 WBS | Principal cost |
| VPS / compute | Existing Coolify infrastructure | Marginal increase expected |
| GPU (Phase 4 STT fine-tuning only) | Rented hours, not owned | Deferred; not a v1 cost |
| Telephony account (if Plivo fallback) | Account + numbers | Contingent on §3.5 |
| LiveKit | Open source, self-hostable | Nil licence cost |
| AI4Bharat IndicConformer | MIT licence | Nil licence cost |

### 4.4 Break-even framing

Break-even is a function of monthly call minutes and the delta between managed
per-minute pricing and self-hosted marginal cost, offset against one-time engineering
effort. The model is specified in PMP-001; it **cannot be completed until §4.5
resolves**, and no numeric break-even is asserted here.

### 4.5 ⚠ Verification required before economic sign-off

The following inputs are **not verified** and must be confirmed before this study's
economic section is treated as decision-grade. They are deliberately left unquantified
rather than estimated, because a wrong number here produces a wrong decision:

| # | Input | Source |
|---|---|---|
| E1 | Current actual monthly spend across Vobiz, Sarvam, Groq, Cartesia | Existing invoices |
| E2 | Current and projected monthly call minutes per vertical | Dograh campaign records |
| E3 | Vapi's current published per-minute pricing | Vendor site |
| E4 | Vobiz SIP trunking rates (if offered) | Vendor quote — combine with §3.5 enquiry |
| E5 | Plivo India outbound rates and DLT charges | Vendor site |
| E6 | GPU hourly rate for the Phase 4 fine-tuning workstream | Cloud provider |

### 4.6 Economic feasibility verdict

**FAVOURABLE, pending §4.5.** The cost structure is sound and strategically correct for
an agency model. Precise break-even is not yet computable. Note that the §3.2 and §3.3
capabilities are not obtainable at *any* price from a managed platform, which partly
removes cost from the decision.

---

## 5. Operational Feasibility

### 5.1 Operating model

Confirmed scope: the platform serves **Vishnu's own client work only**. It is not a
product clients log into. This removes multi-tenancy, per-tenant billing, self-serve
onboarding, permission models and support tooling — roughly 60% of what a comparable
SaaS build would require.

### 5.2 Operational burden introduced

Self-hosting transfers responsibilities previously borne by a vendor:

| Responsibility | Current | Proposed |
|---|---|---|
| Media server uptime | Dograh | **Operator** |
| SIP trunk registration and health | Dograh | **Operator** |
| Capacity for concurrent calls | Dograh | **Operator** |
| Framework upgrades | Dograh | **Operator** |
| Incident response during live campaigns | Dograh | **Operator** |

This burden is real and must not be understated. It is addressed in DEP-001
(monitoring, alerting, runbooks, rollback).

### 5.3 ⚠ Key operational risk — single operator

The platform would be built and operated by one person, replacing a system maintained by
a vendor team, in support of **live campaigns calling real customers where failures cost
money and reach real people**.

Mitigations, specified in DEP-001 and PMP-001:

- Dograh remains running and capable throughout; it is not decommissioned until the new
  platform passes UAT (§7.2)
- Cut-over is per-vertical, beginning with the lowest-value vertical, never all at once
- Documented rollback to Dograh at every gate
- Runbooks for the known failure modes, written before cut-over rather than during an
  incident

### 5.4 Operational feasibility verdict

**FEASIBLE WITH CAVEATS.** Manageable given the restricted scope, but contingent on the
staged cut-over and rollback discipline being genuinely followed rather than nominally
documented.

---

## 6. Legal and Regulatory Feasibility

### 6.1 Position

Building the platform **does not change** BS Wealth Finance's regulatory obligations for
outbound commercial calling in India. Those obligations attach to the calling activity,
not to the software. The current operation is already subject to them.

### 6.2 Obligations requiring review

| Area | Consideration |
|---|---|
| TRAI / DLT | Registration for commercial communications; sender/header and consent-template registration; scrubbing against DND registries |
| Consent | Lawful basis for calling each contact; provenance of purchased or client-supplied lists |
| Call recording | Notice and consent for recording; recordings are used for STT fine-tuning (§3.3), which is a **secondary processing purpose** and must be covered by the consent obtained |
| Data protection (DPDP Act) | Personal data in call audio, transcripts and CRM records; retention limits; storage location; breach obligations |
| Disclosure | Whether and how the caller is informed they are speaking to an automated system |
| Opt-out | Reliable honouring of do-not-call requests — note the prior defect where a *correction* was misclassified as a *refusal*; the inverse failure carries regulatory consequence |

### 6.3 Licensing of components

| Component | Licence | Status |
|---|---|---|
| LiveKit | Open source | Permits self-hosting |
| AI4Bharat IndicConformer | MIT | Commercial use permitted |
| Model/API providers | Commercial terms | Review terms on training/retention of submitted audio |

### 6.4 ⚠ Action required

A DLT/TRAI and DPDP compliance review is **out of scope for this engineering study** and
requires competent Indian regulatory advice. Two items specifically:

1. Whether existing consent covers re-use of call recordings as ASR training data
2. Whether automated-caller disclosure is required for the outbound use case

**Neither blocks design or development. Both block production cut-over.**

### 6.5 Legal feasibility verdict

**FEASIBLE — obligations unchanged, but two items must be cleared before go-live.**

---

## 7. Schedule Feasibility

### 7.1 Approach

A hybrid lifecycle is adopted, because the system has two parts of genuinely different
character:

| Subsystem | Character | Model |
|---|---|---|
| SIP, campaigns, dialer, data layer, dashboard | Requirements knowable up front; correctness objective | **V-model** — each specification level paired with a matching test level |
| Conversation quality, Telugu STT, latency tuning | Empirical; cannot be specified in advance | **Agile / iterative** — short loops against real call evidence |

Applying V-model rigour to conversation quality would produce a thoroughly documented
agent that performs badly, because no specification can predict how a Telugu sales call
actually goes. Applying Agile looseness to SIP and dialer correctness would produce
unreliable infrastructure. The split is deliberate.

### 7.2 Phase gates

| Gate | Exit criterion |
|---|---|
| G0 — Feasibility | This document signed off; §3.5 Vobiz answer received |
| G1 — Requirements | SRS signed off |
| G2 — Design | HLD + LLD signed off |
| G3 — First call | One outbound Telugu call completes end-to-end on the new platform |
| G4 — Quality parity | Measured latency and transcript accuracy at or above Dograh baseline (§3.1) |
| G5 — Campaign parity | A full campaign runs with concurrency, retries and reporting |
| G6 — UAT | Vishnu accepts on real calls, by ear, not by metric alone |
| G7 — Cut-over | One vertical migrated; Dograh retained and available for rollback |

### 7.3 Schedule feasibility verdict

**FEASIBLE.** Detailed estimates and the work-breakdown structure are deferred to
PMP-001. No delivery date is asserted in this document, as doing so before requirements
are specified would be unfounded.

---

## 8. Alternatives Considered

| # | Alternative | Assessment |
|---|---|---|
| A1 | **Do nothing** — stay on Dograh | Rejected. §3.2 is structural; sales and booking remain impossible. Note this alternative does fix P1 (latency) as well as any other, since P1 is not orchestrator-bound. |
| A2 | **Adopt Vapi** | Rejected. Resolves §3.2 but not §3.3 — Telugu STT stays uncustomizable, which is the binding quality constraint. Adds per-minute cost outside the operator's control. |
| A3 | **Keep Dograh, replace only the brain** via its custom LLM `base_url` override (workflow 2 previously used `https://aicredits.in/v1`) | Rejected as the destination, **but valuable as a de-risking step.** Delivers §3.2 quickly without touching audio. Does not deliver §3.3. Retained as a contingency if §3.5 fails. |
| A4 | **Build on Pipecat** | Rejected — §3.4. |
| A5 | **Build from first principles** | Rejected — §3.4. |
| A6 | **Build on LiveKit** | **SELECTED.** |

> **Note on A3.** If the Vobiz SIP gate (§3.5) fails *and* migrating telephony proves
> unattractive, A3 becomes the recommended fallback: it recovers the sales and booking
> capability — the larger of the two justifications — without requiring audio access.

---

## 9. Conditions and Immediate Actions

### 9.1 Blocking action — Vobiz enquiry

To be sent before implementation begins. Suggested text:

> We operate AI voice agents for outbound calling and currently use Vobiz for
> telephony. We are evaluating a change of platform and need to confirm the following:
>
> 1. Do you offer **SIP trunking** (registration or IP-authenticated) for outbound
>    calls, that we can connect to our own media server?
> 2. If so, what codecs are supported — specifically, is **G.711 (PCMU/PCMA)**
>    available?
> 3. Do you support outbound calls originated over SIP from a customer-hosted server,
>    and are there concurrent-channel limits?
> 4. Please confirm per-minute rates for SIP outbound to Indian mobile numbers,
>    and any DLT-related charges or requirements.
>
> If SIP trunking is not available, please confirm whether any real-time media
> streaming interface (for example WebSocket audio streaming) is offered.

### 9.2 Non-blocking parallel actions

| # | Action | Purpose |
|---|---|---|
| N1 | Gather E1–E6 (§4.5) | Complete the economic model |
| N2 | Initiate DLT/DPDP review (§6.4) | Clears go-live, not design |
| N3 | Apply the missing `Reasoning: low` fix to Dograh WF6 | Independent ~1.6s latency win on the current system, at nil cost, regardless of this project |
| N4 | Confirm volume and retention of MinIO call recordings | Sizes the Phase 4 STT fine-tuning opportunity |

> N3 is worth emphasising: it is a real improvement to the system in production today
> and should not wait on this programme.

---

## 10. Conclusion

The project is **feasible and recommended**, on revised grounds.

**Revised 2026-08-23.** The latency argument survives measurement after all — but not in
its original form. The orchestrator is not the bottleneck; the *component decisions the
orchestrator owns* are. Measured against the market rather than against the incumbent,
there is ~880 ms of recoverable server-side latency, and a target of **≤800 ms
server-side** would lead every benchmarked commercial platform. See §3.1 and LAT-001.

The justification is therefore threefold, and each part is decisive on its own:

1. **Architectural control** — mid-conversation tool calling and non-graph conversation
   design, without which sales and appointment booking cannot be built at all
2. **Speech-recognition ownership** — the ability to boost, correct, race and ultimately
   fine-tune Telugu ASR on proprietary in-domain audio, which is the single largest
   determinant of perceived quality on these calls and is unobtainable from any managed
   vendor at any price

3. **Latency leadership** — choosing the endpointing model, the reasoning model and the
   serving region, and training a **Telugu turn detector that does not otherwise exist**.
   Together these target ≤800 ms server-side, ahead of every benchmarked platform. None
   of these decisions are available on a managed platform.

Proceed to SRS-001 upon sign-off of this document and receipt of the §3.5 answer.

---

## Appendix A — Traceability

| Study section | Feeds |
|---|---|
| §3.2 | SRS functional requirements — tool calling, conversation control |
| §3.3 | SRS functional requirements — STT abstraction; NFR — transcript accuracy |
| §3.1, §7.1 | SRS non-functional requirements — latency budget |
| §3.5 | HLD — telephony adapter; PMP — Risk R-01 |
| §5.2, §5.3 | DEP-001 — monitoring, runbooks, rollback |
| §6.2 | SRS — compliance requirements; DEP-001 — data retention |
| §7.2 | PMP-001 — gates and milestones |
| §4.5 | PMP-001 — cost model |

## Appendix B — Open Items

| ID | Item | Owner | Blocks |
|---|---|---|---|
| OI-1 | Vobiz SIP trunking availability | Vishnu | **Implementation start** |
| OI-2 | Cost inputs E1–E6 | Vishnu | Economic sign-off |
| OI-3 | DLT / TRAI / DPDP review | External counsel | Production cut-over |
| OI-4 | Consent basis for ASR training on recordings | External counsel | Phase 4 STT workstream |
| OI-5 | MinIO recording volume and retention | Engineering | Phase 4 scoping |
