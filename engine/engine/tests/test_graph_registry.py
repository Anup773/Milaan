"""Pure-logic tests for engine.dependency_graph.registry -- no database."""
from decimal import Decimal

import pytest

from engine.dependency_graph.graph import CycleError
from engine.dependency_graph.registry import FORMULAS, GraphModel, NodeSpec, register_formula

D = Decimal


def leaf(node_id, value):
    return NodeSpec(id=node_id, label=node_id, kind="ledger", value=D(value))


def calc(node_id, formula, inputs, params=None):
    return NodeSpec(id=node_id, label=node_id, kind="statement", formula=formula, inputs=tuple(inputs), params=params or {})


def small_model():
    """income 1000, rent 300, depreciation 200  ->  net profit 500"""
    return GraphModel([
        leaf("income", "1000.00"), leaf("rent", "300.00"), leaf("depreciation", "200.00"),
        calc("expenses", "sum", ["rent", "depreciation"]),
        calc("net_profit", "difference", ["income", "expenses"]),
    ])


def test_baseline_values_are_computed_from_formulas():
    v = small_model().evaluate()
    assert v["expenses"] == D("500.00") and v["net_profit"] == D("500.00")


def test_recompute_reports_exactly_what_moved_with_before_after_delta():
    r = small_model().recompute({"depreciation": D("120.00")})
    moved = {c["node"]: c for c in r["changes"]}
    assert set(moved) == {"depreciation", "expenses", "net_profit"}
    assert moved["depreciation"]["delta"] == D("-80.00")
    assert moved["expenses"]["before"] == D("500.00") and moved["expenses"]["after"] == D("420.00")
    assert moved["net_profit"]["delta"] == D("80.00")  # less expense, more profit


def test_recompute_lists_changes_in_dependency_order():
    nodes = [c["node"] for c in small_model().recompute({"depreciation": D("0.00")})["changes"]]
    assert nodes == ["depreciation", "expenses", "net_profit"]


def test_recompute_does_not_change_the_model_itself():
    m = small_model()
    m.recompute({"depreciation": D("0.00")})
    assert m.evaluate()["net_profit"] == D("500.00")


def test_unrelated_nodes_are_not_reported():
    nodes = {c["node"] for c in small_model().recompute({"rent": D("0.00")})["changes"]}
    assert "income" not in nodes and "depreciation" not in nodes


def test_override_to_same_value_reports_nothing_changed():
    r = small_model().recompute({"rent": D("300.00")})
    assert r["changes"] == [] and r["downstream_unchanged"] == 2


def test_cannot_override_a_computed_node():
    with pytest.raises(ValueError, match="computed"):
        small_model().recompute({"net_profit": D("1.00")})


def test_cannot_override_an_unknown_node():
    with pytest.raises(ValueError, match="unknown"):
        small_model().recompute({"ghost": D("1.00")})


def test_linear_formula_applies_signs():
    m = GraphModel([leaf("a", "100"), leaf("b", "30"), calc("x", "linear", ["a", "b"], {"coefficients": [1, -1]})])
    assert m.evaluate()["x"] == D("70")
    assert m.recompute({"b": D("50")})["changes"][-1]["after"] == D("50")


def test_linear_needs_one_coefficient_per_input():
    m = GraphModel([leaf("a", "1"), calc("x", "linear", ["a"], {"coefficients": [1, 2]})])
    with pytest.raises(ValueError):
        m.evaluate()


def test_sum_of_no_inputs_is_zero():
    assert GraphModel([calc("empty", "sum", [])]).evaluate()["empty"] == D("0.00")


def test_unknown_formula_is_rejected_when_the_model_is_built():
    with pytest.raises(ValueError, match="unknown formula"):
        GraphModel([leaf("a", "1"), calc("x", "magic", ["a"])])


def test_missing_input_is_rejected():
    with pytest.raises(ValueError, match="missing node"):
        GraphModel([calc("x", "sum", ["ghost"])])


def test_duplicate_node_ids_are_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        GraphModel([leaf("a", "1"), leaf("a", "2")])


def test_circular_formulas_are_rejected():
    with pytest.raises(CycleError):
        GraphModel([calc("a", "sum", ["b"]), calc("b", "sum", ["a"])])


def test_new_formulas_can_be_registered_without_touching_the_evaluator():
    register_formula("test_only_double", lambda vals, params: vals[0] * 2)
    try:
        m = GraphModel([leaf("a", "21"), calc("x", "test_only_double", ["a"])])
        assert m.evaluate()["x"] == D("42")
    finally:
        FORMULAS.pop("test_only_double")


def test_registering_the_same_formula_name_twice_is_refused():
    with pytest.raises(ValueError):
        register_formula("sum", lambda vals, params: D(0))