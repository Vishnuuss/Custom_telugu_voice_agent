"""The gate. Every defect ever seen on a real Vaani call, as a test that costs nothing.

Runs over Dograh **text chat**, so no phone rings, nobody is billed, and it does
not need Vishnu to answer. The runner shape is lifted from `solar_train.py`,
which already proved the text-chat session API works for this; what is new is
what it checks.

Why it exists
-------------
Every rule the agent is held to lived only in prose, and prose is not enforcement.
Run 12 spoke a 272-character blob containing the caller's invented line, the
model's own internal note and the literal control token `MODE: CLOSE`. Runs 3 and
4 show the same class of defect weeks earlier. Nobody knew, because nothing looked.

The rules here are the ones the agent has actually broken, each anchored to the
run that broke it. A case that trips a hard rule FAILS even if it reads perfectly.

    python tools/vaani_eval.py                  # everything
    python tools/vaani_eval.py --only F1 O3     # one or two cases
    python tools/vaani_eval.py --json out.json  # for the regression gate

Exit code is non-zero if any hard rule failed, so CI can block a deploy on it.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

env: dict[str, str] = {}
for line in Path(".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")

BASE = env.get("VAANI_SERVER_API_URL", "https://vaani.bswealthfinance.com").rstrip("/")
KEY = env["VAANI_SERVER_API_KEY"]

# --- hard rules: things that must never reach a caller ----------------------
# Each is anchored to the run where it actually happened.

CONTROL_TOKEN = re.compile(r"MODE\s*:", re.IGNORECASE)          # run 12 turn 4
ROLE_LABEL = re.compile(
    r"(CUSTOMER|CALLER|USER|AGENT|ASSISTANT|BOT|WRONG|RIGHT)\s*:", re.IGNORECASE)
SELF_TALK = re.compile(                                          # run 4 turn 7
    r"\b(we have (all )?(info|name)|not yet|need agreement|ask assessment"
    r"|my name is)\b", re.IGNORECASE)
MARKDOWN = re.compile(r"\*\*|^#{1,6}\s|^\s*[-*]\s", re.MULTILINE)
PLACEHOLDER = re.compile(r"\{(agent_name|business|topic|success_definition)\}")
ENGLISH_FILLER = re.compile(r"\bour service\b", re.IGNORECASE)   # unset `topic`

MAX_REPLY_CHARS = 200        # run 12 turn 4 was 272
MAX_QUESTIONS_PER_TURN = 1   # core.md:44 "Not two questions."
MIN_REPLY_CHARS = 4          # run 12 turn 6 was 'మీ'


def hard_rules(reply: str) -> list[str]:
    """Violations that fail the case outright, whatever else it did well."""
    bad = []
    if CONTROL_TOKEN.search(reply):
        bad.append("control token spoken")
    if ROLE_LABEL.search(reply):
        bad.append("invented a speaker turn")
    if SELF_TALK.search(reply):
        bad.append("spoke its own internal note")
    if MARKDOWN.search(reply):
        bad.append("markdown in speech")
    if PLACEHOLDER.search(reply):
        bad.append("unsubstituted template placeholder")
    if ENGLISH_FILLER.search(reply):
        bad.append("English filler in a Telugu line")
    if len(reply) > MAX_REPLY_CHARS:
        bad.append(f"blob ({len(reply)} chars)")
    if 0 < len(reply.strip()) < MIN_REPLY_CHARS:
        bad.append(f"truncated ({reply.strip()!r})")
    if reply.count("?") > MAX_QUESTIONS_PER_TURN:
        bad.append(f"{reply.count('?')} questions in one turn")
    return bad


# --- cases ------------------------------------------------------------------
# F* reproduce a defect seen on a real call. O* exercise one objection playbook
# each (layers/02_psychology/core.md:152-258). Q* are ordinary qualification.

CASES: list[dict] = [
    # ---- format defects, from real runs ----
    {"id": "F1", "name": "run 12: long multi-part answer must not become a script",
     "turns": ["హలో", "5000", "హైదరాబాద్", "సొంత ఇల్లు, రూఫ్ ఉంది, నా పేరు రాణి"]},
    {"id": "F2", "name": "run 4: giving a name must not trigger self-talk",
     "turns": ["చెప్పండి", "నా పేరు రాణి"]},
    {"id": "F3", "name": "run 12: frustration must get a real reply, not two characters",
     "turns": ["హలో", "ఇంత లేట్ అయి నుంచి కూడా అసలు ఏంది అదంతా"],
     "min_last_reply": 15},
    {"id": "F4", "name": "run 1/3/12: 'what do you do' must not recite the brochure",
     "turns": ["ఏం చేస్తారండి మీరు?"],
     "forbid": [r"aggregator", r"అగ్రిగేటర్"]},
    {"id": "F5", "name": "greeting must be one language",
     "turns": ["హలో"]},

    # ---- objection playbooks ----
    {"id": "O1", "name": "busy - take the exit, offer a specific time",
     "turns": ["ఇప్పుడు కుదరదు"], "expect_any": ["రేపు", "సాయంత్రం", "పొద్దున", "గంట"]},
    {"id": "O2", "name": "whatsapp - agree, and attach one question",
     "turns": ["వాట్సప్ చేయండి"], "expect_any": ["పంపిస్తాను", "పంపుతాను", "సరే"],
     "want_question": True},
    {"id": "O3", "name": "not interested - exactly one gentle probe",
     "turns": ["నాకు ఆసక్తి లేదు"], "must_not_end_before": 1},
    {"id": "O4", "name": "expensive - reframe, never invent a price",
     "turns": ["చాలా ఖరీదు కదా"], "forbid": [r"\d{4,}", "లక్ష"]},
    {"id": "O5", "name": "ask my husband - support it, propose a time",
     "turns": ["మా ఆయనని అడగాలి"], "must_not_end_before": 1},
    {"id": "O6", "name": "how did you get my number - answer straight",
     "turns": ["నా నంబర్ మీకు ఎలా వచ్చింది?"], "must_not_end_before": 1},
    {"id": "O7", "name": "anger - apologise once, offer the exit",
     "turns": ["ఎందుకు ఇలా విసిగిస్తున్నారు!"],
     "expect_any": ["క్షమించండి", "మన్నించండి", "సారీ"]},
    {"id": "O8", "name": "a child answered - stop selling entirely",
     "turns": ["అమ్మ ఇంట్లో లేరు, నేను చిన్న పిల్లని"],
     "forbid": ["సోలార్ పెట్ట", "బిల్లు ఎంత"]},
    {"id": "O9", "name": "are you a robot - admit it and carry on",
     "turns": ["మీరు రోబోటా?"], "must_not_end_before": 1},
    {"id": "O10", "name": "second refusal ends the call, no third probe",
     "turns": ["ఆసక్తి లేదు", "వద్దు అన్నాను కదా"]},

    # ---- ordinary qualification ----
    {"id": "Q1", "name": "happy path - one question at a time",
     "turns": ["చెప్పండి", "2000", "అనంతపూర్", "సొంత ఇల్లు", "ఉంది", "సరే"]},
    {"id": "Q2", "name": "a direct question is answered, not deferred",
     "turns": ["ఎంత ఖర్చు అవుతుంది?"],
     "forbid": ["తర్వాత మాట్లాడ", "రేపు కాల్ చేస్తాను"]},
    {"id": "Q3", "name": "buying signal outranks the checklist",
     "turns": ["ఒకసారి వచ్చి చూడండి"],
     "expect_any": ["రేపు", "ఎప్పుడు", "సమయం", "గంట"]},

    # ---- reference parity: what the client's own reference call does --------
    # Measured from Downloads/AISORIGIN_VIDEO/apgovt.mpeg. The reference is no
    # faster than us (1.38s vs our 1.27s); it is better at these.
    {"id": "R1", "name": "reference: acknowledges the answer before asking next",
     "turns": ["చెప్పండి", "రెండు వేలు వస్తుంది", "అనంతపూర్"],
     "want_acknowledgement": True},
    {"id": "R2", "name": "reference: names the options on a categorical question",
     "turns": ["చెప్పండి", "2000", "అనంతపూర్"],
     "want_options": True},
    {"id": "R3", "name": "reference: repairs a mishearing instead of repeating",
     "turns": ["చెప్పండి", "ఏంది", "అర్థం కాలేదండి", "ఏంటి అది"],
     "want_repair": True},
    {"id": "R4", "name": "run 96: an unclear caller must not get the same line 4 times",
     "turns": ["హలో", "ఏంది?", "అర్థం కాదండి.", "ఓకే సార్.", "చెప్పండి కదండీ.",
               "హలో.", "అర్థమవుతుందా మీకు?"]},
    {"id": "R5", "name": "out of scope: subsidy question is ANSWERED, not deflected",
     "turns": ["ఇండస్ట్రీస్ కి సబ్సిడీ ఉందా?"],
     "expect_any": ["సబ్సిడీ", "ప్రభుత్వ", "అర్హత", "వెండర్"],
     "must_not_end_before": 1},
    {"id": "R6", "name": "out of scope: 'what warranty do I get' is answered",
     "turns": ["వారంటీ ఎంత ఇస్తారు?"],
     "expect_any": ["వెండర్", "కోట్", "ప్యానెల్", "ఇన్వర్టర్"],
     "must_not_end_before": 1},
    {"id": "R7", "name": "caller demands details before answering anything",
     "turns": ["ముందు నాకు డీటెయిల్స్ చెప్పండి మొత్తం"],
     "forbid": ["ముందు ఒక్క విషయం చెప్ప"],
     "must_not_end_before": 1},
]


# Coolify reports an app "running:healthy" before its workers can serve a
# session, so an eval fired straight after a deploy gets `503: no available
# server` on every case -- 17 of 18 on the first attempt. That is a false
# failure, and a gate that cries wolf gets ignored, which is worse than no gate.
RETRY_STATUSES = {502, 503, 504}
RETRIES = 6
RETRY_WAIT_S = 10


def req(method: str, path: str, body=None, timeout=90):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"X-API-Key": KEY}
    if data:
        headers["Content-Type"] = "application/json"
    last = (0, "no attempt")
    for attempt in range(RETRIES):
        r = urllib.request.Request(f"{BASE}{path}", data=data, headers=headers,
                                   method=method)
        try:
            with urllib.request.urlopen(r, timeout=timeout) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            last = (e.code, e.read().decode("utf-8", "replace"))
            if e.code not in RETRY_STATUSES:
                return last
        except urllib.error.URLError as e:
            last = (0, repr(e.reason))
        if attempt < RETRIES - 1:
            time.sleep(RETRY_WAIT_S)
    return last


def wait_until_ready(wid: int) -> bool:
    """Open and discard one session, so a cold worker pool is never scored."""
    print("  waiting for a worker...", end="", flush=True)
    st, _ = req("POST", f"/api/v1/workflow/{wid}/text-chat/sessions", {})
    print(" ready" if st < 400 else f" NOT READY (HTTP {st})")
    return st < 400


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def assistant_texts(payload: dict) -> list[str]:
    """Spoken replies in order.

    They live in `session_data.turns[].assistant_message.text`;
    `session_data.messages` exists but is always empty, which once made an
    earlier battery report "NO REPLY" on every case.
    """
    out = []
    for t in (payload.get("session_data") or {}).get("turns") or []:
        am = t.get("assistant_message") or {}
        if am.get("text"):
            out.append(norm(str(am["text"])))
    return out


def run_case(wid: int, case: dict) -> dict:
    st, s = req("POST", f"/api/v1/workflow/{wid}/text-chat/sessions", {})
    if not isinstance(s, dict):
        return {"error": f"session create HTTP {st}: {str(s)[:200]}"}
    rid = s.get("workflow_run_id") or s.get("id")

    replies = assistant_texts(s)
    lats, ended_at, r = [], None, s
    for i, turn in enumerate(case["turns"], start=1):
        t0 = time.time()
        st, r = req("POST",
                    f"/api/v1/workflow/{wid}/text-chat/sessions/{rid}/messages",
                    {"text": turn})
        if not isinstance(r, dict):
            return {"error": f"turn {i} HTTP {st}: {str(r)[:200]}", "replies": replies}
        lats.append(time.time() - t0)
        replies = assistant_texts(r)
        if r.get("is_completed") and ended_at is None:
            ended_at = i
            break
    return {"run_id": rid, "replies": replies, "lats": lats, "ended_at": ended_at}



# --- conversation quality, measured against the reference call ---------------
# The battery scored 18/18 while run 96 asked the same question four times and
# the caller said "you told me nothing". Everything below exists because the
# reference agent (Downloads/AISORIGIN_VIDEO/apgovt.mpeg) does it and ours does
# not. Measured on that file: it responds in 1.38s p50 against our 1.27s, so the
# gap the client is reacting to is entirely in these behaviours, not in speed.

# "చాలా సంతోషమండి" / "మంచి ఆలోచన" / "మంచిది" / "సరేనండి" / "అర్థమైంది".
ACKNOWLEDGEMENT = re.compile(
    r"(సరే|మంచి|అర్థ‌మైంది|అర్థమైంది|సంతోష|ధన్యవాద|కరెక్ట్|ఓకే|"
    r"అలాగే|తప్పకుండా|క్షమించండి|మన్నించండి|సారీ)", re.IGNORECASE)

# The reference names the choices: "ఇల్లా లేకా ఆఫీసా", "కాంక్రీట్ రూఫా లేకా మెటల్ షీటా".
OFFERS_OPTIONS = re.compile(r"(లేదా|లేకా|లేక)\s")

# What it says instead of repeating itself verbatim.
REPAIR = re.compile(r"(వినిపించ|మళ్ళీ చెప్|మళ్లీ చెప్|అర్థం కాలేదు|"
                    r"సరిగ్గా విన)", re.IGNORECASE)


def _normalise_reply(text: str) -> str:
    """For comparing two replies, ignoring punctuation and spacing."""
    return re.sub(r"[^\wఀ-౿]+", " ", (text or "").lower()).strip()


def repeated_replies(replies: list[str]) -> list[str]:
    """Sentences the agent said more than once.

    Run 96 asked "సార్, మీ నెలవారీ బిల్లు ఎంత రూపాయలుగా వస్తుంది?" three times
    and "సైట్ అసెస్‌మెంట్ ఏర్పాటు చేసుకోవాలనుకుంటున్నారా?" four times, word for
    word. Layer 1 says "Never say the same sentence twice in a call"; nothing
    enforced it. The reference never repeats -- it uses a repair line instead.
    """
    seen, dupes = {}, []
    for r in replies:
        # The opening acknowledgement is supposed to recur -- the reference
        # agent opens nearly every turn with one -- so only what follows it
        # decides whether this is the same reply twice.
        key = _normalise_reply(re.sub(
            r"^\W*(సరే\w*|మంచిది|అర్థమైంది|అర్ధమైంది|అలాగే\w*|కరెక్టే?|ఓకే|"
            r"తప్పకుండా|చాలా\s*సంతోషమండి)[\s,.]*(సార్|అండి|మేడమ్)?[\s,.]*",
            "", r.strip(), count=1))
        if len(key) < 12:
            continue          # an acknowledgement on its own is not a repeat
        if key in seen:
            dupes.append(r)
        seen[key] = True
    return dupes


def check(case: dict, res: dict) -> tuple[list[str], list[str]]:
    """Return (hard failures, soft notes)."""
    hard, soft = [], []
    replies = res.get("replies") or []
    if res.get("error"):
        return [res["error"]], []
    if not replies:
        return ["no reply at all"], []

    for n, reply in enumerate(replies, 1):
        for v in hard_rules(reply):
            hard.append(f"turn {n}: {v}")

    # Saying the same sentence twice is the defect the client named first.
    for dup in repeated_replies(replies):
        hard.append(f"repeated verbatim: {dup[:70]!r}")

    if case.get("want_acknowledgement"):
        # The reference acknowledges before it asks. Checked on the reply to the
        # caller's first real answer, not on the greeting.
        target = replies[1] if len(replies) > 1 else replies[0]
        if not ACKNOWLEDGEMENT.search(target):
            soft.append(f"no acknowledgement before the next question: "
                        f"{target[:60]!r}")

    if case.get("want_options"):
        if not any(OFFERS_OPTIONS.search(r) for r in replies):
            soft.append("categorical question asked without naming the options")

    if case.get("want_repair"):
        if not any(REPAIR.search(r) for r in replies):
            soft.append("mishearing handled by repeating, not by a repair line")

    joined = " ".join(replies)
    last = replies[-1]

    for pat in case.get("forbid", []):
        if re.search(pat, joined, re.IGNORECASE):
            hard.append(f"said a forbidden thing: {pat}")

    want = case.get("expect_any")
    if want and not any(w.lower() in joined.lower() for w in want):
        soft.append(f"expected one of {want}")

    if case.get("want_question") and "?" not in last:
        soft.append("agreed but asked nothing back")

    floor = case.get("min_last_reply")
    if floor and len(last) < floor:
        hard.append(f"last reply only {len(last)} chars: {last!r}")

    early = case.get("must_not_end_before")
    if early is not None and res.get("ended_at") is not None:
        if res["ended_at"] <= early:
            hard.append(f"ended at turn {res['ended_at']}, too early")
    return hard, soft


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workflow", type=int, default=2)
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--json")
    ap.add_argument("--gate", metavar="BASELINE.json",
                    help="fail if any case that passed in BASELINE now fails")
    ap.add_argument("--save-baseline", metavar="OUT.json",
                    help="record this run as the new known-good baseline")
    a = ap.parse_args()

    cases = [c for c in CASES if not a.only or c["id"] in a.only]
    print(f"{BASE}  workflow {a.workflow}  -- {len(cases)} case(s)")
    if not wait_until_ready(a.workflow):
        print("the server never became ready; scoring now "
              "would be meaningless")
        return 2
    print()

    results, hard_total, soft_total, all_lats = [], 0, 0, []
    for case in cases:
        res = run_case(a.workflow, case)
        hard, soft = check(case, res)
        hard_total += len(hard)
        soft_total += len(soft)
        all_lats += res.get("lats") or []
        status = "FAIL" if hard else ("warn" if soft else "pass")
        print(f"  [{status:>4}] {case['id']:<4} {case['name']}")
        for h in hard:
            print(f"           HARD  {h}")
        for s_ in soft:
            print(f"           warn  {s_}")
        if hard and res.get("replies"):
            print(f"           last: {res['replies'][-1][:110]!r}")
        results.append({"case": case["id"], "name": case["name"],
                        "hard": hard, "soft": soft,
                        "replies": res.get("replies"), "lats": res.get("lats")})

    print(f"\n{'='*66}")
    passed = sum(1 for r in results if not r["hard"])
    print(f"  {passed}/{len(results)} cases with no hard failure")
    print(f"  {hard_total} hard violation(s), {soft_total} warning(s)")
    if all_lats:
        print(f"  reply latency p50 {statistics.median(all_lats):.2f}s "
              f"max {max(all_lats):.2f}s  (text chat -- no telephony)")

    if a.json:
        Path(a.json).write_text(
            json.dumps({"passed": passed, "total": len(results),
                        "hard": hard_total, "soft": soft_total,
                        "results": results}, ensure_ascii=False, indent=1),
            encoding="utf-8")
        print(f"  wrote {a.json}")

    # A drop is worse than a low absolute score. A run can be imperfect for
    # known reasons and still be shippable; a case that USED to pass and now
    # fails is a regression, and that is what must stop a deploy.
    regressed = []
    if a.gate:
        base = json.loads(Path(a.gate).read_text(encoding="utf-8"))
        was_ok = {r["case"] for r in base.get("results", []) if not r["hard"]}
        now_bad = {r["case"] for r in results if r["hard"]}
        regressed = sorted(was_ok & now_bad)
        print("")
        print(f"  gate: baseline {a.gate}  "
              f"({len(was_ok)} case(s) passing then)")
        if regressed:
            print(f"  REGRESSED: {', '.join(regressed)}")
            for cid in regressed:
                for r in results:
                    if r["case"] == cid:
                        for h in r["hard"]:
                            print(f"    {cid}: {h}")
        else:
            print("  no case that passed before is failing now")

    if a.save_baseline:
        Path(a.save_baseline).write_text(
            json.dumps({"results": [{"case": r["case"], "hard": r["hard"]}
                                    for r in results]}, indent=1),
            encoding="utf-8")
        print(f"  baseline written to {a.save_baseline}")

    # Non-zero exit blocks a deploy.
    if a.gate:
        return 1 if regressed else 0
    return 1 if hard_total else 0


if __name__ == "__main__":
    raise SystemExit(main())
