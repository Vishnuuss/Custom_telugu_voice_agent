# HDFC loan agent — cut to a one-minute handoff call

**Date:** 3 September 2026
**Workflow:** vaani id 3, *HDFC Bank Loan — qualification (BS Wealth Finance)*
**Backup of the previous definition:** `backups/vaani_wf3_20260903_pre_simplify.json`

---

## What changed and why

The agent was a full qualifier: loan type, amount, occupation, monthly income,
existing EMI. The client's instruction was that none of that belongs on this
call. The loan team qualifies; the agent's only job is to find out *whether*
there is a demand and *which of three products* it is, then hand off and hang
up inside a minute.

Everything below is a change to **Layer 3 only** — the per-client business
prompt stored on the node. The shared trained layers (1 persona, 2 psychology,
4 mission) were not touched, by instruction: they are general and stay
identical across every agent.

### 1. The flow is three turns

| Turn | Agent |
|---|---|
| Greeting | "నమస్కారం అండి. నేను శ్రేయ, HDFC BANK నుంచి మాట్లాడుతున్నాను. మీకు ఏదైనా లోన్ అవసరం ఉందా?" |
| They need one | "ఏ loan అండి? Personal, business, education — ఏది కావాలి?" → "సరే అండి, మా team మీకు call చేసి పూర్తి details చెప్తారు." → End Call |
| They don't | "సరే అండి, ఇబ్బంది పెట్టినందుకు sorry. Thank you, మంచి రోజు అండి." → End Call |

### 2. Three loan types, not six

Personal, business, education. Home, vehicle and gold loan were removed from
the prompt entirely — the agent must not offer what this campaign does not
sell.

### 3. Every product word stays in Latin script

The first live test came back with "కార్, గోల్డ్, ఎడ్యుకేషన్". Cartesia's
Telugu voice reads `education loan` cleanly and the transliteration badly, so
the prompt now forbids the Telugu spelling of any English product word or
number.

### 4. "What loans do you have?" is answered like a person

Three worked example lines, deliberately different from each other, each
ending by handing the turn straight back. A flat recitation of the product list
is the most robotic thing available on this call, and it is named as such in
the prompt.

### 5. It cannot ask whether they need a loan twice

Found in testing: "తెలియట్లేదు అండి, ఏం తీసుకోవాలో" (*I don't know which to
take*) got back the greeting's own question. "Don't know" is a **yes**, not a
no — it now gets one warm nudge and a handoff, never a loop.

### 6. Nothing else is ever asked

Amount, salary, occupation, EMI, CIBIL, age, city, documents, timing — all
removed from the prompt *and* from the extraction schema, so there is no
spoken question left to leak. Rate/EMI/eligibility questions get one line:
"అది మా team చూసుకుంటారు అండి, వాళ్ళు call చేసి పూర్తిగా చెప్తారు."

---

## Configuration changes

| Setting | Was | Now |
|---|---|---|
| `max_call_duration` | 200 s | **60 s** |
| extraction variables | 8 | **4** — `loan_required`, `loan_type`, `do_not_call`, `summary` |
| webhook payload keys | 21 | 16 — dropped `budget`, `loan_amount`, `occupation`, `monthly_income`, `existing_emi` |

The dashboard still receives a qualification signal: `hasQualificationSignal()`
fires on `interested` (← `loan_required`) or `loan_type`, both of which are
kept. Call *scoring* will be coarser than before, because the inputs it scored
on are no longer collected — that is the intended trade, not a regression.

---

## Test evidence

Six text-chat sessions against live workflow 3 (runs 349–354). Every branch,
verbatim:

```
[user]  ఏఏ loans ఉన్నాయి అండి?
[agent] Personal loan, business loan, education loan అండి — ఈ మూడు. మీకు ఏది కావాలి?   (1.1 s)
[user]  తెలియట్లేదు అండి
[agent] పర్లేదు అండి. మీ అవసరం ఏంటో మా team అడిగి, ఏది సరిపోతుందో చెప్తారు.
        వాళ్ళు call చేస్తారు, thank you అండి.                                            (1.6 s)

[user]  business loan అండి
[agent] సరే అండి, మా team మీకు call చేసి పూర్తి details చెప్తారు. Thank you అండి.        (0.9 s)
[user]  interest ఎంత?
[agent] అది మా team చూసుకుంటారు అండి, వాళ్ళు call చేసి పూర్తిగా చెప్తారు.               (1.3 s)

[user]  వద్దు అండి, నాకు లోన్ అవసరం లేదు
[agent] సరే అండి, ఇబ్బంది పెట్టినందుకు sorry. Thank you, మంచి రోజు అండి.                (1.0 s)
```

No question outside the three-turn flow was asked in any session.

---

## Recordings and transcripts: fixed

They downloaded as 0 bytes for every run. The chain:

```
GET /api/v1/public/download/workflow/<token>/recording
  -> 302 https://vaani-api.bswealthfinance.com/voice-audio/recordings/347.wav
  -> 404 {"detail":"Not Found"}     <- served by the API itself, nothing behind it
```

`MINIO_PUBLIC_ENDPOINT` pointed at the API host, and `/voice-audio` is the
bucket name, not a route the API serves. The vaani stack published only two
Coolify domains, `ui` and `api`; the older dograh stack publishes a third for
MinIO. Vaani's object storage had no public address at all.

