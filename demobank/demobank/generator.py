"""The deterministic historical data generator (pure).

`generate(seed, anchor_date)` returns DemoBank's one business account and
about six months of fictional transactions ending on `anchor_date`. The same
seed and anchor date always give the same data.

Generation has two steps:

- `schedule(anchor_date)` gives every transaction's booking date,
  counterparty, direction, description and amount range in cents. It does not
  use the seed, so the dates never depend on it
- `generate` draws each amount in its slot's range with
  `rng.randint(min_cents, max_cents)`, and picks the customer of each
  ordinary receipt with `rng.choice`, in schedule order, from one
  `random.Random(seed)`

The balance and anomaly invariants (`demobank/README.md`) therefore depend
only on the dates and the amount ranges, and the tests check the worst case
of every range directly.

This module does no I/O, reads no clock and no settings. Money is `Decimal`
built from integer cents: no floating point is involved at any step.
"""

import random
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

Direction = Literal["debit", "credit"]

ACCOUNT_ID = "acc_operating_001"
ACCOUNT_DISPLAY_NAME = "Demo Retail Ltd — Operating"
CURRENCY = "EUR"
OPENING_BALANCE_CENTS = 2_500_000  # 25,000.00 at the start of the first day
STATUS = "booked"

# The history covers `anchor_date - 182` to `anchor_date`, both inclusive.
HISTORY_DAYS = 183

# #25 category keys. Each counterparty belongs to exactly one.
REVENUE = "revenue"
RENT = "rent"
SOFTWARE = "software"
UTILITIES = "utilities"
SUPPLIER_OTHER = "supplier_other"
INVENTORY = "inventory"
EXPENSE_CATEGORIES = (RENT, SOFTWARE, UTILITIES, SUPPLIER_OTHER, INVENTORY)


@dataclass(frozen=True)
class Counterparty:
    """A fictional business. None is the name of a real company or product."""

    name: str
    reference: str  # `DEMO-CP-` and a 4-digit number
    category: str  # the #25 key of every transaction with this counterparty


def _counterparty(number: int, name: str, category: str) -> Counterparty:
    return Counterparty(name=name, reference=f"DEMO-CP-{number:04d}", category=category)


# Customers paying the business (credits, `revenue`).
CUSTOMERS = (
    _counterparty(1, "Quillmere Interiors", REVENUE),
    _counterparty(2, "Brackenfold Events", REVENUE),
    _counterparty(3, "Corvanta Design Studio", REVENUE),
    _counterparty(4, "Duskwillow Florists", REVENUE),
    _counterparty(5, "Embervale Guesthouses", REVENUE),
    _counterparty(6, "Fernhollow Cafe", REVENUE),
)

LANDLORD = _counterparty(11, "Halvenmoor Properties", RENT)
SOFTWARE_VENDORS = (
    _counterparty(21, "Ledgerkite Cloud", SOFTWARE),
    _counterparty(22, "Pixelquarry Design Suite", SOFTWARE),
    _counterparty(23, "Tallowfield Till Systems", SOFTWARE),
)
UTILITY_PROVIDERS = (
    _counterparty(31, "Wattmere Energy", UTILITIES),
    _counterparty(32, "Rillbourne Water", UTILITIES),
)
OTHER_SUPPLIERS = (
    _counterparty(41, "Sparkvale Cleaning", SUPPLIER_OTHER),
    _counterparty(42, "Tallyhook Bookkeeping", SUPPLIER_OTHER),
)
INVENTORY_SUPPLIERS = (
    _counterparty(51, "Orchardine Wholesale", INVENTORY),
    _counterparty(52, "Brimcastle Trading", INVENTORY),
    _counterparty(53, "Quaymoss Supplies", INVENTORY),
)

COUNTERPARTIES = (
    *CUSTOMERS,
    LANDLORD,
    *SOFTWARE_VENDORS,
    *UTILITY_PROVIDERS,
    *OTHER_SUPPLIERS,
    *INVENTORY_SUPPLIERS,
)


@dataclass(frozen=True)
class MonthlyPayment:
    """A debit on a fixed day of every month (1 to 28, so every month has it)."""

    counterparty: Counterparty
    day: int
    min_cents: int
    max_cents: int


