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
| 9 | [Latency Engineering Plan](09-latency-engineering-plan.md) | *How do we get to sub-800ms?* | L-G1…L-G6 |

Each document also exists as `.docx` alongside its `.md`.
Regenerate with `python tools/md_to_docx.py`.

---

## The short version

**The project is recommended.** Three justifications, each decisive on its own.

> **Revised 2026-08-23.** An earlier version of this set targeted *latency parity* with
> the incumbent. That anchored to the system being replaced instead of to the market and
> was wrong. Latency is now a primary goal — see justification 3 and document 9.

1. **Architectural control.** Dograh's node graph cannot make tool calls
   mid-conversation, silently drops edges when saved, and can't express the nuanced
   conditions sales depends on. Sales and appointment booking are structurally
   impossible on it — not hard, impossible.
2. **Speech-recognition ownership.** Telugu ASR can be boosted, corrected, raced, and
   ultimately **fine-tuned on your own call recordings** using AI4Bharat's MIT-licensed
   IndicConformer. No managed platform offers this at any price, and it is the single
   biggest determinant of perceived quality on these calls.
   → Planned in full in [document 8](08-stt-customization-plan.md).

3. **Latency leadership.** The orchestrator itself is not slow — but owning it is what
   makes three decisions yours: *when to stop listening*, *which model reasons*, and
   *where components run*. Those are worth ~1,290 ms. Target: **≤800 ms server-side**,
   which would lead every benchmarked commercial platform.
   → Planned in full in [document 9](09-latency-engineering-plan.md).

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

## Getting to 800ms — the budget

Measured reality first, because the numbers circulating are misleading. On **real phone
calls**, caller-experienced p50: Telnyx 1,296 ms · ElevenLabs 1,424 ms · Bland 1,520 ms ·
**Vapi 1,558 ms** · Retell 1,740 ms. **Nobody is sub-second.** Vendor figures run ~490 ms
lower because they measure server-side, not what the caller hears.

*"100 ms" is a single-component number* — Cartesia's time-to-first-audio is ~40 ms.
Voice-to-voice 100 ms is below PSTN round-trip. It does not exist.

| Component | Now | Target | Lever |
|---|---|---|---|
| **End-of-speech detection** | **800 ms** | **250 ms** | **Telugu turn detector — the blocker** |
| STT finalisation | 200 ms | 100 ms | Streaming partials |
| **LLM → first spoken token** | **600 ms** | **200 ms** | **Non-reasoning model** |
| TTS first audio | 150 ms | 60 ms | Cartesia Sonic 4 |
| Transport / queuing | 200 ms | 50 ms | Co-location in India |
| **Server-side total** | **1,950 ms** | **660 ms** | |
| Telephony (not controllable) | +490 ms | +490 ms | Carrier physics |
| **Caller experiences** | ~2,440 ms | **~1,150 ms** | Would rank **1st** |

### ⚠ The blocker: LiveKit's turn detector doesn't support Telugu

It covers 14 languages — including **Hindi**, not Telugu. Silence-based endpointing can't
safely go below ~0.6 s (your callers already protested at 0.35 s), and 0.6 s alone eats
75% of an 800 ms budget. **So a Telugu turn-detector model has to be trained.** 19 of the
42 latency days are exactly that. Precedent exists — the same was done for Thai.

### Is 800ms actually feasible? Yes.

**OpenAI's own flagship speech-to-speech model measures 820 ms end-to-end.** So 800 ms
cascaded is at the frontier, not beyond it. Gemini 3.1 Flash Live measures 2.98 s.

We also checked whether a **speech-to-speech model** (one model, audio in → audio out, no
TTS stage) would be easier. It would not:

| | Cascaded (chosen) | Speech-to-speech |
|---|---|---|
| Latency | ~800 ms target | 820 ms (OpenAI) / 2.98 s (Gemini) |
| Telugu | Yours to train | **Essentially none** |
| STT ownership | **Full — the whole ladder above** | **Gone — there is no transcript stage** |
| Cost | $0.0095–$0.17/min | up to **$0.30/min** |
| Vendors | 5+ STT, 7+ TTS, dozens of LLMs | **Two: OpenAI, Google** |

Adopting S2S would mean rebuilding the platform in order to give up the exact capability
it exists to provide — and going back to per-minute pricing from one of two vendors.
Revisit if a self-hostable Telugu full-duplex model appears; **Hindi-Moshi** shows the
path is real.

**Sequencing:** the cheap wins (co-location, non-reasoning model, streaming TTS) reach
~1,200 ms with *no model training at all* — already better than 4 of the 5 platforms
above. The turn detector buys the last 400 ms.

**Every latency target is paired with a false-interruption target.** Faster endpointing
buys interruptions, and a latency win purchased with interruptions is not a win.

---

## Scope

| | |
|---|---|
| **v1 (non-negotiable)** | Outbound calling + campaigns + STT levels 0–2 + ≤800 ms latency + live human transfer |
| **v2** | Appointment booking, agent-builder UI, inbound, **fine-tuned ASR (L3)** |
| **Never** | Multi-tenancy, client logins, billing — you operate it, clients don't log in |

**Stack:** SIP trunk → LiveKit (WebRTC/SIP) → pluggable STT → your Brain → pluggable TTS

**Estimate:** ~188 engineering-days for v1, ~244 with contingency, plus 32 planned for
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
- Never trim *instructions* for latency — worth ~0.1 s, and objection handling is the payload.
  Shortening *spoken output* does pay, because Telugu tokenises expensively.
- Diagnose the running system before redesigning it
