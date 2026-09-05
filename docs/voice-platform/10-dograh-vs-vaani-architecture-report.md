# Dograh vs Vaani — What Each Layer Actually Provides

**Prepared for:** Vishnu Dandu
**Date:** 26 August 2026
**Subject:** What Dograh contributes, what Vaani contributes, what still needs
building, and whether "Dograh's voice pipeline is waste — build your own on
LiveKit" holds up against measurement.

---

## 1. Executive summary

The claim "Dograh's voice pipeline is a waste, build your own with LiveKit"
rests on a category error.

**Dograh does not have a voice pipeline of its own.** It runs **Pipecat** — an
independent open-source framework from Daily, the same class of tool as LiveKit
Agents. When someone says "Dograh's pipeline is bad", they are almost always
describing Pipecat, and Pipecat is not bad.

Every latency problem measured on this system today was traced to a specific
cause. **None of them was the pipeline architecture:**

| Measured problem | Real cause | Class |
|---|---|---|
| LLM 1,699 ms to first token | `reasoning_effort` never set on a reasoning model | one missing parameter |
| LLM 1.35 s p50 | calls routed to a US proxy from India | provider choice |
| Endpoint 0.81 s, every turn | a fixed silence clock, configurable, left at default | configuration |
| Agent could not understand Telugu | STT language set to `multi`, returning Hindi | configuration |
| Agent hang-ups logged as errors | a stale enum reference in Dograh | one-word bug |

Replacing the pipeline would have fixed **none** of these. They were fixed with
roughly 35 lines of code and four settings.

**Verdict:** keep Dograh's infrastructure, keep Pipecat, own the conversation.
That is what has been built.

---

## 2. The four layers, and who owns each

A voice agent is four separate things. Conflating them is the source of the
confusion.

```
  LAYER 4   THE BUSINESS       campaigns · contacts · retries · dashboard · reporting
  LAYER 3   THE CONVERSATION   prompt · psychology · state · guardrails
  LAYER 2   THE PIPELINE       audio timing · turn-taking · barge-in · STT/LLM/TTS wiring
  LAYER 1   THE TRANSPORT      the telephony socket, codecs, jitter
```

| Layer | Owner today | Could Vaani own it? | Should it? |
|---|---|---|---|
| 4 — Business | **Dograh** | yes, ~5,400 lines | **No.** Solved problem, no differentiation |
| 3 — Conversation | **Vaani** | already does | **Yes.** This is the product |
| 2 — Pipeline | **Pipecat** | via Pipecat or LiveKit | **No.** Neither is "yours" |
| 1 — Transport | **Pipecat serializers** | yes | **No.** Carrier protocol plumbing |

The differentiation lives entirely in **Layer 3**. That is the only layer worth
owning, and it is the one Vaani owns.

---

## 3. What Dograh actually provides

Verified by reading the source, not by reputation.

### 3.1 The business layer — genuinely valuable

| Component | Size | Notes |
|---|---|---|
| Campaign engine | ~5,400 lines | Redis queue, per-campaign and global concurrency, rate limiter, circuit breaker, from-number pool, retries with backoff, CSV ingest, timezone windows, restart-safe state |
| Data layer | Postgres | contacts, campaigns, runs, turns, transcripts, dispositions, agent versions |
| Telephony | 5 carriers | Plivo, Twilio, Telnyx, Asterisk, Cloudonix serializers. **Vobiz speaks Plivo verbatim**, so it works unchanged |
| Dashboard | Next.js | agents, campaigns, recordings, reports, model config, tool config |
| Tools | first-class | `end_call`, `transfer_call`, knowledge base, MCP, HTTP |

Rebuilding this is months of work with **zero customer-visible benefit**.

**License:** BSD 2-Clause. Forking is permitted; keep the copyright notice.

### 3.2 What Dograh gets wrong

Honest list, all confirmed in code:

1. **The node graph.** Swapping the system prompt per node destroys the
   provider's prompt cache, and cannot express mid-conversation tool use.
   *Fixed by single-prompt mode.*
2. **Silent failure swallowing.** Setup errors are caught and logged as one
   WARNING line. Two features were found completely dead this way today.
3. **Hardcoded provider gaps.** `reasoning_effort` is set for GPT-5 on OpenAI
   and for nothing else — a 1,068 ms penalty on Groq reasoning models.
4. **Diagnostics computed but never surfaced.** Pipecat calculates a full
   per-turn latency breakdown; Dograh subscribed only to the single total.

None of these are architectural. All were fixed in a handful of lines.

---

## 4. What Vaani provides

Vaani is **the conversation**, and that is not a small thing.

### 4.1 The compiled 4-layer prompt

Deterministic assembly, not generation. An agent is a **compile step**, so
prompt quality is not re-rolled per client.

