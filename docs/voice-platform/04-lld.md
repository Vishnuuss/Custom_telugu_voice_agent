# Low-Level Design
## Self-Hosted Voice AI Orchestration Platform ("Project Vaani")

| Field | Value |
|---|---|
| Document ID | LLD-001 |
| Version | 1.0 |
| Date | 2026-08-23 |
| Status | Draft — awaiting sign-off (Gate G2) |
| Preceding documents | SRS-001, HLD-001 |
| V-model pair | Verified by **Integration Testing** (TP-001 §4) |

> **Scope note.** This document specifies interfaces, schemas, state machines and error
> semantics. It does not prescribe implementation line-by-line. Signatures are given in
> Python-style pseudocode for precision, not as a language mandate — though Python is
> assumed for the media plane, since LiveKit Agents and the existing tooling are Python.

---

## 1. Module Interfaces

### 1.1 M1 — Telephony Port

```python
class CallOutcome(Enum):
    ANSWERED        = "answered"
    BUSY            = "busy"
    NO_ANSWER       = "no_answer"
    REJECTED        = "rejected"
    INVALID_NUMBER  = "invalid_number"
    VOICEMAIL       = "voicemail"
    FAILED          = "failed"          # provider-side failure
    # NOTE: platform faults are NOT outcomes. See §5.2.

@dataclass(frozen=True)
class CallHandle:
    provider_call_id: str
    session_ref: str            # links to the media session
    provider: str

class TelephonyPort(Protocol):
    async def originate(
        self,
        to_number: E164,
        from_cli: E164,
        session_ref: str,
        max_duration_s: int,
    ) -> CallHandle: ...

    async def hangup(self, handle: CallHandle) -> None: ...

    def subscribe(self, cb: Callable[[CallProgressEvent], Awaitable[None]]) -> None: ...
```

**Implementations for v1:** `SipTelephonyAdapter` (real), `SimulatorTelephonyAdapter`
(replays recorded audio; places no calls). Satisfies NFR-MAINT-02, NFR-MAINT-03.

**Adapter contract rules.**

| Rule | Reason |
|---|---|
| Provider outcome strings are mapped to `CallOutcome` inside the adapter | FR-TEL-03; no provider vocabulary escapes M1 |
| Unknown provider outcome maps to `FAILED` **and** emits an `UNKNOWN_PROVIDER_OUTCOME` event | Silent mapping loss is how diagnosis breaks |
| `originate` must be idempotent per `session_ref` | Prevents double-dialling on retry |

### 1.2 M2 — STT Port

> The most important interface in the system (HLD ADR-04, FS-001 §3.3).

```python
@dataclass(frozen=True)
class Transcript:
    text: str
    is_final: bool
    confidence: float | None
    language: str
    started_at: float          # monotonic seconds
    ended_at: float
    alternatives: list[tuple[str, float]] = field(default_factory=list)

class SttPort(Protocol):
    async def stream(
        self,
        audio: AsyncIterator[AudioFrame],
        *,
        language: str,
        vocabulary: list[str] | None = None,   # FR-PIPE-04
    ) -> AsyncIterator[Transcript]: ...

    @property
    def capabilities(self) -> SttCapabilities: ...
```

```python
@dataclass(frozen=True)
class SttCapabilities:
    supports_streaming: bool
    supports_vocabulary_boost: bool
    supports_confidence: bool
    supports_alternatives: bool
    languages: frozenset[str]
```

**Why `capabilities` exists.** Providers differ in what they support. Rather than
littering the pipeline with provider checks, each adapter declares its capabilities and
the pipeline degrades explicitly. This is what keeps the port honest when a self-hosted
IndicConformer (which will support confidence and alternatives but perhaps not
vocabulary boost) is introduced.

**Planned implementations:** `SarvamStt` (v1 baseline), `SimulatorStt` (fixture-driven),
`SelfHostedStt` (HTTP/WebSocket to a model server — the Phase 4 target), `RacingStt`
(composite, v2 — FR-PIPE-06).

### 1.3 M2 — TTS Port

