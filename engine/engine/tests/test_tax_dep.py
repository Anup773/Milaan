"""Tax depreciation (Phase 24): Nepal pools, India blocks, US MACRS, and the roll-forward. No database needed."""
from datetime import date
from decimal import Decimal

import pytest

from engine.calendars.fiscal import fiscal_year_containing
from engine.schedules.tax_dep import india, nepal, service, us
from engine.schedules.tax_dep.common import ADDITION, DISPOSAL, OPENING, Movement, RateRow

D = Decimal


def mv(pool, kind, when, amount, **details):
    return Movement(pool=pool, kind=kind, event_date=date.fromisoformat(when), amount=D(amount).quantize(D('0.01')), details=details,
                    description="", id=None)


def row_of(rows, pool):
    return next(r for r in rows if r["pool"] == pool)


# ── Nepal ───────────────────────────────────────────────────────────────────────────────────────────────

NP_FY = fiscal_year_containing(date(2024, 12, 1), "BS", 4)        # 2081/82: 2024-07-16 .. 2025-07-16


def test_nepal_fiscal_year_dates():
    assert NP_FY.label == "2081/82"
    assert (NP_FY.start, NP_FY.end) == (date(2024, 7, 16), date(2025, 7, 16))


@pytest.mark.parametrize("when,thirds", [
    ("2024-07-16", 3), ("2024-09-01", 3), ("2025-01-13", 3),    # Shrawan 1 .. Poush
    ("2025-01-14", 2), ("2025-02-20", 2), ("2025-04-13", 2),    # Magh .. Chaitra
    ("2025-04-14", 1), ("2025-07-16", 1),                       # Baisakh .. Ashadh (the last day is 32)
])
def test_nepal_timing_thirds(when, thirds):
    assert nepal.timing_thirds(NP_FY, date.fromisoformat(when)) == thirds


def test_nepal_pool_b_with_deferred_part_carried_forward():
    state = {"B": nepal.PoolState(wdv=D("100000"))}
    moves = [mv("B", ADDITION, "2024-09-01", "30000"), mv("B", ADDITION, "2025-02-20", "60000")]
    rows, out = nepal.compute_year(state, moves, NP_FY)
    r = row_of(rows, "B")
    # 100,000 + 30,000 (3/3) + 40,000 (2/3 of 60,000) = 170,000 at 25%
    assert r["additions_counted"] == "70000.00" and r["deferred_out"] == "20000.00"
    assert r["base"] == "170000.00" and r["depreciation"] == "42500.00" and r["closing"] == "127500.00"
    # the deferred 20,000 comes in next year
    fy2 = fiscal_year_containing(date(2025, 12, 1), "BS", 4)
    rows2, out2 = nepal.compute_year(out, [], fy2)
    r2 = row_of(rows2, "B")
    assert r2["carried_in"] == "20000.00" and r2["base"] == "147500.00" and r2["depreciation"] == "36875.00"
    assert r2["closing"] == "110625.00" and out2["B"].deferred == 0


def test_nepal_small_balance_claimed_in_full():
    rows, out = nepal.compute_year({"D": nepal.PoolState(wdv=D("5000"))}, [], NP_FY)
    r = row_of(rows, "D")
    assert r["depreciation"] == "5000.00" and r["closing"] == "0.00"
    assert any("2,000" in n for n in r["notes"])


def test_nepal_small_balance_rule_can_be_switched_off():
    rows, _ = nepal.compute_year({"D": nepal.PoolState(wdv=D("5000"))}, [], NP_FY, claim_small_balance=False)
    assert row_of(rows, "D")["depreciation"] == "750.00"


def test_nepal_disposal_above_balance_is_income():
    rows, _ = nepal.compute_year({"A": nepal.PoolState(wdv=D("100000"))}, [mv("A", DISPOSAL, "2025-01-01", "150000")], NP_FY)
    r = row_of(rows, "A")
    assert r["income_from_disposal"] == "50000.00" and r["depreciation"] == "0.00" and r["closing"] == "0.00"