Fix, applied 3 Sep:

1. Attached `vaani-storage.bswealthfinance.com:9000` to the `minio` service in
   the vaani Coolify app (the DNS record already existed).
2. Set `MINIO_PUBLIC_ENDPOINT=https://vaani-storage.bswealthfinance.com`.
3. Redeployed.

Verified: run 347's recording downloads at 696,364 bytes and its transcript
returns the full turn-by-turn text. Runs recorded *before* the fix are also
readable now -- the redirect is built at request time, so nothing was lost.

`tools/coolify.py` needed two fixes to do this work: it crashed with
`UnicodeEncodeError` printing Coolify's emoji on a cp1252 console, and its
6000-character output cap hid `docker_compose_domains` in the truncated tail of
every `raw GET /applications/<uuid>`. Both fixed; `raw` now takes `--limit`.

---

## Root cause of the silence: a stale Groq API key on the server

Recordings made the diagnosis possible. Every failing call had one fingerprint:

| leg | per-second RMS |
|---|---|
| bot | `3524 4174 4354 4223 6008 3589` then `0 0 0 0 0 0 0 ...` |
| user | `43 12 14 11 13 11 504 12 11 704 821 55 48 11 ...` |

The bot spoke its greeting and then emitted digital silence. The caller's
speech **was** present and recorded, so audio reached the server -- but the
transcript held only the greeting and `usage_info.llm` was empty. The LLM was
never invoked, not once.

Ruled out by measurement first: not the prompt (run 344 failed identically on
the *old* prompt), not Sarvam (61 partials / 6 finals on the server's own key),
not Cartesia (the greeting is synthesised and billed every time), not the media
path (the caller's voice is in the recording).

It was the **LLM credential**. The organization's model configuration held a
Groq key ending `M3M2`; `.env` held a different one ending `B15Y`. Tested
directly against `api.groq.com`, the `.env` key returned HTTP 200. The server's
key was never valid from this side and the pipeline could not complete a single
completion -- which is exactly a call that greets you and then says nothing,
because the greeting is the one line that needs no LLM.

Pointing the server at the working key fixed it on the next call.

> A caveat worth keeping: Groq keys are all 56 characters, so the tool's
> length-based write check cannot prove this particular write landed. The
> masked read-back changing from `...M3M2` to `...B15Y` is what proves it.

`tools/set_stt_config.py` only ever handled STT, so there was no way to see or
set the LLM and TTS credentials. It now takes `--section stt|llm|tts` -- all
three live in the same `byok.pipeline` object and need the same masked-secret
merge.

### The second defect this exposed

The first repaired call, run 377, said this out loud:

> "True only if the customer said they currently need a loan?"

That is `loan_required`'s **extraction hint**, read to the caller in English.
The failure mode is already documented in `tools/set_spoken_questions.py`: a
field with no `ask` gets its `prompt` spoken. It had never leaked before because
the greeting always filled `loan_required` on turn one -- and the simplified
prompt now forbids re-asking that question, leaving the agent no sentence of its
own.

Giving `loan_required` its own `ask` stopped the leak and immediately caused the
thing the client had explicitly rejected: "సరే, మీకు లోన్ అవసరం ఉందా అండి?" --
the greeting's question, asked twice. **The spoken-question mechanism overrides
the prompt; the prompt cannot talk it out of asking.**

The fix is to point `loan_required` and `loan_type` at the *same* sentence:

    ఏ loan అండి? Personal, business, education -- ఏది కావాలి?

Whenever the pipeline decides it still needs either field, it asks the one
question this call is allowed to ask, and the answer fills both. `do_not_call`
and `summary` keep no `ask` at all, which is how they shipped and how they have
never leaked.

---

## Verified on a real call

Run **384**, 3 Sep 06:14 UTC, 23 s, disposition `end_call` (the agent hung up
itself):

```
agent: నమస్కారం అండి. నేను శ్రేయ, HDFC BANK నుంచి మాట్లాడుతున్నాను. మీకు ఏదైనా లోన్ అవసరం ఉందా?
user:  హా అండి అండి.
agent: సరే. ఏ loan అండి?
user:  ఏమేమి ఉన్నాయండి మీ దగ్గర?
agent: Personal loan, business loan, education loan అండి -- ఈ మూడు. మీకు ఏది అండి?
user:  ఎజ్యూకేషనల్ లోన్
agent: సరే, మా team మీకు call చేసి పూర్తి details చెప్తారు. Thank you అండి.
```

Extracted: `loan_required: true`, `loan_type: education`, `do_not_call: false`,
`summary: "The customer requested an educational loan."`

Three turns, one question, natural Telugu, product names in English, ended by
the agent inside 23 seconds of a 60-second cap.

### Left in a non-default state

STT is currently on `saarika:v2.5`, switched while testing whether
`saaras:v3-realtime` was the fault. It was not -- the Groq key was. v3-realtime
is the faster model (0.167 s speech-end-to-final vs 0.373 s) and should be
switched back and re-tested on a live call:

    python tools/set_stt_config.py --model saaras:v3-realtime --apply