```python
class TtsPort(Protocol):
    async def synthesize(
        self,
        text: str,
        *,
        voice: str,
        language: str,
        speed: float = 1.0,
        volume: float = 1.0,
    ) -> AsyncIterator[AudioFrame]: ...      # MUST yield first chunk ASAP

    async def cancel(self) -> None: ...      # required for barge-in
```

`cancel()` is mandatory, not optional: barge-in (FR-PIPE-10, ≤300 ms) is unachievable if
synthesis cannot be aborted mid-stream.

### 1.4 M2 — Endpointer

```python
class EndpointDecision(Enum):
    CONTINUE = "continue"
    TURN_END = "turn_end"

class Endpointer(Protocol):
    def observe(self, t: Transcript, silence_s: float) -> EndpointDecision: ...
```

**v1 strategy — `HybridEndpointer`:** the model-based turn detector decides; the silence
threshold is the fallback and the hard ceiling.

```
  turn_end  ⟸  detector says complete AND silence_s >= min_silence_s
            OR  silence_s >= max_silence_s
```

| Parameter | Default | Constraint |
|---|---|---|
| `min_silence_s` | 0.35 | — |
| `max_silence_s` | 0.80 | **≥ 0.60 for Telugu** — validated at config load (FR-PIPE-08) |
| `min_words` | 1 | **Must be 1**; higher values discard one-word Telugu turns (FR-PIPE-09) |

> `min_words` has a documented history of drifting back to 3 in the incumbent system,
> silently discarding అవును / వద్దు / ఆ. The registry validator rejects any value above 1
> unless an explicit override flag is present.

### 1.5 M2 — Echo Guard

```python
class EchoGuard:
    def __init__(self, window_s: float = 4.0, similarity: float = 0.85): ...
    def note_spoken(self, text: str, at: float) -> None: ...
    def is_echo(self, t: Transcript) -> bool: ...
```

Rejects an incoming transcript whose normalised similarity to any system utterance
within `window_s` exceeds `similarity`. Every rejection emits an `ECHO_SUPPRESSED` event
— suppressions must be visible, because a guard that is too aggressive would silently
discard real caller speech.

### 1.6 M3 — LLM Port and Brain

```python
@dataclass
class BrainResponse:
    speech: str | None
    tool_calls: list[ToolCall]
    state_updates: dict[str, Any]
    extraction: dict[str, Any] | None
    disposition: str | None
    end_call: bool

class LlmPort(Protocol):
    async def complete(
        self,
        messages: list[Message],
        tools: list[ToolSchema],
        *,
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> AsyncIterator[LlmDelta]: ...
```

```python
class BrainService:
    async def on_turn(self, transcript: Transcript, state: CallState) -> BrainResponse:
        ...
```

**Turn algorithm.**

```
1.  append caller utterance to history
2.  intent pre-checks (deterministic, before the model):
       a. opt-out detected?      → suppression + closing + end        (FR-BRAIN-10)
       b. correction vs refusal disambiguation                        (FR-BRAIN-09)
3.  invoke LlmPort with history + state + tool schemas
4.  if tool_calls:
       start tools concurrently
       if expected latency > filler_threshold_s: emit filler speech   (FR-PIPE-17)
       await results, append, re-invoke  (bounded: max 2 rounds)
5.  if no usable response → capped re-prompt, never silence           (FR-BRAIN-12/13)
6.  apply state_updates and extraction
7.  if end_call → closing statement exactly once                      (NFR-QUAL-07)
```

**Step 2 is deliberately deterministic and placed before the model.** Opt-out and
correction handling carry regulatory and reputational consequence; they are not left to
prompt phrasing. A prior production call told a caller who had *corrected their loan
type* that they would never be called again, because a refusal condition matched a bare
negation.

**Re-invocation is capped at 2 tool rounds** to bound worst-case turn latency.

### 1.7 M6 — Dialer gate chain

```python
class GateResult(Enum):
    ALLOW = "allow"
    DEFER = "defer"      # eligible later (hours, backoff, concurrency)
    DENY  = "deny"       # never dial (suppressed, cap exhausted, invalid)

class DialGate(Protocol):
    name: str
    def evaluate(self, c: CampaignContact, now: datetime) -> tuple[GateResult, str]: ...
```