def test_nepal_disposal_below_balance_reduces_base():
    rows, _ = nepal.compute_year({"A": nepal.PoolState(wdv=D("100000"))}, [mv("A", DISPOSAL, "2025-01-01", "40000")], NP_FY)
    r = row_of(rows, "A")
    assert r["base"] == "60000.00" and r["depreciation"] == "3000.00" and r["closing"] == "57000.00"


def test_nepal_pool_dissolves_with_loss():
    rows, out = nepal.compute_year({"C": nepal.PoolState(wdv=D("80000"))},
                                   [mv("C", DISPOSAL, "2025-01-01", "50000", dissolves_pool=True)], NP_FY)
    r = row_of(rows, "C")
    assert r["loss_on_disposal"] == "30000.00" and r["depreciation"] == "0.00" and out["C"].wdv == 0


def test_nepal_company_rate_overrides_standard():
    own = [RateRow("B", D("33.33"), date(2024, 7, 16), "powerhouse", "company")]
    rows, _ = nepal.compute_year({"B": nepal.PoolState(wdv=D("100000"))}, [], NP_FY, own)
    r = row_of(rows, "B")
    assert r["rate"] == "33.33" and r["rate_source"] == "company" and r["depreciation"] == "33330.00"


def test_nepal_rate_from_a_later_date_does_not_apply_earlier():
    own = [RateRow("B", D("33.33"), date(2026, 7, 17), "later", "company")]
    rows, _ = nepal.compute_year({"B": nepal.PoolState(wdv=D("100000"))}, [], NP_FY, own)
    assert row_of(rows, "B")["rate"] == "25"


def test_nepal_intangible_straight_line_over_life():
    moves = [mv("E", ADDITION, "2024-08-01", "120000", life_years="4")]
    rows, st = nepal.compute_year({}, moves, NP_FY)
    r = row_of(rows, "E")
    assert r["rate"] == "25.00" and r["depreciation"] == "30000.00" and r["closing"] == "90000.00"
    total = D(r["depreciation"])
    fy = NP_FY
    for _ in range(5):
        fy = fiscal_year_containing(fy.end.replace(day=17) if False else date(fy.end.year, 7, 20), "BS", 4)
        rows, st = nepal.compute_year(st, [], fy)
        total += D(row_of(rows, "E")["depreciation"])
    assert total == D("120000.00")                                    # never more than the cost


def test_nepal_intangible_needs_a_life_and_one_life_per_pool():
    with pytest.raises(ValueError, match="useful life"):
        nepal.compute_year({}, [mv("E", ADDITION, "2024-08-01", "1000")], NP_FY)
    with pytest.raises(ValueError, match="different lives"):
        nepal.compute_year({}, [mv("E", ADDITION, "2024-08-01", "1000", life_years="4"),
                                mv("E", ADDITION, "2024-09-01", "1000", life_years="5")], NP_FY)


def test_nepal_intangible_life_rounds_to_half_year():
    assert nepal.half_year_life(D("4.2")) == D("4.0")
    assert nepal.half_year_life(D("4.25")) == D("4.5")
    with pytest.raises(ValueError):
        nepal.half_year_life(D("0"))


def test_nepal_input_state_is_not_mutated():
    st = nepal.PoolState(wdv=D("100000"), life_years=D("4"), counted_cost=D("100000"), accumulated=D("10000"))
    before = (st.wdv, st.deferred, st.life_years, st.counted_cost, st.accumulated)
    nepal.compute_year({"E": st}, [mv("E", ADDITION, "2024-09-01", "1000", life_years="4")], NP_FY)
    assert (st.wdv, st.deferred, st.life_years, st.counted_cost, st.accumulated) == before


def test_nepal_totals_add_up():
    rows, _ = nepal.compute_year({"A": nepal.PoolState(wdv=D("100000")), "B": nepal.PoolState(wdv=D("40000"))}, [], NP_FY)
    t = nepal.totals(rows)
    assert t["depreciation"] == "15000.00" and t["closing"] == "125000.00"


# ── India ───────────────────────────────────────────────────────────────────────────────────────────────

IN_FY = fiscal_year_containing(date(2025, 8, 1), "AD", 4)         # 2025-26: 2025-04-01 .. 2026-03-31


