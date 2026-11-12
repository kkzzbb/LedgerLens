"""The fixed category list and the rules that categorize a bank transaction (pure).

`categorize` checks `RULES` in order and returns the first match, or `other`.
A rule matches when the transaction has the rule's direction and its
counterparty name or description contains one of the rule's keywords,
case-insensitively, after runs of whitespace are collapsed to one space.

A credit can only be `revenue` or `other`; a debit can be any category except
`revenue` (`docs/accounting-rules.md`, Categories). The rules are code; there
are no manual corrections.
"""

from dataclasses import dataclass
from typing import Final, Literal, get_args

CategoryKey = Literal[
    "revenue", "rent", "software", "utilities", "inventory", "supplier_other", "other"
]
Kind = Literal["revenue", "expense", "other"]


@dataclass(frozen=True)
class Category:
    key: CategoryKey
    name: str
    kind: Kind


CATEGORIES: Final = (
    Category("revenue", "Revenue", "revenue"),
    Category("rent", "Rent", "expense"),
    Category("software", "Software", "expense"),
    Category("utilities", "Utilities", "expense"),
    Category("inventory", "Inventory", "expense"),
    Category("supplier_other", "Other suppliers", "expense"),
    Category("other", "Other", "other"),
)

CATEGORY_KEYS: Final[tuple[CategoryKey, ...]] = get_args(CategoryKey)
OTHER: Final[CategoryKey] = "other"


@dataclass(frozen=True)
class Rule:
    direction: str
    keywords: tuple[str, ...]
    category: CategoryKey


RULES: Final = (
    Rule("credit", ("customer payment",), "revenue"),
    Rule("debit", ("inventory purchase", "wholesale", "trading", "supplies"), "inventory"),
    Rule("debit", ("shop rent", "properties"), "rent"),
    Rule("debit", ("software subscription",), "software"),
    Rule("debit", ("utility bill", "energy", "water"), "utilities"),
    Rule("debit", ("service fee", "deep clean", "cleaning", "bookkeeping"), "supplier_other"),
)


def _normalize(text: str | None) -> str:
    return " ".join((text or "").split()).casefold()


def categorize(
    direction: str, counterparty_name: str | None, description: str | None
) -> CategoryKey:
    """The category key of the first matching rule in `RULES`, or `other`."""
    texts = (_normalize(counterparty_name), _normalize(description))
    for rule in RULES:
        if rule.direction == direction and any(
            keyword in text for keyword in rule.keywords for text in texts
        ):
            return rule.category
    return OTHER