Evaluated in fixed order; first non-`ALLOW` wins and its reason is persisted:

| Order | Gate | Non-allow result |
|---|---|---|
| 1 | `SuppressionGate` | `DENY` |
| 2 | `CallingWindowGate` | `DEFER` |
| 3 | `RetryPolicyGate` | `DEFER` or `DENY` (cap exhausted) |
| 4 | `ConcurrencyGate` | `DEFER` |

**The gate chain is the only path to origination**, including manual test calls
(FR-CMP-01). No module may call `TelephonyPort.originate` directly.

---

## 2. Data Model

PostgreSQL. Migrations are ordered and versioned (FR-DATA-05).

### 2.1 Schema

```sql
-- ============ AGENTS ============
CREATE TABLE agent (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    key             text NOT NULL UNIQUE,            -- e.g. 'bswealth-loan-te'
    name            text NOT NULL,
    vertical        text NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE agent_version (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id        uuid NOT NULL REFERENCES agent(id),
    version         integer NOT NULL,
    config          jsonb NOT NULL,                  -- validated artefact (§3)
    config_sha256   text NOT NULL,
    git_ref         text,                            -- provenance (FR-AGENT-02)
    created_at      timestamptz NOT NULL DEFAULT now(),
    deployed_at     timestamptz,
    UNIQUE (agent_id, version)
);
-- agent_version rows are IMMUTABLE after insert (HLD §4.9).

-- ============ CONTACTS ============
CREATE TABLE contact_list (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name            text NOT NULL,
    source          text NOT NULL,                   -- provenance (FR-CMP-02)
    consent_basis   text NOT NULL,                   -- FR-CMP-02
    uploaded_at     timestamptz NOT NULL DEFAULT now(),
    row_count       integer NOT NULL DEFAULT 0
);

CREATE TABLE contact (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    list_id         uuid NOT NULL REFERENCES contact_list(id) ON DELETE CASCADE,
    phone_e164      text NOT NULL,
    name            text,
    attributes      jsonb NOT NULL DEFAULT '{}',     -- city, budget, vertical, ...
    UNIQUE (list_id, phone_e164)
);
CREATE INDEX ON contact (phone_e164);

CREATE TABLE suppression_list (
    phone_e164      text PRIMARY KEY,
    reason          text NOT NULL,                   -- 'opt_out' | 'manual' | 'dnd'
    source_call_id  uuid,
    created_at      timestamptz NOT NULL DEFAULT now()
);
-- Independent of campaigns; never cascade-deleted (FR-DATA-04).

-- ============ CAMPAIGNS ============
CREATE TABLE campaign (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name                text NOT NULL,
    list_id             uuid NOT NULL REFERENCES contact_list(id),
    agent_version_id    uuid NOT NULL REFERENCES agent_version(id),  -- PINNED
    status              text NOT NULL DEFAULT 'draft',
    max_concurrency     integer NOT NULL DEFAULT 5,
    calling_window      jsonb NOT NULL,              -- days, start, end, tz
    retry_policy        jsonb NOT NULL,              -- cap, backoff, per-outcome
    webhook_url         text,
    webhook_secret      text,
    scheduled_start_at  timestamptz,
    created_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT campaign_status_valid CHECK (status IN
        ('draft','scheduled','running','paused','completed','stopped'))
);
-- agent_version_id is pinned, never 'latest': a deployment mid-campaign
-- must not change behaviour halfway through (HLD §4.5).

CREATE TABLE campaign_contact (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id     uuid NOT NULL REFERENCES campaign(id) ON DELETE CASCADE,
    contact_id      uuid NOT NULL REFERENCES contact(id),
    state           text NOT NULL DEFAULT 'pending',
    attempts        integer NOT NULL DEFAULT 0,
    next_eligible_at timestamptz,
    last_gate_reason text,
    UNIQUE (campaign_id, contact_id),
    CONSTRAINT cc_state_valid CHECK (state IN
        ('pending','eligible','dialing','in_call','done','failed','suppressed','exhausted'))
);
CREATE INDEX ON campaign_contact (campaign_id, state, next_eligible_at);

-- ============ CALLS ============
CREATE TABLE call (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_contact_id uuid REFERENCES campaign_contact(id),
    agent_version_id    uuid NOT NULL REFERENCES agent_version(id),
    phone_e164          text NOT NULL,
    provider            text NOT NULL,
    provider_call_id    text,                        -- billing reconciliation (FR-TEL-09)
    started_at          timestamptz NOT NULL DEFAULT now(),
    answered_at         timestamptz,
    ended_at            timestamptz,
    duration_s          numeric,
    outcome             text,                        -- CallOutcome
    disposition         text,                        -- business result
    end_reason          text,                        -- HLD §5.2
    extraction          jsonb,
    cost                jsonb,                       -- per-component (FR-OBS-03)
    is_test             boolean NOT NULL DEFAULT false
);
CREATE INDEX ON call (started_at DESC);
CREATE INDEX ON call (outcome);

CREATE TABLE turn (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    call_id             uuid NOT NULL REFERENCES call(id) ON DELETE CASCADE,
    turn_index          integer NOT NULL,
    caller_text         text,
    agent_text          text,
    -- latency breakdown (FR-OBS-02) --------------------------------
    speech_end_at       numeric,      -- t0
    stt_final_at        numeric,
    brain_first_token_at numeric,
    brain_complete_at   numeric,      -- t1
    tts_first_audio_at  numeric,      -- t2
    turn_latency_s      numeric GENERATED ALWAYS AS
                            (tts_first_audio_at - speech_end_at) STORED,
    ---------------------------------------------------------------
    tool_calls          jsonb,
    prompt_tokens       integer,
    completion_tokens   integer,
    barge_in            boolean NOT NULL DEFAULT false,
    UNIQUE (call_id, turn_index)
);

CREATE TABLE event (
    id              bigserial PRIMARY KEY,
    call_id         uuid REFERENCES call(id) ON DELETE CASCADE,
    campaign_id     uuid REFERENCES campaign(id) ON DELETE CASCADE,
    at              timestamptz NOT NULL DEFAULT now(),
    severity        text NOT NULL,                   -- debug|info|warn|error|critical
    type            text NOT NULL,                   -- §5.1 taxonomy
    payload         jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX ON event (type, at DESC);
CREATE INDEX ON event (call_id);

CREATE TABLE recording (
    call_id                     uuid PRIMARY KEY REFERENCES call(id) ON DELETE CASCADE,
    object_key                  text NOT NULL,       -- MinIO
    duration_s                  numeric,
    bytes                       bigint,
    training_use_permitted      boolean NOT NULL DEFAULT false,  -- FR-CMP-04
    retention_expires_at        timestamptz          -- FR-DATA-03
);
-- Phase 4 ASR export may select ONLY WHERE training_use_permitted = true.

CREATE TABLE audit_log (
    id          bigserial PRIMARY KEY,
    at          timestamptz NOT NULL DEFAULT now(),
    actor       text NOT NULL,
    action      text NOT NULL,     -- campaign_start|campaign_stop|agent_deploy|...
    target      text NOT NULL,
    detail      jsonb NOT NULL DEFAULT '{}'
);
```

