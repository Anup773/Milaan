"""
Pure-logic tests for Phase 5's planner (engine.mapping.planner). No
database involved -- these exercise plan_entries() directly against
in-memory SourceRow/Period objects, the same way test_ingestion.py tests
parsing without a database.
"""
from datetime import date
from decimal import Decimal

from engine.mapping.planner import Period, SourceRow, normalize_ref, plan_entries

OPEN_PERIOD = Period(
    id="period-open", label="FY2025-26 Q1",
    start=date(2025, 4, 1), end=date(2025, 6, 30), locked=False,
)
LOCKED_PERIOD = Period(
    id="period-locked", label="FY2024-25 (closed)",
    start=date(2024, 4, 1), end=date(2025, 3, 31), locked=True,
)
MAPPING = {
    "cash": "acc-cash",
    "sales": "acc-sales",
    "bank account": "acc-bank",
    "purchase of raw materials": "acc-purchases",
}


def row(row_number, account_ref, debit="0", credit="0", ref="V1", txn_date=date(2025, 4, 10),
        description="", status="OK", issues=()):
    return SourceRow(
        id=f"row-{row_number}", row_number=row_number, account_ref=account_ref,
        transaction_date=txn_date, description=description,
        debit=Decimal(debit), credit=Decimal(credit), reference=ref,
        status=status, issues=issues,
    )


def test_normalize_ref_collapses_case_and_whitespace():
    assert normalize_ref("Bank Account") == normalize_ref("bank  account ")
    assert normalize_ref("  BANK   ACCOUNT") == normalize_ref("Bank Account")


def test_balanced_mapped_group_produces_one_entry():
    rows = [
        row(2, "Cash", debit="1000.00", ref="V1"),
        row(3, "Sales", credit="1000.00", ref="V1"),
    ]
    plan = plan_entries(rows, MAPPING, [OPEN_PERIOD])

    assert not plan.blocked
    assert not plan.skipped
    assert len(plan.entries) == 1
    entry = plan.entries[0]
    assert entry.total == Decimal("1000.00")
    assert entry.period_id == "period-open"
    assert entry.anchor_row_id == "row-2"
    assert {line.account_id for line in entry.lines} == {"acc-cash", "acc-sales"}


def test_unmapped_account_blocks_the_whole_group():
    rows = [
        row(2, "Cash", debit="500.00", ref="V2"),
        row(3, "Some New Vendor", credit="500.00", ref="V2"),
    ]
    plan = plan_entries(rows, MAPPING, [OPEN_PERIOD])

    assert not plan.entries
    assert len(plan.blocked) == 1
    assert any("not mapped yet" in reason and "Some New Vendor" in reason for reason in plan.blocked[0].reasons)


def test_unbalanced_group_is_blocked_not_partially_posted():
    rows = [
        row(2, "Cash", debit="1000.00", ref="V3"),
        row(3, "Sales", credit="900.00", ref="V3"),
    ]
    plan = plan_entries(rows, MAPPING, [OPEN_PERIOD])

    assert not plan.entries
    assert len(plan.blocked) == 1
    assert any("does not balance" in reason for reason in plan.blocked[0].reasons)


def test_all_zero_group_is_skipped_not_blocked():
    rows = [
        row(2, "Cash", debit="0", credit="0", ref="V4"),
        row(3, "Sales", debit="0", credit="0", ref="V4"),
    ]
    plan = plan_entries(rows, MAPPING, [OPEN_PERIOD])

    assert not plan.entries
    assert not plan.blocked
    assert len(plan.skipped) == 1
    assert "zero" in plan.skipped[0].reason


def test_date_outside_every_period_is_blocked():
    rows = [
        row(2, "Cash", debit="100.00", ref="V5", txn_date=date(2026, 1, 1)),
        row(3, "Sales", credit="100.00", ref="V5", txn_date=date(2026, 1, 1)),
    ]
    plan = plan_entries(rows, MAPPING, [OPEN_PERIOD])

    assert not plan.entries
    assert any("no accounting period covers" in reason for reason in plan.blocked[0].reasons)


def test_locked_period_is_blocked():
    rows = [
        row(2, "Cash", debit="100.00", ref="V6", txn_date=date(2024, 6, 1)),
        row(3, "Sales", credit="100.00", ref="V6", txn_date=date(2024, 6, 1)),
    ]
    plan = plan_entries(rows, MAPPING, [OPEN_PERIOD, LOCKED_PERIOD])

    assert not plan.entries
    assert any("is locked" in reason for reason in plan.blocked[0].reasons)


def test_ingestion_error_row_blocks_with_a_readable_reason():
    rows = [
        row(2, "Cash", debit="100.00", ref="V7"),
        row(3, "", credit="100.00", ref="V7", status="ERROR", issues=("ERROR: account: missing account name",)),
    ]
    plan = plan_entries(rows, MAPPING, [OPEN_PERIOD])

    assert not plan.entries
    reasons = plan.blocked[0].reasons
    assert any("could not be read properly" in r and "missing account name" in r for r in reasons)


def test_rows_with_no_reference_group_by_date_and_warn():
    rows = [
        row(2, "Cash", debit="50.00", ref=""),
        row(3, "Sales", credit="50.00", ref=""),
    ]
    plan = plan_entries(rows, MAPPING, [OPEN_PERIOD])

    assert len(plan.entries) == 1
    assert any("no voucher/reference" in w for w in plan.entries[0].warnings)


def test_two_separate_vouchers_on_the_same_day_stay_separate():
    rows = [
        row(2, "Cash", debit="100.00", ref="A"),
        row(3, "Sales", credit="100.00", ref="A"),
        row(4, "Bank Account", debit="200.00", ref="B"),
        row(5, "Purchase of Raw Materials", credit="200.00", ref="B"),
    ]
    plan = plan_entries(rows, MAPPING, [OPEN_PERIOD])

    assert len(plan.entries) == 2
    totals = sorted(e.total for e in plan.entries)
    assert totals == [Decimal("100.00"), Decimal("200.00")]