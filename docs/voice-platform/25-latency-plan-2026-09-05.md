# Cutting Vaani per-turn latency to the 800 ms budget

## Context

Measured on real telephony (run 392, 19 turns): **TOTAL 1,119 ms** against a
budget of 800 ms. The client's requirement is non-negotiable, and three
behaviours that currently work must not regress: the agent answers the caller's
question first then asks its own, it answers off-topic questions, and it
remembers across turns (ask budget + repeat guard).

The client also asked specifically for **semantic turn detection** — audio and
text combined, with the LLM thinking before the caller has finished. Pipecat
ships exactly that and we are not using it.

### Two corrections to what was previously reported to the client

**1. Prompt size does NOT cause MB Solar's extra 600 ms.** I reported a
correlation across the five agents (1,890 chars → 1.45 s, 9,811 → 2.06 s).
`dograh-vapi/findings.md` §F6 already ran this as a *controlled* experiment —
every tier cache-warmed, round-robin interleaved, 7 rounds — and found the
across-tier effect (0.339 s) sits **inside** the within-tier noise floor
(0.786 s), with reasoning output flat (~110 chars) at every prompt size. My
comparison was uncontrolled and is the same cache-warmth artefact. **Trimming
prompts is cancelled**, which also preserves the standing rule that objection
handling is the payload.

**2. The agent does NOT already stream speech — the client was right.**
I said streaming was already working. It is not. `service_factory.py:618` passes
`text_aggregation_mode=TextAggregationMode.TOKEN` to **Deepgram**, with a comment
whose reasoning is written *about Cartesia*. The live Cartesia branch at
`service_factory.py:697` does **not** pass it. Pipecat's own Cartesia docstring:
*"we aggregate sentences before sending to TTS. This adds ~200-300ms of latency
per sentence… TODO: Consider making TOKEN the default for Cartesia in 1.0."*
Worse for us: the sentence aggregator needs a non-whitespace character *after*
terminal punctuation, and our replies are typically one sentence ending in a
question mark — so the TTS receives nothing until the LLM has finished the whole
reply. The measured "TTS 69 ms" is clocked *after* that wait, which is why it
looked free.

---

## Phase 0 — Ship the safe wins now (client's chosen sequencing)

Three changes, none touching the turn decision, so none can raise the
false-interruption rate.

### 0a. Kill a 250 ms dead timer — config only
`stt_finalisation_budget_secs: 0.45 → 0.2` (schema floor is `ge=0.2`) on all five
workflows via `bswealthfinance/tools/sync_latency_config.py`.

With `turn_wait_for_transcript=False` this value no longer gates waiting *for* a
final. What it still does: when the late final arrives,
`turn_analyzer_user_turn_stop_strategy.py:302` arms
`max(0, stt_timeout − stop_secs)` = **0.25 s of dead wait** before
`push_aggregation()` emits the context frame. `SarvamSTTService` never sets
`TranscriptionFrame.finalized`, so the fast branch cannot short-circuit it.
**Saving: exactly 250 ms on every late-final turn.** Revert is one command.

### 0b. Stream tokens to Cartesia — the client's own "speak while generating"
Add `stream_tokens` to `create_tts_service` (mirror the existing
`stt_finalisation_budget_secs` parameter pattern at `service_factory.py:264`),
thread it from `run_configs` at `run_pipeline.py:784`, pass
`text_aggregation_mode=TextAggregationMode.TOKEN` into the **Cartesia** branch
(`service_factory.py:697`). Default **False** in
`api/schemas/workflow_configurations.py`; enable per workflow.

**Saving: 100–400 ms**, largest on single-sentence replies, which is most of ours.
`ReplySanitizer.HOLDBACK = 24` means the first chunk is already ~24 characters,
so the opening is not synthesised letter-by-letter, and Cartesia keeps prosody
context across the websocket stream.

**Rollout: MB Solar only, listen to one test call, then the other four.** No test
can judge Telugu prosody — only an ear. (Assumption, since the client did not
pick a rollout option; the one-command revert makes this safe.)

### 0c. `llm_hedge: 2 → 3` — config only
Code default is already 3 (`workflow_configurations.py:127`); all five stored
configs say 2 and stored config wins. In-repo bench: hedge-2 p50 0.653 / p90
0.761 vs hedge-3 p50 0.325 / p90 0.405.

**Be sceptical**: one bench, one prompt, one afternoon, against a documented
0.256–1.161 s within-request spread. **Expect 100–250 ms with wide bars.** Do
not run this concurrently with Phase 3 speculation — hedge-3 × speculation is up
to 6 concurrent generations per turn, and run 92 lost a call to less than that.

---

## Phase 1 — Measurement, in parallel with Phase 0

