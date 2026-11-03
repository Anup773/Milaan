"""
United States: federal MACRS tax depreciation -- pure logic, no database.

How it works (IRS Publication 946; confirm with a CPA):

  Each addition is ONE asset with a recovery class: 3, 5, 7, 10, 15 or 20-year personal property, 27.5-year residential rental
  property, or 39-year nonresidential real property. The pool code names the class ("5-year", "27.5-year").

  Basis. cost minus any Section 179 expense, minus bonus depreciation (a percentage of the remaining basis) for personal property.
  Section 179 and bonus are taken in full in the year the asset is placed in service. Milaan does NOT enforce the Section 179
  limits or the business-income limit, and does not decide whether an asset qualifies for bonus: you enter the amounts.

  Convention. Personal property uses the half-year convention, unless more than 40% of the year's personal-property basis (cost
  less Section 179, leaving out assets placed in service and sold in the same year) was placed in service in the last three months
  of the fiscal year, when the mid-quarter convention applies to all of that year's personal property. Real property uses mid-month
  (the month placed in service counts from the first month of the fiscal year).

  Percentages are the IRS tables (Publication 946, Appendix A): half-year (A-1), mid-quarter (A-2 to A-5), 27.5-year (A-6) and
  39-year (A-7a). The tables are the General Depreciation System (GDS); the Alternative Depreciation System is not built.

  Sales. In the year of sale the asset gets a partial year (half-year: half; mid-quarter: (quarter - 0.5) / 4; real property:
  (month - 0.5) / 12 of that year's percentage), none after. Gain, loss and depreciation recapture (sections 1245 and 1250) are NOT
  computed. State rules that differ from federal depreciation are not modelled.
"""
from __future__ import annotations

import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from ...calendars.fiscal import FiscalYear
from .common import ADDITION, DISPOSAL, HUNDRED, ZERO, Movement, RateRow, col, fmt, money

PERSONAL = ("3", "5", "7", "10", "15", "20")
REAL = ("27.5", "39")
CLASSES = PERSONAL + REAL
POOL_NAMES: Dict[str, str] = {
    "3": "3-year property", "5": "5-year property (cars, light trucks, computers)", "7": "7-year property (office furniture, most equipment)",
    "10": "10-year property", "15": "15-year property (land improvements)", "20": "20-year property",
    "27.5": "27.5-year residential rental property", "39": "39-year nonresidential real property",
}


def _p(*values: str) -> Tuple[Decimal, ...]:
    return tuple(Decimal(v) for v in values)


# Publication 946, Table A-1: half-year convention.
HALF_YEAR: Dict[str, Tuple[Decimal, ...]] = {
    "3": _p("33.33", "44.45", "14.81", "7.41"),
    "5": _p("20.00", "32.00", "19.20", "11.52", "11.52", "5.76"),
    "7": _p("14.29", "24.49", "17.49", "12.49", "8.93", "8.92", "8.93", "4.46"),
    "10": _p("10.00", "18.00", "14.40", "11.52", "9.22", "7.37", "6.55", "6.55", "6.56", "6.55", "3.28"),
    "15": _p("5.00", "9.50", "8.55", "7.70", "6.93", "6.23", "5.90", "5.90", "5.91", "5.90", "5.91", "5.90", "5.91", "5.90", "5.91", "2.95"),
    "20": _p("3.750", "7.219", "6.677", "6.177", "5.713", "5.285", "4.888", "4.522", "4.462", "4.461", "4.462", "4.461", "4.462", "4.461",
             "4.462", "4.461", "4.462", "4.461", "4.462", "4.461", "2.231"),
}

