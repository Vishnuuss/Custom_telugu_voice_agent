"""Budget validation CLI.

    python -m vaani.check                 # validate the budget file
    python -m vaani.check --confidence    # how much of it is guesswork

Exits non-zero if the budget does not add up, so CI can gate on it.
"""
from __future__ import annotations

import argparse
import sys

from vaani.latency import BudgetInvalid, LatencyBudget


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="vaani.check")
    ap.add_argument("--confidence", action="store_true",
                    help="report how much of the budget is estimated")
    ap.add_argument("--file", default=None, help="path to latency_budget.yaml")
    args = ap.parse_args(argv)

    try:
        budget = LatencyBudget.load(args.file)
    except BudgetInvalid as e:
        print(f"BUDGET INVALID: {e}", file=sys.stderr)
        return 1

    print(f"Budget OK: {budget.allocated_ms:.0f}ms allocated of "
          f"{budget.target_p50_ms:.0f}ms target "
          f"({budget.headroom_ms:.0f}ms headroom)")

    if args.confidence:
        print()
        print(budget.confidence_report())

    if budget.headroom_ms < budget.target_p50_ms * 0.05:
        print(f"\nWARNING: headroom is {budget.headroom_ms:.0f}ms "
              f"({budget.headroom_ms / budget.target_p50_ms * 100:.1f}%). "
              f"A budget this tight fails if any component misses.",
              file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
