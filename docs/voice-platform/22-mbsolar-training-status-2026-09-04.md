# MB Solar agent — what is done, what is not

**4 September 2026 · Project Vaani · workflow 2 (MB Solar Hub), id 336**

This document answers five questions directly, with measured numbers. Where the
answer is "no", it says no.

---

## Summary

| # | Asked for | Status | The number |
|---|---|---|---|
| 1 | Ontology | **DONE and LIVE** | 5 families, 21 sub-services |
| 2 | Latency 700 ms | **NOT MET** | p50 **1.10 s** text, **1.13 s** on the one real call with usable audio |
| 3 | Turn detection trained | **Already trained. Deliberately NOT retrained today** | 2,754 → 2,759 utterances = **5 new in 8 days** |
| 4 | Prompt cache working | **YES — it was never broken** | 2,816 of 2,888 tokens cached = 97.5% |
| 5 | Reinforcement learning | **NOT BUILT. Does not exist** | 474,568 bytes of training data collected, nothing consumes it |

Two of five are done. One was already true. **Two are not done: latency and
reinforcement learning.**

---

## 1. Ontology — DONE

Built from a fresh fetch of all 43 live pages. Site content was unchanged since
the 30 August scrape. Full map in
`21-mbsolar-website-ontology-2026-09-04.docx`.

The structure: five service families, twenty-one sub-services, and for each one
*who it is for* and *the one thing that caller needs to know*.

**What went live**, and it is not what was originally planned. The ontology was
first written into the agent's knowledge base. That was measured and it made the
agent **worse**:

| Knowledge base | Size | Eval result |
|---|---|---|
| Original | 9,811 chars | **20/25, 8 hard — twice, identical** |
| With full ontology | 14,904 | 21/25 |
| With trimmed ontology | 11,997 | **15/25, then 18/25** |

The mechanism is that **a list in the prompt gets recited**. The failing case
produced a 277-character blob — the agent reading out the service catalogue.
That is the "brain rotting" behaviour the client complained about, caused by the
fix meant to prevent it. Writing "do not recite this list" directly above the
list did not stop it.

So the knowledge base was **reverted to its original 9,811 characters**, and the
ontology went instead into the just-in-time coach (`coach.py`), which selects
one row from the caller's own words and costs nothing on turns that do not
match. The agent now recognises a society, apartment, warehouse, institution,
industry, office or land caller, plus job enquiries, "how do you verify
vendors", and "when will someone call me".

Noise floor was measured first: two runs on an identical published version
differed by 3 cases, so the 20 → 15/18 drop is outside noise.

---

## 2. Latency 700 ms — NOT MET

**Measured p50 is 1.10 s in text chat and 1.13 s on the one recent real call
that had usable audio (run 392).** The target is 700 ms. It has not been hit,
and nothing shipped today was expected to hit it.

What is known about where the time goes, from this project's own measurement on
run 7: perceived latency 2.256 s, of which **~1.385 s is the caller falling
silent to a final transcript** and 0.872 s is transcript to first audio.
**Endpointing is the larger half.** Every LLM optimisation so far has been
competing over the smaller half.

So the route to 700 ms runs through the turn detector — which brings us to the
next item, and to the reason it is stuck.

Two levers are currently switched off in the live config and were not touched:
`speculation_enabled: false` and `context_compaction_enabled: false`.

---

## 3. Turn detection — already trained, deliberately not retrained

It is **working, not dead**. The live config has
`turn_stop_strategy: "turn_analyzer"`, and the server loads a real trained
model, `audio_turn_gbm.json` (176,933 bytes, 28 August): a boosted forest over
prosody, trained on 2,754 real Telugu utterances from 651 callers. No vendor
detector supports Telugu at all — Smart Turn v3 covers 23 languages, LiveKit 14,
Deepgram Flux 10, AssemblyAI 4–6, and Telugu is in none of them.

**A full harvest of all 2,097 runs was taken on 4 September. It produced 2,759
utterances against the previous 2,754 — five new lines in eight days**, verified
by set difference, not by counting. The preference file was byte-identical.

**Retraining was therefore refused, as a decision.** The model is tuned to hold
false cut-offs under 2% — cutting a caller off mid-sentence being the failure
Telugu callers actually complained about. A 0.18% increase in data cannot
improve that and can only move the operating point.