def test_india_fiscal_year():
    assert (IN_FY.start, IN_FY.end, IN_FY.label) == (date(2025, 4, 1), date(2026, 3, 31), "2025-26")


def test_india_half_rate_for_late_additions():
    moves = [mv("PLANT", ADDITION, "2025-06-01", "50000"), mv("PLANT", ADDITION, "2026-01-15", "40000")]
    rows, out = india.compute_year({"PLANT": D("100000")}, moves, IN_FY)
    r = row_of(rows, "PLANT")
    assert r["rate"] == "15" and r["depreciation"] == "25500.00" and r["closing"] == "164500.00"
    assert out["PLANT"] == D("164500.00")


def test_india_180_day_boundary():
    # 180 days used (counting both ends) still gets the full rate; 179 gets half
    full = mv("PLANT", ADDITION, "2025-10-03", "1000")
    half = mv("PLANT", ADDITION, "2025-10-04", "1000")
    assert india.days_used(full.event_date, IN_FY) == 180 and india.days_used(half.event_date, IN_FY) == 179
    rows, _ = india.compute_year({}, [full], IN_FY)
    assert row_of(rows, "PLANT")["depreciation"] == "150.00"
    rows, _ = india.compute_year({}, [half], IN_FY)
    assert row_of(rows, "PLANT")["depreciation"] == "75.00"


def test_india_sale_reduces_block():
    rows, _ = india.compute_year({"FURNITURE": D("100000")}, [mv("FURNITURE", DISPOSAL, "2025-09-01", "20000")], IN_FY)
    r = row_of(rows, "FURNITURE")
    assert r["base"] == "80000.00" and r["depreciation"] == "8000.00" and r["closing"] == "72000.00"


def test_india_sale_above_block_is_short_term_gain():
    moves = [mv("PLANT", ADDITION, "2026-02-01", "5000"), mv("PLANT", DISPOSAL, "2026-03-01", "25000")]
    rows, out = india.compute_year({"PLANT": D("10000")}, moves, IN_FY)
    r = row_of(rows, "PLANT")
    assert r["short_term_gain"] == "10000.00" and r["depreciation"] == "0.00" and r["closing"] == "0.00" and out["PLANT"] == 0


def test_india_block_ceases_with_loss():
    rows, out = india.compute_year({"PLANT": D("20000")}, [mv("PLANT", DISPOSAL, "2025-09-01", "12000", block_ceases=True)], IN_FY)
    r = row_of(rows, "PLANT")
    assert r["short_term_loss"] == "8000.00" and r["depreciation"] == "0.00" and out["PLANT"] == 0


def test_india_company_rate_wins_and_later_dates_do_not_apply_early():
    own = [RateRow("COMPUTER", D("60"), date(2025, 4, 1), "", "company"), RateRow("PLANT", D("20"), date(2026, 4, 1), "", "company")]
    rows, _ = india.compute_year({"COMPUTER": D("1000"), "PLANT": D("1000")}, [], IN_FY, own)
    assert row_of(rows, "COMPUTER")["rate"] == "60" and row_of(rows, "PLANT")["rate"] == "15"


def test_india_unknown_block_has_no_rate():
    with pytest.raises(ValueError, match="no rate"):
        india.compute_year({"MYSTERY": D("100")}, [], IN_FY)


def test_india_standard_rates_are_the_main_blocks():
    got = {r.pool: str(r.rate) for r in india.STANDARD_RATES}
    assert got == {"BLDG_RES": "5", "BLDG_OTHER": "10", "BLDG_TEMP": "40", "FURNITURE": "10", "PLANT": "15", "CAR": "15",
                   "VEHICLE_HIRE": "30", "COMPUTER": "40", "INTANGIBLE": "25"}


# ── United States ───────────────────────────────────────────────────────────────────────────────────────

def cy(year):
    return fiscal_year_containing(date(year, 6, 1), "AD", 1)


def fy_of_cy(d):
    return fiscal_year_containing(d, "AD", 1)


def asset(ref, pool, when, cost, **details):
    return mv(pool, ADDITION, when, cost, asset_ref=ref, **details)