# Tables A-2 to A-5: mid-quarter convention, by the quarter the asset was placed in service (1-4).
MID_QUARTER: Dict[int, Dict[str, Tuple[Decimal, ...]]] = {
    1: {
        "3": _p("58.33", "27.78", "12.35", "1.54"),
        "5": _p("35.00", "26.00", "15.60", "11.01", "11.01", "1.38"),
        "7": _p("25.00", "21.43", "15.31", "10.93", "8.75", "8.74", "8.75", "1.09"),
        "10": _p("17.50", "16.50", "13.20", "10.56", "8.45", "6.76", "6.55", "6.55", "6.56", "6.55", "0.82"),
        "15": _p("8.75", "9.13", "8.21", "7.39", "6.65", "5.99", "5.90", "5.91", "5.90", "5.91", "5.90", "5.91", "5.90", "5.91", "5.90", "0.74"),
        "20": _p("6.563", "7.000", "6.482", "5.996", "5.546", "5.130", "4.746", "4.459", "4.459", "4.459", "4.459", "4.460", "4.459", "4.460",
                 "4.459", "4.460", "4.459", "4.460", "4.459", "4.460", "0.565"),
    },
    2: {
        "3": _p("41.67", "38.89", "14.14", "5.30"),
        "5": _p("25.00", "30.00", "18.00", "11.37", "11.37", "4.26"),
        "7": _p("17.85", "23.47", "16.76", "11.97", "8.87", "8.87", "8.87", "3.34"),
        "10": _p("12.50", "17.50", "14.00", "11.20", "8.96", "7.17", "6.55", "6.55", "6.56", "6.55", "2.46"),
        "15": _p("6.25", "9.38", "8.44", "7.59", "6.83", "6.15", "5.91", "5.90", "5.91", "5.90", "5.91", "5.90", "5.91", "5.90", "5.91", "2.21"),
        "20": _p("4.688", "7.148", "6.612", "6.116", "5.658", "5.233", "4.841", "4.478", "4.463", "4.463", "4.463", "4.463", "4.463", "4.463",
                 "4.462", "4.463", "4.462", "4.463", "4.462", "4.463", "1.673"),
    },
    3: {
        "3": _p("25.00", "50.00", "16.67", "8.33"),
        "5": _p("15.00", "34.00", "20.40", "12.24", "11.30", "7.06"),
        "7": _p("10.71", "25.51", "18.22", "13.02", "9.30", "8.85", "8.86", "5.53"),
        "10": _p("7.50", "18.50", "14.80", "11.84", "9.47", "7.58", "6.55", "6.55", "6.56", "6.55", "4.10"),
        "15": _p("3.75", "9.63", "8.66", "7.80", "7.02", "6.31", "5.90", "5.90", "5.91", "5.90", "5.91", "5.90", "5.91", "5.90", "5.91", "3.69"),
        "20": _p("2.813", "7.289", "6.742", "6.237", "5.769", "5.336", "4.936", "4.566", "4.460", "4.460", "4.460", "4.460", "4.461", "4.460",
                 "4.461", "4.460", "4.461", "4.460", "4.461", "4.460", "2.788"),
    },
    4: {
        "3": _p("8.33", "61.11", "20.37", "10.19"),
        "5": _p("5.00", "38.00", "22.80", "13.68", "10.94", "9.58"),
        "7": _p("3.57", "27.55", "19.68", "14.06", "10.04", "8.73", "8.73", "7.64"),
        "10": _p("2.50", "19.50", "15.60", "12.48", "9.98", "7.99", "6.55", "6.55", "6.56", "6.55", "5.74"),
        "15": _p("1.25", "9.88", "8.89", "8.00", "7.20", "6.48", "5.90", "5.90", "5.90", "5.91", "5.90", "5.91", "5.90", "5.91", "5.90", "5.17"),
        "20": _p("0.938", "7.430", "6.872", "6.357", "5.880", "5.439", "5.031", "4.654", "4.458", "4.458", "4.458", "4.458", "4.458", "4.458",
                 "4.458", "4.458", "4.458", "4.459", "4.458", "4.459", "3.901"),
    },
}