**The constraint is call volume, not training.** Workflow 2 has taken 50 runs in
its entire life. A better turn detector needs more real calls.

One gap for the future: `audio_index.jsonl` came back empty because `--audio`
was not passed, and the acoustic model needs prosody. Any real retrain must
harvest with `--audio`.

---

## 4. Prompt cache — working, and never broken

An earlier note in this project's planning files claimed the cache missed at
every node transition. **That was wrong**, and it described Dograh, the old
engine.

- `10-dograh-vs-vaani-architecture-report.md` §6.4 is titled **"Prompt caching —
  not broken"**: Groq caches a stable prefix and needs about two calls to warm.
- The same report lists the node-graph cache destruction as a Dograh defect,
  marked **"Fixed by single-prompt mode."**
- Measured: call 1 and 2 `cached_tokens None`; call 3 **2,816 of 2,888 = 97.5%**.
- `compiler.py` confirms the layout — persona and psychology are constants at
  the front, and `build_messages` puts the varying state block last, after the
  history.

There is nothing to repair here. This was removed from the work plan.

---

## 5. Reinforcement learning — does not exist

There is **no reinforcement learning in this codebase.** A search for
reinforce / reward / bandit / RLHF across `api/` returns one prose hit, the word
"reinforce" inside a guidance string. There is no trainer in `tools/`.

It is **half built, and the collected half is the data half**:

- `vaani_harvest.py`: "dpo.jsonl is the free win. Every reply that FAILS
  hard_rules is a labelled [rejection]."
- `vaani_dataset.py`: "preference pairs, one per turn where a REJECTED reply
  exists."
- The file exists — **474,568 bytes of preference pairs.** Nothing has ever
  trained on it.

What does the adaptive work today is `coach.py`, which selects rules by pattern
from the caller's words. That is rule selection, not learning. Calling the
current system reinforcement learning would be false.

Note the same volume constraint applies: preference data did not grow at all
between 27 August and 4 September.

---

## The defect that is still open, and where the value is

The eval's remaining 8 hard failures are all one family: **the agent repeating a
question verbatim instead of hearing the caller change their answer.** This is
the client's own first complaint — "if I tell something first it is considering
it, if I try to change it, it is not listening".

The 4 September harvest quantified it across the whole call history:

| Defect | Occurrences |
|---|---|
| **Two questions in one turn** | **226** |
| Markdown read aloud | 42 |
| Three questions in one turn | 15 |
| Truncated mid-word | 9 |
| Four questions in one turn | 4 |
| Blob over 210 characters | 3 |
| Five questions in one turn | 3 |

A repetition guard already exists — `brain_processor._is_repeat` substitutes
`guardrails.REPAIR_LINE`, similarity-based, decided on the first chunk before
anything is spoken. It fires, but not enough. Text chat runs the same
`ReplyFilter`, so the eval failures are a genuine signal and not an artefact of
the text path.

**This is the remaining work with real value in it.**

---

## Production incident, 4 September

Deploying the day's code took vaani.bswealthfinance.com and
vaani-api.bswealthfinance.com down with 502 for roughly an hour.

**Cause.** The last successful deploy was 26 August 18:10 UTC. Commit `a4f8665`,
*"compose: stop publishing host ports"*, landed 22 minutes later and was never
deployed — the stack ran 9-day-old containers for nine days. That day's deploy
shipped it along with 73 other commits. With no published ports, Coolify could
not infer a Traefik backend for the `ui` and `api` services. `minio` survived
because its domain entry already carried an explicit `:9000`.

**Fix.** Declare the ports in `docker_compose_domains`, as minio already did:
`ui -> :3010`, `api -> :8000`. The API requires an array,
`[{"name":"ui","domain":"..."}]`; the object form is rejected.

**Verified after.** api 200, ui 307, storage 403. Eval 20/25, 8 hard — identical
to the pre-change baseline, so nothing regressed. Latency p50 1.10 s.
`voice.bswealthfinance.com` was never touched and stayed up throughout.

**Lesson.** Nine days of undeployed commits is what made one deploy dangerous.
Deploying more often makes each deploy smaller and safer.
