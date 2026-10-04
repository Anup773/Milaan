"""Pure-logic tests for engine.schedules.fixed_assets -- no database."""
from datetime import date
from decimal import Decimal

from engine.schedules.fixed_assets import (
    FixedAsset,
    compute_period_depreciation,
    monthly_straight_line_depreciation,
    months_of_depreciation_in_period,
)

Q1 = (date(2025, 4, 1), date(2025, 6, 30))  # a 3-calendar-month period


def asset(acquisition_date, cost="120000", salvage="0", life=60, disposed=None):
    return FixedAsset(
        id="asset-1", name="Test Machine", acquisition_date=acquisition_date,
        cost=Decimal(cost), salvage_value=Decimal(salvage), useful_life_months=life,
        disposed_date=disposed,
    )


def test_monthly_rate_is_depreciable_base_over_life():
    assert monthly_straight_line_depreciation(Decimal("120000"), Decimal("0"), 60) == Decimal("2000.00")
    assert monthly_straight_line_depreciation(Decimal("120000"), Decimal("12000"), 60) == Decimal("1800.00")


def test_full_period_held_the_whole_time_counts_all_months():
    months = months_of_depreciation_in_period(date(2020, 1, 1), None, *Q1)
    assert months == 3


def test_acquired_mid_period_counts_from_acquisition_month():
    months = months_of_depreciation_in_period(date(2025, 5, 15), None, *Q1)
    assert months == 2


def test_disposed_mid_period_counts_up_to_disposal_month():
    months = months_of_depreciation_in_period(date(2020, 1, 1), date(2025, 5, 20), *Q1)
    assert months == 2


def test_acquired_after_period_ends_counts_zero():
    months = months_of_depreciation_in_period(date(2025, 8, 1), None, *Q1)
    assert months == 0


def test_disposed_before_period_starts_counts_zero():
    months = months_of_depreciation_in_period(date(2020, 1, 1), date(2025, 1, 1), *Q1)
    assert months == 0


def test_compute_period_depreciation_full_quarter():
    a = asset(date(2020, 1, 1))
    amount = compute_period_depreciation(a, *Q1, accumulated_before_period=Decimal("0"))
    assert amount == Decimal("6000.00")


def test_compute_period_depreciation_respects_salvage_value():
    a = asset(date(2020, 1, 1), cost="120000", salvage="12000")
    amount = compute_period_depreciation(a, *Q1, accumulated_before_period=Decimal("0"))
    assert amount == Decimal("5400.00")


def test_compute_period_depreciation_caps_at_remaining_depreciable_base():
    a = asset(date(2020, 1, 1), cost="120000", salvage="0", life=60)
    amount = compute_period_depreciation(a, *Q1, accumulated_before_period=Decimal("119000"))
    assert amount == Decimal("1000.00")


def test_compute_period_depreciation_already_fully_depreciated_is_zero():
    a = asset(date(2020, 1, 1), cost="120000", salvage="0", life=60)
    amount = compute_period_depreciation(a, *Q1, accumulated_before_period=Decimal("120000"))
    assert amount == Decimal("0.00")


def test_compute_period_depreciation_not_yet_acquired_is_zero():
    a = asset(date(2025, 8, 1))
    amount = compute_period_depreciation(a, *Q1, accumulated_before_period=Decimal("0"))
    assert amount == Decimal("0.00")