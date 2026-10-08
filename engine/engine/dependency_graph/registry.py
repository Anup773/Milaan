"""
The node/formula registry -- the "rest of Phase 8" in ARCHITECTURE.md §6.
Recompute is DATA-DRIVEN: a model is just a list of NodeSpecs (plain data),
and each computed node names a formula from the registry below. There is
no per-node if/elif dispatch anywhere; adding a new kind of calculation
means registering one function, not editing the evaluator.

A node is either:
  * a LEAF  -- has a `value` (e.g. an account's balance read from the
               ledger) and no formula; the only kind that can be overridden.
  * COMPUTED -- names a `formula`, lists the `inputs` it is computed from.

All arithmetic is Decimal, never float (ARCHITECTURE.md §3).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Tuple

from .graph import DependencyGraph

ZERO = Decimal("0.00")

FormulaFn = Callable[[List[Decimal], Mapping[str, Any]], Decimal]
FORMULAS: Dict[str, FormulaFn] = {}


def register_formula(name: str, fn: FormulaFn) -> None:
    if name in FORMULAS:
        raise ValueError(f"formula {name!r} is already registered")
    FORMULAS[name] = fn


def _sum(values: List[Decimal], params: Mapping[str, Any]) -> Decimal:
    return sum(values, ZERO)


def _difference(values: List[Decimal], params: Mapping[str, Any]) -> Decimal:
    """first input minus all the others."""
    if not values:
        raise ValueError("difference needs at least one input")
    return values[0] - sum(values[1:], ZERO)


def _linear(values: List[Decimal], params: Mapping[str, Any]) -> Decimal:
    """sum of coefficient_i * input_i. params: {"coefficients": [1, -1, ...]}"""
    coefficients = params.get("coefficients")
    if not isinstance(coefficients, (list, tuple)) or len(coefficients) != len(values):
        raise ValueError("linear needs one coefficient per input")
    return sum((Decimal(str(c)) * v for c, v in zip(coefficients, values)), ZERO)


register_formula("sum", _sum)
register_formula("difference", _difference)
register_formula("linear", _linear)


@dataclass(frozen=True)
class NodeSpec:
    id: str
    label: str
    kind: str  # 'ledger' | 'schedule' | 'statement' | 'check'
    inputs: Tuple[str, ...] = ()
    formula: Optional[str] = None
    params: Mapping[str, Any] = field(default_factory=dict)
    value: Optional[Decimal] = None
    meta: Mapping[str, Any] = field(default_factory=dict)

    @property
    def is_leaf(self) -> bool:
        return self.formula is None


class GraphModel:
    """A validated set of NodeSpecs plus the DependencyGraph built from them."""

    def __init__(self, specs: Iterable[NodeSpec]) -> None:
        self.specs: Dict[str, NodeSpec] = {}
        for spec in specs:
            if spec.id in self.specs:
                raise ValueError(f"duplicate node id: {spec.id!r}")
            self.specs[spec.id] = spec

        for spec in self.specs.values():
            if spec.is_leaf:
                if spec.inputs:
                    raise ValueError(f"leaf node {spec.id!r} cannot have inputs")
                if not isinstance(spec.value, Decimal):
                    raise ValueError(f"leaf node {spec.id!r} needs a Decimal value")
            else:
                if spec.formula not in FORMULAS:
                    raise ValueError(f"node {spec.id!r} uses unknown formula {spec.formula!r}")
                for inp in spec.inputs:
                    if inp not in self.specs:
                        raise ValueError(f"node {spec.id!r} depends on missing node {inp!r}")

        self.graph = DependencyGraph()
        for spec in self.specs.values():
            self.graph.add_node(spec.id)
        for spec in self.specs.values():
            for inp in spec.inputs:
                self.graph.add_edge(inp, spec.id)  # raises CycleError if circular

    def evaluate(self, overrides: Optional[Mapping[str, Decimal]] = None) -> Dict[str, Decimal]:
        """Value of every node. `overrides` replace leaf values for this run only."""
        overrides = overrides or {}
        for node_id in overrides:
            spec = self.specs.get(node_id)
            if spec is None:
                raise ValueError(f"unknown node: {node_id!r}")
            if not spec.is_leaf:
                raise ValueError(f"{node_id!r} is a computed node; only source (leaf) nodes can be changed")

        values: Dict[str, Decimal] = {}
        for node_id in self.graph.topological_order():
            spec = self.specs[node_id]
            if spec.is_leaf:
                values[node_id] = overrides.get(node_id, spec.value)  # type: ignore[arg-type]
            else:
                inputs = [values[i] for i in spec.inputs]
                values[node_id] = FORMULAS[spec.formula](inputs, spec.params)  # type: ignore[index]
        return values

    def recompute(self, overrides: Mapping[str, Decimal]) -> Dict[str, Any]:
        """
        "Change one thing, see every impact": baseline vs. with the overrides
        applied, listing every node whose value moved, in dependency order.
        Nothing is written anywhere -- this is a what-if, not a posting.
        """
        before = self.evaluate()
        after = self.evaluate(overrides)

        affected = set(overrides)
        for node_id in overrides:
            affected.update(self.graph.downstream_of(node_id))

        changes = []
        unchanged = 0
        for node_id in self.graph.topological_order():
            if node_id not in affected:
                continue
            if before[node_id] == after[node_id]:
                if node_id not in overrides:  # "downstream_unchanged" counts only downstream nodes
                    unchanged += 1
                continue
            spec = self.specs[node_id]
            changes.append({
                "node": node_id, "label": spec.label, "kind": spec.kind,
                "before": before[node_id], "after": after[node_id],
                "delta": after[node_id] - before[node_id],
            })
        return {
            "overrides": {k: v for k, v in overrides.items()},
            "changes": changes,
            "downstream_unchanged": unchanged,
        }

    def describe_node(self, node_id: str, values: Mapping[str, Decimal]) -> Dict[str, Any]:
        spec = self.specs[node_id]
        return {
            "id": spec.id, "label": spec.label, "kind": spec.kind,
            "is_leaf": spec.is_leaf, "formula": spec.formula,
            "value": values[node_id], "meta": dict(spec.meta),
        }