"""The shared validation and business-rule engine.

Built generically from the outset because two later steps plug into it: Sales in Step 5 and FA in
Step 6 each register their own evaluators against the same registry, under the same rule
identifiers, and neither has to restructure anything here to do it.
"""

from app.services.rules.catalog import ALL_RULE_IDS, RULE_BY_ID, RULE_CATALOG, CheckKey, RuleId
from app.services.rules.engine import (
    current_results,
    latest_evaluations,
    outstanding,
    run_validation,
)
from app.services.rules.registry import (
    RuleContext,
    RuleOutcome,
    registered_rules,
)

__all__ = [
    "ALL_RULE_IDS",
    "RULE_BY_ID",
    "RULE_CATALOG",
    "CheckKey",
    "RuleContext",
    "RuleId",
    "RuleOutcome",
    "current_results",
    "latest_evaluations",
    "outstanding",
    "registered_rules",
    "run_validation",
]