def year_dep(moves, year):
    rows, lines = us.compute_year(moves, cy(year), fy_of_cy)
    return rows, {ln["asset"]: ln for ln in lines}


def test_macrs_tables_sum_to_100():
    for cls, t in us.HALF_YEAR.items():
        assert sum(t) == 100, cls
    for q, tables in us.MID_QUARTER.items():
        for cls, t in tables.items():
            assert sum(t) == 100, (q, cls)
    for month in range(1, 13):
        assert sum(us.real_275_table(month)) == 100
        assert abs(sum(us.real_39_table(month)) - 100) < D("0.005")


def test_macrs_table_spot_values_match_publication_946():
    assert us.HALF_YEAR["5"][:3] == (D("20.00"), D("32.00"), D("19.20"))
    assert us.HALF_YEAR["7"][0] == D("14.29") and us.HALF_YEAR["7"][1] == D("24.49")
    assert us.MID_QUARTER[1]["5"][0] == D("35.00") and us.MID_QUARTER[4]["5"][0] == D("5.00")
    assert us.MID_QUARTER[2]["7"][0] == D("17.85") and us.MID_QUARTER[3]["7"][0] == D("10.71")
    assert us.real_39_table(1)[0] == D("2.461") and us.real_39_table(12)[0] == D("0.107")
    assert us.real_275_table(1)[0] == D("3.485") and us.real_275_table(12)[0] == D("0.152")
    assert us.real_275_table(1)[1] == D("3.636")


def test_macrs_five_year_half_year_over_its_life():
    a = [asset("truck", "5-year", "2025-03-01", "10000")]
    got = []
    for y in range(2025, 2031):
        _, lines = year_dep(a, y)
        got.append(lines["truck"]["macrs"])
    assert got == ["2000.00", "3200.00", "1920.00", "1152.00", "1152.00", "576.00"]
    _, lines = year_dep(a, 2030)
    assert lines["truck"]["remaining_basis"] == "0.00" and lines["truck"]["accumulated"] == "10000.00"
    rows, lines = year_dep(a, 2031)
    assert rows == [] and lines == {}                              # fully depreciated: nothing left to show


def test_macrs_mid_quarter_applies_when_over_40_percent_in_last_quarter():
    a = [asset("desk", "7-year", "2025-02-10", "10000"), asset("press", "7-year", "2025-11-20", "100000")]
    _, lines = year_dep(a, 2025)
    assert lines["desk"]["convention"] == "Mid-quarter" and lines["press"]["convention"] == "Mid-quarter"
    assert lines["desk"]["macrs"] == "2500.00"                    # Q1: 25.00%
    assert lines["press"]["macrs"] == "3570.00"                   # Q4: 3.57%


def test_macrs_exactly_40_percent_stays_half_year():
    a = [asset("a", "5-year", "2025-02-10", "60000"), asset("b", "5-year", "2025-11-20", "40000")]
    _, lines = year_dep(a, 2025)
    assert lines["a"]["convention"] == "Half-year" and lines["b"]["convention"] == "Half-year"


def test_macrs_section_179_is_left_out_of_the_40_percent_test():
    a = [asset("a", "5-year", "2025-02-10", "60000"),
         asset("b", "5-year", "2025-11-20", "100000", section_179="70000")]
    _, lines = year_dep(a, 2025)                                  # 30,000 of 90,000 is 33%
    assert lines["a"]["convention"] == "Half-year"
    assert lines["b"]["section_179"] == "70000.00" and lines["b"]["macrs"] == "6000.00"   # 30,000 x 20%


def test_macrs_real_property_is_not_in_the_40_percent_test():
    a = [asset("a", "5-year", "2025-02-10", "60000"), asset("b", "5-year", "2025-03-10", "10000"),
         asset("shop", "39-year", "2025-11-20", "1000000")]
    _, lines = year_dep(a, 2025)
    assert lines["a"]["convention"] == "Half-year" and lines["shop"]["convention"] == "Mid-month"


