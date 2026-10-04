"""
Pure straight-line depreciation math -- no database. Only method
implemented so far: STRAIGHT_LINE. Written-down-value (reducing balance,
the method most commonly used for tax depreciation in India/Nepal) is a
real future need but a genuinely different parameterization (a rate
applied to the shrinking balance, not cost/useful-life) -- adding it
later is a new depreciation_method enum value and a new branch here, not
a schema rewrite, but it isn't built now rather than risk getting
tax-sensitive math wrong under time pressure.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

ZERO = Decimal("0.00")
CENTS = Decimal("0.01")


@dataclass(frozen=True)
class FixedAsset:
    id: str
    name: str
    acquisition_date: date
    cost: Decimal
    salvage_value: Decimal
    useful_life_months: int
    disposed_date: Optional[date]


def _month_index(d: date) -> int:
    return d.year * 12 + (d.month - 1)


def months_of_depreciation_in_period(
    acquisition_date: date,
    disposed_date: Optional[date],
    period_start: date,
    period_end: date,
) -> int:
    """
    Whole calendar months during which the asset was held AND which fall
    inside the period -- the acquisition month and the disposal month
    each count as a full month if the asset was held at all during that
    month. This is a stated convention, not a universal rule: a future
    company-level accounting-policy setting (ARCHITECTURE.md §13) should
    make it configurable per company instead of fixed here.
    """
    asset_start = _month_index(acquisition_date)
    asset_end = _month_index(disposed_date) if disposed_date else None
    period_start_idx = _month_index(period_start)
    period_end_idx = _month_index(period_end)

    overlap_start = max(asset_start, period_start_idx)
    overlap_end = min(asset_end, period_end_idx) if asset_end is not None else period_end_idx

    return max(0, overlap_end - overlap_start + 1)


def monthly_straight_line_depreciation(cost: Decimal, salvage_value: Decimal, useful_life_months: int) -> Decimal:
    """(cost - salvage_value) / useful_life_months, rounded to the cent."""
    depreciable_base = cost - salvage_value
    return (depreciable_base / useful_life_months).quantize(CENTS, rounding=ROUND_HALF_UP)


def compute_period_depreciation(
    asset: FixedAsset, period_start: date, period_end: date, accumulated_before_period: Decimal,
) -> Decimal:
    """
    The amount to charge for exactly this period: the straight-line
    monthly figure times however many months of this period the asset
    was held, capped so accumulated depreciation never exceeds (cost -
    salvage_value) regardless of rounding or a period that runs long.
    Returns ZERO (never negative) once nothing is left to depreciate, or
    if the asset wasn't held at all during this period.
    """
    months = months_of_depreciation_in_period(asset.acquisition_date, asset.disposed_date, period_start, period_end)
    if months <= 0:
        return ZERO

    monthly = monthly_straight_line_depreciation(asset.cost, asset.salvage_value, asset.useful_life_months)
    raw = monthly * months

    depreciable_base = asset.cost - asset.salvage_value
    remaining = depreciable_base - accumulated_before_period
    if remaining <= ZERO:
        return ZERO
    return min(raw, remaining)