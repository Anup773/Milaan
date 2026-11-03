"""Phase 24: the BS calendar, strict date reading, and fiscal years (pure logic, no database)."""
from datetime import date, datetime, timedelta

import pytest

from engine.calendars import bs
from engine.calendars.dates import (
    LEGACY_RULES, DateRules, adjust_native, current_rules, explain, parse_date_detailed, use_rules,
)
from engine.calendars.fiscal import fiscal_months, fiscal_year_containing, fiscal_year_label
from engine.ingestion.money_parse import parse_date

NP = DateRules("BS", "DMY")
IN_ = DateRules("AD", "DMY")
US = DateRules("AD", "MDY")


# ── the table ────────────────────────────────────────────────────────────
def test_every_bs_day_round_trips_and_is_consecutive():
    expected = bs.AD_MIN
    for year in range(bs.MIN_YEAR, bs.MAX_YEAR + 1):
        assert 365 <= bs.days_in_year(year) <= 366
        for month in range(1, 13):
            assert 29 <= bs.days_in_month(year, month) <= 32
            for day in (1, bs.days_in_month(year, month)):
                ad = bs.bs_to_ad(year, month, day)
                assert bs.ad_to_bs(ad) == (year, month, day)
    # walk every AD day once: BS dates advance one day at a time with no gap or repeat
    d, prev = bs.AD_MIN, None
    while d <= bs.AD_MAX:
        b = bs.ad_to_bs(d)
        assert bs.bs_to_ad(*b) == d
        if prev is not None:
            nxt = (prev.year, prev.month, prev.day + 1)
            if nxt[2] > bs.days_in_month(prev.year, prev.month):
                nxt = (prev.year, prev.month + 1, 1) if prev.month < 12 else (prev.year + 1, 1, 1)
            assert tuple(b) == nxt
        prev, d = b, d + timedelta(days=1)
    assert expected == bs.AD_MIN


def test_known_dates_from_the_two_sample_statements():
    # Nepali New Year, and the fiscal-year boundaries printed in the Upper Syange / Kalinchowk statements
    assert bs.bs_to_ad(2082, 1, 1) == date(2025, 4, 14)
    assert bs.bs_to_ad(2081, 1, 1) == date(2024, 4, 13)
    assert bs.bs_to_ad(2081, 4, 1) == date(2024, 7, 16)        # Shrawan 1, 2081 -> FY 2081/82 starts
    assert bs.ad_to_bs(date(2024, 7, 15)) == (2081, 3, 31)      # last day of FY 2080/81 ("2024.07.15" in the PDF)
    assert bs.bs_to_ad(2082, 3, 32) == date(2025, 7, 16)        # last day of FY 2081/82 ("2082/03/32")
    assert bs.bs_to_ad(2083, 3, 32) == date(2026, 7, 16)        # last day of FY 2082/83
    assert bs.bs_to_ad(2082, 4, 1) == date(2025, 7, 17)
    assert bs.bs_to_ad(2082, 1, 1).weekday() == 0               # 14 April 2025 was a Monday


def test_invalid_bs_dates_are_refused_with_a_reason():
    with pytest.raises(ValueError, match="Ashadh 2081 BS has 31 days"):
        bs.bs_to_ad(2081, 3, 32)
    with pytest.raises(ValueError, match="outside the supported range"):
        bs.bs_to_ad(1999, 1, 1)
    with pytest.raises(ValueError, match="month must be 1-12"):
        bs.bs_to_ad(2082, 13, 1)
    with pytest.raises(ValueError, match="outside the supported BS range"):
        bs.ad_to_bs(date(1900, 1, 1))
    assert bs.is_valid(2082, 3, 32) and not bs.is_valid(2081, 3, 32)


def test_year_status_marks_years_after_2083_provisional():
    assert bs.year_status(2081) == "confirmed" and bs.year_status(2083) == "confirmed"
    assert bs.year_status(2084) == "provisional" and bs.year_status(2062) == "provisional"


def test_month_names_and_spellings():
    assert bs.month_name_to_number("Shrawan") == 4 and bs.month_name_to_number("srawan") == 4
    assert bs.month_name_to_number("Ashar") == 3 and bs.month_name_to_number("Chaitra") == 12
    assert bs.month_name_to_number("March") is None
    assert bs.format_bs(date(2025, 7, 16)) == "2082-03-32" and bs.format_bs(date(2025, 7, 17), "long") == "1 Shrawan 2082"


