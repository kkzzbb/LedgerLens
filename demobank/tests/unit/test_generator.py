"""The deterministic historical data generator (#9): records and structure.

The balance and anomaly invariants are in `test_generator_invariants.py`.
"""

import ast
import dataclasses
import hashlib
import json
import re
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from demobank import generator
from demobank.generator import (
    ANCHORED_RECEIPTS,
    COUNTERPARTIES,
    CUSTOMERS,
    Dataset,
    Transaction,
    generate,
    history_start,
    schedule,
)

GENERATOR_SOURCE = Path(generator.__file__).read_text(encoding="utf-8")

# SHA-256 of `canonical_serialisation(generate(42, date(2026, 6, 30)))`.
# Update it on purpose only, when the data is meant to change. Then update the
# hash in `demobank/README.md` and the data of LedgerLens' demo seed (#44) with it.
GOLDEN_SHA256 = "409debe08911b327eddd03927a4774b003cb5ec6d95cca7798c427fe123ec2af"

SEEDS = [0, 42, 1234]
ANCHORS = [date(2026, 6, 30), date(2024, 2, 29), date(2026, 12, 31), date(2027, 1, 1)]
MATRIX = [(seed, anchor) for seed in SEEDS for anchor in ANCHORS]
MATRIX_IDS = [f"{seed}-{anchor}" for seed, anchor in MATRIX]

IBAN_SHAPE = re.compile(r"[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}")
INVOICE = re.compile(r"INV-(\d{4})")
BILL = re.compile(r"BILL-(\d{4})")

TRANSACTION_FIELDS = [
    "transaction_id",
    "account_id",
    "booking_date",
    "value_date",
    "amount",
    "currency",
    "direction",
    "counterparty_name",
    "counterparty_reference",
    "description",
    "status",
]


def canonical_serialisation(dataset: Dataset) -> bytes:
    """Every field of every record, in order, as strings (amounts too), as JSON."""

    def record(item: object) -> list[list[str]]:
        assert dataclasses.is_dataclass(item)
        return [[field.name, str(getattr(item, field.name))] for field in dataclasses.fields(item)]

    payload = {
        "account": record(dataset.account),
        "transactions": [record(t) for t in dataset.transactions],
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def looks_like_iban(value: str) -> bool:
    return IBAN_SHAPE.search(value.replace(" ", "")) is not None


def ordinary_receipts(dataset: Dataset) -> list[Transaction]:
    return [
        t
        for t in dataset.transactions
        if t.direction == "credit"
        and (match := INVOICE.search(t.description)) is not None
        and int(match.group(1)) < 9001
    ]


def anchored_receipts(dataset: Dataset) -> list[Transaction]:
    ordinary = set(ordinary_receipts(dataset))
    return [t for t in dataset.transactions if t.direction == "credit" and t not in ordinary]


# Determinism


def test_same_seed_and_anchor_give_equal_datasets() -> None:
    assert generate(42, date(2026, 6, 30)) == generate(42, date(2026, 6, 30))


def test_golden_hash() -> None:
    digest = hashlib.sha256(canonical_serialisation(generate(42, date(2026, 6, 30))))

    assert digest.hexdigest() == GOLDEN_SHA256


def test_another_seed_gives_other_amounts() -> None:
    first = [t.amount for t in generate(42, date(2026, 6, 30)).transactions]
    second = [t.amount for t in generate(43, date(2026, 6, 30)).transactions]

    assert first != second


def test_the_schedule_does_not_depend_on_the_seed() -> None:
    anchor = date(2026, 6, 30)
    for seed in (0, 1, 42):
        dataset = generate(seed, anchor)
        assert [(t.booking_date, t.direction) for t in dataset.transactions] == [
            (slot.booking_date, slot.direction) for slot in schedule(anchor)
        ]


def test_amounts_are_drawn_with_randint_in_schedule_order() -> None:
    import random

    anchor = date(2026, 6, 30)
    rng = random.Random(7)
    expected = []
    for slot in schedule(anchor):
        if len(slot.counterparties) > 1:
            rng.choice(slot.counterparties)
        expected.append(Decimal(rng.randint(slot.min_cents, slot.max_cents)).scaleb(-2))

    assert [t.amount for t in generate(7, anchor).transactions] == expected


# The module is pure


def imported_modules(source: str) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            found.add(node.module)
    return found


def test_generator_imports_only_the_standard_library_it_needs() -> None:
    assert imported_modules(GENERATOR_SOURCE) == {
        "dataclasses",
        "datetime",
        "decimal",
        "random",
        "typing",
    }


def test_generator_uses_no_module_level_random_function() -> None:
    uses = {
        node.attr
        for node in ast.walk(ast.parse(GENERATOR_SOURCE))
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "random"
    }

    assert uses == {"Random"}
    calls = [
        node
        for node in ast.walk(ast.parse(GENERATOR_SOURCE))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "Random"
    ]
    assert len(calls) == 1


@pytest.mark.parametrize(
    "forbidden",
    [
        "float(",
        "uniform",
        "random.random",
        "hash(",
        "today(",
        "now(",
        "import time",
        "environ",
        "open(",
        "sqlalchemy",
        "demobank.config",
    ],
)
def test_generator_source_does_not_mention(forbidden: str) -> None:
    assert forbidden not in GENERATOR_SOURCE


def test_generator_uses_no_set_hash_or_float() -> None:
    tree = ast.parse(GENERATOR_SOURCE)
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}

    assert not any(isinstance(node, ast.Set | ast.SetComp) for node in ast.walk(tree))
    assert names.isdisjoint({"set", "frozenset", "hash", "float"})