### 2.2 Schema decisions

| Decision | Reason |
|---|---|
| `turn_latency_s` is a generated column | The governing NFR metric cannot drift from its components or be forgotten at write time |
| `campaign.agent_version_id` pins a version | A deployment mid-campaign must not change behaviour halfway |
| `agent_version` immutable | Any call is reproducible from the exact config that ran it |
| `suppression_list` keyed by phone, not contact | Opt-out follows the person, across every list and campaign |
| `recording.training_use_permitted` defaults **false** | Consent is opt-in; the ASR workstream cannot accidentally consume non-consented audio |
| `call.is_test` flag | Test calls must be excluded from client reporting yet still gated (FR-CMP-01) |

---

## 3. Agent Configuration Artefact

Stored in git; validated before deployment (FR-AGENT-01, FR-AGENT-04).

```yaml
key: bswealth-loan-te
version: 12
name: "Shreya — Telugu loan qualification"
language: te-IN

model:
  provider: groq
  name: openai/gpt-oss-120b
  temperature: 0.3
  max_tokens: 400
  base_url: null            # OpenAI-compatible override (EI-03)

stt:
  provider: sarvam
  model: saarika:v2.5
  vocabulary:               # FR-PIPE-04
    - లోన్
    - ఈఎంఐ
    - వడ్డీ

tts:
  provider: cartesia
  model: sonic-3
  voice: <voice-id>
  speed: 1.2
  volume: 1.2

turn_taking:
  min_silence_s: 0.35
  max_silence_s: 0.80       # validator: >= 0.60 for te-IN
  min_words: 1              # validator: must be 1
  barge_in: true
  filler_threshold_s: 1.2

conversation:
  instructions: |
    <single instruction set — no graph>
  closing_statement: |
    <spoken exactly once>
  max_reprompts: 1
  max_duration_s: 300

tools: []                   # v1 ships none; the mechanism exists (FR-BRAIN-05)

extraction:
  schema:
    loan_type:   {type: string, enum: [personal, home, business, vehicle]}
    amount:      {type: number}
    qualified:   {type: boolean}

dispositions:
  - user_qualified
  - not_interested
  - callback_requested
  - opted_out
  - no_answer

compliance:
  disclosure: "<automated-caller statement>"    # FR-CMP-03
  recording_consent_required: true
```