def test_macrs_bonus_depreciation():
    a = [asset("laptops", "5-year", "2025-04-01", "10000", bonus_percent="60")]
    _, lines = year_dep(a, 2025)
    ln = lines["laptops"]
    assert ln["bonus"] == "6000.00" and ln["macrs"] == "800.00" and ln["depreciation"] == "6800.00"
    assert ln["remaining_basis"] == "3200.00"
    _, lines = year_dep(a, 2026)
    assert lines["laptops"]["bonus"] == "0.00" and lines["laptops"]["macrs"] == "1280.00"


def test_macrs_39_year_building():
    a = [asset("shop", "39-year", "2025-01-15", "1000000")]
    _, l25 = year_dep(a, 2025)
    _, l26 = year_dep(a, 2026)
    assert l25["shop"]["macrs"] == "24610.00" and l26["shop"]["macrs"] == "25640.00"


def test_macrs_27_5_year_rental_placed_in_july():
    a = [asset("flat", "27.5-year", "2025-07-05", "275000")]
    _, l25 = year_dep(a, 2025)
    _, l26 = year_dep(a, 2026)
    assert l25["flat"]["macrs"] == "4584.25"                      # 1.667%
    assert l26["flat"]["macrs"] == "9999.00"                      # 3.636% (the IRS table figure, not exactly 1/27.5)


def test_macrs_sale_year_takes_half_and_then_stops():
    a = [asset("van", "5-year", "2025-03-01", "10000"), mv("5-year", DISPOSAL, "2026-08-01", "4000", asset_ref="van")]
    _, l26 = year_dep(a, 2026)
    assert l26["van"]["macrs"] == "1600.00" and l26["van"]["disposed"] == "2026-08-01"
    rows, l27 = year_dep(a, 2027)
    assert l27 == {} and rows == []


def test_macrs_asset_sold_in_year_bought_is_left_out_of_the_40_percent_test():
    a = [asset("a", "5-year", "2025-02-10", "10000"), asset("b", "5-year", "2025-11-20", "9000"),
         mv("5-year", DISPOSAL, "2025-12-01", "9000", asset_ref="b")]
    _, lines = year_dep(a, 2025)
    assert lines["a"]["convention"] == "Half-year"


def test_macrs_non_calendar_fiscal_year():
    fy = fiscal_year_containing(date(2025, 5, 1), "AD", 4)        # 2025-04-01 .. 2026-03-31
    a = [asset("x", "5-year", "2026-03-10", "10000"), asset("y", "5-year", "2025-04-10", "100000")]   # x: month 12, quarter 4
    rows, lines = us.compute_year(a, fy, lambda d: fiscal_year_containing(d, "AD", 4))
    assert {ln["asset"]: ln["macrs"] for ln in lines}["x"] == "2000.00" and us.quarter_in_year(date(2026, 3, 10), fy) == 4 and us.month_in_year(date(2025, 4, 1), fy) == 1


def test_macrs_rows_group_by_class_and_total():
    a = [asset("a", "5-year", "2025-03-01", "10000"), asset("b", "5-year", "2025-03-02", "20000"), asset("c", "7-year", "2025-03-03", "5000")]
    rows, _ = year_dep(a, 2025)
    r5 = row_of(rows, "5-year")
    assert r5["assets"] == "2" and r5["cost"] == "30000.00" and r5["macrs"] == "6000.00"
    assert us.totals(rows)["depreciation"] == "6714.50"          # 6000 + 5000 x 14.29%


def test_macrs_refuses_bad_inputs():
    with pytest.raises(ValueError, match="same asset reference"):
        year_dep([asset("a", "5-year", "2025-03-01", "1"), asset("a", "5-year", "2025-03-02", "1")], 2025)
    with pytest.raises(ValueError, match="asset_ref"):
        year_dep([mv("5-year", DISPOSAL, "2025-03-01", "1")], 2025)
    with pytest.raises(ValueError, match="before it was placed"):
        year_dep([asset("a", "5-year", "2025-03-01", "1"), mv("5-year", DISPOSAL, "2025-01-01", "1", asset_ref="a")], 2025)
    with pytest.raises(ValueError, match="Section 179"):
        year_dep([asset("a", "5-year", "2025-03-01", "100", section_179="200")], 2025)
    with pytest.raises(ValueError, match="bonus percent"):
        year_dep([asset("a", "5-year", "2025-03-01", "100", bonus_percent="150")], 2025)
    with pytest.raises(ValueError, match="real property"):
        year_dep([asset("a", "39-year", "2025-03-01", "100", bonus_percent="50")], 2025)
    with pytest.raises(ValueError, match="not a MACRS class"):
        us.recovery_class("12-year")