# Account


def test_account() -> None:
    account = generate(42, date(2026, 6, 30)).account

    assert account.account_id == "acc_operating_001"
    assert account.display_name == "Demo Retail Ltd — Operating"
    assert account.currency == "EUR"
    assert account.opening_balance == Decimal("25000.00")
    assert str(account.opening_balance) == "25000.00"


def test_records_are_frozen() -> None:
    dataset = generate(42, date(2026, 6, 30))

    with pytest.raises(dataclasses.FrozenInstanceError):
        dataset.account.currency = "USD"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        dataset.transactions[0].amount = Decimal("1.00")  # type: ignore[misc]


# Range and fields


@pytest.mark.parametrize(("seed", "anchor"), MATRIX, ids=MATRIX_IDS)
def test_history_covers_183_days(seed: int, anchor: date) -> None:
    dates = [t.booking_date for t in generate(seed, anchor).transactions]
    start = anchor - timedelta(days=182)

    assert history_start(anchor) == start
    assert all(start <= day <= anchor for day in dates)
    assert any(day <= start + timedelta(days=6) for day in dates)
    assert any(day >= anchor - timedelta(days=6) for day in dates)


def test_transaction_fields() -> None:
    assert [field.name for field in dataclasses.fields(Transaction)] == TRANSACTION_FIELDS
    for t in generate(42, date(2026, 6, 30)).transactions:
        assert t.account_id == "acc_operating_001"
        assert t.value_date == t.booking_date
        assert t.counterparty_name
        assert t.counterparty_reference
        assert t.description


@pytest.mark.parametrize(("seed", "anchor"), MATRIX, ids=MATRIX_IDS)
def test_transaction_ids_follow_booking_order(seed: int, anchor: date) -> None:
    transactions = generate(seed, anchor).transactions
    ids = [t.transaction_id for t in transactions]

    assert ids == [f"txn_{n:06d}" for n in range(1, len(ids) + 1)]
    by_id = sorted(transactions, key=lambda t: t.transaction_id)
    by_date = sorted(transactions, key=lambda t: (t.booking_date, t.transaction_id))
    assert by_id == by_date


# Record invariants


@pytest.mark.parametrize(("seed", "anchor"), MATRIX, ids=MATRIX_IDS)
def test_record_invariants(seed: int, anchor: date) -> None:
    transactions = generate(seed, anchor).transactions
    names = {counterparty.name for counterparty in COUNTERPARTIES}

    for t in transactions:
        assert t.currency == "EUR"
        assert t.status == "booked"
        assert t.direction in ("debit", "credit")
        assert isinstance(t.amount, Decimal)
        assert Decimal("0") < t.amount <= Decimal("999999999999.99")
        assert t.amount.as_tuple().exponent == -2
        assert t.counterparty_name in names
        for value in (
            t.transaction_id,
            t.account_id,
            t.counterparty_name,
            t.counterparty_reference,
            t.description,
        ):
            assert not looks_like_iban(value), value
    assert len({t.transaction_id for t in transactions}) == len(transactions)


