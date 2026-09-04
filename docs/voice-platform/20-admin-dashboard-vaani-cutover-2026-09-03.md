# Pointing admin.bswealthfinance.com at Vaani

**Date:** 3 September 2026
**Dashboard:** `AI-Voice-Agent-Dashboard`, Coolify app `p13rm5zldwj523sjrobbiff9`
**Backend before:** voice.bswealthfinance.com · **after:** vaani-api.bswealthfinance.com
**Backups:** `backups/vaani_wf6_20260903-*.json` (one per write to workflow 6)

---

## Why this was needed

The dashboard was still dialling the old Dograh. Every one of the twelve most
recent rows in `call_logs` carried a run id in the 2081–2097 range — those are
voice.bswealthfinance.com runs — and every one of them had failed identically:

```
401 Failed to initiate Vobiz call: {"error":{"code":401,"message":"Invalid authentication credentials"}}
```

Meanwhile Vaani was placing calls successfully. Workflow 3 run 384 (06:14 UTC)
was a real 23-second Vobiz call with two measured turns at 0.799 s and 1.001 s.
So the calling capability had already moved; only the dashboard had not.

No Vaani run id has ever appeared in `call_logs`. The webhook path from Vaani to
the dashboard had never once delivered.

## The two halves had to move together

The workflow ids collide across the two backends. Pointing `DOGRAH_API_URL` at
Vaani without remapping the ids would have dialled Vaani workflow 1 — an empty
placeholder agent — for every loan lead, and the Tata Solar agent for every
real-estate lead.

| business line | voice id | vaani id | vaani agent |
|---|---|---|---|
| loan | 1 | 3 | HDFC Bank Loan — qualification |
| solar | 5 | 4 | Tata Solar — qualification |
| investing | 6 | 5 | BS Wealth Finance Investment — qualification |
| real estate | 4 | 6 | BS Wealth Finance Property — qualification |

Vaani workflow 2 (MB Solar Hub, 336 runs) is a different client and is
deliberately not wired to this dashboard.

There is a second reason the base URL and the ids cannot be changed
independently: `app/api/webhook/call-result/route.ts` reads the finished run
*back* through `lib/dograh.ts` to meter the charge. Point that at one backend
while the run was produced by the other and the meter looks up an id that does
not exist.

## What changed

Seven variables, in `.env.local` and on the Coolify app (upsert only — no other
variable was touched):

```
DOGRAH_API_URL=https://vaani-api.bswealthfinance.com
DOGRAH_API_KEY=<the Vaani server key>
DOGRAH_WORKFLOW_ID=3
DOGRAH_WORKFLOW_ID_LOAN=3
DOGRAH_WORKFLOW_ID_SOLAR=4
DOGRAH_WORKFLOW_ID_INVESTING=5
DOGRAH_WORKFLOW_ID_REALESTATE=6
```

`vaani.bswealthfinance.com` serves the same API and would also work;
`vaani-api` was chosen because that is what the app reports as its own
`backend_api_endpoint`.

The webhook secret needed no change: the `X-API-Key` header on the Vaani
workflows' webhook nodes is already byte-identical to `DOGRAH_WEBHOOK_SECRET`.

## Bringing the four agents up to the MB Solar standard

### Layers 1, 2 and 4 were never the gap

`api/services/pipecat/run_pipeline.py:1134` calls `compile_vaani_system_prompt`
unconditionally on every non-realtime run, so persona, psychology and mission
are prepended to every agent automatically. The 9 811-vs-1 374-character spread
between MB Solar's node text and real estate's is Layer 3 alone. Confirmed on
the wire: a wf3 text-chat turn billed 16 646 prompt tokens against a 4 302
character Layer 3.

### Turn-taking was the gap

`workflow_configurations` is stored per workflow and beats every `DEFAULT_*` in
the code. Workflows 3, 4, 5 and 6 carried stale values that had been silently
overriding two tuned constants:

| setting | code default | wf2 | wf3–6 before | after |
|---|---|---|---|---|
| `smart_turn_stop_secs` | 0.2 | 0.2 | 0.8 | 0.2 |
| `turn_start_min_words` | 3 | 3 | 1 | 3 |

0.8 s of silence plus 0.2 s of VAD is a full second before the agent answers,
on every turn of every call those four agents had ever taken. Every write was
read back. Workflow 3's `max_call_duration: 60` is deliberate — the one-minute
handoff design — and was left alone. Workflows 4, 5 and 6 are now byte-identical
to MB Solar's configuration.

### The `ask` field was the other gap

`compiler.spoken_question()` falls back to the extraction hint when a variable
has no `ask`, and the hint is English schema prose. MB Solar carries an `ask` on
all six of its variables. The others did not, and workflow 6 was reading the
hint out loud:

> **AGENT:** True only if the customer said they currently want to buy a property?

Spoken Telugu was added for `property_interest` and `timeline` on workflow 6 and
for `investment_type` and `interested` on workflow 5.

### `deal_type` had to go

Fixing the leak exposed a worse problem. Workflow 6 asked buy-sell-or-rent three
turns running, to a caller who had already said "plot చూస్తున్నాను", named
Gachibowli and given a forty-lakh budget.

Vaani turns *every* extraction variable into a pending field in the live state
block (`build_vaani_brain`). `property_interest` and `deal_type` are the same
question, so answering one left the other pending forever and the agent asked it
again on every turn. Rewriting the extraction hint did not help — three attempts
— because the state block, not the extractor, drives the asking.

`deal_type` was removed from workflow 6's extraction schema and from its webhook
payload. The dashboard treats it as optional: `propertyWantOf()` joins property
type and deal type and tolerates a missing deal, so the lead card reads "Plot"
where it would have read "Plot · Buy".

Workflow 6's Layer 3 also gained a section modelled on the one already drafted
for workflow 3 — ask each thing once, treat a plot or a budget as settled proof
of buying, and never say a field name or an English instruction out loud.

After the fix, a four-turn probe runs clean: buy intent, location, timeline,
then a handoff offering two slots. No English, no repeats, no field names.

## The three bugs found after the cutover

Calls were being placed successfully, but nothing about them reached the
dashboard correctly. Three separate causes.

### 1. The four workflows were never published — now fixed

Editing a workflow updates its **draft**; telephony serves the last
**published** version. The webhook nodes added on 30 August had never been
published for solar or real estate:

| workflow | was | now | webhook in the published version |
|---|---|---|---|
| 3 loan | v4 | v5 | yes (already) |
| 4 solar | v1 | **v2** | **added** |
| 5 investing | v2 | **v3** | yes, plus the spoken-Telugu fixes |
| 6 real estate | v2 | **v4** | **added**, plus the Layer 3 fixes |

All four are published. A per-vertical check now reports zero problems and
zero warnings across the whole chain: active workflow, published version,
enabled webhook to admin, payload keys matching what the dashboard reads,
spoken Telugu on every question, and MB Solar's turn-taking values.

`tools/publish_workflow.py` could not do this — it was hardcoded to
voice.bswealthfinance.com. It now takes `--server vaani`.

### 2. Recordings and transcripts were never stored

Dograh reports a recording twice on the same run: `recording_url` is a storage
key (`recordings/400.wav`) and `recording_public_url` is the only fetchable
link. `usableMediaUrl` rightly rejects the key.

The trap: the campaign-runs **list** endpoint the reconcile sweep reads returns
`recording_public_url`, `transcript_public_url` **and** `public_access_token`
as `null`, while the per-run fetch returns real links for the same call.
Verified on runs 398 and 400. So the sweep only ever saw the unusable value and
stored NULL — on every call it recovered, which is every call on an agent whose
published workflow had no webhook.

