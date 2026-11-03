"""Phase 22 -- the company accounting policy: validation, defaults, who may change it, the depreciation convention it
sets, and the checks that keep this module, the migration and the code that reads it in step."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from engine import policy
from engine.audit import policy as audit_pol
from engine.exceptions import Thresholds
from engine.policy import model
from engine.policy.repository import applicable_rule_sets
from engine.schedules.fixed_assets import FixedAsset, compute_period_depreciation, months_of_depreciation_in_period

ENGINE_DIR = Path(__file__).resolve().parents[2]
MIGRATION = ENGINE_DIR / "migrations" / "0012_accounting_policies.sql"
MIGRATION_24 = ENGINE_DIR / "migrations" / "0014_country_profiles_tax_depreciation.sql"
# These tests read the SQL migrations; the engine can also be tested without them next to it, so they skip rather than fail.
NEEDS_MIGRATIONS = pytest.mark.skipif(not (MIGRATION.exists() and MIGRATION_24.exists()), reason="migrations/ not found")


def good(**over):
    base = {
        "accounting_framework": "Ind AS", "jurisdiction": "IN", "currency": "INR", "fiscal_year_start_month": 4,
        "tax_regime": "GST", "depreciation_method": "STRAIGHT_LINE", "depreciation_start": "ACQUISITION_MONTH",
        "default_useful_life_months": 60, "capitalization_threshold": "5000", "inventory_valuation_method": "FIFO",
        "review_min_amount": "1000", "review_large_amount": "100000",
        "calendar": "AD", "date_order": "DMY", "number_grouping": "INDIAN", "statement_rounding": "EXACT",
    }
    base.update(over)
    return base


# ── validation ───────────────────────────────────────────────────────────
def test_a_good_policy_is_accepted_and_tidied():
    clean = model.validate(good(jurisdiction="in", currency="inr", tax_regime="gst", accounting_framework="ind as"))
    assert clean["jurisdiction"] == "IN" and clean["currency"] == "INR" and clean["tax_regime"] == "GST"
    assert clean["accounting_framework"] == "Ind AS"
    assert clean["capitalization_threshold"] == Decimal("5000.00") and clean["review_large_amount"] == Decimal("100000.00")
    assert list(clean) == list(model.FIELDS)


def test_the_useful_life_is_optional():
    assert model.validate(good(default_useful_life_months=None))["default_useful_life_months"] is None
    data = good()
    del data["default_useful_life_months"]
    assert model.validate(data)["default_useful_life_months"] is None


def test_every_other_setting_is_required():
    for field in model.FIELDS:
        if field in model.OPTIONAL_FIELDS:
            continue
        data = good()
        del data[field]
        with pytest.raises(ValueError, match="required"):
            model.validate(data)
        with pytest.raises(ValueError, match="required"):
            model.validate(good(**{field: ""}))


def test_zero_is_a_real_value_not_a_missing_one():
    clean = model.validate(good(capitalization_threshold=0, review_min_amount=0))
    assert clean["capitalization_threshold"] == Decimal("0.00") and clean["review_min_amount"] == Decimal("0.00")


@pytest.mark.parametrize("over,message", [
    ({"accounting_framework": "Made-up GAAP"}, "accounting_framework must be one of"),
    ({"accounting_framework": 5}, "accounting_framework must be one of"),
    ({"jurisdiction": "ZZ"}, "jurisdiction must be one of"),
    ({"jurisdiction": None}, "required"),
    ({"currency": "XXX"}, "currency must be one of"),
    ({"fiscal_year_start_month": 0}, "1 to 12"),
    ({"fiscal_year_start_month": 13}, "1 to 12"),
    ({"fiscal_year_start_month": "4"}, "1 to 12"),
    ({"fiscal_year_start_month": True}, "1 to 12"),
    ({"fiscal_year_start_month": 4.5}, "1 to 12"),
    ({"tax_regime": "SALES"}, "tax_regime must be one of"),
    ({"depreciation_method": "WRITTEN_DOWN_VALUE"}, "depreciation_method must be one of"),
    ({"depreciation_start": "MID_MONTH"}, "depreciation_start must be one of"),
    ({"inventory_valuation_method": "LIFO"}, "LIFO is allowed only"),
    ({"inventory_valuation_method": "FILO"}, "inventory_valuation_method must be one of"),
    ({"calendar": "HIJRI"}, "calendar must be one of"),
    ({"date_order": "YMD"}, "date_order must be one of"),
    ({"number_grouping": "SWISS"}, "number_grouping must be one of"),
    ({"statement_rounding": "THOUSANDS"}, "statement_rounding must be one of"),
    ({"calendar": "BS"}, "for Nepal only"),
    ({"accounting_framework": "NFRS"}, "framework of Nepal only"),
    ({"accounting_framework": "US GAAP"}, "framework of United States only"),
    ({"default_useful_life_months": 0}, "1 to 1200"),
    ({"default_useful_life_months": 1201}, "1 to 1200"),
    ({"default_useful_life_months": "sixty"}, "1 to 1200"),
    ({"capitalization_threshold": -1}, "cannot be negative"),
    ({"capitalization_threshold": "abc"}, "must be an amount"),
    ({"capitalization_threshold": "NaN"}, "must be an amount"),
    ({"capitalization_threshold": "Infinity"}, "must be an amount"),
    ({"capitalization_threshold": 12.5}, "must be an amount"),
    ({"capitalization_threshold": True}, "must be an amount"),
    ({"capitalization_threshold": "10.005"}, "two decimal places"),
    ({"capitalization_threshold": "1" + "0" * 16}, "too large"),
    ({"review_min_amount": 500, "review_large_amount": 100}, "cannot be smaller"),
])
def test_bad_values_are_refused_with_a_clear_message(over, message):
    with pytest.raises(ValueError, match=message):
        model.validate(good(**over))


def test_unknown_settings_are_refused_not_ignored():
    with pytest.raises(ValueError, match="unknown setting"):
        model.validate(good(colour="red"))


def test_a_policy_must_be_an_object():
    with pytest.raises(ValueError, match="must be an object"):
        model.validate([1, 2])  # type: ignore[arg-type]


def test_the_large_amount_may_equal_the_small_one():
    assert model.validate(good(review_min_amount=100, review_large_amount=100))


def test_framework_options_follow_the_rules_catalog():
    opts = model.framework_options()
    assert opts[-1] == "Local GAAP" and {"IFRS", "Ind AS", "NFRS", "FRS 102"} <= set(opts)
    assert "ISA" not in opts and "GST" not in opts and "ANY" not in opts          # only accounting frameworks


def test_a_new_framework_in_the_catalog_becomes_a_choice(monkeypatch):
    from engine.rules import registry as reg
    before = dict(reg.RULE_SETS)
    try:
        reg.register_rule_set(reg.RuleSet(id="xx-gaap", family="accounting", title="X", framework="XGAAP", jurisdiction="XX",
                                          authority="a", status=reg.CATALOG_ONLY, description="d", items=(reg.item("i", "I", "d"),)))
        assert model.validate(good(accounting_framework="xgaap"))["accounting_framework"] == "XGAAP"
    finally:
        reg.RULE_SETS.clear()
        reg.RULE_SETS.update(before)


# ── defaults ─────────────────────────────────────────────────────────────
def test_defaults_keep_the_behaviour_milaan_had_before_policies():
    d = model.DEFAULTS
    assert d["depreciation_start"] == "ACQUISITION_MONTH" and d["depreciation_method"] == "STRAIGHT_LINE"
    assert d["capitalization_threshold"] == 0 and d["default_useful_life_months"] is None


def test_review_defaults_equal_the_detectors_own_defaults():
    th = Thresholds()
    assert model.DEFAULTS["review_min_amount"] == th.min_amount
    assert model.DEFAULTS["review_large_amount"] == th.large_amount


def test_effective_values_use_defaults_without_a_policy_and_the_policy_with_one():
    assert model.effective_values(None) == model.DEFAULTS
    clean = model.validate(good(depreciation_start="NEXT_MONTH", review_min_amount=2500))
    eff = model.effective_values(clean)
    assert eff["depreciation_start"] == "NEXT_MONTH" and eff["review_min_amount"] == Decimal("2500.00")
    assert set(eff) == set(model.DEFAULTS)


def test_every_default_is_itself_a_legal_value():
    clean = model.validate(good(**{k: v for k, v in model.DEFAULTS.items()}))
    for k, v in model.DEFAULTS.items():
        assert clean[k] == v


# ── who may ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("role,exists,ok", [
    ("accountant", False, False), ("senior_accountant", False, True), ("ca", False, True), ("reviewer", False, False), ("admin", False, True),
    ("accountant", True, False), ("senior_accountant", True, False), ("ca", True, True), ("reviewer", True, False), ("admin", True, True),
])
def test_who_may_set_up_and_who_may_change(role, exists, ok):
    assert model.can_write(role, exists) is ok
    if ok:
        model.check_may_write(role, exists)
    else:
        with pytest.raises(PermissionError, match="cannot"):
            model.check_may_write(role, exists)


def test_an_unknown_role_is_a_bad_request_not_a_permission_problem():
    with pytest.raises(ValueError, match="role must be one of"):
        model.check_may_write("janitor", False)
    assert model.can_write("janitor", False) is False


# ── reasons and changes ───────────────────────────────────────────────────
def test_a_reason_is_needed_to_change_but_not_to_set_up():
    assert model.clean_reason(None, required=False) is None
    assert model.clean_reason("  ", required=False) is None
    with pytest.raises(ValueError, match="say why"):
        model.clean_reason(None, required=True)
    with pytest.raises(ValueError, match="say why"):
        model.clean_reason("   ", required=True)
    assert model.clean_reason("  new auditor advice ", required=True) == "new auditor advice"
    with pytest.raises(ValueError, match="too long"):
        model.clean_reason("x" * 501, required=True)
    with pytest.raises(ValueError, match="must be text"):
        model.clean_reason(5, required=True)


def test_changed_settings_lists_only_what_differs_in_screen_order():
    old = model.validate(good())
    assert model.changed_settings(old, old) == []
    new = model.validate(good(currency="USD", review_min_amount=1500, depreciation_start="NEXT_MONTH"))
    assert model.changed_settings(old, new) == ["currency", "depreciation_start", "review_min_amount"]
    assert model.changed_settings(None, new) == list(model.FIELDS)
    # 5000 and 5000.00 are the same amount
    assert model.changed_settings(old, model.validate(good(capitalization_threshold="5000.00"))) == []


def test_only_the_depreciation_settings_are_locked_once_depreciation_is_posted():
    assert model.depreciation_locked(["currency", "depreciation_start"]) == ["depreciation_start"]
    assert model.depreciation_locked(["currency", "review_min_amount"]) == []
    assert set(model.DEPRECIATION_LOCKED_FIELDS) <= set(model.FIELDS)
    assert set(model.LOCKED_NAMES) == set(model.DEPRECIATION_LOCKED_FIELDS)


# ── every setting says what reads it ─────────────────────────────────────
def test_every_setting_has_a_label_and_a_statement_of_what_reads_it():
    assert set(model.FIELD_LABELS) == set(model.FIELD_USE) == set(model.FIELDS)
    recorded_only = [f for f, text in model.FIELD_USE.items() if "no schedule reads it yet" in text or "no inventory schedule" in text]
    assert set(recorded_only) == {"currency", "inventory_valuation_method"}


def test_options_cover_every_legal_value():
    o = model.options()
    assert {x["value"] for x in o["countries"]} == set(model.COUNTRIES)
    assert {x["value"] for x in o["currencies"]} == set(model.CURRENCIES)
    assert [x["value"] for x in o["months"]] == list(range(1, 13))
    assert {x["value"] for x in o["tax_regimes"]} == set(model.TAX_REGIMES)
    assert {x["value"] for x in o["depreciation_starts"]} == set(model.DEPRECIATION_STARTS)
    assert {x["value"] for x in o["inventory_methods"]} == set(model.INVENTORY_METHODS)
    assert o["accounting_frameworks"] == model.framework_options()
    json.dumps(o)


# ── the depreciation convention ───────────────────────────────────────────
ASSET = FixedAsset(id="a1", name="Machine", acquisition_date=date(2026, 4, 15), cost=Decimal("12000.00"),
                   salvage_value=Decimal("0.00"), useful_life_months=12, disposed_date=None)
Q1 = (date(2026, 4, 1), date(2026, 6, 30))


def test_default_convention_counts_the_acquisition_month_in_full():
    assert months_of_depreciation_in_period(date(2026, 4, 15), None, *Q1) == 3
    assert compute_period_depreciation(ASSET, *Q1, Decimal("0.00")) == Decimal("3000.00")


def test_next_month_convention_starts_the_month_after_acquisition():
    assert months_of_depreciation_in_period(date(2026, 4, 15), None, *Q1, starts_next_month=True) == 2
    assert compute_period_depreciation(ASSET, *Q1, Decimal("0.00"), True) == Decimal("2000.00")


def test_an_asset_acquired_in_the_last_month_of_a_period_starts_in_the_next_period_under_next_month():
    last_month = date(2026, 6, 20)
    assert months_of_depreciation_in_period(last_month, None, *Q1) == 1
    assert months_of_depreciation_in_period(last_month, None, *Q1, starts_next_month=True) == 0
    q2 = (date(2026, 7, 1), date(2026, 9, 30))
    assert months_of_depreciation_in_period(last_month, None, *q2, starts_next_month=True) == 3


def test_the_two_conventions_charge_the_same_total_over_the_asset_life():
    # Starting a month later must not lose or add cost: the asset still depreciates by exactly cost - salvage.
    for next_month in (False, True):
        accumulated = Decimal("0.00")
        start = date(2026, 4, 1)
        for i in range(30):                         # 30 one-month periods, longer than the 12-month life
            y, m = divmod(start.year * 12 + start.month - 1 + i, 12)
            period = (date(y, m + 1, 1), date(y, m + 1, 28))
            accumulated += compute_period_depreciation(ASSET, *period, accumulated, next_month)
        assert accumulated == Decimal("12000.00"), next_month


def test_next_month_convention_with_a_disposal_in_the_acquisition_month_depreciates_nothing():
    disposed = FixedAsset(id="a2", name="Sold at once", acquisition_date=date(2026, 4, 5), cost=Decimal("1200.00"),
                          salvage_value=Decimal("0.00"), useful_life_months=12, disposed_date=date(2026, 4, 25))
    assert compute_period_depreciation(disposed, *Q1, Decimal("0.00"), True) == Decimal("0.00")
    assert compute_period_depreciation(disposed, *Q1, Decimal("0.00")) == Decimal("100.00")


# ── the rule sets that apply (Phase 21 meets Phase 22) ─────────────────────
def test_no_policy_means_no_rule_sets_are_claimed_to_apply():
    assert applicable_rule_sets(None) == []


def test_an_indian_gst_company_gets_indian_and_international_sets():
    ids = {r["id"] for r in applicable_rule_sets(model.validate(good()))}
    assert {"ind-as", "core-ledger", "isa", "sa-india", "india-gst", "india-tds", "internal-controls"} <= ids
    assert not ids & {"nfrs", "frs-102", "uk-vat", "nepal-vat", "uae-vat", "ifrs"}


def test_the_accounting_framework_chosen_decides_which_accounting_set_is_listed():
    ifrs = {r["id"] for r in applicable_rule_sets(model.validate(good(accounting_framework="IFRS", jurisdiction="GB", tax_regime="VAT")))}
    assert "ifrs" in ifrs and "ind-as" not in ifrs and "uk-vat" in ifrs
    local = {r["id"] for r in applicable_rule_sets(model.validate(good(accounting_framework="Local GAAP", jurisdiction="NP", tax_regime="VAT")))}
    assert "core-ledger" in local and not {"ifrs", "ind-as", "nfrs"} & local          # no standard is claimed for local GAAP
    assert "nepal-vat" in local


def test_a_company_with_no_indirect_tax_gets_no_tax_sets():
    ids = {r["id"] for r in applicable_rule_sets(model.validate(good(tax_regime="NONE")))}
    assert not {"india-gst", "india-tds"} & ids and "ind-as" in ids


# ── the migration and the audit vocabulary agree with the model ────────────
@NEEDS_MIGRATIONS
def test_the_migration_has_a_column_for_every_setting_and_the_same_legal_values():
    sql = MIGRATION.read_text()
    sql24 = MIGRATION_24.read_text()
    body = sql[sql.index("CREATE TABLE accounting_policies"):sql.index(");", sql.index("CREATE TABLE accounting_policies"))]
    columns = set(re.findall(r"^\s{4}([a-z_]+)\s+(?:uuid|text|smallint|integer|numeric|timestamptz)", body, re.M))
    added = set(re.findall(r"ADD COLUMN\s+([a-z_]+)\s+text", sql24))
    assert set(model.FIELDS) <= columns | added, set(model.FIELDS) - columns - added

    def checked(column):
        m = re.search(rf"{column}\s+text NOT NULL[^,]*?IN \(([^)]*)\)", body, re.S)
        return set(re.findall(r"'([A-Z_]+)'", m.group(1)))
    def widened(column):  # migration 0014 replaces these two CHECKs
        m = re.search(rf"CHECK \({column} IN \(([^)]*)\)\)", sql24)
        return set(re.findall(r"'([A-Z_]+)'", m.group(1)))
    assert widened("tax_regime") == set(model.TAX_REGIMES)
    assert checked("depreciation_method") == set(model.DEPRECIATION_METHODS)
    assert checked("depreciation_start") == set(model.DEPRECIATION_STARTS)
    assert widened("inventory_valuation_method") == set(model.INVENTORY_METHODS)
    for column, allowed in (("calendar", model.CALENDARS), ("date_order", model.DATE_ORDERS),
                            ("number_grouping", model.NUMBER_GROUPINGS), ("statement_rounding", model.ROUNDINGS)):
        m = re.search(rf"ADD COLUMN\s+{column}\s+text NOT NULL DEFAULT '([A-Z]+)'\s+CHECK \({column} IN \(([^)]*)\)\)", sql24)
        assert set(re.findall(r"'([A-Z]+)'", m.group(2))) == set(allowed), column
        assert m.group(1) == model.DEFAULTS[column], column      # an existing company keeps today's behaviour
    assert "UNIQUE REFERENCES companies" in body or re.search(r"company_id\s+uuid NOT NULL UNIQUE", body)
    for d in ("depreciation_start", "inventory_valuation_method"):
        assert re.search(rf"{d}\s+text NOT NULL DEFAULT '{model.DEFAULTS[d]}'", body), d
    assert re.search(r"review_min_amount\s+numeric\(18,2\) NOT NULL DEFAULT 1000\.00", body)
    assert re.search(r"review_large_amount\s+numeric\(18,2\) NOT NULL DEFAULT 100000\.00", body)
    assert "REVOKE DELETE ON accounting_policies FROM app_user" in sql
    assert "ENABLE ROW LEVEL SECURITY" in sql and "company_isolation" in sql


@NEEDS_MIGRATIONS
def test_the_migration_only_writes_audit_actions_and_object_types_the_trail_knows():
    sql = MIGRATION.read_text()
    actions = set(re.findall(r"'((?:[a-z_]+)\.(?:[a-z_]+))'", sql)) - {"app.current_user_id", "app.current_company_id"}
    assert actions == {"policy.create", "policy.update"}
    assert actions <= set(audit_pol.ACTIONS)
    types = set(re.findall(r"PERFORM audit_emit\([^,]+,[^,]+,[^,]+,\s*'([a-z_]+)'", sql))
    assert types == {"accounting_policy"} and types <= set(audit_pol.OBJECT_TYPES)
    assert audit_pol.action_label("policy.update") == "Accounting policy changed"
    assert "audit_accounting_policies AFTER INSERT OR UPDATE ON accounting_policies" in sql


def test_the_model_matches_the_columns_the_repository_reads_and_writes():
    from engine.policy import repository
    assert repository._COLUMNS == model.FIELDS


@NEEDS_MIGRATIONS
def test_audit_columns_hold_every_setting_named_in_the_audit_document():
    sql = MIGRATION_24.read_text()
    doc = sql[sql.index("jsonb_build_object("):sql.index("$$;", sql.index("jsonb_build_object("))]
    assert set(re.findall(r"'([a-z_]+)',", doc)) == set(model.FIELDS)


# ── the command line (what the API runs) ──────────────────────────────────
def _cli(*args):
    return subprocess.run([sys.executable, "-m", "engine.policy.cli", *args], cwd=ENGINE_DIR, capture_output=True, text=True)


def _status(out):
    return json.loads(out.stderr.strip().splitlines()[-1])


FIRM = COMPANY = USER = "11111111-1111-1111-1111-111111111111"


@pytest.mark.parametrize("args,status", [
    ((), 2),
    (("get",), 2),
    (("get", "nope", COMPANY, "ca"), 400),            # firm id is not an id
    (("get", FIRM, "nope", "ca"), 400),
    (("get", FIRM, COMPANY), 400),                    # role missing
    (("get", FIRM, COMPANY, "janitor"), 400),
    (("put", FIRM, COMPANY, "nope", "ca", "{}"), 400),
    (("put", FIRM, COMPANY, USER, "janitor", "{}"), 400),
    (("put", FIRM, COMPANY, USER, "ca", "not json"), 400),
    (("put", FIRM, COMPANY, USER, "ca", "[1]"), 400),
    (("put", FIRM, COMPANY, USER), 400),
    (("frobnicate", FIRM, COMPANY), 400),
])
def test_cli_bad_input_is_refused_before_touching_the_database(args, status):
    out = _cli(*args)
    assert out.returncode != 0
    if status == 2:
        assert out.returncode == 2
    else:
        assert _status(out)["status"] == status


# ── the API routes agree with the policy ──────────────────────────────────
ROOT = ENGINE_DIR.parent
POLICY_ROUTES = ROOT / "api" / "src" / "modules" / "policy" / "routes.ts"
ASSET_ROUTES = ROOT / "api" / "src" / "modules" / "schedules" / "routes.ts"


@pytest.mark.skipif(not POLICY_ROUTES.exists(), reason="api/ not next to engine/")
def test_the_route_lets_in_exactly_the_roles_that_may_set_the_policy_up():
    text = POLICY_ROUTES.read_text()
    found = set(re.findall(r'"(\w+)"', re.search(r"const SETUP_ROLES: Role\[\] = \[(.*?)\];", text).group(1)))
    assert found == model.SETUP_ROLES
    assert model.CHANGE_ROLES <= model.SETUP_ROLES        # nobody may change a policy who could not have set it up


@pytest.mark.skipif(not POLICY_ROUTES.exists(), reason="api/ not next to engine/")
def test_every_policy_route_is_behind_authentication_and_the_company_check():
    text = POLICY_ROUTES.read_text()
    assert text.count("policyRouter.") == 2
    assert len(re.findall(r"policyRouter\.(?:get|put)\([^)]*authenticate", text)) == 2
    assert text.count("assertCompanyInFirm(") == 2
    assert "requireRole(...SETUP_ROLES)" in text


@pytest.mark.skipif(not ASSET_ROUTES.exists(), reason="api/ not next to engine/")
def test_adding_a_fixed_asset_reads_the_policy_columns_that_exist():
    text = ASSET_ROUTES.read_text()
    assert "FROM accounting_policies WHERE company_id = $1" in text
    for column in ("capitalization_threshold", "default_useful_life_months"):
        assert column in model.FIELDS and column in text