# Table A-7a: 39-year nonresidential real property, mid-month. Year 1 by the month placed in service (1-12); years 2-39 are 2.564;
# year 40 mirrors year 1 (the part of the first year not taken).
REAL_39_FIRST = _p("2.461", "2.247", "2.033", "1.819", "1.605", "1.391", "1.177", "0.963", "0.749", "0.535", "0.321", "0.107")
REAL_39_MIDDLE = Decimal("2.564")
REAL_39_LAST = tuple(reversed(REAL_39_FIRST))

def real_275_table(month: int) -> Tuple[Decimal, ...]:
    """
    Table A-6, 27.5-year residential rental property (mid-month), for a placement month 1-12: years 1 to 29.
    Straight line over 27.5 years with half a month in the month of placing in service. Each year's figure is the change in the
    cumulative total rounded to three decimals, which reproduces the IRS table's 3.636 / 3.637 pattern and sums to exactly 100.
    """
    unit = HUNDRED / Decimal("27.5")
    first = unit * (Decimal("12.5") - month) / 12
    cumulative = [first]
    while cumulative[-1] + unit < HUNDRED:
        cumulative.append(cumulative[-1] + unit)
    cumulative.append(HUNDRED)
    rounded = [c.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP) for c in cumulative]
    return tuple(b - a for a, b in zip([Decimal("0")] + rounded, rounded))


def real_39_table(month: int) -> Tuple[Decimal, ...]:
    return (REAL_39_FIRST[month - 1],) + (REAL_39_MIDDLE,) * 38 + (REAL_39_LAST[month - 1],)


_POOL_RE = re.compile(r"^\s*(3|5|7|10|15|20|27\.5|39)\s*-?\s*(year|yr|y)?\s*$", re.IGNORECASE)


def recovery_class(pool: str) -> str:
    m = _POOL_RE.match(pool)
    if not m:
        raise ValueError(f"pool {pool!r} is not a MACRS class; use one of: " + ", ".join(f"{c}-year" for c in CLASSES))
    return m.group(1)


def month_in_year(d: date, fy: FiscalYear) -> int:
    """1-12: which month of the fiscal year the date falls in."""
    return (d.year - fy.start.year) * 12 + (d.month - fy.start.month) + 1


def quarter_in_year(d: date, fy: FiscalYear) -> int:
    return (month_in_year(d, fy) - 1) // 3 + 1


class Asset:
    """One addition worked out: its class, basis and convention. Built by build_assets()."""

    def __init__(self, move: Movement, cls: str, placed_fy: FiscalYear, sec179: Decimal, bonus_pct: Decimal) -> None:
        self.move, self.cls, self.placed_fy = move, cls, placed_fy
        self.ref = str(move.details.get("asset_ref") or move.id or move.description or f"{move.pool} {move.event_date.isoformat()}")
        self.cost = move.amount
        self.sec179 = sec179
        self.bonus_pct = bonus_pct
        after_179 = move.amount - sec179
        self.bonus = money(after_179 * bonus_pct / HUNDRED)
        self.basis = after_179 - self.bonus          # what MACRS tables apply to
        self.convention = "HY"
        self.disposed: Optional[Movement] = None
        self.month = month_in_year(move.event_date, placed_fy)
        self.quarter = quarter_in_year(move.event_date, placed_fy)

    def percent_table(self) -> Tuple[Decimal, ...]:
        if self.cls == "39":
            return real_39_table(self.month)
        if self.cls == "27.5":
            return real_275_table(self.month)
        if self.convention == "MQ":
            return MID_QUARTER[self.quarter][self.cls]
        return HALF_YEAR[self.cls]


