# Deployment and Operations Plan
## Self-Hosted Voice AI Orchestration Platform ("Project Vaani")

| Field | Value |
|---|---|
| Document ID | DEP-001 |
| Version | 1.0 |
| Date | 2026-08-23 |
| Status | Draft |
| Preceding documents | FS-001, SRS-001, HLD-001, LLD-001, TP-001 |

> **Framing.** FS-001 §5.3 identified the principal operational risk: a single operator
> assuming responsibilities previously carried by a vendor, in support of live campaigns
> that call real customers. This document exists to make that risk survivable. Its most
> important sections are §7 (cut-over), §9 (alerting) and §10 (runbooks) — not the
> infrastructure diagram.

---

## 1. Environments

| Env | Purpose | Telephony | Data | Real calls |
|---|---|---|---|---|
| **LOCAL** | Development | Simulator | Ephemeral | Never |
| **CI** | Automated verification | Simulator | Ephemeral | Never |
| **STAGING** | Pre-production; real providers | Real trunk, **allow-list only** | Staging DB | Operator's own numbers |
| **PROD** | Live client campaigns | Real trunk | Production DB | Yes |

**Enforcement, not convention:** the STAGING allow-list is implemented as an additional
dial gate in the gate chain (LLD §1.7). A misconfiguration cannot cause staging to dial
a customer.

---

## 2. Infrastructure

### 2.1 Target topology

```
┌──────────────────── Coolify host (existing) ─────────────────────┐
│                                                                   │
│  ┌────────────────┐  ┌────────────────┐  ┌──────────────────┐    │
│  │ Platform API   │  │ Campaign Engine│  │     Dialer       │    │
│  │  (container)   │  │  (container)   │  │  (container)     │    │
│  └────────────────┘  └────────────────┘  └──────────────────┘    │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │        Session Workers (scaled by concurrency)           │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                   │
│  ┌────────────────┐                                              │
│  │ LiveKit server │  (self-hosted; or LiveKit Cloud early — A-02)│
│  └────────────────┘                                              │
│                                                                   │
│  ┌────────────────┐                                              │
│  │  Dograh        │  ◀── RETAINED AND RUNNING until G7           │
│  └────────────────┘                                              │
└───────────────────────────────────────────────────────────────────┘
        │                    │                       │
        ▼                    ▼                       ▼
  Supabase Postgres     MinIO (audio)          SIP trunk
        │
        ▼
  Dashboard (existing pipeline)
```

### 2.2 Component sizing (initial)

| Component | Instances | Notes |
|---|---|---|
| Platform API | 1 | Stateless |
| Campaign Engine | 1 | Single-writer per campaign (LLD §7) |
| Dialer | 1 | Single dispatch loop |
| Session Workers | Scaled to concurrency | Target ≥10 concurrent (NFR-SCAL-01) |
| LiveKit | 1 | Or Cloud in early phases |

> **Deliberate simplicity.** Single instances of control-plane services are correct at
> this scale and for one operator (Objective 6). Horizontal scaling is a design property
> (NFR-SCAL-02), not a v1 deployment.

### 2.3 Coexistence with Dograh

Dograh **remains running and fully capable throughout** (constraint C-04). It is not
modified, not degraded, and not decommissioned until after Gate G7. It is the rollback
target.

---

## 3. Configuration and Secrets

| Class | Storage | Rule |
|---|---|---|
| Secrets (provider keys, DB credentials, webhook secrets) | Environment variables via Coolify | **Never** in git, never in agent artefacts (NFR-SEC-01) |
| Agent configurations | Git | Source of truth (FR-AGENT-02) |
| Platform defaults | Git | Versioned |
| Campaign overrides | Database | Operator-set |

Resolution order, most specific winning: platform default → agent version → campaign
override.

**Secret rotation** is a documented procedure (§10.7) rather than an ad-hoc action,
because provider auth failure is one of the two historical outage causes.

---

## 4. CI/CD

### 4.1 Pipeline

```
  commit
    │
    ├─▶ lint + type check
    ├─▶ unit tests            (TP-001 §3)          ─┐
    ├─▶ integration tests     (TP-001 §4)           ├─ all on simulators, no calls
    ├─▶ config validation     (LLD §3.1 V1–V9)     ─┘
    │
    ├─▶ build container images
    │
    ├─▶ deploy to STAGING     (automatic)
    │
    └─▶ deploy to PROD        (MANUAL APPROVAL REQUIRED)
```