The 523 ms "endpoint" is a residual (`total − llm_ttfb − tts_ttfb`), not a
measured quantity. It hides at least: VAD 200 ms, analyzer wait, STT
finalisation *after* the verdict, the 250 ms timer from 0a, and TTS sentence
aggregation from 0b.

- **`tools/vaani_runs.py::decompose`** — also read `rtf-latency-breakdown`; print
  the **per-turn distribution**, not the mean. Late-final turns cluster near
  0.8–1.0 s; that cluster's size is the multiplier on 0a's and Phase 2's savings.
- **`run_pipeline.py:1391-1415`** — add `text_aggregation_secs` to the payload.
  Pipecat already computes it (`user_bot_latency_observer.py:83-92`) and we throw
  it away. **That field is 0b's saving, measured.**
- Cross-check against `tools/true_latency.py`, which measures from the separated
  `user.wav`/`bot.wav` and owes nothing to the logs.

---

## Phase 2 — Semantic turn detection (the client's explicit request)

### What we have now
`TeluguTurnAnalyzer` is already a **hybrid** detector: audio prosody (f0 track,
1.5 s tail) plus text via `TextAwareTurnStopStrategy.note_text()` and
`completeness.sounds_unfinished()`. It ends 33.9–43.9% of turns early at under a
2% false-cutoff rate. It exists because **no vendor turn detector supports
Telugu** — Smart Turn v3 covers 23 languages, LiveKit 14, Deepgram Flux 10.
The text half is a heuristic, not a model. That is the gap.

### 2a. Switch STT to `saaras:v3-realtime` — prerequisite for everything below
Config only; routing already exists (`service_factory.py:432-436`). Measured
speech-end→transcript **0.373 s (saarika:v2.5) vs 0.091–0.121 s (realtime)**.
Critically, `saarika:v2.5` emits **no `InterimTranscriptionFrame` at all**, which
is why partial-response and speculation are inert today. No partials = no
semantic turn detection is possible.

Gate this on **transcript accuracy, not latency**: `stream_type="fast"` is
Sarvam's least stable, and a documented pair read "yes yes yes" as partial and
"no no no, I don't have" as final. Compare field-capture rate over ≥3 calls each
way before keeping it.

### 2b. Fix two latent outages that 2a would arm — MUST precede 2a going live
- **`partial_response.py` direction bug (confirmed, not suspected).**
  `UserStoppedSpeakingFrame` is broadcast from the aggregator
  (`llm_response_universal.py:1290`), and `broadcast_frame` pushes one copy
  **upstream**. `PartialResponder` sits *before* the aggregator, so the only copy
  it sees is upstream, and it re-pushes the promoted transcript in that same
  direction — toward the STT, never reaching the LLM. It also sets `_promoted`,
  which **suppresses the genuine final**. With interims on, that is a turn where
  the agent gets no text and says nothing. All six tests use `DOWNSTREAM`, the
  direction that never occurs live. Fix: push `DOWNSTREAM` unconditionally; add a
  test driving `UPSTREAM`. **Keep the existing "only promote if no final in hand"
  trigger** — do not promote at VAD-stop until a hit-rate measurement exists.
- **Speculation would generate from the wrong prompt.**
  `run_pipeline.py:249` builds the speculative prompt from
  `compose_system_prompt_for_node`, not `compile_vaani_system_prompt`, and
  `:263` passes `get_state_block=lambda: ""`. **The state block is where all
  three protected behaviours live** — answer-first, `MAX_ASKS_PER_FIELD`, the
  repeat guard. A speculation hit would speak a reply with none of them.
  Set `speculation_enabled: false` in stored config on all five workflows before
  2a, and add a test asserting the speculative system prompt is byte-identical to
  the installed one with a non-empty state block.

### 2c. Adopt pipecat's LLM turn-completion protocol
`pipecat/src/pipecat/turns/user_stop/llm_turn_completion_user_turn_stop_strategy.py`
is precisely the architecture in the client's transcript: the LLM is polled on
partial input and emits a marker instead of a reply —
**✓ complete → speak; ○ incomplete-short → wait; ◐ incomplete-long → wait** —
so the model is *thinking while the caller is still speaking* and the response is
ready the moment the turn ends. Config lives in `UserTurnCompletionConfig`
(instructions, `incomplete_short_timeout` 5 s, `incomplete_long_timeout` 10 s).
It installs alongside `deferred(...)`-wrapped detector strategies, so
**`TeluguTurnAnalyzer` keeps its authority over the audio half** and the LLM
supplies the semantic half — audio + text, which is exactly the transcript's
recommendation.

**Two integration risks that must be settled first:**
1. **Marker protocol vs `MODE_PROTOCOL`.** Our compiler already requires the
   first line of every reply to be `MODE: ASK|CLOSE` (`compiler.py:270`). Two
   protocols both claiming the first token will collide. Decide whether the mode
   line moves, or the completion instructions are rewritten to co-exist.