# The monthly debits, in the order they are booked within a day. A date
# outside the history range is skipped, not moved. Changing any value means
# rerunning the range checks in `tests/unit/test_generator_invariants.py`.
MONTHLY_PAYMENTS = (
    MonthlyPayment(LANDLORD, 1, 280_000, 280_000),
    MonthlyPayment(SOFTWARE_VENDORS[0], 5, 8_900, 8_900),
    MonthlyPayment(SOFTWARE_VENDORS[1], 12, 12_900, 12_900),
    MonthlyPayment(SOFTWARE_VENDORS[2], 20, 18_900, 18_900),
    MonthlyPayment(UTILITY_PROVIDERS[0], 8, 30_000, 34_000),
    MonthlyPayment(UTILITY_PROVIDERS[1], 22, 12_000, 14_000),
    MonthlyPayment(OTHER_SUPPLIERS[0], 15, 24_000, 24_000),
    MonthlyPayment(OTHER_SUPPLIERS[1], 25, 38_000, 38_000),
    *(
        MonthlyPayment(supplier, day, 170_000, 240_000)
        for supplier, days in zip(
            INVENTORY_SUPPLIERS, ((3, 13, 23), (6, 16, 26), (9, 19, 28)), strict=True
        )
        for day in days
    ),
)

# One ordinary customer receipt on each Monday to Friday.
RECEIPT_MIN_CENTS = 150_000
RECEIPT_MAX_CENTS = 250_000
FIRST_INVOICE_NUMBER = 1001
FIRST_BILL_NUMBER = 1001


@dataclass(frozen=True)
class AnchoredReceipt:
    """A fixed extra customer receipt, the same for every seed (#44 relies on it).

    It is booked `offset_days` before `anchor_date`, on top of the ordinary
    receipt of that day.
    """

    offset_days: int
    customer: Counterparty
    amount_cents: int
    description: str


# `INV-9001` and up are reserved for these: the ordinary sequence never gets
# there. The last one carries no invoice number (an unmatched incoming
# payment). #44's demo seed must change with this list.
ANCHORED_RECEIPTS = (
    AnchoredReceipt(1, CUSTOMERS[0], 184_500, "Customer payment INV-9001"),
    AnchoredReceipt(4, CUSTOMERS[2], 212_000, "Customer payment INV-9002"),
    AnchoredReceipt(9, CUSTOMERS[4], 167_550, "Customer payment INV-9003"),
    AnchoredReceipt(13, CUSTOMERS[1], 234_000, "Customer payment INV-9004"),
    AnchoredReceipt(18, CUSTOMERS[3], 199_000, "Customer payment INV-9005"),
    AnchoredReceipt(26, CUSTOMERS[5], 221_000, "Customer payment"),
)


@dataclass(frozen=True)
class PlantedDebit:
    """A fixed debit booked on `anchor_date` after the history, for every seed (#12).

    The planted debits give LedgerLens' anomaly rules one possible duplicate
    payment (#28) and one unusually large expense (#30) to flag.
    """

    scenario: str
    counterparty: Counterparty
    amount_cents: int
    description: str


# `SVC-9001` and `BILL-9001` are outside the ordinary sequences.
PLANTED_DEBITS = (
    PlantedDebit("duplicate_payment", OTHER_SUPPLIERS[0], 45_500, "Deep clean SVC-9001"),
    PlantedDebit("duplicate_payment", OTHER_SUPPLIERS[0], 45_500, "Deep clean SVC-9001"),
    PlantedDebit(
        "unusual_expense", INVENTORY_SUPPLIERS[0], 785_000, "Inventory purchase BILL-9001"
    ),
)


@dataclass(frozen=True)
class Slot:
    """One scheduled transaction, before its amount (and customer) is drawn.

    `counterparties` has one entry, except for an ordinary customer receipt,
    whose customer is picked from it with `rng`.
    """

    booking_date: date
    counterparties: tuple[Counterparty, ...]
    direction: Direction
    description: str
    min_cents: int
    max_cents: int

    @property
    def category(self) -> str:
        """The #25 key, the same for every possible counterparty of the slot."""
        return self.counterparties[0].category


@dataclass(frozen=True)
class Account:
    account_id: str
    display_name: str
    currency: str
    opening_balance: Decimal


@dataclass(frozen=True)
class Transaction:
    """A generated transaction, with the fields #11 serves."""

    transaction_id: str
    account_id: str
    booking_date: date
    value_date: date
    amount: Decimal
    currency: str
    direction: Direction
    counterparty_name: str
    counterparty_reference: str
    description: str
    status: str


@dataclass(frozen=True)
class Dataset:
    account: Account
    transactions: tuple[Transaction, ...]


def cents_to_amount(cents: int) -> Decimal:
    """`Decimal` with exactly 2 decimal places: `123450` gives `1234.50`."""
    return Decimal(cents).scaleb(-2)


