"""Project Vaani — voice agent framework with an enforced latency budget.

The 800ms server-side turn latency target is not a goal in a document. It is
loaded from latency_budget.yaml, enforced on every turn by vaani.latency, and
validated in CI. See AGENTS.md before writing any code in this package.
"""

from vaani.latency import (
    BudgetExceeded,
    BudgetInvalid,
    ComponentBudget,
    LatencyBudget,
    Span,
    TurnBudget,
    budgeted,
)

__all__ = [
    "BudgetExceeded",
    "BudgetInvalid",
    "ComponentBudget",
    "LatencyBudget",
    "Span",
    "TurnBudget",
    "budgeted",
]
