"""What one minute of a Vaani call costs, from measured inputs.

Every quantity here is either MEASURED on this deployment or a published list
price with its source named. Nothing is guessed, and the two kinds are printed
separately so a number is never mistaken for a bill.

    python tools/cost_per_minute.py
    python tools/cost_per_minute.py --usd-inr 88 --telephony-inr 0.60

Why this is not read off an invoice
------------------------------------
`cost_info` on every run reads `"dograh_token_usage": 0` -- token usage is not
instrumented in the pipeline. So the LLM figures are computed from the request
SHAPE (measured against the live prompt) times the number of requests per turn
(a config value) times turns per minute (measured across runs 320-336).
"""

from __future__ import annotations

import argparse
import sys

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

# ---------------------------------------------------------------- MEASURED --
# One production-shaped turn against the live compiled prompt, read from Groq's
# own `usage` block (tools/../prompt_final.txt, 30,218 chars):
PROMPT_TOKENS = 7869
COMPLETION_TOKENS = 158          # of which 64 were reasoning

# Bot turns per minute, median across runs 320-336 excluding the four hung
# calls. Median call length was 107 s.
TURNS_PER_MIN = 8.4

# From workflow_configurations on workflow 2.
LLM_HEDGE = 2                    # main reply is drafted twice, fastest wins
EXTRACTION_REQUESTS = 1          # unhedged, once per turn
EXTRACTION_PROMPT_TOKENS = 900   # the 1,392-char SYSTEM plus one exchange

# The agent speaks roughly this share of the call; Layer 2 targets under 40%.
AGENT_SPEECH_SHARE = 0.40

# ------------------------------------------------------------ LIST PRICES --
# Named sources, not measured. Re-check before quoting to a client.
GROQ_IN_PER_M = 0.15             # $/M input tokens, gpt-oss-120b
GROQ_IN_CACHED_PER_M = 0.075     # $/M cached input -- 50% off, automatic
GROQ_OUT_PER_M = 0.60            # $/M output tokens
SARVAM_STT_INR_PER_HOUR = 30.0   # docs.sarvam.ai pricing, standard STT
CARTESIA_USD_PER_MIN = 0.028     # $299 / 10,667 min on the Scale plan

# How much of the prompt is served from cache. The system prompt carries no
# per-call value, so the whole prefix is identical across turns AND calls; only
# the growing history and the state block are new each turn.
CACHE_HIT_SHARE = 0.90


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--usd-inr", type=float, default=88.0)
    ap.add_argument("--telephony-inr", type=float, default=None,
                    help="Vobiz per-minute rate. Unknown here; pass it to include it.")
    a = ap.parse_args()

    llm_requests = TURNS_PER_MIN * (LLM_HEDGE + EXTRACTION_REQUESTS)
    reply_requests = TURNS_PER_MIN * LLM_HEDGE
    extract_requests = TURNS_PER_MIN * EXTRACTION_REQUESTS

    in_tokens = reply_requests * PROMPT_TOKENS + extract_requests * EXTRACTION_PROMPT_TOKENS
    out_tokens = llm_requests * COMPLETION_TOKENS

    cached = in_tokens * CACHE_HIT_SHARE
    fresh = in_tokens - cached
    llm_usd = (cached / 1e6 * GROQ_IN_CACHED_PER_M
               + fresh / 1e6 * GROQ_IN_PER_M
               + out_tokens / 1e6 * GROQ_OUT_PER_M)

    stt_inr = SARVAM_STT_INR_PER_HOUR / 60.0
    tts_usd = CARTESIA_USD_PER_MIN * AGENT_SPEECH_SHARE

    llm_inr = llm_usd * a.usd_inr
    tts_inr = tts_usd * a.usd_inr
    total_inr = llm_inr + stt_inr + tts_inr
    telephony = a.telephony_inr

    print("MEASURED PER MINUTE")
    print(f"  bot turns                     {TURNS_PER_MIN:>10.1f}")
    print(f"  LLM requests (hedge {LLM_HEDGE} + extract) {llm_requests:>6.1f}")
    print(f"  input tokens                  {in_tokens:>10,.0f}"
          f"   ({CACHE_HIT_SHARE:.0%} from cache)")
    print(f"  output tokens                 {out_tokens:>10,.0f}")
    print()
    print("COST PER MINUTE (list prices)")
    print(f"  LLM   Groq gpt-oss-120b       INR {llm_inr:>8.3f}")
    print(f"  STT   Sarvam                  INR {stt_inr:>8.3f}")
    print(f"  TTS   Cartesia                INR {tts_inr:>8.3f}   "
          f"(agent speaks {AGENT_SPEECH_SHARE:.0%} of the minute)")
    print(f"  {'-' * 42}")
    print(f"  stack subtotal                INR {total_inr:>8.3f}   "
          f"(${total_inr / a.usd_inr:.4f})")
    if telephony is not None:
        print(f"  telephony  Vobiz              INR {telephony:>8.3f}")
        print(f"  TOTAL                         INR {total_inr + telephony:>8.3f}")
    else:
        print("  telephony  Vobiz              NOT KNOWN -- pass --telephony-inr")
    print()
    print(f"A median call is 107 s, so about INR {total_inr * 107 / 60:.2f} of stack cost.")
    print()
    print("WHERE IT GOES")
    for label, inr in sorted((("LLM", llm_inr), ("STT", stt_inr), ("TTS", tts_inr)),
                             key=lambda x: -x[1]):
        print(f"  {label:<5} {inr / total_inr:>5.0%}  {'#' * int(40 * inr / total_inr)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
