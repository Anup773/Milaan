"""Country profiles, whole-unit rounding, the comparison helper and the audit vocabulary (Phase 24). No database needed."""
from decimal import Decimal

import pytest

from engine.audit import policy as audit_policy
from engine.ledger import rounding
from engine.ledger.checks import ERROR, FIGURE_LABELS, PASS, compare
from engine.policy import countries, model
from engine.schedules.tax_dep import service

D = Decimal
BASE = {"depreciation_method": "STRAIGHT_LINE", "depreciation_start": "ACQUISITION_MONTH", "default_useful_life_months": 60,
        "capitalization_threshold": "5000", "review_min_amount": "1000", "review_large_amount": "100000"}


@pytest.mark.parametrize("code", sorted(countries.PROFILES))
def test_every_countrys_suggestion_is_a_legal_policy(code):
    clean = model.validate({**BASE, **countries.profile_for(code).suggested_policy()})
    assert clean["jurisdiction"] == code


def test_full_support_countries_have_a_scheme_and_basic_ones_do_not():
    for code, profile in countries.PROFILES.items():
        assert (profile.support == "full") == (profile.tax_depreciation_scheme is not None), code
        assert (profile.support == "full") == (code in service.SCHEMES), code


def test_the_three_target_countries_are_set_up_as_expected():
    np_, in_, us_ = (countries.profile_for(c) for c in ("NP", "IN", "US"))
    assert (np_.calendar, np_.fiscal_year_start_month, np_.currency, np_.date_order) == ("BS", 4, "NPR", "DMY")
    assert (in_.calendar, in_.fiscal_year_start_month, in_.currency, in_.number_grouping) == ("AD", 4, "INR", "INDIAN")
    assert (us_.calendar, us_.fiscal_year_start_month, us_.currency, us_.date_order, us_.number_grouping) == ("AD", 1, "USD", "MDY", "WESTERN")
    assert us_.statements["profit_and_loss"] == "Income Statement" and "LIFO" in us_.inventory_methods


def test_each_guide_says_built_partial_or_not_built_and_never_overclaims():
    for profile in countries.PROFILES.values():
        assert profile.guide
        for g in profile.guide:
            assert g["status"] in (countries.BUILT, countries.PARTIAL, countries.NOT_BUILT) and g["text"] and g["topic"]
    # things that are not built must not be listed as built
    for code in ("NP", "IN", "US"):
        built = " ".join(g["topic"] for g in countries.profile_for(code).guide if g["status"] == countries.BUILT).lower()
        for missing in ("deferred tax", "vat", "gst", "payroll", "lease"):
            assert missing not in built, (code, missing)


def test_a_company_cannot_choose_another_countrys_framework():
    with pytest.raises(ValueError):
        model.validate({**BASE, **countries.profile_for("NP").suggested_policy(), "accounting_framework": "US GAAP"})
    with pytest.raises(ValueError):
        model.validate({**BASE, **countries.profile_for("US").suggested_policy(), "calendar": "BS"})


def test_lifo_only_under_us_gaap_or_local_gaap():
    us = {**BASE, **countries.profile_for("US").suggested_policy()}
    assert model.validate({**us, "inventory_valuation_method": "LIFO"})["inventory_valuation_method"] == "LIFO"
    with pytest.raises(ValueError, match="LIFO"):
        model.validate({**us, "accounting_framework": "IFRS", "inventory_valuation_method": "LIFO"})
    with pytest.raises(ValueError, match="LIFO"):
        model.validate({**BASE, **countries.profile_for("IN").suggested_policy(), "inventory_valuation_method": "LIFO"})


# ── whole-unit statements ───────────────────────────────────────────────────────────────────────────────

def test_tolerance_and_agreement():
    assert rounding.tolerance("EXACT") == 0 and rounding.tolerance("WHOLE") == 1
    assert rounding.agree(D("100.00"), D("100.00"), "EXACT") and not rounding.agree(D("100.00"), D("100.01"), "EXACT")
    assert rounding.agree(D("100"), D("101"), "WHOLE") and not rounding.agree(D("100"), D("101.01"), "WHOLE")
    with pytest.raises(ValueError):
        rounding.tolerance("SOMETIMES")


def test_round_unit_halves_go_away_from_zero():
    assert rounding.round_unit(D("2.5")) == 3 and rounding.round_unit(D("-2.5")) == -3 and rounding.round_unit(D("2.4999")) == 2


def test_presented_section_shows_the_footing_difference_instead_of_hiding_it():
    # three lines of x.5 each round up; the total 1.5 x 3 = 4.5 rounds to 5, the lines add to 6
    section = rounding.present_section([D("1.5"), D("1.5"), D("1.5")], D("4.5"))
    assert section["lines"] == [2, 2, 2] and section["total"] == 5 and section["footing_difference"] == -1


def test_presented_equity_has_one_rounding_line():
    eq = {"components": [{"closing": D("0.4")}, {"closing": D("0.4")}, {"closing": D("0.4")}], "totals": {"closing": D("1.2")}}
    out = rounding.present_equity(eq)
    assert out["closing_total"] == 1 and out["rounding"] == 1


def test_compare_marks_agreement_within_the_company_tolerance():
    exact = compare("Net profit", D("250000.20"), D("250000"), "EXACT", "ledger", "printed")
    whole = compare("Net profit", D("250000.20"), D("250000"), "WHOLE", "ledger", "printed")
    assert exact["status"] == ERROR and whole["status"] == PASS and "within rounding" in whole["message"]
    assert compare("x", D("5"), D("5"), "EXACT", "a", "b")["message"].endswith("agree.")


def test_figure_labels_cover_the_main_statement_totals():
    assert {"total_assets", "total_liabilities", "total_equity", "net_profit", "closing_cash"} <= set(FIGURE_LABELS)


# ── the audit trail knows the new tables and actions (they are written by the 0014 triggers) ────────

def test_audit_vocabulary_has_the_tax_depreciation_events():
    for action in ("tax_pool.add", "tax_pool.change", "tax_pool.remove", "tax_rate.set", "tax_rate.change", "tax_rate.remove"):
        assert audit_policy.action_label(action) != action, action
    for object_type in ("tax_pool_movement", "tax_depreciation_rate"):
        assert audit_policy.object_label(object_type) != object_type, object_type