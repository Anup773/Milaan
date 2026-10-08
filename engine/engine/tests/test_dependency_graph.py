"""Pure-logic tests for engine.dependency_graph.graph -- no database."""
import pytest

from engine.dependency_graph.graph import CycleError, DependencyGraph


def chain():
    g = DependencyGraph()
    g.add_edge("cost", "depreciation")
    g.add_edge("depreciation", "net_profit")
    g.add_edge("net_profit", "retained_earnings")
    return g


def test_downstream_follows_the_whole_chain_in_order():
    assert chain().downstream_of("cost") == ["depreciation", "net_profit", "retained_earnings"]


def test_upstream_is_the_same_chain_walked_backwards():
    assert chain().upstream_of("retained_earnings") == ["cost", "depreciation", "net_profit"]


def test_a_node_is_never_its_own_downstream_or_upstream():
    g = chain()
    assert "net_profit" not in g.downstream_of("net_profit")
    assert "net_profit" not in g.upstream_of("net_profit")


def test_leaf_and_root_have_empty_far_sides():
    g = chain()
    assert g.downstream_of("retained_earnings") == []
    assert g.upstream_of("cost") == []


def test_diamond_dependency_lists_each_node_once_and_in_valid_order():
    g = DependencyGraph()
    for u, d in [("a", "b"), ("a", "c"), ("b", "d"), ("c", "d")]:
        g.add_edge(u, d)
    down = g.downstream_of("a")
    assert sorted(down) == ["b", "c", "d"] and len(down) == 3
    assert down.index("d") > down.index("b") and down.index("d") > down.index("c")
    assert g.upstream_of("d") == ["a", "b", "c"]


def test_topological_order_puts_inputs_before_dependents():
    order = chain().topological_order()
    assert order.index("cost") < order.index("depreciation") < order.index("net_profit")


def test_direct_neighbours():
    g = chain()
    assert g.direct_downstream("cost") == ["depreciation"]
    assert g.direct_upstream("net_profit") == ["depreciation"]


def test_self_dependency_is_rejected():
    with pytest.raises(CycleError):
        DependencyGraph().add_edge("a", "a")


def test_edge_that_would_close_a_loop_is_rejected_and_graph_is_unchanged():
    g = chain()
    with pytest.raises(CycleError):
        g.add_edge("retained_earnings", "cost")
    assert g.downstream_of("cost") == ["depreciation", "net_profit", "retained_earnings"]
    assert ("retained_earnings", "cost") not in g.edges()


def test_cycle_error_is_a_value_error_so_the_api_reports_400():
    assert issubclass(CycleError, ValueError)


def test_repeating_an_edge_is_harmless():
    g = DependencyGraph()
    g.add_edge("a", "b")
    g.add_edge("a", "b")
    assert g.edges() == [("a", "b")]


def test_unknown_node_is_a_value_error():
    with pytest.raises(ValueError):
        chain().downstream_of("nope")
    with pytest.raises(ValueError):
        chain().upstream_of("nope")