def build_assets(movements: Sequence[Movement], fy_of: Callable[[date], FiscalYear]) -> List[Asset]:
    """The additions, with Section 179 and bonus read from their details, matched with disposals and given their convention."""
    assets: List[Asset] = []
    for m in movements:
        if m.kind != ADDITION:
            continue
        cls = recovery_class(m.pool)
        sec179 = money(Decimal(str(m.details.get("section_179", 0) or 0)))
        bonus_pct = Decimal(str(m.details.get("bonus_percent", 0) or 0))
        if sec179 < 0 or sec179 > m.amount:
            raise ValueError(f"{m.event_date.isoformat()} {m.pool}: Section 179 expense must be between 0 and the cost")
        if not 0 <= bonus_pct <= 100:
            raise ValueError(f"{m.event_date.isoformat()} {m.pool}: bonus percent must be between 0 and 100")
        if cls in REAL and (sec179 > 0 or bonus_pct > 0):
            raise ValueError(f"{m.event_date.isoformat()} {m.pool}: Section 179 and bonus depreciation do not apply to real property here")
        assets.append(Asset(m, cls, fy_of(m.event_date), sec179, bonus_pct))
    by_ref = {a.ref: a for a in assets}
    if len(by_ref) != len(assets):
        raise ValueError("two assets have the same asset reference; give each addition its own reference (details: asset_ref)")
    for m in movements:
        if m.kind != DISPOSAL:
            continue
        ref = str(m.details.get("asset_ref") or "")
        if ref not in by_ref:
            raise ValueError(f"a disposal on {m.event_date.isoformat()} must name the asset it sold (details: asset_ref) matching an addition")
        if by_ref[ref].disposed is not None:
            raise ValueError(f"asset {ref!r} is disposed of twice")
        if m.event_date < by_ref[ref].move.event_date:
            raise ValueError(f"asset {ref!r} is disposed of before it was placed in service")
        by_ref[ref].disposed = m
    # mid-quarter test, once per fiscal year of placement
    by_year: Dict[date, List[Asset]] = {}
    for a in assets:
        if a.cls in PERSONAL:
            by_year.setdefault(a.placed_fy.start, []).append(a)
    for year_assets in by_year.values():
        fy = year_assets[0].placed_fy
        counted = [a for a in year_assets if not (a.disposed is not None and a.disposed.event_date <= fy.end)]
        total = sum((a.cost - a.sec179 for a in counted), ZERO)
        last_quarter = sum((a.cost - a.sec179 for a in counted if a.quarter == 4), ZERO)
        if total > 0 and last_quarter * 10 > total * 4:
            for a in year_assets:
                a.convention = "MQ"
    for a in assets:
        if a.cls in REAL:
            a.convention = "MM"
    return assets


def depreciation_in_year(a: Asset, fy: FiscalYear) -> Dict[str, Decimal]:
    """One asset's deductions in one fiscal year: Section 179, bonus and the MACRS amount."""
    if fy.start < a.placed_fy.start or (a.disposed is not None and a.disposed.event_date < fy.start):
        return {"section_179": ZERO, "bonus": ZERO, "macrs": ZERO}
    year_no = fy.start.year - a.placed_fy.start.year + 1
    table = a.percent_table()
    pct = table[year_no - 1] if year_no <= len(table) else ZERO
    amount = a.basis * pct / HUNDRED
    if a.disposed is not None and a.disposed.event_date <= fy.end:
        d = a.disposed.event_date
        if a.convention == "HY":
            amount = amount / 2
        elif a.convention == "MQ":
            amount = amount * (Decimal(quarter_in_year(d, fy)) - Decimal("0.5")) / 4
        else:
            amount = amount * (Decimal(month_in_year(d, fy)) - Decimal("0.5")) / 12
    return {"section_179": a.sec179 if year_no == 1 else ZERO, "bonus": a.bonus if year_no == 1 else ZERO, "macrs": money(amount)}


