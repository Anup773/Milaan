"""
How a company's dates are READ -- pure logic, no database.

The problem this fixes: a date typed as 01/04/2026 means 1 April in Nepal and India and 4 January in the United
States, and a Nepali ledger writes 2082-04-01 for 16 July 2025. The old reader guessed (day first, then month
first) and happily read BS year 2082 as the AD year 2082. Now each company says how it writes dates (its
calendar, AD or BS, and whether slash dates are day-first or month-first) and the reader follows that
strictly. Anything that does not fit is refused with a reason, never guessed.

A company with no policy yet keeps the old behaviour (LEGACY_RULES: AD, day first, month first as a fallback),
except that a year that is plainly a BS year is no longer accepted as an AD year.

Every date this module returns is an AD date; BS dates are converted on the way in.
"""
from __future__ import annotations

import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterator, Optional, Tuple

from . import bs

CALENDARS = ("AD", "BS")
ORDERS = ("DMY", "MDY")

# An AD year at or beyond this is not a real ledger date: it is almost certainly a BS year (BS 2070 = AD 2013,
# and BS years from 2075 on are in daily use). A BS year below the other limit is almost certainly an AD year.
AD_MAX_PLAUSIBLE_YEAR = 2070
AD_MIN_PLAUSIBLE_YEAR = 1900
BS_MIN_PLAUSIBLE_YEAR = 2050

