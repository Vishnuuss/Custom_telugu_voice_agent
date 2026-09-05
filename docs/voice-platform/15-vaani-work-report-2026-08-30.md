# Vaani work report — 30 August 2026

## 1. Run 318: the first call after the fixes

Run 318 (WR-TEL-OUT-55669215, 200s) is the only call placed after commit
`992b10d` and after the knowledge base went in. Runs 315–317 predate both by
minutes, which is why 317 still says "ten oclock" and 318 does not.

**What the fixes delivered, measured:**

| | |
|---|---|
| p50 TOTAL | **0.892 s** |
| Clock phrasing | `ten గంటలకు` — the o'clock fix is live |
| Subsidy question | answered with the real MNRE figures for the first time |
| "మీ కంపెనీ పేరేం?" / "మీ ఆఫీస్ ఎక్కడ?" | both answered instead of deflected |

The subsidy answer, verbatim: *"PM Surya Ghar scheme ప్రకారం మొదటి 2 kW కి
30,000 rupees per kW, తర్వాత 18,000 rupees per kW, మొత్తం 78,000 rupees వరకు."*
That is the knowledge base working exactly as intended.

**And it still lost the lead in 200 seconds.** None of it was speed.

---

## 2. It sized a solar system on the phone

    USER : మా ఫ్యాక్టరీ ... 300 స్క్వేర్ మీటర్స్ ... ఎన్ని ప్యానెల్స్ కావాలి?
    BOT  : 300 square meters రూఫ్ మీద సుమారు 30 kW సిస్టమ్ పెట్టవచ్చు,
           అంటే 80-100 panels అవసరం అవుతాయి.

Nobody supplied 30 kW, or 80, or 100. The agent did the arithmetic itself, on a
call, for a factory owner who will repeat that figure to a vendor. One sentence
earlier it had answered the same question correctly — that it depends on the
site — and then produced the number anyway.

Layer 2 has said **"Never manufacture a specific"** since the beginning. The
existing price guard only catches four-or-more-digit rupee amounts, so nothing
flagged it.

### Why a blacklist could not fix it

Banning "kW" would have broken the best answer this agent has. The subsidy reply
above is *full* of kW and rupee figures, and every one of them is correct.

So the rule is a **whitelist**: a number the agent says must appear either in the
knowledge base or in what the caller just said. Anything else it invented.

The allowed set is derived from the client's own compiled prompt, once per call.
That is what makes it reusable — a new client's knowledge base defines its own
legal numbers just by containing them, with no code change. An empty whitelist
means no knowledge base was compiled, and the rule stays off rather than gagging
the agent on its first sentence.

Only sentences carrying a **unit** are examined — kW, panels, units, square
metres, percent, years. A bare number in ordinary speech ("ఒక నిమిషం") is not a
technical claim, and checking those would fire on nearly every turn.

---

## 3. It offered the same appointment eight times in ninety seconds

Between 04:10:04 and 04:11:30 the agent launched the appointment offer eight
times, at a caller who was asking real questions about cost and panel counts
each time.

The two-ask budget **worked**. `assessment_agreed` had already dropped out of the
checklist. The problem was what replaced it:

```
STILL_NEED: []
```

That is the entire instruction the model received. **An empty checklist is not
an instruction.** With nothing to do, the model fell back on the conversation
history — and by then the history was six appointment offers deep, so it
produced a seventh.

That is precisely what the client means by harassing: an agent with nothing left
to ask, asking the last thing again. The state block now says what to do
instead — answer what they ask, do not offer a time again, thank them and end.

### A note on the "truncated" replies

Five places in run 318 show a reply starting and stopping mid-clause. The
timestamps settle what they are:

```
04:10:16.990  USER  ఎంత పడుతుంది ప్యానెల్స్?
04:10:17.012  BOT   రేపు ఉదయం ten గంటలకు లేదా ఎల్లుండి
```

**22 milliseconds.** No model answers in 22 ms. That is the *previous* reply,
already being spoken, cut off because the caller talked over it. Barge-in
working correctly. The defect is not the truncation — it is that the agent kept
launching into an offer the caller had to interrupt.

---

## 4. The layers disagreed with each other

Three clock conventions were live at once:

| Source | Produced |
|---|---|
| Layer 1 (persona) | `eleven o'clock` — endorsed in an example |
| `booking.Slot.say()` | `ten గంటలకు` |
| The model, sometimes | `పది గంటలకు` |

So the agent flipped between them, and runs 300, 314 and 317 all put `oclock` on
the line — once as **`four oclockకి`**, with the Telugu case ending glued onto an
English word.

One convention now, stated once: **English figure, Telugu frame.** The full rule
set is written up in
[14-telugu-voice-register-guide.md](14-telugu-voice-register-guide.md).

---

## 5. The shared layers are reusable again

The client asked for a Telugu human he can reuse across clients. That only works
if the shared layers carry no industry. They had stopped doing so:

| Layer | Leakage found |
|---|---|
| 01 persona | `సౌర శక్తి → సోలార్`, `విద్యుత్ బిల్లు → కరెంట్ బిల్లు`, and a sentence naming *subsidy, panel, meter, battery* as the words to say in English |
| 02 psychology | none |
| 04 mission | none |

All correct for MB Solar Hub. All dead weight in a jewellery agent's cached
prefix, and all of it inviting the model to talk about panels to someone buying
gold.