def test_macrs_class_names():
    assert us.recovery_class("5-year") == "5" and us.recovery_class(" 27.5 year ") == "27.5" and us.recovery_class("39") == "39"


# ── The service's pure parts: choosing and checking inputs, and rolling forward ─────────────────────────

NP = service.Scheme("NP", "BS", 4)
IN = service.Scheme("IN", "AD", 4)
US = service.Scheme("US", "AD", 1)


def test_pool_codes_are_checked_per_country():
    assert NP.pool_code("b") == "B" and NP.pool_code("E-licence") == "E-licence"
    for bad in ("F", "AB", "", "E-"):
        with pytest.raises(ValueError):
            NP.pool_code(bad)
    assert IN.pool_code("plant") == "PLANT" and IN.pool_code("bldg res") == "BLDG_RES"
    with pytest.raises(ValueError):
        IN.pool_code("A")
    assert US.pool_code("5") == "5-year" and US.pool_code("27.5 year") == "27.5-year"


def test_movement_checks():
    ok = NP.clean_movement({"kind": "addition", "pool": "b", "event_date": "2025-01-01", "amount": "100.5"})
    assert ok["kind"] == ADDITION and ok["pool"] == "B" and ok["amount"] == D("100.50")
    for bad, msg in (({"kind": "X"}, "kind"),
                     ({"kind": "ADDITION", "pool": "B", "event_date": "2025-13-01", "amount": "1"}, "date"),
                     ({"kind": "ADDITION", "pool": "B", "event_date": "2025-01-01", "amount": "-1"}, "amount"),
                     ({"kind": "ADDITION", "pool": "B", "event_date": "2025-01-01", "amount": "0"}, "more than zero"),
                     ({"kind": "ADDITION", "pool": "B", "event_date": "2025-01-01", "amount": "1", "details": {"asset_ref": "x"}}, "not used"),
                     ({"kind": "ADDITION", "pool": "E", "event_date": "2025-01-01", "amount": "1"}, "life_years")):
        with pytest.raises(ValueError, match=msg):
            NP.clean_movement(bad)


def test_opening_balance_must_be_the_first_day_of_a_fiscal_year():
    NP.clean_movement({"kind": "OPENING", "pool": "A", "event_date": "2024-07-16", "amount": "1"})
    with pytest.raises(ValueError, match="first day of a fiscal year"):
        NP.clean_movement({"kind": "OPENING", "pool": "A", "event_date": "2024-07-17", "amount": "1"})
    IN.clean_movement({"kind": "OPENING", "pool": "PLANT", "event_date": "2025-04-01", "amount": "1"})
    with pytest.raises(ValueError, match="first day"):
        IN.clean_movement({"kind": "OPENING", "pool": "PLANT", "event_date": "2025-01-01", "amount": "1"})


def test_us_has_no_opening_balance_and_needs_an_asset_reference():
    with pytest.raises(ValueError, match="no opening balance"):
        US.clean_movement({"kind": "OPENING", "pool": "5-year", "event_date": "2025-01-01", "amount": "1"})
    with pytest.raises(ValueError, match="asset_ref"):
        US.clean_movement({"kind": "ADDITION", "pool": "5-year", "event_date": "2025-01-01", "amount": "1"})
    ok = US.clean_movement({"kind": "ADDITION", "pool": "5", "event_date": "2025-01-01", "amount": "100",
                            "details": {"asset_ref": "van", "section_179": "40", "bonus_percent": "50"}})
    assert ok["details"] == {"asset_ref": "van", "section_179": "40.00", "bonus_percent": "50.00"}
    with pytest.raises(ValueError, match="Section 179"):
        US.clean_movement({"kind": "ADDITION", "pool": "5", "event_date": "2025-01-01", "amount": "100",
                           "details": {"asset_ref": "v", "section_179": "400"}})