### 3.1 Validation rules

Rejection is at deploy time, before any call (HLD §7.1).

| # | Rule | Traces |
|---|---|---|
| V1 | `max_silence_s >= 0.60` when language is `te-IN` unless `override_endpointing: true` | FR-PIPE-08 |
| V2 | `min_words == 1` unless explicitly overridden | FR-PIPE-09 |
| V3 | `closing_statement` text must not also appear inside `instructions` | NFR-QUAL-07 |
| V4 | `max_reprompts >= 1` | FR-BRAIN-13 |
| V5 | Every `dispositions` entry referenced by `instructions` must exist, and vice versa | FR-BRAIN-08 |
| V6 | `extraction.schema` must be valid JSON Schema | FR-BRAIN-07 |
| V7 | No secret-shaped value anywhere in the artefact | NFR-SEC-01 |
| V8 | `disclosure` non-empty when `compliance.disclosure_required` | FR-CMP-03 |
| V9 | Referenced model/voice identifiers must resolve with the configured provider | FR-AGENT-04 |

> V3 exists because duplicating the closing line inside the instructions caused it to be
> spoken twice in production. V1 and V2 exist because those exact values regressed
> repeatedly on the incumbent and each regression silently degraded live calls.

---

## 4. State Machines

### 4.1 `campaign_contact.state`

```
                    ┌──────────┐
                    │ pending  │
                    └────┬─────┘
             gate chain  │
        ┌────────────────┼────────────────┐
        │ DENY           │ ALLOW          │ DEFER
        ▼                ▼                ▼
 ┌─────────────┐   ┌──────────┐   (stay pending,
 │ suppressed  │   │ eligible │    next_eligible_at set)
 │ / exhausted │   └────┬─────┘
 └─────────────┘        │ dispatched
                        ▼
                   ┌──────────┐   answered   ┌──────────┐
                   │ dialing  │─────────────▶│ in_call  │
                   └────┬─────┘              └────┬─────┘
        not answered /  │                         │ call ends
        provider fault  │                         │
                        ▼                         ▼
                 ┌─────────────┐            ┌──────────┐
                 │  pending    │            │   done   │
                 │ (retry) or  │            └──────────┘
                 │  failed     │
                 └─────────────┘
```

| Transition rule | Reason |
|---|---|
| A **platform fault** returns the contact to `pending` for retry, never `failed` | The contact was never actually reached (HLD §7.1) |
| `exhausted` is terminal and distinct from `failed` | Distinguishes "we stopped trying" from "the call failed" |
| `suppressed` is terminal and irreversible within the campaign | FR-CAMP-08 |
| All transitions are persisted before the next action | NFR-REL-02, FR-CAMP-10 |

### 4.2 `campaign.status`

```
draft → scheduled → running ⇄ paused → completed
                        │                  ▲
                        └──── stopped ─────┘
```