### 4.2 Rules

| Rule | Reason |
|---|---|
| No CI stage may place a real call | TP-001 §1.3 |
| Production deployment is manual and explicit | C-05 — live campaigns, real customers |
| Agent config validation runs in CI, before deployment | Catches V1–V9 violations before they can reach a call |
| Database migrations run as an explicit, ordered step | FR-DATA-05 |
| A production deploy while a campaign is running requires acknowledgement | Campaigns pin agent versions, but infrastructure changes still affect in-flight calls |

---

## 5. Release Procedure

### 5.1 Platform release

1. Confirm no campaign is running, or acknowledge the running campaign explicitly
2. Verify CI green
3. Apply database migrations
4. Deploy control plane
5. Deploy session workers
6. Verify `/api/health` including provider status
7. Place one simulated call
8. Place one real test call to an operator number
9. Monitor for one campaign cycle

### 5.2 Agent release

1. Edit the agent artefact in git; commit
2. **Dry run** the deployment; read the diff (default behaviour — NFR-USE-03)
3. Confirm the diff is only what was intended
4. Apply, pinning the version
5. Text-based evaluation (TP-001 §7.3)
6. One real test call
7. Analyse transcript and latency before any further change

> Steps 2–3 are non-negotiable. A stale local file silently reverting live tuning is a
> documented historical failure (REG-10).

---

## 6. Rollback

| Scenario | Procedure | Target |
|---|---|---|
| Bad agent version | Redeploy previous version | ≤ 5 min (NFR-REL-05) |
| Bad platform release | Redeploy previous images; reverse migration if required | ≤ 15 min |
| **Platform unfit for a vertical** | **Repoint the vertical to Dograh** | ≤ 30 min (NFR-REL-06) |

**The Dograh rollback must be rehearsed before G7, not first attempted during an
incident.** Rehearsal is an explicit exit criterion of that gate.

---

## 7. Cut-Over Strategy

### 7.1 Principle

**Per-vertical, lowest-value first, never all at once.** Dograh continues to serve every
vertical not yet migrated.

### 7.2 Sequence

| Step | Vertical | Rationale |
|---|---|---|
| 1 | Lowest-value / lowest-volume | A defect here costs least |
| 2 | Next vertical | Only after step 1 runs a full campaign cycle cleanly |
| 3 | … | … |
| Last | **Loan (workflow 1)** | Highest value, most tuned, most exposed — migrated last |

### 7.3 Per-vertical criteria

Before migrating a vertical:

- [ ] Its agent passes text evaluation (TP-001 §7.3)
- [ ] Real test calls pass (RT-02…05)
- [ ] Latency and ASR at or above the Dograh baseline for that vertical
- [ ] A small live campaign (RT-06) completes correctly
- [ ] Rollback to Dograh rehearsed for this vertical
- [ ] Operator accepts by ear (UAT-10)

After migrating:

- [ ] Dograh workflow left intact, unpublished changes only
- [ ] One full campaign cycle monitored closely
- [ ] Outcomes compared against the vertical's historical rates

### 7.4 Rollback trigger

Any of: platform-fault call rate above 1%; latency regression beyond parity; a
compliance defect; or operator judgement. **Rollback is not a failure of the programme;
refusing to roll back is.**

---

## 8. Monitoring

### 8.1 Health

`GET /api/health` reports: database, object storage, LiveKit, SIP registration, and each
AI provider (reachability and credential validity).

### 8.2 Metrics

| Metric | Source |
|---|---|
| Calls attempted / connected / failed | `call` |
| Platform-fault rate | `call.end_reason` + `event` |
| Turn latency p50 / p95, with component breakdown | `turn` |
| ASR confidence distribution | `turn` |
| Disposition distribution | `call` |
| Provider error rate by type | `event` |
| Concurrent calls | runtime |
| Cost per call by component | `call.cost` |

### 8.3 Retention

| Data | Retention |
|---|---|
| Call and turn records | Per policy (FR-DATA-03) |
| Recordings | Per policy; `training_use_permitted` governs reuse |
| Events | Shorter than call records |
| Audit log | Longest — compliance evidence |

