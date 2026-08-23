# Project Vaani — Custom Telugu Voice Agent Platform

Engineering documentation for a **self-hosted voice AI orchestration platform** built on
[LiveKit](https://livekit.io) — an alternative to managed platforms such as Vapi, aimed
at outbound Indian-language (primarily Telugu) calling.

> **Status:** design phase. No implementation has begun. The documents here are awaiting
> sign-off at gates G0–G2.

---

## Why build this

The platform is not being built for speed. Measurement on the incumbent system showed
LLM time-to-first-token at **0.09 s** of a **1.95 s** turn — orchestration is under 5% of
turn latency, so rebuilding it recovers almost nothing. That justification was examined
and rejected.

Two justifications do hold:

**1. Architectural control.** A node-graph conversation engine cannot make tool calls at
an arbitrary point in a conversation, silently drops edges when persisted, and evaluates
nuanced conditions unreliably. Sales dialogue and appointment booking are not decision
trees, so they are not merely hard to build on a graph — they are structurally
impossible.

**2. Speech-recognition ownership.** Generic Telugu ASR performs poorly on spontaneous,
narrowband, code-mixed telephone speech, and worst of all on the entities that decide a
call — names, cities, amounts. Owning the pipeline allows vocabulary boosting, transcript
correction, engine racing, and ultimately fine-tuning
[AI4Bharat IndicConformer](https://github.com/AI4Bharat/IndicConformerASR) (MIT licensed)
on in-domain call audio. No managed platform offers this at any price.

---

## Documentation

Read in order. Each document also exists as `.docx` alongside its `.md`.

| # | Document | Answers |
|---|---|---|
| 0 | [Index](docs/voice-platform/00-index.md) | Start here |
| 1 | [Feasibility Study](docs/voice-platform/01-feasibility-study.md) | Should we build it? |
| 2 | [Software Requirements Specification](docs/voice-platform/02-srs.md) | What must it do? |
| 3 | [High-Level Design](docs/voice-platform/03-hld.md) | How is it structured? |
| 4 | [Low-Level Design](docs/voice-platform/04-lld.md) | How is each part built? |
| 5 | [Test Plan](docs/voice-platform/05-test-plan.md) | How do we know it works? |
| 6 | [Deployment & Operations](docs/voice-platform/06-deployment-ops.md) | How do we run it safely? |
| 7 | [Project Management Plan](docs/voice-platform/07-project-management-plan.md) | Who does what, and what could go wrong? |
| 8 | [STT Customization Workstream](docs/voice-platform/08-stt-customization-plan.md) | How do we actually fix Telugu ASR? |

---

## Approach

**Hybrid lifecycle.** V-model rigour for infrastructure (SIP, dialer, campaigns, data,
API) where requirements are knowable and correctness is objective. Agile iteration for
conversation quality, Telugu ASR and latency tuning, where nothing can be specified in
advance and only real calls tell you the truth.

**Target architecture:**

```
SIP trunk ──▶ LiveKit (WebRTC/SIP) ──▶ pluggable STT ──▶ Brain ──▶ pluggable TTS
                                            │
                                    vocabulary boost
                                    transcript correction
                                    self-hosted fine-tuned model
```

**Scope:**

| | |
|---|---|
| v1 | Outbound calling, campaigns, STT levels 0–2 |
| v2 | Appointment booking, agent-builder UI, inbound, fine-tuned ASR |
| Not planned | Multi-tenancy, client logins, billing |

---

## Tooling

`tools/` holds deterministic Python scripts for the existing system — call analysis,
latency measurement, model comparison, agent evaluation and workflow patching. All
credentials are read from environment variables; none are stored in this repository.

Regenerate the DOCX versions of the documentation:

```bash
python tools/md_to_docx.py
```

---

## License

Documentation and tooling © Vishnu. Third-party components referenced retain their own
licences — notably LiveKit and AI4Bharat IndicConformer (MIT).
