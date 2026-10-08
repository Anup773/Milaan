
"""Pure-logic tests for engine.reconciliation (registry + helpers) -- no database."""
from decimal import Decimal

import pytest

from engine.reconciliation import registry as reg
from engine.reconciliation.registry import ReconContext, RuleResult, result, run_rules, summarize
from engine.reconciliation.rules import compare_account_totals

D = Decimal


@pytest.fixture
def temp_rules():
    """Register throw-away rules for a test and always remove them afterwards."""
    added = []

    def add(rule_id, fn, scope="ledger"):
        reg.register_rule(rule_id, f"title {rule_id}", "d", scope)(fn)
        added.append(rule_id)

    yield add
    for rid in added:
        reg.RULES.pop(rid, None)


def ctx():
    return ReconContext(None, "c", "p")  # no database needed for these


def test_built_in_rules_are_all_registered_with_titles_and_scope():
    import engine.reconciliation.repository  # noqa: F401 -- registers the built-ins
    cat = {r["id"]: r for r in reg.catalog()}
    for rid in ("trial_balance_balanced", "balance_sheet_balanced", "fixed_asset_accumulated_depreciation",
                "depreciation_posted_for_period", "source_rows_with_errors", "source_rows_in_ledger",
                "adjustments_pending_review"):
        assert rid in cat and cat[rid]["title"] and cat[rid]["description"]
    assert cat["balance_sheet_balanced"]["scope"] == "scenario"
    assert cat["trial_balance_balanced"]["scope"] == "ledger"


def test_a_rule_runs_and_its_title_comes_from_the_registry(temp_rules):
    temp_rules("t_ok", lambda c: result("t_ok", reg.PASS, "fine", x=1))
    [r] = run_rules(ctx(), ["t_ok"])
    assert (r.status, r.message, r.title, r.details["x"]) == ("PASS", "fine", "title t_ok", 1)


def test_a_crashing_rule_is_reported_as_error_never_skipped_or_passed(temp_rules):
    def boom(c):
        raise RuntimeError("database fell over")
    temp_rules("t_boom", boom)
    [r] = run_rules(ctx(), ["t_boom"])
    assert r.status == "ERROR" and "could not run" in r.message and "database fell over" in r.message
    assert r.details["crashed"] is True


def test_one_crash_does_not_stop_the_other_rules(temp_rules):
    def boom(c):
        raise RuntimeError("x")
    temp_rules("t_a", lambda c: result("t_a", reg.PASS, "a"))
    temp_rules("t_b", boom)
    temp_rules("t_c", lambda c: result("t_c", reg.WARNING, "c"))
    assert [r.status for r in run_rules(ctx(), ["t_a", "t_b", "t_c"])] == ["PASS", "ERROR", "WARNING"]


def test_a_rule_returning_a_made_up_status_is_an_error(temp_rules):
    temp_rules("t_bad", lambda c: RuleResult("t_bad", "", "MAYBE", "hm"))
    [r] = run_rules(ctx(), ["t_bad"])
    assert r.status == "ERROR"


def test_unknown_rule_id_is_a_value_error():
    with pytest.raises(ValueError, match="unknown rule"):
        run_rules(ctx(), ["nope"])


def test_registering_a_rule_twice_is_refused(temp_rules):
    temp_rules("t_dup", lambda c: result("t_dup", reg.PASS, "x"))
    with pytest.raises(ValueError):
        reg.register_rule("t_dup", "t", "d")(lambda c: result("t_dup", reg.PASS, "x"))


def test_result_rejects_unknown_status():
    with pytest.raises(ValueError):
        result("r", "MAYBE", "x")


def mk(*statuses):
    return [RuleResult(f"r{i}", "t", s, "m") for i, s in enumerate(statuses)]


def test_overall_error_beats_warning_beats_pass():
    assert summarize(mk("PASS", "WARNING", "ERROR"))["overall_status"] == "ERROR"
    assert summarize(mk("PASS", "WARNING", "PASS"))["overall_status"] == "WARNING"
    assert summarize(mk("PASS", "PASS"))["overall_status"] == "PASS"


def test_not_checked_does_not_spoil_a_pass_but_is_always_counted():
    s = summarize(mk("PASS", "NOT_CHECKED", "NOT_CHECKED"))
    assert s["overall_status"] == "PASS" and s["counts"]["NOT_CHECKED"] == 2


def test_counts_cover_every_status():
    assert summarize(mk("PASS", "ERROR"))["counts"] == {"PASS": 1, "WARNING": 0, "ERROR": 1, "NOT_CHECKED": 0}


def test_context_values_apply_what_if_overrides():
    from engine.dependency_graph.registry import GraphModel, NodeSpec
    model = GraphModel([NodeSpec(id="a", label="a", kind="ledger", value=D("10.00")),
                        NodeSpec(id="b", label="b", kind="statement", formula="sum", inputs=("a",))])
    assert ReconContext(None, "c", "p", None, model).values()["b"] == D("10.00")
    c2 = ReconContext(None, "c", "p", {"a": D("99.00")}, model)
    assert c2.has_overrides and c2.values()["b"] == D("99.00")


def test_shared_accumulated_depreciation_account_matches_when_totals_add_up():
    # two machines share one account: schedule total is the SUM, compared once
    assert compare_account_totals({"acc1": D("300.00")}, {"acc1": D("300.00")}, {"acc1": "1510 Accum"}) == []


def test_mismatch_is_reported_with_the_difference():
    bad = compare_account_totals({"acc1": D("300.00")}, {"acc1": D("250.00")}, {"acc1": "1510 Accum"})
    assert len(bad) == 1 and bad[0]["difference"] == D("-50.00") and bad[0]["account"] == "1510 Accum"


def test_account_missing_from_ledger_counts_as_zero():
    bad = compare_account_totals({"acc1": D("100.00")}, {}, {"acc1": "1510 Accum"})
    assert bad[0]["ledger"] == D("0.00") and bad[0]["difference"] == D("-100.00")