@pytest.mark.parametrize("iban", ["DE89370400440532013000", "GB82 WEST 1234 5698 7654 32"])
def test_iban_checker_catches_an_iban(iban: str) -> None:
    assert looks_like_iban(iban)
    assert looks_like_iban(f"Payment to {iban} thanks")


@pytest.mark.parametrize("value", ["Customer payment INV-1001", "DEMO-CP-0001", "txn_000001"])
def test_iban_checker_lets_the_generated_shapes_through(value: str) -> None:
    assert not looks_like_iban(value)


def test_amounts_are_built_from_integer_cents() -> None:
    assert str(generator.cents_to_amount(123450)) == "1234.50"
    assert str(generator.cents_to_amount(100)) == "1.00"
    assert str(generator.cents_to_amount(7)) == "0.07"


# Patterns


EXPECTED_MONTHLY = {
    # counterparty: (category, days, min, max), as in the issue's table
    "Halvenmoor Properties": ("rent", {1}, "2800.00", "2800.00"),
    "Ledgerkite Cloud": ("software", {5}, "89.00", "89.00"),
    "Pixelquarry Design Suite": ("software", {12}, "129.00", "129.00"),
    "Tallowfield Till Systems": ("software", {20}, "189.00", "189.00"),
    "Wattmere Energy": ("utilities", {8}, "300.00", "340.00"),
    "Rillbourne Water": ("utilities", {22}, "120.00", "140.00"),
    "Sparkvale Cleaning": ("supplier_other", {15}, "240.00", "240.00"),
    "Tallyhook Bookkeeping": ("supplier_other", {25}, "380.00", "380.00"),
    "Orchardine Wholesale": ("inventory", {3, 13, 23}, "1700.00", "2400.00"),
    "Brimcastle Trading": ("inventory", {6, 16, 26}, "1700.00", "2400.00"),
    "Quaymoss Supplies": ("inventory", {9, 19, 28}, "1700.00", "2400.00"),
}


def test_monthly_constants_match_the_table() -> None:
    found: dict[str, tuple[str, set[int], str, str]] = {}
    for payment in generator.MONTHLY_PAYMENTS:
        name = payment.counterparty.name
        days = found[name][1] if name in found else set()
        found[name] = (
            payment.counterparty.category,
            days | {payment.day},
            str(generator.cents_to_amount(payment.min_cents)),
            str(generator.cents_to_amount(payment.max_cents)),
        )

    assert found == EXPECTED_MONTHLY


@pytest.mark.parametrize(("seed", "anchor"), MATRIX, ids=MATRIX_IDS)
def test_monthly_debits_fall_on_their_days_in_range(seed: int, anchor: date) -> None:
    transactions = generate(seed, anchor).transactions
    start = history_start(anchor)
    debits = [t for t in transactions if t.direction == "debit"]

    for t in debits:
        _, days, low, high = EXPECTED_MONTHLY[t.counterparty_name]
        assert t.booking_date.day in days
        assert Decimal(low) <= t.amount <= Decimal(high)
    expected = Counter(
        name
        for name, (_, days, _, _) in EXPECTED_MONTHLY.items()
        for n in range((anchor - start).days + 1)
        if (start + timedelta(days=n)).day in days
    )
    assert Counter(t.counterparty_name for t in debits) == expected


@pytest.mark.parametrize(("seed", "anchor"), MATRIX, ids=MATRIX_IDS)
def test_one_ordinary_receipt_on_each_weekday(seed: int, anchor: date) -> None:
    dataset = generate(seed, anchor)
    receipts = ordinary_receipts(dataset)
    start = history_start(anchor)
    weekdays = [
        start + timedelta(days=n) for n in range(183) if (start + timedelta(days=n)).weekday() < 5
    ]

    assert [t.booking_date for t in receipts] == weekdays
    customers = {customer.name for customer in CUSTOMERS}
    for t in receipts:
        assert t.counterparty_name in customers
        assert Decimal("1500.00") <= t.amount <= Decimal("2500.00")