The register **rule** stays in Layer 1. The industry's **words** come from Layer
3's "Words real customers use for this", which the client's knowledge base
fills. `api/tests/test_layers_are_reusable.py` now checks all three shared layers
for industry vocabulary, client names and concrete rupee figures on every test
run — because the easiest way to fix a solar call is to put a solar example in
the persona, and the next client then inherits it.

---

## 6. Cost and efficiency

### 6.0 Nothing was measuring cost

`cost_info` on every run reads `"dograh_token_usage": 0`. Token usage is not
instrumented. Every figure below is therefore **computed from measured request
counts and measured prompt size**, not read off a bill, and it is labelled as
such rather than presented as an invoice.

Compiled prompt for workflow 2: **33,350 characters ≈ 10,600 input tokens**,
constant for the whole call.

### 6.1 Speculation was a dead feature — 0 hits in 145 attempts

Measured across every run from 300 to 318:

| run | speculations | hits |
|---|---|---|
| 300 | 21 | 0 |
| 305 | 12 | 0 |
| 311 | 10 | 0 |
| 312 | 6 | 0 |
| 313 | 16 | 0 |
| 314 | 16 | 0 |
| 316 | 12 | 0 |
| 317 | 18 | 0 |
| 318 | 25 | 0 |
| **total** | **145** | **0 — 0.0%** |

Speculation runs through the same hedged LLM, so it was issuing a full extra set
of requests every turn and discarding all of them. Turned off.

### 6.2 The hedge was above its own recommended default

`llm_hedge` was **3**. `hedged_llm.py`'s own bench sets `DEFAULT_HEDGE = 2` and
records that hedge-2 already collapses the tail. Set to 2.

### 6.3 What those two together do

| | before | after |
|---|---|---|
| LLM requests per turn | 3 main + 3 speculative = **6** | **2** |
| Input tokens per turn (~12,000/req) | ~72,000 | ~24,000 |
| Run 318 (19 turns), estimated | ~1.37 M | ~456 K |

**A two-thirds reduction in LLM spend**, and the speculative half provably cost
nothing to remove.

### 6.4 Prefix caching — already correct, and worth protecting

Groq applies prompt caching automatically on `openai/gpt-oss-120b`: **50% off
cached input tokens, no write fee**, on prefixes shared with recent requests.

The structure already earns it, and that is not an accident —
`compile_prompt`'s docstring says *"Constants first, for cache locality"*:

- The system prompt contains no per-call value. Persona, psychology, business
  layer and mission are all workflow constants, so the ~10,600-token prefix is
  identical **across calls**, not merely within one.
- The state block is a separate system message placed **after** the history, so
  the freshest instruction never sits inside the cacheable prefix.

The actionable form of this is a prohibition: **never put the caller's name, the
time, or any per-call value into the system prompt.** It is the obvious place to
put them and it would silently cost 50% of every input token for the rest of
the call.

### 6.5 Context compaction — evaluated and rejected, with a reason

`context_compaction_enabled` is `false`. Leaving it false is the right call, and
this is the one place where the obvious optimisation is wrong.

Compaction rewrites earlier turns to shorten the history. Rewriting anything
*inside* the prefix invalidates the cache from that point on, for every
remaining turn of the call. The saving is a few hundred tokens of history; the
cost is the 50% discount on ~10,600 tokens, every turn thereafter. Recent work
on long-horizon agentic tasks reports the same effect — naive full-context
caching and mid-context edits can raise latency rather than lower it.

For a 25-turn call the history tail is roughly 3,500 tokens against a 10,600
token constant prefix. Compaction is optimising the smaller term by destroying
the discount on the larger one.

### 6.6 The remaining lever, not yet taken

Extraction runs its own unhedged LLM call every turn. It is small — a field list
and one exchange — but it is a third request per turn and it is *not* cached,
because its prompt changes every time. Batching it (extract every second turn,
or only when the caller's utterance contains something extractable) is the next
real saving. Not done, and not estimated, because it needs a measurement first.

---

## 7. Verification

- **427 passing** across the synchronous Vaani suite. 27 new:
  `test_run318_defects.py` (16) and `test_layers_are_reusable.py` (11).
- The one failure in `test_reply_sanitizer.py` is pre-existing — confirmed
  identical by stashing the work and re-running, not assumed.
- Config changes applied to workflow 2 and **read back verified**, because this
  API has returned HTTP 200 for a write that changed nothing before.
- Deployed as `3c77465`; the app reports `running:healthy`.

## 8. Still open

- **No call has yet exercised any of section 2, 3, 5 or 6.** Deployed and
  verified-by-test is not verified-by-call.
- `max_call_duration` is 200s and run 318 hit it mid-conversation with an
  engaged caller. Left alone deliberately: the section 3 fix should make calls
  end sooner rather than later, and changing both at once would confound the
  measurement.
- Token usage is still not instrumented (section 6.0).
- Appointment times are still stored wrong. Run 316's caller said
  **"రేపు ఉదయం"** — tomorrow morning — and the stored slot was
  `2026-08-30T17:00`, five in the evening. Not fixed today.
- `location` is normalised inconsistently: run 318 stored `అనంటపూర్` in Telugu
  script, run 316 stored `Hyderabad` in English.
- The repository is still public; the Coolify token, Dograh API key and Sarvam
  key still need rotating.
