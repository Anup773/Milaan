"""
Impact analysis -- turns "these source figures change" into a formal
current / scenario / delta report. Pure logic over a GraphModel
(engine.dependency_graph); no database, nothing written.

Sections:
  summary          one-line headline + counts
  sources          the figures that were changed (what the scenario sets)
  profit_and_loss  total income, total expense, net profit
  balance_sheet    total assets, liabilities, equity, retained earnings
  checks           the balance check (0 = balanced) before and after
  accounts         every ledger account whose balance moves
  flow             every affected figure in dependency order -- the "so what
                   else changes" chain, from the source to the statements

Every figure is a row: {node, label, current, scenario, delta, pct_change}.
pct_change is None when the current figure is 0 (a percentage of zero is
meaningless). Statement rows only appear for statements the model has, so
the same builder works on any model that uses the same node ids.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Mapping, Optional

from ..dependency_graph.registry import GraphModel

PL_NODES = ("pl:total_income", "pl:total_expense", "pl:net_profit")
BS_NODES = ("bs:total_assets", "bs:total_liabilities", "bs:total_equity", "bs:retained_earnings")
CHECK_NODE = "bs:check"
PCT = Decimal("0.01")


def _row(model: GraphModel, node_id: str, before: Mapping[str, Decimal], after: Mapping[str, Decimal]) -> Dict[str, Any]:
    spec = model.specs[node_id]
    current, scenario = before[node_id], after[node_id]
    delta = scenario - current
    pct: Optional[Decimal] = None
    if current != 0:
        pct = (delta / abs(current) * 100).quantize(PCT, rounding=ROUND_HALF_UP)
    return {"node": node_id, "label": spec.label, "current": current, "scenario": scenario,
            "delta": delta, "pct_change": pct}


def _headline(model: GraphModel, before: Mapping[str, Decimal], after: Mapping[str, Decimal]) -> str:
    if "pl:net_profit" not in model.specs:
        return "Impact calculated."
    cur, new = before["pl:net_profit"], after["pl:net_profit"]
    if cur == new:
        return "Net profit would be unchanged."
    verb = "increase" if new > cur else "decrease"
    return f"Net profit would {verb} by {abs(new - cur):,.2f} (from {cur:,.2f} to {new:,.2f})."


def build_impact_report(model: GraphModel, overrides: Mapping[str, Decimal]) -> Dict[str, Any]:
    if not overrides:
        raise ValueError("there are no changes to analyse")
    before = model.evaluate()
    after = model.evaluate(overrides)  # validates: unknown / computed nodes raise ValueError

    changes = model.recompute(overrides)["changes"]

    accounts: List[Dict[str, Any]] = []
    for node_id, spec in model.specs.items():
        if spec.kind != "ledger" or spec.meta.get("other_postings") or before[node_id] == after[node_id]:
            continue
        row = _row(model, node_id, before, after)
        row.update(code=spec.meta.get("code"), name=spec.meta.get("name"),
                   account_type=spec.meta.get("account_type"), scope=spec.meta.get("scope"))
        accounts.append(row)
    accounts.sort(key=lambda r: (str(r["code"]), str(r["scope"])))

    pl = [_row(model, n, before, after) for n in PL_NODES if n in model.specs]
    bs = [_row(model, n, before, after) for n in BS_NODES if n in model.specs]

    checks = None
    if CHECK_NODE in model.specs:
        checks = _row(model, CHECK_NODE, before, after)
        checks["balanced_before"] = before[CHECK_NODE] == 0
        checks["balanced_after"] = after[CHECK_NODE] == 0

    statement_rows_moved = sum(1 for r in pl + bs if r["delta"] != 0)
    return {
        "summary": {
            "headline": _headline(model, before, after),
            "nothing_changes": not changes or all(c["delta"] == 0 for c in changes),
            "figures_changed": len(changes),
            "accounts_affected": len(accounts),
            "statement_lines_affected": statement_rows_moved,
            "balanced_after": None if checks is None else checks["balanced_after"],
        },
        "sources": [_row(model, n, before, after) for n in overrides],
        "profit_and_loss": pl,
        "balance_sheet": bs,
        "checks": checks,
        "accounts": accounts,
        "flow": [{"node": c["node"], "label": c["label"], "kind": c["kind"], "delta": c["delta"]} for c in changes],
    }