def test_customers_are_picked_with_the_seed() -> None:
    receipts = ordinary_receipts(generate(42, date(2026, 6, 30)))

    assert len({t.counterparty_name for t in receipts}) == len(CUSTOMERS)


# References


@pytest.mark.parametrize(("seed", "anchor"), MATRIX, ids=MATRIX_IDS)
def test_invoice_numbers_follow_booking_order(seed: int, anchor: date) -> None:
    receipts = ordinary_receipts(generate(seed, anchor))
    numbers = [INVOICE.findall(t.description) for t in receipts]

    assert all(len(found) == 1 for found in numbers)
    assert [int(found[0]) for found in numbers] == list(range(1001, 1001 + len(receipts)))
    assert 1001 + len(receipts) - 1 < 9001


def test_invoice_sequence_ends_near_inv_1131() -> None:
    receipts = ordinary_receipts(generate(42, date(2026, 6, 30)))

    assert receipts[-1].description == "Customer payment INV-1131"


@pytest.mark.parametrize(("seed", "anchor"), MATRIX, ids=MATRIX_IDS)
def test_bill_numbers_follow_booking_order(seed: int, anchor: date) -> None:
    transactions = generate(seed, anchor).transactions
    inventory = [
        t
        for t in transactions
        if EXPECTED_MONTHLY.get(t.counterparty_name, ("",))[0] == "inventory"
    ]
    numbers = [BILL.findall(t.description) for t in inventory]

    assert all(len(found) == 1 for found in numbers)
    assert [int(found[0]) for found in numbers] == list(range(1001, 1001 + len(inventory)))
    assert len(inventory) <= 63
    others = [t for t in transactions if t not in inventory]
    assert not any(BILL.search(t.description) for t in others)


def test_counterparty_references() -> None:
    references = [counterparty.reference for counterparty in COUNTERPARTIES]

    assert all(re.fullmatch(r"DEMO-CP-\d{4}", reference) for reference in references)
    assert len(set(references)) == len(references)
    assert len({counterparty.name for counterparty in COUNTERPARTIES}) == len(COUNTERPARTIES)
    by_name = {counterparty.name: counterparty.reference for counterparty in COUNTERPARTIES}
    for t in generate(42, date(2026, 6, 30)).transactions:
        assert t.counterparty_reference == by_name[t.counterparty_name]


# Anchored receipts (#44)


def test_anchored_receipts_constant() -> None:
    customers = {customer.name for customer in CUSTOMERS}
    invoices = [INVOICE.findall(receipt.description) for receipt in ANCHORED_RECEIPTS]

    assert len(ANCHORED_RECEIPTS) >= 5
    for receipt in ANCHORED_RECEIPTS:
        assert 0 <= receipt.offset_days <= 29
        assert receipt.customer.name in customers
        assert 150_000 <= receipt.amount_cents <= 250_000
    assert sum(1 for found in invoices if found and int(found[0]) >= 9001) >= 4
    assert sum(1 for found in invoices if not found) >= 1
    assert all(int(found[0]) >= 9001 for found in invoices if found)
    assert len({receipt.offset_days % 7 for receipt in ANCHORED_RECEIPTS}) >= 5


@pytest.mark.parametrize(("seed", "anchor"), MATRIX, ids=MATRIX_IDS)
def test_anchored_receipts_are_the_same_for_every_seed(seed: int, anchor: date) -> None:
    found = [
        (t.booking_date, t.counterparty_name, t.amount, t.description)
        for t in anchored_receipts(generate(seed, anchor))
    ]
    expected = [
        (
            anchor - timedelta(days=receipt.offset_days),
            receipt.customer.name,
            generator.cents_to_amount(receipt.amount_cents),
            receipt.description,
        )
        for receipt in ANCHORED_RECEIPTS
    ]

    assert sorted(found) == sorted(expected)