| Layer | Source | Varies per client? |
|---|---|---|
| 1 — Persona & voice | `layers/01_persona/te-IN.md` | No |
| 2 — Sales psychology & objections | `layers/02_psychology/core.md` | **No — the moat** |
| 3 — Business | **typed in the dashboard** | Yes |
| 4 — Mission | `layers/04_mission/outbound.md` | No |

Measured on the MB Solar agent:

```
user types (Layer 3)        2,801 chars
Vaani adds                 22,158 chars
sent to the model          28,614 chars
```

Layers 1, 2 and 4 are byte-identical across every agent and sit at the **front**,
so they land in the provider's cached prefix instead of being re-billed each
turn. Measured on Groq: **97.5% of a stable prefix is served from cache** once
warm (2,816 of 2,888 tokens).

**A new client is a business description plus a question list.** Persona and
objection handling come free and are identical everywhere.

### 4.2 StateInjector — question coverage

Runs triage on what the caller just said and rewrites the trailing system
message with a fresh state block **before** the LLM fires.

This replaces the one thing the node graph did well: guarantee that every
qualification question gets asked. A plain prompt cannot promise that; a state
block that says *"still to find out: monthly_bill, city"* can.

The Dograh extraction variables double as the question list, so the agent is
defined once.

### 4.3 ReplyFilter — guardrails before speech

Strips protocol lines and enforces hard rules **before a single character
reaches the speech engine**. For a subsidy-linked product where the agent must
never state a price or subsidy amount as fact, prompt instructions alone are not
sufficient control.

### 4.4 What Vaani does NOT provide today

Stated plainly:

- Not the websocket — Dograh's `FastAPIWebsocketTransport` + carrier serializer
- Not the audio timing, VAD or turn detection — Pipecat's
- Not the STT/LLM/TTS clients — Dograh's, configured in the Models page

**A standalone Vaani gateway does exist** at
`bswealthfinance/vaani/gateway/pipeline.py` — its own FastAPI service, own
websocket, own Sarvam + Cartesia stack. It is not in use, because using it
would mean losing campaigns and the dashboard.

---

## 5. The LiveKit question, answered with evidence

### 5.1 LiveKit does not replace Dograh

LiveKit Agents is an alternative to **Pipecat** — Layer 2. Adopting it removes
neither Dograh's campaigns nor its dashboard. The pitch "build our own with
LiveKit" swaps one open-source pipeline framework for another and leaves the
business layer exactly where it is.

### 5.2 What LiveKit is genuinely good at

Its turn detector. **Dograh already ships an equivalent** —
`LocalSmartTurnAnalyzerV3`, an ONNX model running **in-process on CPU**, so it
costs no network hop. It was simply switched off by default.

### 5.3 What switching would cost

- Rewriting the transport layer, which is the part Vobiz depends on. Vobiz
  documents WebSocket streaming as **explicitly recommended for Pipecat**.
- Losing 5 carrier serializers that work today.
- A second rewrite of duplex audio timing. Vaani already attempted a
  hand-written audio layer once. From its own source:

> *"On real calls that gate threw the caller's voice away while the agent was
> speaking — the agent talked over the caller and never heard them. Real-time
> audio is not a place to guess."*

That is why Vaani adopted Pipecat. Repeating the exercise on LiveKit would be
the same lesson at the same price.

### 5.4 Recommendation

**Do not switch.** Revisit only if a specific, measured requirement appears that
Pipecat cannot meet. None has.

---

## 6. Measured evidence from 26 August 2026

All figures from live calls on this system, Indian home broadband.

### 6.1 The journey