def compute_year(movements: Sequence[Movement], fy: FiscalYear, fy_of: Callable[[date], FiscalYear]
                 ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    One fiscal year. `movements` is every addition and disposal up to the end of the year (earlier years' assets still depreciate).
    Returns (one row per recovery class, one line per asset still depreciating or placed this year).
    """
    assets = [a for a in build_assets(movements, fy_of) if a.placed_fy.start <= fy.start]
    lines: List[Dict[str, Any]] = []
    for a in assets:
        this = depreciation_in_year(a, fy)
        if a.disposed is not None and a.disposed.event_date < fy.start:
            continue  # sold in an earlier year
        earlier = ZERO
        # accumulated deductions before this year: add each earlier year's amounts
        year_start = a.placed_fy.start.year
        for yr in range(year_start, fy.start.year):
            shifted = _shift(a.placed_fy, yr - year_start, fy_of)
            prev = depreciation_in_year(a, shifted)
            earlier += prev["section_179"] + prev["bonus"] + prev["macrs"]
        total = this["section_179"] + this["bonus"] + this["macrs"]
        remaining = a.cost - earlier - total
        if total == 0 and earlier >= a.cost - Decimal("0.01"):
            continue  # fully depreciated in an earlier year
        lines.append({
            "pool": a.move.pool, "asset": a.ref, "description": a.move.description, "placed_in_service": a.move.event_date.isoformat(),
            "convention": {"HY": "Half-year", "MQ": "Mid-quarter", "MM": "Mid-month"}[a.convention], "cost": fmt(a.cost),
            "section_179": fmt(this["section_179"]), "bonus": fmt(this["bonus"]), "macrs": fmt(this["macrs"]),
            "depreciation": fmt(total), "accumulated": fmt(earlier + total), "remaining_basis": fmt(remaining),
            "disposed": a.disposed.event_date.isoformat() if a.disposed is not None else "",
        })
    rows: List[Dict[str, Any]] = []
    for cls in CLASSES:
        mine = [ln for ln in lines if recovery_class(ln["pool"]) == cls]
        if not mine:
            continue
        rows.append({
            "pool": f"{cls}-year", "name": POOL_NAMES[cls], "rate": "", "assets": str(len(mine)),
            "cost": fmt(sum((Decimal(l["cost"]) for l in mine), ZERO)),
            "section_179": fmt(sum((Decimal(l["section_179"]) for l in mine), ZERO)),
            "bonus": fmt(sum((Decimal(l["bonus"]) for l in mine), ZERO)),
            "macrs": fmt(sum((Decimal(l["macrs"]) for l in mine), ZERO)),
            "depreciation": fmt(sum((Decimal(l["depreciation"]) for l in mine), ZERO)),
            "accumulated": fmt(sum((Decimal(l["accumulated"]) for l in mine), ZERO)),
            "remaining_basis": fmt(sum((Decimal(l["remaining_basis"]) for l in mine), ZERO)),
            "notes": [],
        })
    return rows, lines


def _shift(fy: FiscalYear, years: int, fy_of: Callable[[date], FiscalYear]) -> FiscalYear:
    """The fiscal year `years` after fy (an AD fiscal year keeps its start month, so this is the same month and day)."""
    return fy_of(date(fy.start.year + years, fy.start.month, fy.start.day))


COLUMNS = [
    col("pool", "Class", False), col("assets", "Assets", False), col("cost", "Cost"), col("section_179", "Section 179"),
    col("bonus", "Bonus"), col("macrs", "MACRS"), col("depreciation", "Total deduction"), col("accumulated", "Accumulated"),
    col("remaining_basis", "Remaining basis"),
]
LINE_COLUMNS = [
    col("asset", "Asset", False), col("pool", "Class", False), col("placed_in_service", "Placed in service", False),
    col("convention", "Convention", False), col("cost", "Cost"), col("section_179", "Section 179"), col("bonus", "Bonus"),
    col("macrs", "MACRS"), col("depreciation", "Total deduction"), col("accumulated", "Accumulated"), col("remaining_basis", "Remaining basis"),
]
RATE_PRESETS: Tuple[Dict[str, Any], ...] = ()
STANDARD_RATES: Tuple[RateRow, ...] = ()


def totals(rows: Sequence[Mapping[str, Any]]) -> Dict[str, str]:
    keys = ("cost", "section_179", "bonus", "macrs", "depreciation", "accumulated", "remaining_basis")
    return {k: fmt(sum((Decimal(r[k]) for r in rows), ZERO)) for k in keys}