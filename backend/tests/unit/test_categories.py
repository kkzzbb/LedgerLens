"""The category list and `categorize` (#25)."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ledgerlens.api.app import create_app
from ledgerlens.domain.categories import CATEGORIES, CATEGORY_KEYS, categorize

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "demobank_seed42.json"


def test_the_list_holds_the_seven_categories_in_order() -> None:
    assert [(c.key, c.name, c.kind) for c in CATEGORIES] == [
        ("revenue", "Revenue", "revenue"),
        ("rent", "Rent", "expense"),
        ("software", "Software", "expense"),
        ("utilities", "Utilities", "expense"),
        ("inventory", "Inventory", "expense"),
        ("supplier_other", "Other suppliers", "expense"),
        ("other", "Other", "other"),
    ]
    assert [c.key for c in CATEGORIES] == list(CATEGORY_KEYS)


def test_get_categories_returns_the_list_without_a_database() -> None:
    # No settings and no database: the route must not open a session.
    response = TestClient(create_app()).get("/api/categories")

    assert response.status_code == 200
    assert response.json() == {
        "items": [{"key": c.key, "name": c.name, "kind": c.kind} for c in CATEGORIES]
    }


@pytest.mark.parametrize(
    ("direction", "name", "description", "expected"),
    [
        ("credit", "Acme", "Customer payment INV-1", "revenue"),
        ("debit", "Acme", "Inventory purchase BILL-1", "inventory"),
        ("debit", "Acme Properties", None, "rent"),
        ("debit", None, "Software subscription 2026-05", "software"),
        ("debit", "Acme", "Utility bill 2026-05", "utilities"),
        ("debit", "Acme", "Service fee 2026-05", "supplier_other"),
    ],
)
def test_each_rule(
    direction: str, name: str | None, description: str | None, expected: str
) -> None:
    assert categorize(direction, name, description) == expected


def test_the_first_matching_rule_wins() -> None:
    # Rule 2 (`wholesale`) and rule 6 (`cleaning`) both match.
    assert categorize("debit", "Cleaning Wholesale", None) == "inventory"


@pytest.mark.parametrize("direction", ["debit", "credit"])
def test_unknown_text_falls_back_to_other(direction: str) -> None:
    assert categorize(direction, "Unknown Ltd", "Something else") == "other"


def test_the_direction_guards_each_rule() -> None:
    assert categorize("credit", None, "Shop rent") == "other"
    assert categorize("debit", None, "Customer payment") == "other"


def test_case_and_whitespace_are_ignored() -> None:
    assert categorize("debit", None, "  SHOP   RENT 2026-05") == "rent"
    assert categorize("debit", "Shop\t\nrent", None) == "rent"


def test_none_fields_count_as_empty() -> None:
    assert categorize("debit", None, None) == "other"
    assert categorize("credit", None, "Customer payment") == "revenue"


def test_demobank_rows_get_their_counterparty_category() -> None:
    r"""Every row of DemoBank's `generate(42, date(2026, 11, 12))`, planted debits included.

    Regenerate from `demobank/` (one-off; the backend never imports DemoBank):

        uv run python -c 'import json; from datetime import date; \
from demobank.generator import COUNTERPARTIES, generate; \
c = {p.name: p.category for p in COUNTERPARTIES}; \
rows = [{"transaction_id": t.transaction_id, "booking_date": t.booking_date.isoformat(), \
"amount": str(t.amount), "direction": t.direction, "counterparty_name": t.counterparty_name, \
"description": t.description, "category": c[t.counterparty_name]} \
for t in generate(42, date(2026, 11, 12)).transactions]; \
print("[\n" + ",\n".join(json.dumps(r) for r in rows) + "\n]")' \
> ../backend/tests/fixtures/demobank_seed42.json
    """
    rows: list[dict[str, str]] = json.loads(FIXTURE.read_text(encoding="utf-8"))

    wrong = [
        row
        for row in rows
        if categorize(row["direction"], row["counterparty_name"], row["description"])
        != row["category"]
    ]
    assert wrong == []
    assert {row["category"] for row in rows} >= set(CATEGORY_KEYS) - {"other"}