def history_start(anchor_date: date) -> date:
    """The first day of the history ending on `anchor_date`."""
    return anchor_date - timedelta(days=HISTORY_DAYS - 1)


def _days(start: date, end: date) -> list[date]:
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def schedule(anchor_date: date) -> list[Slot]:
    """Every transaction of the history, in booking order. Uses no seed.

    Within a day: the ordinary customer receipt, then the anchored receipts,
    then the monthly debits in `MONTHLY_PAYMENTS` order.
    """
    start = history_start(anchor_date)
    anchored: dict[date, list[AnchoredReceipt]] = {}
    for receipt in ANCHORED_RECEIPTS:
        anchored.setdefault(anchor_date - timedelta(days=receipt.offset_days), []).append(receipt)

    slots: list[Slot] = []
    invoice_number = FIRST_INVOICE_NUMBER
    bill_number = FIRST_BILL_NUMBER
    for day in _days(start, anchor_date):
        if day.weekday() < 5:  # Monday to Friday
            slots.append(
                Slot(
                    booking_date=day,
                    counterparties=CUSTOMERS,
                    direction="credit",
                    description=f"Customer payment INV-{invoice_number:04d}",
                    min_cents=RECEIPT_MIN_CENTS,
                    max_cents=RECEIPT_MAX_CENTS,
                )
            )
            invoice_number += 1
        for receipt in anchored.get(day, []):
            slots.append(
                Slot(
                    booking_date=day,
                    counterparties=(receipt.customer,),
                    direction="credit",
                    description=receipt.description,
                    min_cents=receipt.amount_cents,
                    max_cents=receipt.amount_cents,
                )
            )
        for payment in MONTHLY_PAYMENTS:
            if payment.day != day.day:
                continue
            if payment.counterparty.category == INVENTORY:
                description = f"Inventory purchase BILL-{bill_number:04d}"
                bill_number += 1
            else:
                description = _monthly_description(payment.counterparty, day)
            slots.append(
                Slot(
                    booking_date=day,
                    counterparties=(payment.counterparty,),
                    direction="debit",
                    description=description,
                    min_cents=payment.min_cents,
                    max_cents=payment.max_cents,
                )
            )
    return slots


def planted_slots(anchor_date: date) -> list[Slot]:
    """The planted debits, all on `anchor_date`, in `PLANTED_DEBITS` order."""
    return [
        Slot(
            booking_date=anchor_date,
            counterparties=(debit.counterparty,),
            direction="debit",
            description=debit.description,
            min_cents=debit.amount_cents,
            max_cents=debit.amount_cents,
        )
        for debit in PLANTED_DEBITS
    ]


_MONTHLY_DESCRIPTIONS = {
    RENT: "Shop rent",
    SOFTWARE: "Software subscription",
    UTILITIES: "Utility bill",
    SUPPLIER_OTHER: "Service fee",
}


def _monthly_description(counterparty: Counterparty, day: date) -> str:
    return f"{_MONTHLY_DESCRIPTIONS[counterparty.category]} {day.year:04d}-{day.month:02d}"


def generate(seed: int, anchor_date: date) -> Dataset:
    """The account and its transactions for `seed` and `anchor_date`.

    The history (`schedule`) is followed by the planted debits
    (`planted_slots`), which are booked on `anchor_date` and so sort after
    every history row. Transaction IDs (`txn_000001`, ...) follow that order,
    which is `(booking_date, schedule order)` order.
    """
    rng = random.Random(seed)
    transactions: list[Transaction] = []
    slots = [*schedule(anchor_date), *planted_slots(anchor_date)]
    for number, slot in enumerate(slots, start=1):
        if len(slot.counterparties) == 1:
            counterparty = slot.counterparties[0]
        else:
            counterparty = rng.choice(slot.counterparties)
        cents = rng.randint(slot.min_cents, slot.max_cents)
        transactions.append(
            Transaction(
                transaction_id=f"txn_{number:06d}",
                account_id=ACCOUNT_ID,
                booking_date=slot.booking_date,
                value_date=slot.booking_date,
                amount=cents_to_amount(cents),
                currency=CURRENCY,
                direction=slot.direction,
                counterparty_name=counterparty.name,
                counterparty_reference=counterparty.reference,
                description=slot.description,
                status=STATUS,
            )
        )
    account = Account(
        account_id=ACCOUNT_ID,
        display_name=ACCOUNT_DISPLAY_NAME,
        currency=CURRENCY,
        opening_balance=cents_to_amount(OPENING_BALANCE_CENTS),
    )
    return Dataset(account=account, transactions=tuple(transactions))