The token cannot be rebuilt locally, so `lib/reconcile.ts` now falls back to the
per-run fetch. It runs after the duplicate check, so a steady-state sweep makes
no extra requests. Runs 398 and 400 were backfilled by hand and now show both a
recording and a transcript.

### 3. Run ids had stopped being unique — the dangerous one

`call_logs.dograh_run_id` and `call_usage.dograh_run_id` identify a call by the
backend's own run id, and migration 006 made the first UNIQUE. That was correct
while there was one backend.

voice.bswealthfinance.com reached run 2097. Vaani numbers from 1 and is at about
400, so **1000 of the ids it is about to issue already sit in call_logs** and 183
in call_usage. The next collision is Vaani run 464 — roughly sixty calls away.

At each collision a real call is treated as a redelivery of a call from August:

- the webhook insert fails 23505 and returns `Already processed`, HTTP 200
- the reconcile sweep's existence check returns `duplicate`
- the meter's `ignoreDuplicates` drops the usage row
- the ledger key `call:run:<id>` matches a charge already posted

No call log, no lead update, no score, no bill — and no error anywhere. It is
indistinguishable from the call never happening.

Identity is now `(provider, run id)`. The ledger key **deliberately keeps its
historical shape** for the old backend: re-keying it would make a thousand
already-billed calls look unbilled and the next sweep would charge the client a
second time. Only the new backend gets `call:vaani:run:<id>`.

**Migrations 009 (client database) and 010 (billing database) still have to be
pasted into the Supabase SQL editor.** Until they are, the guard is inert —
every read and write probes for the column once per process and degrades to the
old behaviour if it is absent, because losing the collision guard is bad but
losing the call log itself is worse.

## Tests

The dashboard had no test framework. It now has one with no new dependencies —
`node --test` with a small resolver hook so the app's own `@/` aliases and
extensionless imports work unchanged.

```
npm test     # 36 tests, all passing
```

They cover the provider identity and its degradation path, the ledger key on
both sides of the cutover, the billable/test-call rules, the whole-minute
billing maths, and the exact media-url pair taken from live run 400.

## What is still outstanding

### The two migrations are not applied

009 and 010 above. This is the only thing between the system and the run-id
collision at Vaani run 464.

### The webhook delivery has still never been proven end to end

The payload shape matches the dashboard's `pick()` aliases, and the reconcile
sweep demonstrably lands rows (runs 398 and 400 both arrived that way). But a
delivery from the webhook node itself has not been watched into Supabase,
because the test would write a lead into the client's production database.

### A stray test lead is in the client's database

`ZZ TEST - vaani wiring check`, real estate, score 50, against call_logs run 397.
It is not from a real call and should be deleted.

### The state block still names fields in English

`state.py` renders `STILL_NEED: ['timeline']` — raw field names — as the last
thing in the context, which is the most authoritative position. Usually the
`ASK THIS, IN THESE EXACT WORDS` line beside it wins, but not always: workflow 6
was caught saying "timeline గురించి చెప్పగలరా అండి?".

A generalised rule in Layer 3 (never say a field name, with the Telugu sentence
to use instead) fixed it — 8 consecutive probes clean where it had failed 1 in 2
before. The structural fix is to render the question rather than the field name,
which needs a Vaani deploy.

### Derived fields are still asked

`summary`, `lead_score` and `do_not_call` are extraction variables on all four
agents, so Vaani lists them in "You must find out" with their English hints.
Today this is held back only by Layer 3 prose telling each agent not to ask
anything else. The structural fix is a compiler change to exclude derived
fields, which needs a Vaani deploy and is not a data change.

### Server outage

At roughly 21:05 IST every host on 200.141.7.188 — admin, vaani, vaani-api,
voice and Coolify itself — stopped completing a TLS handshake. Unrelated sites
are reachable and public DNS returns the same address, so this is the server,
not the network. Nothing further was attempted against production after it was
found.
