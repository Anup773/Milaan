"""
Shared pieces of the tax depreciation schedules (Phase 24) -- pure logic, no database.

Tax depreciation is a MEMO schedule: it feeds the tax computation and deferred tax, and posts nothing to the ledger
(book depreciation is the fixed-asset schedule). Each country's rules are their own module (nepal.py, india.py, us.py);
what they share is here: the input and output shapes, rounding, and how a pool's rate is chosen for a year.

Rates are DATA, not constants in the maths. Each scheme has standard rates with the date they take effect, and a company
may set its own rate for a pool from a date (Nepal: a powerhouse project adds one third to the rates; Upper Syange's
statements use rates the other sample, Kalinchowk, does not). `resolve_rate` picks the latest rate whose date is on or
before the end of the fiscal year, the company's own first.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ...calendars.fiscal import FiscalYear

ZERO = Decimal("0.00")
CENTS = Decimal("0.01")
HUNDRED = Decimal("100")
OPENING, ADDITION, DISPOSAL = "OPENING", "ADDITION", "DISPOSAL"
KINDS = (OPENING, ADDITION, DISPOSAL)


def money(x: Decimal) -> Decimal:
    return Decimal(x).quantize(CENTS, rounding=ROUND_HALF_UP)


def positive_money(value: Any, label: str) -> Decimal:
    try:
        d = Decimal(str(value).strip())
    except Exception:  # noqa: BLE001 -- any bad input is a ValueError for the caller
        raise ValueError(f"{label} must be an amount") from None
    if not d.is_finite() or d < 0:
        raise ValueError(f"{label} must be an amount of zero or more")
    return money(d)


@dataclass(frozen=True)
class Movement:
    """One input line: a pool's opening balance, an addition (cost) or a disposal (proceeds)."""
    pool: str
    kind: str
    event_date: date
    amount: Decimal
    description: str = ""
    details: Mapping[str, Any] = field(default_factory=dict)
    id: Optional[str] = None


@dataclass(frozen=True)
class RateRow:
    pool: str
    rate: Decimal          # percent per year
    effective_from: date
    note: str = ""
    source: str = "standard"   # 'standard' or 'company'


def resolve_rate(pool: str, fy_end: date, company: Sequence[RateRow], standard: Sequence[RateRow]) -> RateRow:
    """The company's own rate for the pool that took effect most recently on or before `fy_end`, else the standard one."""
    for rows in (company, standard):
        found = [r for r in rows if r.pool == pool and r.effective_from <= fy_end]
        if found:
            return max(found, key=lambda r: r.effective_from)
    raise ValueError(f"there is no rate for pool {pool!r} in force on {fy_end.isoformat()}; set the company's rate for it "
                     "(Tax depreciation > Rates)")


def col(key: str, label: str, money_col: bool = True) -> Dict[str, Any]:
    return {"key": key, "label": label, "money": money_col}


def fmt(d: Decimal) -> str:
    return format(d, "f")


def months_since(start: date, d: date) -> int:
    """Whole calendar months from the first of start's month to the date's month (0 for the first month)."""
    return (d.year - start.year) * 12 + (d.month - start.month)


def check_in_year(m: Movement, fy: FiscalYear) -> None:
    if not fy.start <= m.event_date <= fy.end:
        raise ValueError(f"{m.kind.lower()} dated {m.event_date.isoformat()} is outside the fiscal year {fy.label}")