# ── reading dates ────────────────────────────────────────────────────────
def test_bs_company_reads_year_first_and_year_last_dates_as_bs():
    for text in ("2082-04-01", "2082/04/01", "2082.04.01", "01/04/2082", "01-04-2082", "20820401", "1-Shrawan-2082", "१-४-२०८२",
                 "२०८२/०४/०१"):
        got = parse_date_detailed(text, NP)
        assert got.value == date(2025, 7, 17), text
        assert got.bs == (2082, 4, 1)
    assert parse_date_detailed("2082-03-32", NP).value == date(2025, 7, 16)


def test_bs_company_refuses_what_is_not_a_bs_date():
    assert parse_date_detailed("2082-03-33", NP).value is None
    assert "has 32 days" in parse_date_detailed("2082-03-33", NP).problem
    got = parse_date_detailed("2026-03-31", NP)  # an AD date in a BS company must not become BS 2026
    assert got.value is None and "AD date" in got.problem
    assert parse_date_detailed("32/03/2081", NP).value is None  # Ashadh 2081 has only 31 days
    assert parse_date_detailed("2082-13-01", NP).value is None


def test_provisional_bs_years_warn_but_still_convert():
    got = parse_date_detailed("2085-01-01", NP)
    assert got.value is not None and got.warnings and "provisional" in got.warnings[0]
    assert not parse_date_detailed("2082-01-01", NP).warnings


def test_the_old_silent_bug_ad_company_no_longer_accepts_a_bs_year():
    for rules in (IN_, US, LEGACY_RULES):
        got = parse_date_detailed("2082-04-01", rules)
        assert got.value is None and "Bikram Sambat" in got.problem
        assert parse_date_detailed("01/04/2082", rules).value is None
    assert parse_date("2082-04-01") is None  # the old function, with no company rules, is fixed too
    assert parse_date("01/04/2082") is None
    assert parse_date("2082-03-32") is None


def test_day_first_versus_month_first_is_the_companys_choice_never_a_guess():
    assert parse_date_detailed("03/04/2026", IN_).value == date(2026, 4, 3)
    assert parse_date_detailed("03/04/2026", US).value == date(2026, 3, 4)
    assert parse_date_detailed("25/03/2026", IN_).value == date(2026, 3, 25)
    bad = parse_date_detailed("25/03/2026", US)
    assert bad.value is None and "month first" in bad.problem
    bad = parse_date_detailed("03/25/2026", IN_)
    assert bad.value is None and "day first" in bad.problem
    # legacy (a company with no policy): the old behaviour, day first with a month-first fallback
    assert parse_date_detailed("03/25/2026", LEGACY_RULES).value == date(2026, 3, 25)
    assert parse_date_detailed("03/04/2026", LEGACY_RULES).value == date(2026, 4, 3)


def test_iso_and_named_month_dates_are_unambiguous_in_every_ad_company():
    for rules in (IN_, US, LEGACY_RULES):
        assert parse_date_detailed("2026-03-31", rules).value == date(2026, 3, 31)
        assert parse_date_detailed("31-Mar-2026", rules).value == date(2026, 3, 31)
        assert parse_date_detailed("31 March 2026", rules).value == date(2026, 3, 31)
        assert parse_date_detailed("Mar 31, 2026", rules).value == date(2026, 3, 31)
    assert parse_date_detailed("31 Smarch 2026", IN_).value is None


def test_two_digit_years_only_when_asked():
    assert parse_date_detailed("31/03/26", IN_).value is None
    assert parse_date_detailed("31/03/26", IN_, two_digit_years=True).value == date(2026, 3, 31)
    assert parse_date_detailed("03/31/26", US, two_digit_years=True).value == date(2026, 3, 31)
    assert parse_date_detailed("01/04/82", NP, two_digit_years=True).value == date(2025, 7, 17)


def test_empty_and_junk():
    assert parse_date_detailed(None, NP).value is None and parse_date_detailed(None, NP).problem is None
    assert parse_date_detailed("  ", NP).problem is None
    assert "not a date" in parse_date_detailed("soon", IN_).problem
    assert explain("2082-04-01", IN_) and explain("2026-03-31", IN_) is None