---

## 9. Alerting

Few alerts, so that they are read. Each maps to an action in §10.

| Alert | Condition | Severity | Runbook |
|---|---|---|---|
| Provider credit exhausted | `PROVIDER_CREDIT_EXHAUSTED` | **Critical** | §10.1 |
| Provider auth failed | `PROVIDER_AUTH_FAILED` | **Critical** | §10.2 |
| Rate limiting | `PROVIDER_RATE_LIMITED` above threshold | High | §10.3 |
| Silent call | Any `SILENT_CALL` | High | §10.4 |
| Platform-fault rate | > 1% of attempts | High | §10.5 |
| Latency regression | p50 above parity | Medium | §10.6 |
| Campaign stalled | Running, no completion in interval | Medium | §10.8 |
| SIP registration lost | Trunk unregistered | **Critical** | §10.9 |
| Webhook failures | Sustained `WEBHOOK_FAILED` | Medium | §10.10 |

> The first two are Critical because both have already caused multi-day production
> outages, and in both cases the alert that would have resolved them in minutes did not
> exist.

---

## 10. Runbooks

Each runbook exists because the failure has occurred, or because its absence would be
costly. Written before cut-over, not during an incident.

### 10.1 Provider credit exhausted

**Symptom.** Every call fails immediately, often at 0 s. `PROVIDER_CREDIT_EXHAUSTED`.

**This is a billing problem, never a prompt or configuration problem.**

1. Confirm the provider from the event payload
2. Confirm the campaign auto-paused (LLD §5.3) — if not, pause manually
3. Top up the provider account
4. Verify with `/api/health`
5. Place one test call
6. Resume the campaign

*History: exhausted TTS credit killed every call across three workflows; a call seven
minutes earlier had completed normally. Nothing about the agent had changed.*

### 10.2 Provider auth failed

**Symptom.** All calls fail; `PROVIDER_AUTH_FAILED`.

1. Confirm which provider
2. Check whether the key was rotated or revoked
3. Re-issue and update the environment variable; **never** commit it
4. Restart affected services; verify health
5. Test call, then resume

### 10.3 Rate limiting

**Symptom.** Intermittent failures, retries, elevated latency.

1. Identify the provider and the limit hit (per-minute vs per-day)
2. Reduce campaign concurrency
3. If a daily cap: **stop the campaign** — continuing burns the contact list against a
   wall. Resume next cycle or raise the tier
4. Consider a provider tier upgrade if recurrent

*History: a daily LLM token cap presented as ordinary call failures and cost days of
misdirected prompt debugging. Approximately 4–7 calls per day were possible before every
call began failing at two seconds.*

### 10.4 Silent call

**Symptom.** A call completes with no system speech.

1. Open the call; check for `SESSION_FATAL` or provider events
2. Check whether TTS produced audio
3. Check whether the Brain returned text
4. If the Brain returned nothing: an unhandled input reached no re-prompt — a defect
   against FR-BRAIN-12; raise S1
5. Add a regression test before closing

### 10.5 Elevated platform-fault rate

1. Group recent `event` rows by type — one cause usually dominates
2. If provider-related, follow §10.1–10.3
3. If session-related, check worker resources
4. If unclear, pause the campaign. **Pausing is cheap; calling customers with a broken
   agent is not.**

### 10.6 Latency regression

1. Pull the component breakdown (TP-001 §7.1) — do not guess
2. Attribute to STT, Brain or TTS by comparing against baseline
3. **Do not trim prompts as a first response.** Measurement has repeatedly shown prompt
   size is worth ~0.1 s while turn-taking configuration is worth over a second
4. Check whether endpointing configuration drifted (REG-12)
5. If a provider is slow, consider failover

> Shortening *spoken* Telugu lines is the one prompt-side lever that pays, because Telugu
> tokenizes expensively and TTS time scales with output length. Shortening instructions
> does not.

### 10.7 Secret rotation

1. Issue the new credential at the provider
2. Update the environment variable in Coolify
3. Restart affected services
4. Verify `/api/health`
5. Revoke the old credential **only after** verification
6. Record in the audit log

### 10.8 Campaign stalled