def test_rate_checks():
    ok = NP.clean_rate({"pool": "b", "rate": "33.33", "effective_from": "2024-07-16", "note": "x"})
    assert ok["rate"] == D("33.33")
    for bad in ({"pool": "B", "rate": "101", "effective_from": "2024-07-16"}, {"pool": "B", "rate": "-1", "effective_from": "2024-07-16"},
                {"pool": "B", "rate": "abc", "effective_from": "2024-07-16"}, {"pool": "B", "rate": "5", "effective_from": "nope"},
                {"pool": "B", "rate": "5.1234567", "effective_from": "2024-07-16"}):
        with pytest.raises(ValueError):
            NP.clean_rate(bad)
    with pytest.raises(ValueError, match="IRS tables"):
        US.clean_rate({"pool": "5-year", "rate": "20", "effective_from": "2025-01-01"})


def test_roll_forward_nepal_across_years_matches_hand_calculation():
    moves = [mv("B", OPENING, "2024-07-16", "100000"), mv("B", ADDITION, "2024-09-01", "30000"),
             mv("B", ADDITION, "2025-02-20", "60000")]
    year1 = fiscal_year_containing(date(2025, 1, 1), "BS", 4)
    year2 = fiscal_year_containing(date(2025, 12, 1), "BS", 4)
    rows1, _ = service.roll_forward(NP, [Movement(**{**m.__dict__, "details": dict(m.details)}) for m in moves], [], year1)
    assert row_of(rows1, "B")["closing"] == "127500.00"
    rows2, _ = service.roll_forward(NP, moves, [], year2)
    assert row_of(rows2, "B")["closing"] == "110625.00" and row_of(rows2, "B")["opening"] == "127500.00"


def test_roll_forward_with_a_later_opening_balance_resets_the_pool():
    moves = [mv("A", OPENING, "2024-07-16", "100000"), mv("A", OPENING, "2025-07-17", "50000")]
    year2 = fiscal_year_containing(date(2025, 12, 1), "BS", 4)
    rows, _ = service.roll_forward(NP, moves, [], year2)
    r = row_of(rows, "A")
    assert r["opening"] == "50000.00" and r["depreciation"] == "2500.00"


def test_roll_forward_pool_e_opening_state():
    moves = [mv("E", OPENING, "2024-07-16", "90000", life_years="4", accumulated="30000")]
    rows, _ = service.roll_forward(NP, moves, [], NP_FY)
    r = row_of(rows, "E")
    assert r["opening"] == "90000.00" and r["depreciation"] == "30000.00" and r["closing"] == "60000.00"


def test_roll_forward_india_two_years():
    moves = [mv("PLANT", OPENING, "2025-04-01", "100000"), mv("PLANT", ADDITION, "2025-06-01", "50000")]
    y2 = fiscal_year_containing(date(2026, 8, 1), "AD", 4)
    rows, _ = service.roll_forward(IN, moves, [], y2)
    # year 1: 150,000 x 15% = 22,500 -> 127,500; year 2: 127,500 x 15% = 19,125 -> 108,375
    r = row_of(rows, "PLANT")
    assert r["opening"] == "127500.00" and r["depreciation"] == "19125.00" and r["closing"] == "108375.00"


def test_roll_forward_with_no_data_is_empty():
    assert service.roll_forward(NP, [], [], NP_FY) == ([], [])
    assert service.roll_forward(IN, [mv("PLANT", OPENING, "2030-04-01", "5")], [], IN_FY) == ([], [])


def test_roll_forward_us_uses_every_earlier_year():
    moves = [asset("truck", "5-year", "2024-03-01", "10000")]
    rows, lines = service.roll_forward(US, moves, [], cy(2025))
    assert lines[0]["macrs"] == "3200.00" and lines[0]["accumulated"] == "5200.00"


def test_every_scheme_has_notes_and_names():
    for code in service.SCHEMES:
        assert service.SCHEME_NOTES[code] and service.SCHEME_NAMES[code]
        assert all(c["key"] and c["label"] for c in service.SCHEMES[code].COLUMNS)