`running → completed` occurs when no contact remains in `pending` or `eligible`.
`paused` halts dispatch but does not terminate calls already in progress.

### 4.3 Call session

```
  INIT → RINGING → CONNECTED → GREETING → TURN_LOOP → CLOSING → ENDED
            │           │                      │
            └───────────┴──────────────────────┴──▶ ERROR → ENDED
```

`CLOSING` is entered exactly once; re-entry is a defect and is asserted against
(NFR-QUAL-07).

---

## 5. Error Handling

### 5.1 Event taxonomy

| Type | Severity | Meaning | Alert |
|---|---|---|---|
| `PROVIDER_RATE_LIMITED` | error | 429 from any provider | above threshold |
| `PROVIDER_CREDIT_EXHAUSTED` | critical | 402 / quota exhausted | **immediate** |
| `PROVIDER_AUTH_FAILED` | critical | 401 / 403 | **immediate** |
| `PROVIDER_TIMEOUT` | warn | Upstream timeout | on rate |
| `UNKNOWN_PROVIDER_OUTCOME` | warn | Unmapped outcome string | on occurrence |
| `ECHO_SUPPRESSED` | info | Echo Guard rejected a transcript | on rate |
| `REPROMPT_ISSUED` | info | Unhandled input handled | on rate |
| `REPROMPT_EXHAUSTED` | warn | Cap reached | on rate |
| `SILENT_CALL` | error | Call ended with no system speech | **immediate** |
| `LATENCY_REGRESSION` | warn | p50 above parity target | on window |
| `CONFIG_REJECTED` | error | Agent artefact failed validation | on occurrence |
| `WEBHOOK_FAILED` | warn | Delivery failed after retries | on rate |
| `SUPPRESSION_HIT` | info | Dial blocked by suppression | never (expected) |
| `SESSION_FATAL` | error | Unrecoverable session error | on rate |

### 5.2 The provider-fault rule

> **A provider fault is never written to `call.outcome`.**
>
> It is written as an `event`, the call is marked `end_reason = 'platform_error'`, and
> the contact returns to `pending` for retry.

This rule exists because two prolonged production outages — a daily LLM token cap and an
exhausted TTS credit balance — presented as ordinary call failures and sent diagnosis to
the prompts for days. Encoding the distinction in the data model is what prevents the
recurrence; a runbook alone would not.

### 5.3 Retry semantics

| Fault | Retry | Backoff |
|---|---|---|
| `PROVIDER_RATE_LIMITED` | yes | exponential, campaign-wide throttle |
| `PROVIDER_CREDIT_EXHAUSTED` | **no — pause campaign** | manual intervention |
| `PROVIDER_AUTH_FAILED` | **no — pause campaign** | manual intervention |
| `PROVIDER_TIMEOUT` | yes | exponential |
| `no_answer` / `busy` | per campaign policy | per campaign policy |
| `invalid_number` | no | terminal (`exhausted`) |

> Rows 2 and 3 pause the campaign rather than retrying. Retrying into an exhausted
> credit balance burns the entire contact list against a wall in minutes — which is
> materially what happened on the incumbent.

---

## 6. Platform API

Authenticated (NFR-SEC-03). JSON over HTTPS.

| Method | Path | Purpose | Requirement |
|---|---|---|---|
| POST | `/api/agents/{key}/versions` | Register a version | FR-AGENT-01 |
| POST | `/api/agents/{key}/deploy` | Deploy (`dry_run` default **true**) | FR-AGENT-03/06 |
| GET | `/api/agents/{key}/diff?from=&to=` | What would change | FR-AGENT-06 |
| POST | `/api/contact-lists` | Upload CSV | FR-CAMP-01 |
| POST | `/api/campaigns` | Create | FR-CAMP-03 |
| POST | `/api/campaigns/{id}/start` | Start (**confirmation required**) | FR-CAMP-04, NFR-USE-02 |
| POST | `/api/campaigns/{id}/pause` | Pause | FR-CAMP-04 |
| GET | `/api/campaigns/{id}/progress` | Live progress | FR-CAMP-09 |
| POST | `/api/calls/test` | Single test call | FR-UI-05 |
| GET | `/api/calls/{id}` | Transcript, turns, events, recording URL | FR-UI-04 |
| GET | `/api/calls/{id}/latency` | Turn breakdown | FR-OBS-02 |
| GET | `/api/reports/campaign/{id}` | Aggregates | FR-OBS-07 |
| POST | `/api/suppression` | Add a number | FR-DATA-04 |
| GET | `/api/health` | Liveness and provider status | DEP-001 |