1. Check status — paused automatically?
2. Check gate reasons on pending contacts (`last_gate_reason`)
3. Common benign cause: outside the calling window
4. Common real cause: concurrency gate blocked by sessions that never terminated —
   check for orphaned workers
5. Check `next_eligible_at` clustering from retry backoff

### 10.9 SIP registration lost

1. Confirm trunk status with the provider
2. Check credentials and network egress
3. Re-register; verify with a test call
4. If provider-side, pause campaigns until restored — failed originations otherwise
   consume retry budget for no reason

### 10.10 Webhook failures

1. Confirm the client endpoint is reachable
2. Verify the signing secret matches
3. Replay failed deliveries once resolved
4. Client-side outages must not block calling — delivery is retried independently

### 10.11 Suspected echo (agent answering itself)

**Symptom.** Transcripts show the agent's previous sentence attributed to the caller;
the agent answers itself and never advances.

1. Compare `turn.caller_text` against the preceding `turn.agent_text`
2. Check for `ECHO_SUPPRESSED` events — if absent, Echo Guard did not fire
3. Usual real-world cause: the caller is on speakerphone
4. Tune Echo Guard window/similarity; add the case to the regression corpus

**Do not modify prompts for this symptom.** It is acoustic, and looks exactly like a
prompt defect.

---

## 11. Backup and Disaster Recovery

| Asset | Backup | RPO | RTO |
|---|---|---|---|
| Database | Managed Supabase backups | ≤ 24 h | ≤ 4 h |
| Recordings | MinIO; verify durability config | ≤ 24 h | ≤ 24 h |
| Agent configs | Git | 0 | Minutes |
| Platform config | Git | 0 | Minutes |
| Secrets | Operator's password manager | Manual | Minutes |

**Restore must be tested**, not assumed. An untested backup is a hypothesis.

**Whole-platform DR:** repoint verticals to Dograh (§6) while rebuilding. This is the
practical benefit of not decommissioning Dograh early.

---

## 12. Capacity

| Dimension | Initial | Trigger to revisit |
|---|---|---|
| Concurrent calls | 10 | Sustained gate-4 deferrals |
| Contacts per campaign | 50,000 | Ingestion slowdown |
| Storage | Existing MinIO | 70% utilisation |
| Provider limits | Current tiers | Any `PROVIDER_RATE_LIMITED` |

> Provider quotas are a capacity dimension, not merely an error condition. They should be
> reviewed before each volume increase — the historical incident was fundamentally a
> capacity planning failure that presented as a software defect.

---

## 13. Routine Operations

| Cadence | Task |
|---|---|
| Per campaign | Pre-flight: health, provider credit, calling window, suppression freshness |
| Daily (while migrating) | Review failed calls; check platform-fault rate |
| Weekly | Latency and ASR trend; provider spend vs forecast |
| Monthly | Retention job verification; backup restore test; secret age review |
| Per release | §5 procedure |
| Quarterly | Config drift audit (REG-12); runbook review |

---

## 14. Decommissioning Dograh

Only after **all** of:

- [ ] Every vertical migrated and stable for a full campaign cycle
- [ ] Rollback rehearsed and no longer exercised in anger
- [ ] Historical call data exported and retained
- [ ] Recordings needed for the ASR workstream secured in MinIO
- [ ] Operator confirms no vertical remains dependent

Even then, **archive rather than delete**: retain the workflow definitions and
configuration as documentation of the tuned behaviour, which took months of production
diagnosis to arrive at.

---

## Appendix A — Operational Risks

| ID | Risk | Mitigation |
|---|---|---|
| OR-1 | Single operator unavailable during a live campaign | Campaigns pause safely; no unattended auto-resume after a critical alert |
| OR-2 | Provider quota exhausted mid-campaign | §10.1/§10.3; pre-flight credit check; capacity review (§12) |
| OR-3 | Self-hosted LiveKit exceeds operational capacity | A-02: LiveKit Cloud for v1 |
| OR-4 | Cut-over regression noticed only by the client | Per-vertical migration; outcome-rate comparison (§7.3) |
| OR-5 | Config drift between artefact and running system | Post-deploy verification; quarterly audit (REG-12) |
| OR-6 | Backup never restored until needed | Monthly restore test (§11) |
| OR-7 | Runbooks written but never rehearsed | Rollback rehearsal is a G7 exit criterion (§6) |