_DEVANAGARI = {ord(ch): str(i) for i, ch in enumerate("०१२३४५६७८९")}
_AD_MONTHS = {name: i + 1 for i, name in enumerate(
    ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"))}
for _full, _n in list(_AD_MONTHS.items()):
    _AD_MONTHS.setdefault(_full[:3], _n)
_AD_MONTHS["sept"] = 9

_Y_FIRST = re.compile(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$")
_Y_LAST = re.compile(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4}|\d{2})$")
_COMPACT = re.compile(r"^(\d{4})(\d{2})(\d{2})$")
_DAY_NAME_YEAR = re.compile(r"^(\d{1,2})[-\s./]+([A-Za-z]+)\.?[-\s./,]+(\d{4}|\d{2})$")
_NAME_DAY_YEAR = re.compile(r"^([A-Za-z]+)\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})$")


@dataclass(frozen=True)
class DateRules:
    """How one company writes dates. calendar AD|BS; order DMY|MDY applies to dates written with the year last."""
    calendar: str = "AD"
    order: str = "DMY"
    lenient: bool = False  # legacy only: try the other order when the first one is impossible

    def __post_init__(self) -> None:
        if self.calendar not in CALENDARS:
            raise ValueError(f"calendar must be one of {', '.join(CALENDARS)}")
        if self.order not in ORDERS:
            raise ValueError(f"date order must be one of {', '.join(ORDERS)}")


LEGACY_RULES = DateRules("AD", "DMY", lenient=True)

_current: ContextVar[DateRules] = ContextVar("milaan_date_rules", default=LEGACY_RULES)


def current_rules() -> DateRules:
    """The rules in force for this piece of work (set by the CLI that knows the company); LEGACY_RULES otherwise."""
    return _current.get()


@contextmanager
def use_rules(rules: DateRules) -> Iterator[DateRules]:
    token = _current.set(rules)
    try:
        yield rules
    finally:
        _current.reset(token)


@dataclass(frozen=True)
class ParsedDate:
    value: Optional[date]                 # the AD date, or None when it could not be read
    problem: Optional[str] = None         # why not (None for an empty cell)
    warnings: Tuple[str, ...] = ()        # read, but worth a second look (a provisional BS year)
    bs: Optional[bs.BSDate] = None        # the BS date, when the company's calendar is BS

    @property
    def ok(self) -> bool:
        return self.value is not None


def _normalise(raw: object) -> str:
    return str(raw).translate(_DEVANAGARI).strip()


def _full_year(two: str, calendar: str) -> int:
    n = int(two)
    if calendar == "BS":
        return 2000 + n
    return 2000 + n if n < 69 else 1900 + n


def _ad_plausible(year: int) -> Optional[str]:
    if year >= AD_MAX_PLAUSIBLE_YEAR:
        return (f"year {year} is too far ahead to be an AD year; it looks like a Bikram Sambat (BS) date. "
                "If this company keeps its books in BS, set its calendar to BS in the accounting policy")
    if year < AD_MIN_PLAUSIBLE_YEAR:
        return f"year {year} is too far back to be a ledger date"
    return None


def _from_parts(year: int, month: int, day: int, rules: DateRules) -> ParsedDate:
    if rules.calendar == "BS":
        if year < BS_MIN_PLAUSIBLE_YEAR:
            return ParsedDate(None, f"year {year} is too early to be a BS year in use; it looks like an AD date. "
                                    "This company's calendar is BS, so dates must be BS (for example 2082-04-01)")
        try:
            ad = bs.bs_to_ad(year, month, day)
        except ValueError as exc:
            return ParsedDate(None, str(exc))
        warnings = (bs.provisional_note(year),) if bs.year_status(year) == "provisional" else ()
        return ParsedDate(ad, None, warnings, bs.BSDate(year, month, day))
    problem = _ad_plausible(year)
    if problem:
        return ParsedDate(None, problem)
    try:
        return ParsedDate(date(year, month, day))
    except ValueError:
        return ParsedDate(None, f"{day:02d}/{month:02d}/{year} is not a real date")


def _order_hint(rules: DateRules) -> str:
    return "day first (DD/MM/YYYY)" if rules.order == "DMY" else "month first (MM/DD/YYYY)"


def _month_by_name(name: str, rules: DateRules) -> Optional[int]:
    if rules.calendar == "BS":
        return bs.month_name_to_number(name)
    return _AD_MONTHS.get(name.lower().strip("."))


def parse_date_detailed(raw: object, rules: Optional[DateRules] = None, *, two_digit_years: bool = False) -> ParsedDate:
    """
    Reads one date cell/text under the company's rules. Accepted shapes:
      2082-04-01  2082/04/01  2082.04.01  20820401       year first: always year-month-day
      01/04/2082  01-04-2082  01.04.2082                 year last: day-month-year or month-day-year per the rules
      1-Shrawan-2082, 5 Apr 2026, Apr 5, 2026            month names (BS names for a BS company)
      two-digit years (01/04/82) only when two_digit_years=True (bank statements)
    Devanagari digits are read. Returns ParsedDate; `problem` says why a non-empty cell could not be read.
    """
    rules = rules or current_rules()
    if raw is None:
        return ParsedDate(None)
    text = _normalise(raw)
    if not text:
        return ParsedDate(None)

    m = _Y_FIRST.match(text) or _COMPACT.match(text)
    if m:
        return _from_parts(int(m.group(1)), int(m.group(2)), int(m.group(3)), rules)

    m = _Y_LAST.match(text)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), m.group(3)
        if len(y) == 2:
            if not two_digit_years:
                return ParsedDate(None, "two-digit years are not accepted here; write the year with four digits")
            year = _full_year(y, rules.calendar)
        else:
            year = int(y)
        day, month = (a, b) if rules.order == "DMY" else (b, a)

        def attempt(d: int, mo: int) -> Optional[ParsedDate]:
            return _from_parts(year, mo, d, rules) if 1 <= mo <= 12 else None

        first = attempt(day, month)
        if first is not None and first.ok:
            return first
        if rules.lenient:  # legacy only: the other reading, when the first is impossible
            second = attempt(month, day)
            if second is not None and second.ok:
                return second
        if first is None:
            return ParsedDate(None, f"{text}: {month} is not a month; this company writes dates {_order_hint(rules)}")
        return first

    m = _DAY_NAME_YEAR.match(text)
    if m:
        month = _month_by_name(m.group(2), rules)
        if month is None:
            return ParsedDate(None, f"{m.group(2)!r} is not a month name")
        y = m.group(3)
        if len(y) == 2 and not two_digit_years:
            return ParsedDate(None, "two-digit years are not accepted here; write the year with four digits")
        year = _full_year(y, rules.calendar) if len(y) == 2 else int(y)
        return _from_parts(year, month, int(m.group(1)), rules)

    m = _NAME_DAY_YEAR.match(text)
    if m:
        month = _month_by_name(m.group(1), rules)
        if month is None:
            return ParsedDate(None, f"{m.group(1)!r} is not a month name")
        return _from_parts(int(m.group(3)), month, int(m.group(2)), rules)

    return ParsedDate(None, f"{text!r} is not a date this company's settings can read")


def adjust_native(value: date, rules: Optional[DateRules] = None) -> ParsedDate:
    """
    A date that arrived as a real date value (an Excel date cell). In an AD company it is taken as it is, unless the year is
    a BS-looking year. In a BS company a year of 2050 or more is read as BS (Excel turns a typed 2082/04/01 into the
    year 2082), and an earlier year is a real AD date.
    """
    rules = rules or current_rules()
    if isinstance(value, datetime):
        value = value.date()
    if rules.calendar == "BS" and value.year >= BS_MIN_PLAUSIBLE_YEAR:
        return _from_parts(value.year, value.month, value.day, rules)
    problem = _ad_plausible(value.year)
    if problem:
        return ParsedDate(None, problem)
    return ParsedDate(value, None, (), bs.ad_to_bs(value) if rules.calendar == "BS" and bs.AD_MIN <= value <= bs.AD_MAX else None)


def explain(raw: object, rules: Optional[DateRules] = None) -> Optional[str]:
    """Why this text is not a readable date under the current rules (None when it reads fine or is empty)."""
    return parse_date_detailed(raw, rules, two_digit_years=True).problem