2. **State-block staleness.** Polling mid-utterance renders the state block
   against text the caller has not finished. `SpeculationProbe` currently sits
   *before* `StateInjector` in `vaani/pipeline.py`, so it would see the
   transcript before triage refreshes state. The trigger must move *after*
   `StateInjector` (or be called from `StateInjector.note_user_text` after
   `_refresh()`).

**Expected: up to the full 527 ms LLM TTFB on turns where the verdict lands
after the transcript.** Verify with `rtf-speculation` hit rate and `llm_secs`
going to ~0 on hits. **Acceptance gate: run `tools/vaani_eval.py` with completion
forced on every turn and require byte-identical replies to the non-semantic
path.** If they differ, the state assembly is not identical and it is not ready.

### 2d. Throttle the detector's CPU — last, smallest
`TeluguTurnAnalyzer._probability()` costs ~5–7 ms and runs **synchronously on the
event loop** on every 20 ms frame once silence starts — ~10 calls (53 ms) at a
523 ms endpoint, up to ~54 (286 ms) at `endpoint_max_secs` 1.40 s. Score every
3rd frame instead. `_last_probability` becomes ≤40 ms stale against a
300–1,400 ms wait. This is mostly a **concurrency** win, not a p50 win — do not
claim a median saving without measuring one. A coarser cadence can only delay a
COMPLETE, never advance it, so it cannot raise false interruptions.

---

## Explicitly NOT doing, and why

- **Trim prompts / two-tier prompts** — §F6 ran the controlled experiment and
  cancelled it. Effect inside noise.
- **Lower VAD `stop_secs`, `smart_turn_stop_secs`, or `endpoint_min_secs`** —
  the recorded sweep shows deciding 0.10 s earlier moved early-ended turns
  33.2%→21.1% and mean endpoint *up* 0.718→0.753 s. **Deciding sooner makes calls
  slower**, and spends directly against the 2% false-interruption floor.
- **Move vendors to India** — already there: Groq 30.8 ms, Cartesia 21.1 ms,
  Sarvam 37.8 ms RTT.
- **Add prompt caching** — already working (97.5% measured); `prewarm.py` warms
  the prefix during the greeting.
- **A non-reasoning model** — `reasoning_effort:"none"` is rejected by Groq for
  gpt-oss; `low` is the floor, and this account has no non-reasoning alternative.
- **Reinforcement learning for latency** — RL changes word choice; it cannot make
  the system notice a caller stopped talking. The 3,810 harvested examples are
  worth using for *quality* (distillation/SFT), separately.
- **`turn_start_min_words` / `provisional_vad_pause_secs`** — dead config while
  `turn_start_strategy = "default"`.

---

## Expected outcome

| | now | after |
|---|---|---|
| 250 ms dead timer (0a) | 250 | 0 |
| TTS sentence buffering (0b) | 100–400 | ~0 |
| LLM hedge (0c) | — | −100…−250 |
| STT finalisation (2a) | ~373 | ~110 |
| LLM overlapped (2c) | 527 | →0 on hit turns |

Server-side p50 should land **inside the 800 ms budget**. The caller hears that
plus `telephony_overhead_ms: 490`, which `latency_budget.yaml` marks *"NOT
engineerable"* — so **~1.0 s at the caller's ear is the floor**, and I will
report the real number rather than the target.

---

## Verification (every phase, same method)

1. `python tools/vaani_runs.py --workflow N --run <id>` — per-turn
   endpoint/LLM/TTS decomposition from `rtf-latency-breakdown`.
2. `python tools/latency_timeline.py` — trend across agents and dates.
3. `python tools/vaani_probe.py --workflow N --script derail|website|interrupt|silly`
   — the behaviour scripts, on **all five agents**, before and after.
4. `python tools/vaani_eval.py --workflow 2` — **twice**, because the noise band
   is ±3 cases; a single run proves nothing.
5. Offline suite: `python -m pytest api/tests/test_vaani_*.py test_coach.py
   test_speech_register.py test_layers_are_reusable.py --noconftest` — currently
   **402 pass, 10 pre-existing failures** in `test_vaani_filler_cover`. Diff the
   failure list before/after; **zero new failures** is the gate.
6. After each deploy: `curl` api + ui, and confirm the Coolify
   `docker_compose_domains` ports are intact (the cause of the 4 Sep outage).

Regression guards to add: a `sync_latency_config` assertion that stored config
and code defaults agree (this class of "shipped change never ran" caused 0c); a
`test_cartesia_tts_service_factory` assertion for the aggregation mode; an
`UPSTREAM`-direction test for `PartialResponder`.
