# Project Vaani — SDLC Document Set

Self-hosted voice AI orchestration platform (a Vapi alternative) to replace Dograh for
BS Wealth Finance's outbound Indian-language calling.

**Created:** 2026-08-23 · **Status:** Draft, awaiting sign-off at Gate G0/G1/G2

---

## Read in this order

| # | Document | What it answers | Gate |
|---|---|---|---|
| 1 | [Feasibility Study](01-feasibility-study.md) | *Should we build this at all?* | G0 |
| 2 | [Software Requirements Specification](02-srs.md) | *What must it do?* | G1 |
| 3 | [High-Level Design](03-hld.md) | *How is it structured?* | G2 |
| 4 | [Low-Level Design](04-lld.md) | *How is each part built?* | G2 |
| 5 | [Test Plan](05-test-plan.md) | *How do we know it works?* | — |
| 6 | [Deployment & Operations Plan](06-deployment-ops.md) | *How do we run it safely?* | — |
| 7 | [Project Management Plan](07-project-management-plan.md) | *Who does what, when, and what could go wrong?* | — |
| 8 | [STT Customization Workstream](08-stt-customization-plan.md) | *How do we actually fix Telugu speech recognition?* | S-G0…S-G5 |

Each document also exists as `.docx` alongside its `.md`.
Regenerate with `python tools/md_to_docx.py`.

---

## The short version

**The project is recommended — but not for the reason it was originally proposed.**

The latency argument does not survive measurement. Orchestration is under 5% of a
1.95-second turn; rebuilding it would recover less than 0.1 s. Expect **latency parity**
from v1, not improvement.

The two justifications that do hold, each decisive on its own:

1. **Architectural control.** Dograh's node graph cannot make tool calls
   mid-conversation, silently drops edges when saved, and can't express the nuanced
   conditions sales depends on. Sales and appointment booking are structurally
   impossible on it — not hard, impossible.
2. **Speech-recognition ownership.** Telugu ASR can be boosted, corrected, raced, and
   ultimately **fine-tuned on your own call recordings** using AI4Bharat's MIT-licensed
   IndicConformer. No managed platform offers this at any price, and it is the single
   biggest determinant of perceived quality on these calls.
   → Planned in full in [document 8](08-stt-customization-plan.md).

---

## Fixing Telugu STT — the four levels

| Level | What | Release | Effort |
|---|---|---|---|
| **L0** | **Measure** — build the corpus, get a real baseline, define the entity metric | **v1, Phase 1** | 9 d (≈3 net) |
| **L1** | **Tune** — vocabulary boosting, pick the best provider on evidence | **v1** | 5 d |
| **L2** | **Correct** — fast LLM repairs the transcript; engine racing later | **v1** | 5 d |
| **L3** | **Own** — fine-tuned IndicConformer on your own call audio | **v2** | 32 d |

**L3 is deliberately kept out of v1** — gating your first release on a model-training
project risks never shipping, and L1+L2 improve Telugu measurably on their own. What
keeps L3 real rather than hypothetical is that **v1 must ship three small requirements**:
FR-STT-08 (self-hosted adapter), FR-STT-09 (consented corpus export), FR-STT-12 (per-turn
model attribution). If those slip, L3 becomes a retrofit. [§8.2](08-stt-customization-plan.md)
sets out the alternative if you want L3 in v1 instead — your call.

---

## Scope

| | |
|---|---|
| **v1 (non-negotiable)** | Outbound calling + campaigns + STT levels 0–2 |
| **v2** | Appointment booking, agent-builder UI, inbound, **fine-tuned ASR (L3)** |
| **Never** | Multi-tenancy, client logins, billing — you operate it, clients don't log in |

**Stack:** SIP trunk → LiveKit (WebRTC/SIP) → pluggable STT → your Brain → pluggable TTS

**Estimate:** ~146 engineering-days for v1, ~190 with contingency, plus 32 planned for
the v2 STT workstream. No calendar date asserted — that depends on your availability
alongside client work.

---

## ⚠ Blocking item

**Does Vobiz offer SIP trunking?** Without raw audio access, nothing else matters. The
exact enquiry to send is in [Feasibility Study §9.1](01-feasibility-study.md). Costs
nothing; Plivo is the fallback; the telephony layer is designed provider-agnostic either
way.

---

## Do these now

| # | Action | Why |
|---|---|---|
| 1 | Send the Vobiz SIP enquiry | Blocks all telephony work |
| 2 | Review and sign off documents 1–4 | Opens G0–G2 |
| 3 | Gather cost inputs E1–E6 | No break-even is asserted without them |
| 4 | Start the DLT/DPDP review | Blocks go-live only, not design |
| 5 | **Apply the missing `Reasoning: low` fix to Dograh WF6** | ~1.6 s win on the live system today — unrelated to this project, don't let it wait |

---

## Two risks worth knowing about now

| Risk | Score | Note |
|---|---|---|
| Telugu corpus + Dograh baseline never assembled | **20** | Has no dependencies, so it's easy to postpone — and postponing it makes both "quality parity" and every ASR improvement claim unprovable. Schedule it in Phase 1. |
| Vobiz has no SIP | **15** | One email answers it. |
| Consent doesn't cover training on your recordings | **15** | Gates Level 3 only. Start the review now; levels 0–2 are unaffected. |

---

## Working agreement for the conversation-quality track

Recorded because it is how the current system was successfully diagnosed:

- One call at a time; one change between calls
- Analyse the transcript before the next call
- Never trim prompts for latency — worth ~0.1 s, and objection handling is the payload
- Diagnose the running system before redesigning it
