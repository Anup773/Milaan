"""Pure-logic tests for engine.impact.report -- no database."""
from decimal import Decimal

import pytest

from engine.dependency_graph.registry import GraphModel, NodeSpec
from engine.impact.report import build_impact_report

D = Decimal


def leaf(node_id, value, kind="ledger", label=None, **meta):
    return NodeSpec(id=node_id, label=label or node_id, kind=kind, value=D(value), meta=meta)


def calc(node_id, formula, inputs, kind="statement", params=None, label=None, **meta):
    return NodeSpec(id=node_id, label=label or node_id, kind=kind, formula=formula,
                    inputs=tuple(inputs), params=params or {}, meta=meta)


def model():
    """income 1000, rent 300, depreciation (schedule 200 -> expense account); cash 500; capital 500."""
    return GraphModel([
        leaf("schedule:dep", "200.00", kind="schedule", label="Depreciation posted - Machine"),
        leaf("acct:inc:period", "1000.00", code="4000", name="Sales", account_type="Income", scope="period"),
        leaf("acct:rent:period", "300.00", code="5000", name="Rent", account_type="Expense", scope="period"),
        leaf("acct:exp:period:other", "0.00", code="5100", name="Dep exp", account_type="Expense", scope="period", other_postings=True),
        calc("acct:exp:period", "linear", ["acct:exp:period:other", "schedule:dep"], kind="ledger", params={"coefficients": [1, 1]},
             code="5100", name="Dep exp", account_type="Expense", scope="period"),
        calc("pl:total_income", "sum", ["acct:inc:period"], label="Total income"),
        calc("pl:total_expense", "sum", ["acct:rent:period", "acct:exp:period"], label="Total expense"),
        calc("pl:net_profit", "difference", ["pl:total_income", "pl:total_expense"], label="Net profit"),
        leaf("bs:total_assets", "700.00"),
        leaf("bs:total_liabilities", "0.00"),
        leaf("bs:total_equity", "200.00"),
        calc("bs:retained_earnings", "linear", ["pl:net_profit"], params={"coefficients": [1]}, label="Retained earnings"),
        calc("bs:check", "linear", ["bs:total_assets", "bs:total_liabilities", "bs:total_equity", "bs:retained_earnings"],
             kind="check", params={"coefficients": [1, -1, -1, -1]}),
    ])


def test_net_profit_row_has_current_scenario_delta_and_percent():
    r = build_impact_report(model(), {"schedule:dep": D("100.00")})
    np_row = next(x for x in r["profit_and_loss"] if x["node"] == "pl:net_profit")
    assert (np_row["current"], np_row["scenario"], np_row["delta"]) == (D("500.00"), D("600.00"), D("100.00"))
    assert np_row["pct_change"] == D("20.00")


def test_headline_says_increase_decrease_or_unchanged():
    up = build_impact_report(model(), {"schedule:dep": D("100.00")})["summary"]["headline"]
    down = build_impact_report(model(), {"schedule:dep": D("300.00")})["summary"]["headline"]
    same = build_impact_report(model(), {"schedule:dep": D("200.00")})["summary"]["headline"]
    assert up.startswith("Net profit would increase by 100.00") and "from 500.00 to 600.00" in up
    assert down.startswith("Net profit would decrease by 100.00")
    assert same == "Net profit would be unchanged."


def test_accounts_lists_only_moved_ledger_accounts_not_the_helper_leaf():
    r = build_impact_report(model(), {"schedule:dep": D("100.00")})
    assert [a["code"] for a in r["accounts"]] == ["5100"]
    assert r["accounts"][0]["delta"] == D("-100.00") and r["accounts"][0]["name"] == "Dep exp"


def test_unaffected_statement_lines_show_zero_delta():
    r = build_impact_report(model(), {"schedule:dep": D("100.00")})
    inc = next(x for x in r["profit_and_loss"] if x["node"] == "pl:total_income")
    assert inc["delta"] == D("0.00")
    assert r["summary"]["statement_lines_affected"] == 3  # total expense, net profit, retained earnings


def test_sources_show_what_was_set():
    r = build_impact_report(model(), {"schedule:dep": D("100.00")})
    assert r["sources"][0]["current"] == D("200.00") and r["sources"][0]["scenario"] == D("100.00")


def test_flow_is_in_dependency_order_source_first():
    flow = [f["node"] for f in build_impact_report(model(), {"schedule:dep": D("100.00")})["flow"]]
    assert flow[0] == "schedule:dep"
    assert flow.index("pl:total_expense") < flow.index("pl:net_profit")


def test_balance_check_reports_balanced_after():
    r = build_impact_report(model(), {"schedule:dep": D("100.00")})
    assert r["checks"]["balanced_before"] is True
    assert r["checks"]["balanced_after"] is False  # this toy model feeds profit but not assets
    assert r["summary"]["balanced_after"] is False


def test_percent_is_none_when_current_is_zero():
    r = build_impact_report(model(), {"acct:exp:period:other": D("50.00")})
    row = next(x for x in r["sources"])
    assert row["current"] == D("0.00") and row["pct_change"] is None


def test_override_to_same_value_reports_nothing_changes():
    r = build_impact_report(model(), {"schedule:dep": D("200.00")})
    assert r["summary"]["nothing_changes"] is True and r["accounts"] == []


def test_no_changes_given_is_an_error():
    with pytest.raises(ValueError):
        build_impact_report(model(), {})


def test_computed_or_unknown_nodes_cannot_be_the_source():
    with pytest.raises(ValueError, match="computed"):
        build_impact_report(model(), {"pl:net_profit": D("1.00")})
    with pytest.raises(ValueError, match="unknown"):
        build_impact_report(model(), {"ghost": D("1.00")})


def test_percent_uses_absolute_current_for_negative_figures():
    m = GraphModel([leaf("x", "-200.00"), calc("pl:net_profit", "sum", ["x"])])
    r = build_impact_report(m, {"x": D("-100.00")})
    np_row = r["profit_and_loss"][0]
    assert np_row["delta"] == D("100.00") and np_row["pct_change"] == D("50.00")