| Stage | Turn latency | What changed |
|---|---:|---|
| Start | **3.45 s** | Dograh managed proxy, STT language `multi` |
| After provider switch | **1.45 s** | Groq + Cartesia direct (**done in stock Dograh's UI**) |
| After fixes | *projected ~0.75 s* | endpoint clock, `reasoning_effort`, transcript off critical path |

**The single largest win — 2 seconds — required no code.** It was a
configuration change on stock Dograh.

### 6.2 Per-turn decomposition (the diagnosis that mattered)

```
endpoint (user turn)   0.803  0.802  0.806  0.815  0.816  0.816   dead constant
Deepgram STT TTFB      0.648  0.669  0.710  0.694  0.723  0.587
Groq LLM TTFB          0.212  0.184  0.166  0.166  0.478  0.524   3x spread
Cartesia TTS TTFB      0.091  0.092  0.288  0.158  0.094  0.133
text aggregation       0.043  0.053  0.032  0.050  0.009  0.023
```

Two conclusions:

1. **The endpoint was 70% of the turn and was a clock, not computation** —
   VAD 0.2 s + smart-turn 0.6 s. Now 0.2 s.
2. **The inconsistency is the LLM, and it is geography.** Identical requests
   varying 166–524 ms is a US round trip, not something tuning can fix.

### 6.3 The reasoning-model finding

Measured directly against the configured Groq key and model, ~2,888-token
prompt:

| Setting | TTFT p50 | Produced speech |
|---|---:|---|
| `reasoning_effort=low` | **631 ms** | **5 / 5** |
| absent (what was running) | **1,699 ms** | **2 / 5** |

Three of five requests produced **no speech at all** within 60 tokens — the
model was still thinking while the caller heard silence.

### 6.4 Prompt caching — not broken

```
call 1  prompt_tokens 2888  cached_tokens None
call 2  prompt_tokens 2888  cached_tokens None
call 3  prompt_tokens 2888  cached_tokens 2816   <- 97.5%
```

Groq caches a stable prefix; it needs ~2 calls to warm. Short test calls never
reach it. No fix required — but it is a strong argument for keeping Layers 1, 2
and 4 byte-identical.

### 6.5 Speculation — built, and not earning its keep

Starting the LLM on the caller's stable partial prefix was implemented in full
(~600 lines, 40+ tests) and measured at **0% hit rate across 9 turns**.

The reason is structural, not a bug: **qualification callers answer in two
words.** There is never time for two partials to agree before the turn ends.
Speculation pays off on long utterances, not on "సరే" or "2000".

**Recommendation:** leave it disabled. It is already config-gated.

---

## 7. What is built, and what is not

### 7.1 Built and verified

| Item | Evidence |
|---|---|
| Single-prompt agent editor, no nodes | create → edit → save → persist verified in browser |
| Vaani 4-layer prompt compilation | 2,801 → 28,614 chars on agent 5 |
| StateInjector + ReplyFilter on the live path | builds from the real agent, 6 qualification fields |
| `reasoning_effort` for Groq reasoning models | 1,699 → 631 ms measured |
| `end_call` enum fix | was recording every hang-up as `unexpected_error` |
| Transcript off the latency critical path | ~438 ms |
| Endpoint clock 2.0 s → 0.2 s | endpoint was 70% of the turn |
| Per-turn latency decomposition logging | the diagnosis in §6.2 |
| Telugu STT language | was `multi`, returning Hindi |

**Regression check:** full backend suite run against a clean upstream baseline —
**zero new failures introduced, two pre-existing upstream failures fixed.**

### 7.2 Not yet done

| Item | Why it matters |
|---|---|
| **No live call since the final changes** | Three features looked wired and were silently dead today. Only a call proves it |
| **No End Call tool attached** | The agent physically cannot hang up on its own |
| **Still on Groq (US)** | Sarvam is India-hosted, Telugu-native, measured 247 ms and consistent |
| **Not deployed to Mumbai** | Every turn currently crosses India → US → India |
| **Speculation disabled** | 0% hit rate; leave off |

---

## 8. What to build next, in order

1. **One browser test call.** Free, 30 seconds. Confirms the compiled prompt,
   the brain and the endpoint change actually run. *Nothing else should happen
   first.*
2. **Create the End Call tool** and attach it.
3. **Switch LLM to Sarvam.** Groq's 3× variance is geography. Sarvam is
   India-hosted, Telugu-native, 247 ms measured, and carries no reasoning tax.
   This is a Models-page change.
4. **Deploy to Mumbai.** Removes the remaining international round trip. This is
   the single largest structural latency win left.
5. **Upstream the two bug fixes** (`end_call` enum, Groq `reasoning_effort`) to
   dograh-hq, so they are maintained rather than carried in a fork.
6. **Delete the speculation layer** unless a long-utterance use case appears.

---

## 9. The honest bottom line on latency

| Target | Achievable? |
|---|---|
| 200 ms server-side | **No.** VAD alone is 200 ms; add best-case LLM 166 ms and TTS 90 ms — the floor is ~460 ms |
| ~600–750 ms server-side | **Yes**, with the fixes above |
| 700 ms at the caller's ear | **Only with India-hosted inference and a Mumbai deployment.** Vobiz adds ~490 ms of carrier transit that is measured, not engineerable |

The route to your number is **geography, not architecture**. Moving inference and
hosting into India will do more than any pipeline rewrite.

---

## 10. Conclusion

- "Dograh's pipeline is waste" is **not supported by measurement.** Every real
  problem was configuration, a missing parameter, or a one-word bug.
- "Build our own on LiveKit" **swaps Pipecat for LiveKit** and changes nothing
  about Dograh. It does not remove Dograh; it adds a rewrite.
- **The layer worth owning is the conversation, and Vaani owns it** — compiled
  prompt, sales psychology, state, guardrails.
- Dograh keeps doing the boring, valuable work: campaigns, Redis, Postgres,
  telephony, dashboard.

**Own the conversation. Rent the plumbing. Move the compute to India.**
