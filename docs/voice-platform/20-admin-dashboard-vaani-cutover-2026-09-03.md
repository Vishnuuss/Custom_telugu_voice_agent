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

### 4. The AI Agent page could not show a script, and its save button destroyed one

Reported as "I am not able to see the agent scripts". Two bugs, same cause.

A Vaani agent keeps two very different pieces of text on **one** node:

| field | loan agent | what it is |
|---|---|---|
| `data.greeting` | 88 chars | the opening line, spoken verbatim |
| `data.prompt` | **4,302 chars** | the script driving the rest of the call |

`app/api/agent/prompts/route.ts` was written for the older four-node graph,
where a start node had one piece of text worth editing. So:

- **The script was never sent to the browser.** `readNodeText` returns the
  greeting and stops. The page showed an 88-character opening line, plus three
  permanently empty boxes for parts these agents do not have — which reads as
  the script having been lost.
- **Saving the opening line would have destroyed the script.** The save path set
  `node.data.prompt = start` as well as the greeting, then published. Pressing
  Save on the opening line would have replaced all 4,302 characters of the loan
  script with one sentence, live on the phone line. Nobody pressed it.
- `MAX_PROMPT_LENGTH` was **4000** — shorter than the loan script — so that
  script could not have been saved even through a correct path.

The two fields are now addressed separately: `start` writes only the greeting on
a `greeting_type: 'text'` node, and a new `script` key writes only the prompt.
`llm`-mode start nodes still write both, because there the greeting genuinely is
generated from the prompt. The cap is 20,000. The page renders only the blocks
the loaded agent actually has, and gives the script a tall monospace box.

Eleven tests pin it, including the exact regression: editing the opening line
must leave the script byte-identical.

## Every dashboard operation, checked against Vaani

All 18 endpoints the dashboard depends on answer correctly — verified read-only,
placing no calls and starting no campaigns:

| Page | Operation | Result |
|---|---|---|
| AI Agent | load each of the 4 scripts | 200, opening line + script both present |
| AI Agent | Save & publish | version API reachable |
| Campaigns | list / read / progress / runs | 200 |
| Campaigns | Start / Pause / Resume | routes exist |
| Campaigns | CSV upload (presigned) | 200, `vaani-storage.bswealthfinance.com` |
| Calls | open a call's detail | 200 |

## Four real calls, placed the way the dashboard places them

Run on 2026-09-04 through the exact sequence of `app/api/calls/single/route.ts`
— same lead lookup, credit pre-flight, `campaign_runs` reservation,
compare-and-set claim, one-row CSV, provider campaign with `max_retries: 0`,
start. Every call to the same test number, one at a time.

| agent | run | result | in the dashboard |
|---|---|---|---|
| loan (wf3) | 571 | answered, 29s | logged, lead scored 100 |
| solar (wf4) | 573 | **no answer** | logged as `no_answer`, lead released |
| investing (wf5) | 578 | answered, 98s | logged, scored 50, **billed 8 credits** |
| real estate (wf6) | 579 | answered, 114s | logged, scored 100, **billed 8 credits** |

Twelve links confirmed on each answered call: run row → Vaani campaign → run →
recording and transcript → `call_logs` row → `provider` stamped → media URLs
stored → outcome and duration → lead updated → metered → provider stamped in
billing → ledger debited.

The no-answer is worth its own line: it correctly produced **no** recording URL.
A call that never connects has no recording file, while `recording_public_url`
is built from the access token regardless and would 404. Storing nothing is the
right answer, and the sweep does.

### The first call exposed a money bug

Run 571 is why placing a real call mattered.

```
12:59:40  the call connects
13:00:09  it ends — 29 seconds of talk time
13:00:10  the ten-minute billing sweep reads it while it is still in flight
          and writes duration_seconds 0, outcome 'unknown'
```

`call_usage` rows are insert-if-absent, so that first write is what the client
is charged on for ever. `postDebit` found zero talk time, stamped `billed_at` to
stop reconsidering it, and a real conversation was settled at **zero**. It
cannot self-correct: every later sweep sees the row and skips it.