**Cross-cutting API rules.**

| Rule | Requirement |
|---|---|
| Any endpoint with real-world effect defaults to `dry_run: true` | NFR-USE-03 |
| `POST /campaigns/{id}/start` requires `confirm: true` and returns the count of numbers that will be dialled | NFR-USE-02 |
| `POST /calls/test` passes through the full gate chain | FR-CMP-01 |
| Recording URLs are time-limited presigned links | NFR-SEC-05 |
| Mutating calls are written to `audit_log` | FR-CMP-05 |

### 6.1 Result webhook

```jsonc
POST <campaign.webhook_url>
X-Vaani-Signature: sha256=<hmac of raw body using campaign.webhook_secret>

{
  "call_id": "…", "campaign_id": "…", "phone": "+91…",
  "outcome": "answered", "disposition": "user_qualified",
  "duration_s": 96.4,
  "extraction": { "loan_type": "personal", "amount": 500000, "qualified": true },
  "transcript_url": "https://…",
  "agent": { "key": "bswealth-loan-te", "version": 12 }
}
```

Retries: 3 attempts, exponential backoff; terminal failure raises `WEBHOOK_FAILED`
(FR-CAMP-13).

---

## 7. Concurrency and Resource Model

| Concern | Design |
|---|---|
| One session worker per active call | NFR-REL-03 — isolation |
| Global concurrency cap enforced in `ConcurrencyGate` | Prevents provider rate-limit cascades |
| Dialer dispatch loop is single-writer per campaign | Avoids double-dial races |
| `campaign_contact` claimed by `SELECT … FOR UPDATE SKIP LOCKED` | Safe multi-worker dispatch |
| Audio buffers bounded | Prevents unbounded memory on a stalled provider |

---

## 8. Traceability

| LLD element | Satisfies |
|---|---|
| §1.1 TelephonyPort + adapters | FR-TEL-01…09, NFR-MAINT-02/03 |
| §1.2 SttPort + capabilities | FR-PIPE-02…06, HLD ADR-04 |
| §1.3 TtsPort.cancel | FR-PIPE-10, NFR-PERF-04 |
| §1.4 HybridEndpointer | FR-PIPE-07/08/09, NFR-QUAL-04 |
| §1.5 EchoGuard | FR-PIPE-12, NFR-QUAL-03 |
| §1.6 Brain turn algorithm | FR-BRAIN-01…13, NFR-QUAL-06/07 |
| §1.7 Gate chain | FR-CAMP-05…08, FR-CMP-01 |
| §2.1 `turn` table | FR-OBS-02, NFR-PERF-01…06 |
| §2.1 `recording.training_use_permitted` | FR-CMP-04, FR-DATA-06 |
| §3.1 validation rules | FR-AGENT-04, FR-PIPE-08/09, NFR-QUAL-07 |
| §4.1 state machine | FR-CAMP-07/10, NFR-REL-02 |
| §5.1/§5.2 taxonomy and provider rule | FR-OBS-05/06, NFR-REL-04 |
| §6 API rules | NFR-USE-02/03, NFR-SEC-05, FR-CMP-05 |

---

## Appendix A — Deferred Interfaces (v2)

Declared now so v1 does not foreclose them.

| Interface | Purpose | Requirement |
|---|---|---|
| `RacingStt` composite | Two engines, confidence selection | FR-PIPE-06 |
| `CalendarToolPort` | Appointment booking | FR-BRAIN-14 |
| `TransferPort` | Warm/cold human transfer | FR-TEL-07 |
| Inbound session entry | Inbound calls | FR-TEL-08 |
| ASR training exporter | Corpus export from consented recordings | FR-DATA-06 |
