"""The anomaly rule keys (pure).

Every flag a rule writes is a potential issue for a person to review
(`docs/accounting-rules.md`, Anomaly rules). The `anomaly_flag.rule` check
constraint, the API filters and the rules themselves use these keys.
"""

from typing import Final, Literal, get_args

RuleKey = Literal["possible_duplicate", "large_expense"]

RULE_KEYS: Final[tuple[RuleKey, ...]] = get_args(RuleKey)