`meterSingleRun` already refused exactly this case and its comment spells out
the damage. `meterCampaign` — the cron path that meters everything — never got
the same guard. `isMeterable()` now gates it. `is_completed` is the test rather
than `duration > 0`, because a *finished* call with no talk time is a genuine
no-answer that must be recorded once as unbillable.

The same premature write reached `call_logs` too, via the webhook at hang-up:
that 29-second call was stored as `duration: 0` with no recording, and
`applyRunResult` returned `'duplicate'` without looking. `backfillIncompleteLog`
now repairs a zero duration and missing media from the authoritative run —
facts only. Score, qualification, lead status, retry_count and notes are left
alone, because re-applying those on every tick is the runaway migration 006 had
to clean up after.

Proof it works: run 578, a 98-second call, metered at 98 seconds and billed 8
credits (two minutes, rounded up). Balance 40,000 → 32,000 → 24,000 milli across
the two answered calls.

## Two agent defects found on the real-estate call — NOT fixed

Both are in the agent's behaviour, not the plumbing, and are left alone by
instruction. They are real and reproducible on run 579's transcript.

**It re-asks what it has already been told.** The caller gave the location at
13:37:04 and the timeline at 13:37:19. At 13:37:21 it asked for the location
again, and at 13:37:26 for the property type again. The caller's last words on
the call were:

> ఎన్ని సార్లు చెప్పాలి మీకు ఆన్సర్ లో ఒకసారి గుర్తుపెట్టుకోరా
> *(How many times must I tell you? Can't you remember an answer once?)*

The extraction still came out complete and correct — plot, Andhra Pradesh,
50–60 crore, day after tomorrow, score 100 — so this costs goodwill rather than
data.

**It read its own workflow name aloud.** Asked "who are you?", it answered:

> నేను ప్రియ, **BS Wealth Finance Property — qualification** నుంచి మాట్లాడుతున్నాను

"— qualification" is the internal workflow name, not a company.

## Handover health check, 5 September

### Recordings: fixed a privacy hole and a Safari failure

The player pointed straight at the provider's URL. Those links carry a permanent
access token and need **no login**, so a real customer's phone call was
reachable by anyone who could read the page HTML, copy a link, or export browser
history. Everything else in the dashboard is behind the session; recordings were
not. (Transcripts were already proxied for exactly this reason.)

The provider also serves them as `application/octet-stream`. Verified on runs 578
and 579: genuine WAV files, 1.6 MB and 1.8 MB, `Accept-Ranges: bytes`, `206` on a
range request — but mislabelled. Chrome sniffs the RIFF/WAVE header and plays
them; Safari and iOS are stricter and can fail silently, so the client would have
reported "recordings don't work on my iPhone" and been right.

`/api/calls/[id]/recording` now streams it: SSRF-safe by construction like the
transcript route (the upstream URL comes from the `call_logs` row named by `:id`,
never from the request), Range forwarded and `206` preserved so seeking works,
`Content-Type: audio/wav`, and `private, no-store` because it is somebody's phone
call. Verified: unauthenticated requests now get **401**.

### Foundations checked

| Check | Result |
|---|---|
| Row-level security, client database | anon key reads **0 rows**, writes rejected `42501` |
| Coolify env "duplicates" | **not duplicates** — a production row and an `is_preview` row per key, which is normal |
| Leads stuck in `queued` | 0 |
| Campaign credit pre-flight | refuses below `minimum × concurrency`; warns without blocking when the balance will not cover the run |
| Dashboard operations against Vaani | 18/18 |
| Test suite | 62 passing |

Lead inventory a campaign can dial: solar 7 new + 4 no-answer, loan 23 no-answer
(0 new), investing 1 new, real estate 1 new.

### A regression appeared on the loan agent, not from this work

Workflow 3 was republished to **v7 at 15:35 on 5 September**, and that version
drops the Telugu `ask` on `loan_required`:

| version | `loan_required.ask` |
|---|---|
| v5, v6 | `మీకు ఇప్పుడు loan ఏమైనా కావాలా అండి?` |
| **v7 (live)** | **empty** |

With no `ask`, `compiler.spoken_question()` falls back to the extraction hint, so
the live loan agent — the busiest line, 387 leads — reads out:

> True only if the customer said they currently need a loan

This is the same defect fixed on workflows 5 and 6 on 3 September, reintroduced
on 3 by a later edit. Solar, investing and real estate also carry unpublished
drafts created at 15:24 the same day; their extraction schemas are unchanged, so
only prompt text differs from what is live.

Not corrected here: prompt work was explicitly out of scope for this pass, and
someone was editing these workflows the same afternoon.

## A finished call could land empty and stay empty (06 Sep)

Reported as "call ended 5 minutes ago and the call log still is not updated".
My earlier "the chain works" was based on four calls I placed myself, which was
not proof — this is a race, and it spoils some calls and not others.

**Run 798, solar, 08:49:48 UTC**

| | Vaani | Dashboard, before |
|---|---|---|
| duration | 70s | **0** |
| recording / transcript | present | none |
| house_ownership | `own` | — |
| solar_planning | `true` | — |
| lead score | 100 | **0** |

A qualified customer shown to the client as a dud. Three things had to be true
at once, and all three were:

1. **The webhook wins a race against extraction.** Vaani's webhook node fires at
   hang-up; when `perform_final_variable_extraction` has not finished, every
   `{{gathered_context.X}}` renders empty and the duration renders 0 — and that
   was stored as the record. Of six real calls that day, three arrived complete.
2. **Nothing completed the row.** The 04 Sep backfill repaired only duration and
   media; I had left scoring alone to avoid the 006 re-scoring runaway, so the
   answers never arrived.
3. **The repair could not have run anyway.** The cron's campaign loop only visits
   `queued/running/paused` campaigns — **101 of 113 were `completed`**, and a
   completed campaign is never revisited.

### The fix, at all three points

- The **webhook** now reads the run back from Vaani when the payload carries no
  duration or no qualification, and merges it before the insert. The row is right
  within seconds rather than waiting for a sweep. Best-effort: a failed fetch
  still stores the thin row, because a thin record beats none.
- **`backfillIncompleteLog`** completes the qualification too, but at most once —
  the guard is "stored row has none AND the run has one", so it closes for ever
  after it fires. `attempt_no`, `retry_count` and the notes line are never
  touched; re-counting attempts every tick is what produced 47 rows and
  retry_count 31 for 3 calls in 006.
- **`repairIncompleteCallLogs()`** finds the damage directly — recent rows with
  no talk time or missing media — and repairs each from its run whatever its
  campaign is doing. Bounded to 7 days and 200 rows per tick.

A call where Vaani itself extracted nothing (runs 793, 795 — every variable came
back `""`) is left alone. An invented score is worse than an honest blank.

### The first sweep found a bug in the fix

It reported `repaired 2` **and `errors 6`**, and the six were not noise: they
were the old backend's rows (runs 2091-2097). This pass repairs a row from
whatever run comes back for its id, and a run id is unique only within one
backend. Today they merely 404 because Vaani is at ~800 — but when Vaani reaches
2091 they would start returning a **different customer's call**, merged into an
August row. The same collision `scripts/009` exists for, reintroduced in the new
repair path.

The candidate query is now scoped by `provider`, and a 404 counts as skipped
rather than error (six permanent errors a tick would hide a real one). Next
sweep: `scanned 1, repaired 0, skipped 1, errors 0`.

### Verified

All six of 06 Sep's calls now match Vaani exactly:

| run | Vaani | dashboard | rec | txt |
|---|---|---|---|---|
| 793 | 17s | 17s | Y | Y |
| 794 | 14s | 14s | Y | Y |
| 795 | 14s | 14s | Y | Y |
| 796 | 39s | 39s | Y | Y |
| 797 | 24s | 24s | Y | Y |
| 798 | **70s** | **70s** | Y | Y |

Run 798's lead now reads score 100, qualification `qualified`, `house_ownership`
own, `solar_planning` true. 75 tests passing.

### The account is overdrawn

`balance_milli_credits` is **-24,000** (minus 24 credits), against an auto-pause
floor of 20,000. Auto-pause stops *campaigns*; the per-call pre-flight only
refuses when the balance is below one minimum charge, so a run of single calls
walked it past zero. Needs a top-up before handover, and the per-call floor is
worth revisiting.

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
