# Latency across all five agents — is it consistent, and where does it go

**5 September 2026 · Project Vaani · workflows 2, 3, 4, 5, 6**

The client: *"is that latency of all agents consistent... first figure out where
the latency is losing"*.

Measured, not estimated. Identical six-turn script against every agent, twice.

---

## 1. Is it consistent? Yes — once you account for prompt size

| Agent | wf | node prompt | round 1 | round 2 | avg |
|---|---|---|---|---|---|
| Solar | 4 | **1,890** chars | 1.48 s | 1.41 s | **1.45 s** |
| Investing | 5 | **1,959** | 1.53 s | 1.42 s | **1.48 s** |
| Property | 6 | **2,546** | 1.63 s | 1.41 s | **1.52 s** |
| Loan | 3 | **4,302** | 1.65 s | 1.39 s | **1.52 s** |
| **MB Solar** | 2 | **9,811** | 2.35 s | 1.76 s | **2.06 s** |

Four of the five agents sit within **70 ms of each other**. That is consistency.

**MB Solar is the outlier at ~600 ms slower, and its prompt is 5x the others.**
Nothing about MB Solar's configuration differs — every agent carries identical
turn-taking settings (`llm_hedge 2`, `smart_turn_stop_secs 0.2`,
`turn_start_min_words 3`, `turn_stop_strategy turn_analyzer`). The only variable
is how much text the model must read before it may answer.

This reproduces the project's own earlier measurement exactly: **1,086 extra
characters of prompt took the LLM's first token from 0.22 s to 0.655 s.** Eight
thousand extra characters costing six hundred milliseconds is the same curve.

### The consequence
The MB Solar knowledge base — the thing that makes it answer website questions
well — is also what makes it the slowest agent. That is a direct trade, and it
is worth stating plainly: **every character added to a node prompt is paid for
on every single turn of every single call.**

---

## 2. Where the latency actually goes

From real telephony, run 392, a 167-second call, 19 turns. `TOTAL = endpoint +
LLM + TTS`; STT runs inside the endpoint window.

| Component | measured | budget | verdict |
|---|---|---|---|
| endpoint | 523 ms | 250 ms | **273 ms over** |
| ├─ of which STT finalisation | **415 ms** | 100 ms | **315 ms over — the largest single loss** |
| LLM first token | 527 ms | 200 ms | **327 ms over** |
| TTS first audio | **69 ms** | 190 ms | **121 ms UNDER — giving time back** |
| **TOTAL** | **1,119 ms** | 800 ms | **319 ms over** |

### Ranked, this is where we are losing it

1. **LLM first token — 327 ms over.** Two causes, and they are separable: the
   model is a REASONING model (`gpt-oss-120b`), and on MB Solar the prompt is
   9,811 characters. `latency_budget.yaml` states the requirement outright:
   *"Requires a NON-REASONING model. A reasoning model cannot fit this."*
2. **STT finalisation — 315 ms over.** Waiting for the final transcript. The
   config asks for `stt_finalisation_budget_secs: 0.2` and the measurement is
   0.415. **The configured budget is not being honoured, and nobody had measured
   this before.** It is the single largest component-level miss.
3. **TTS — nothing to win.** 69 ms against a 190 ms allowance. Cartesia is not
   the problem and never was; an earlier "TTS is bimodal at 231 ms" finding was
   an artefact of mis-paired metrics and is documented as such.

### And the part that is not engineerable
`latency_budget.yaml` records `telephony_overhead_ms: 490` — the carrier — and
marks it **"NOT engineerable"**, with `caller_p50_ms: 1290` as what the caller
hears when the 800 ms server target is met. Any target below about one second
end-to-end is not available on a phone line, whatever the code does.

---

## 3. "It should speak while generating, not after complete"

**It already does.** This is not a gap.

The evidence is in the numbers above. `TOTAL` is time to FIRST AUDIO, not time
to a finished reply: TTS first-audio is measured at 69 ms *after the LLM's first
token*, not after its last. The agent begins speaking on the opening fragment
and keeps generating while it talks.

The only buffering is `ReplySanitizer.HOLDBACK = 24` — twenty-four characters,
held so a partial marker (a role label, a mode token) cannot be spoken before it
can be recognised. Its own note: *"costs a few characters of delay and never a
whole sentence."*

So there is no win available here. The reply is already streamed.

---

## 4. What to do, in order of size

1. **Shrink the MB Solar prompt.** It alone costs ~600 ms and affects only that
   agent. The website knowledge does not have to sit in the always-on prompt —
   `coach.py` already demonstrates the pattern of selecting one relevant row per
   turn at ~220 characters instead of carrying the catalogue on every turn.
2. **Close the STT gap: 415 ms → 100 ms.** Largest platform-wide loss, shared by
   every agent, and it is code and configuration rather than training.
   `probe_sarvam_realtime.py` exists for measuring alternatives.
3. **A non-reasoning model for the 200 ms LLM budget.** The harvest already
   reports `distillation / SFT — 3,810 — READY`. Train on the loan agent's 1,095
   calls, not MB Solar's 50.
4. **Nothing on TTS. Nothing on streaming.** Both are already better than budget.

Land 1 and 2 and the server side is roughly **520 ms**, inside the 800 ms
target, with the caller hearing about **1.0 s** instead of 1.5 s.

---

## Method note
Text-chat probe figures measure an API round trip and are therefore higher in
absolute terms than the telephony numbers; they are used here only to COMPARE
agents under identical conditions, which is what the consistency question asks.
The component breakdown comes from real telephony run records. Both rounds were
run back to back to control for server drift — which is real: the same probes
measured 3.3 s the previous evening, and reverting code changed nothing, so that
was environmental.
