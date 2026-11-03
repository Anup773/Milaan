"""
Bikram Sambat (BS) <-> Gregorian (AD) conversion -- pure logic, no database.

Nepal's calendar year and its fiscal year (Shrawan 1 to the end of Ashadh) follow BS, and BS months have 29-32
days that differ from year to year with no formula, so conversion walks a table (bs_data.py). Milaan stores
every date as an AD date in the database; BS is how dates are typed, read and shown for a Nepali company.

Honesty: the table is only as good as its source. Years up to CONFIRMED_THROUGH were checked against four
independent converters; later years are PROVISIONAL (see bs_data.py). `year_status()` says which, and the
parsers warn on every provisional conversion.
"""
from __future__ import annotations

from bisect import bisect_right
from datetime import date
from typing import List, NamedTuple, Optional, Tuple

from .bs_data import BS_MONTH_DAYS, CONFIRMED_THROUGH, DISPUTED_YEARS, EPOCH_AD, EPOCH_BS_YEAR

MIN_YEAR = min(BS_MONTH_DAYS)
MAX_YEAR = max(BS_MONTH_DAYS)

MONTH_NAMES: Tuple[str, ...] = ("Baisakh", "Jestha", "Ashadh", "Shrawan", "Bhadra", "Ashwin", "Kartik", "Mangsir",
                                "Poush", "Magh", "Falgun", "Chaitra")

# Spellings seen in Tally exports and Nepali accounts, lower-case, with no punctuation.
_ALIASES = {
    0: ("baisakh", "baishakh", "baisak", "baishak", "vaisakh", "baisakha", "baishakha"),
    1: ("jestha", "jeth", "jyestha", "jesth"),
    2: ("ashadh", "asadh", "ashad", "asar", "ashar", "asad", "asadha", "ashadha"),
    3: ("shrawan", "srawan", "sawan", "shravan", "saun", "shrawn"),
    4: ("bhadra", "bhadau", "bhad"),
    5: ("ashwin", "asoj", "aswin", "ashoj", "asin", "ashwayuja"),
    6: ("kartik", "kartic", "kattik"),
    7: ("mangsir", "mangshir", "margashirsha", "manshir", "mang"),
    8: ("poush", "push", "pous", "paush"),
    9: ("magh", "mag"),
    10: ("falgun", "phalgun", "fagun", "falgoon"),
    11: ("chaitra", "chait"),
}
_MONTH_BY_ALIAS = {}
for _i, _names in _ALIASES.items():
    for _n in _names:
        _MONTH_BY_ALIAS.setdefault(_n, _i + 1)
for _i, _n in enumerate(MONTH_NAMES):
    _MONTH_BY_ALIAS[_n.lower()] = _i + 1


class BSDate(NamedTuple):
    year: int
    month: int
    day: int

    def iso(self) -> str:
        return f"{self.year:04d}-{self.month:02d}-{self.day:02d}"

    @property
    def month_name(self) -> str:
        return MONTH_NAMES[self.month - 1]

    def __str__(self) -> str:  # 2082-04-01
        return self.iso()


# ── the table, turned into day counts once ───────────────────────────────
_EPOCH_ORD = date(*EPOCH_AD).toordinal()
_YEAR_START_ORD: List[int] = []   # ordinal of Baisakh 1 for each BS year, MIN_YEAR first
_ord = _EPOCH_ORD
for _y in range(EPOCH_BS_YEAR, MAX_YEAR + 1):
    if _y >= MIN_YEAR:
        _YEAR_START_ORD.append(_ord)
    _ord += sum(BS_MONTH_DAYS[_y])
_END_ORD = _ord  # one past the last supported day
AD_MIN = date.fromordinal(_YEAR_START_ORD[0])
AD_MAX = date.fromordinal(_END_ORD - 1)


def month_name_to_number(text: str) -> Optional[int]:
    """'Shrawan', 'srawan', 'Ashar' -> 4, 4, 3. None when the text is not a BS month name."""
    return _MONTH_BY_ALIAS.get("".join(ch for ch in str(text).lower() if ch.isalpha()))


def year_status(year: int) -> str:
    """'confirmed' (all comparison sources agree) or 'provisional' (see bs_data.py)."""
    return "provisional" if year > CONFIRMED_THROUGH or year in DISPUTED_YEARS else "confirmed"


def provisional_note(year: int) -> str:
    return (f"BS {year} month lengths are provisional in Milaan's calendar table (the public sources disagree), "
            "so this date could be a day out; check it against the official calendar")


def days_in_month(year: int, month: int) -> int:
    if year not in BS_MONTH_DAYS:
        raise ValueError(f"BS year {year} is outside the supported range {MIN_YEAR}-{MAX_YEAR}")
    if not 1 <= month <= 12:
        raise ValueError(f"BS month must be 1-12, not {month}")
    return BS_MONTH_DAYS[year][month - 1]


def days_in_year(year: int) -> int:
    days_in_month(year, 1)
    return sum(BS_MONTH_DAYS[year])


def is_valid(year: int, month: int, day: int) -> bool:
    try:
        return 1 <= day <= days_in_month(year, month)
    except (ValueError, TypeError):
        return False


def bs_to_ad(year: int, month: int, day: int) -> date:
    """The AD date of a BS date. ValueError says what is wrong (year out of range, day past the month's end...)."""
    length = days_in_month(year, month)
    if not 1 <= day <= length:
        raise ValueError(f"{MONTH_NAMES[month - 1]} {year} BS has {length} days, so day {day} does not exist")
    offset = _YEAR_START_ORD[year - MIN_YEAR] + sum(BS_MONTH_DAYS[year][: month - 1]) + (day - 1)
    return date.fromordinal(offset)


def ad_to_bs(d: date) -> BSDate:
    """The BS date of an AD date. ValueError when the date is outside the table (1943-2043 AD)."""
    ordinal = d.toordinal()
    if not _YEAR_START_ORD[0] <= ordinal < _END_ORD:
        raise ValueError(f"{d.isoformat()} is outside the supported BS range ({AD_MIN.isoformat()} to {AD_MAX.isoformat()})")
    idx = bisect_right(_YEAR_START_ORD, ordinal) - 1
    year = MIN_YEAR + idx
    remaining = ordinal - _YEAR_START_ORD[idx]
    for month, length in enumerate(BS_MONTH_DAYS[year], start=1):
        if remaining < length:
            return BSDate(year, month, remaining + 1)
        remaining -= length
    raise AssertionError("unreachable: the year's months always add up to its length")  # pragma: no cover


def month_end(year: int, month: int) -> date:
    """The AD date of the last day of a BS month."""
    return bs_to_ad(year, month, days_in_month(year, month))


def format_bs(d: date, style: str = "numeric") -> str:
    """AD date -> text in BS. numeric: 2082-04-01; long: 1 Shrawan 2082."""
    b = ad_to_bs(d)
    if style == "long":
        return f"{b.day} {b.month_name} {b.year}"
    return b.iso()