def test_excel_date_cells():
    # Excel turns a typed 2082/04/01 into a real date in the year 2082
    got = adjust_native(datetime(2082, 4, 1), NP)
    assert got.value == date(2025, 7, 17) and got.bs == (2082, 4, 1)
    # a genuine AD Excel date in a BS company is kept as AD
    got = adjust_native(date(2026, 3, 31), NP)
    assert got.value == date(2026, 3, 31) and got.bs == bs.ad_to_bs(date(2026, 3, 31))
    assert adjust_native(datetime(2082, 4, 1), IN_).value is None
    assert adjust_native(date(2026, 3, 31), US).value == date(2026, 3, 31)


def test_rules_are_validated_and_scoped():
    with pytest.raises(ValueError):
        DateRules("Hijri", "DMY")
    with pytest.raises(ValueError):
        DateRules("AD", "YMD")
    assert current_rules() is LEGACY_RULES
    with use_rules(NP):
        assert current_rules() is NP
        assert parse_date("2082-04-01") == date(2025, 7, 17)   # the old function follows the company's rules in scope
    assert current_rules() is LEGACY_RULES


# ── fiscal years ─────────────────────────────────────────────────────────
def test_nepal_fiscal_year_runs_shrawan_to_ashadh():
    fy = fiscal_year_containing(date(2025, 1, 10), "BS", 4)
    assert (fy.start, fy.end, fy.label) == (date(2024, 7, 16), date(2025, 7, 16), "2081/82")
    assert fiscal_year_containing(date(2025, 7, 16), "BS", 4).label == "2081/82"
    assert fiscal_year_containing(date(2025, 7, 17), "BS", 4).label == "2082/83"
    assert fiscal_year_containing(date(2025, 7, 17), "BS", 4).start == date(2025, 7, 17)


def test_nepal_fiscal_months_are_bs_months_with_uneven_lengths():
    months = fiscal_months(fiscal_year_containing(date(2025, 1, 10), "BS", 4))
    assert [m["label"] for m in months][:2] == ["Shrawan 2081", "Bhadra 2081"] and months[-1]["label"] == "Ashadh 2082"
    assert months[0]["start"] == date(2024, 7, 16) and months[-1]["end"] == date(2025, 7, 16)
    for a, b in zip(months, months[1:]):
        assert b["start"] == a["end"] + timedelta(days=1)  # no gap, no overlap
    assert len({(m["end"] - m["start"]).days for m in months}) > 1


def test_india_us_and_other_fiscal_years():
    fy = fiscal_year_containing(date(2026, 2, 1), "AD", 4)
    assert (fy.start, fy.end, fy.label) == (date(2025, 4, 1), date(2026, 3, 31), "2025-26")
    assert fiscal_year_containing(date(2026, 4, 1), "AD", 4).label == "2026-27"
    fy = fiscal_year_containing(date(2026, 6, 30), "AD", 1)
    assert (fy.start, fy.end, fy.label) == (date(2026, 1, 1), date(2026, 12, 31), "2026")
    fy = fiscal_year_containing(date(2025, 12, 31), "AD", 10)  # a US company with an October year-end start
    assert (fy.start, fy.end) == (date(2025, 10, 1), date(2026, 9, 30))
    months = fiscal_months(fiscal_year_containing(date(2026, 2, 1), "AD", 4))
    assert months[0]["label"] == "April 2025" and months[-1]["end"] == date(2026, 3, 31) and months[10]["end"] == date(2026, 2, 28)
    assert fiscal_year_label(date(2025, 4, 1), "AD", 4) == "2025-26"
    with pytest.raises(ValueError):
        fiscal_year_containing(date(2026, 1, 1), "AD", 13)


def test_the_browser_copy_of_the_bs_table_matches_the_engine():
    """frontend/lib/bs-calendar.ts is generated from bs_data.py; a year that differs would show a different date than the engine stores."""
    from pathlib import Path

    from engine.calendars import bs_data

    path = Path(__file__).resolve().parents[3] / "frontend" / "lib" / "bs-calendar.ts"
    if not path.exists():  # the engine can be tested on its own, without the frontend next to it
        return
    text = path.read_text()
    for year, days in bs_data.BS_MONTH_DAYS.items():
        assert f"  {year}: [{', '.join(str(n) for n in days)}]," in text, year
    assert f"CONFIRMED_THROUGH = {bs_data.CONFIRMED_THROUGH};" in text
