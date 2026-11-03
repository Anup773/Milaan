"""
Fiscal years -- pure logic, no database.

A fiscal year is a pair of real AD dates. For an AD company it starts on the 1st of `start_month`. For a BS company
(Nepal) `start_month` is a BS month: Nepal's fiscal year starts on Shrawan 1 (BS month 4) and ends on the last day of
Ashadh, which falls around 16-17 July, so it can not be described as a Gregorian month. This module turns "the fiscal
year containing this date" into exact start and end dates, a label in the style the country uses, and its months.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import List

from . import bs

AD_MONTH_NAMES = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
                  "November", "December")


@dataclass(frozen=True)
class FiscalYear:
    start: date
    end: date            # the last day, inclusive
    label: str           # "2081/82" (Nepal), "2025-26" (India or any non-January start), "2025" (calendar year)
    calendar: str        # AD | BS
    start_month: int     # in the company's own calendar

    def to_json(self) -> dict:
        return {"start": self.start.isoformat(), "end": self.end.isoformat(), "label": self.label,
                "calendar": self.calendar, "start_month": self.start_month}


def _check(calendar: str, start_month: int) -> None:
    if calendar not in ("AD", "BS"):
        raise ValueError("calendar must be AD or BS")
    if not 1 <= start_month <= 12:
        raise ValueError("the fiscal year start month must be 1-12")


def fiscal_year_label(start: date, calendar: str, start_month: int) -> str:
    """'2081/82' for a BS year starting in Shrawan; '2025-26' for an AD year not starting in January; '2025' otherwise."""
    _check(calendar, start_month)
    if calendar == "BS":
        year = bs.ad_to_bs(start).year
        return f"{year}" if start_month == 1 else f"{year}/{(year + 1) % 100:02d}"
    return f"{start.year}" if start_month == 1 else f"{start.year}-{(start.year + 1) % 100:02d}"


def _start_of(year: int, calendar: str, start_month: int) -> date:
    return bs.bs_to_ad(year, start_month, 1) if calendar == "BS" else date(year, start_month, 1)


def fiscal_year_containing(d: date, calendar: str = "AD", start_month: int = 1) -> FiscalYear:
    """The fiscal year that contains the AD date `d`."""
    _check(calendar, start_month)
    if calendar == "BS":
        b = bs.ad_to_bs(d)
        start_year = b.year if b.month >= start_month else b.year - 1
        if start_year + 1 > bs.MAX_YEAR or start_year < bs.MIN_YEAR:
            raise ValueError("that fiscal year is outside the supported BS range")
    else:
        start_year = d.year if d.month >= start_month else d.year - 1
    start = _start_of(start_year, calendar, start_month)
    end = _start_of(start_year + 1, calendar, start_month) - timedelta(days=1)
    return FiscalYear(start, end, fiscal_year_label(start, calendar, start_month), calendar, start_month)


def fiscal_months(fy: FiscalYear) -> List[dict]:
    """The twelve months of a fiscal year, in the company's own calendar, as exact AD start and end dates."""
    months: List[dict] = []
    if fy.calendar == "BS":
        b = bs.ad_to_bs(fy.start)
        year, month = b.year, b.month
        for _ in range(12):
            start = bs.bs_to_ad(year, month, 1)
            end = bs.month_end(year, month)
            months.append({"label": f"{bs.MONTH_NAMES[month - 1]} {year}", "start": start, "end": end})
            month += 1
            if month > 12:
                month, year = 1, year + 1
    else:
        year, month = fy.start.year, fy.start.month
        for _ in range(12):
            start = date(year, month, 1)
            nxt = date(year + (month == 12), month % 12 + 1, 1)
            months.append({"label": f"{AD_MONTH_NAMES[month - 1]} {year}", "start": start, "end": nxt - timedelta(days=1)})
            year, month = nxt.year, nxt.month
    return months