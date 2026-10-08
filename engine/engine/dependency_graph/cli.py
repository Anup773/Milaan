"""
Command-line entry point for Phase 8, invoked by the Node API as a
subprocess -- same pattern as the other engine CLIs. Everything here is
READ-ONLY: the graph is rebuilt from the ledger on every call and nothing
is ever written.

Usage:
    python -m engine.dependency_graph.cli graph      <firm_id> <company_id> <period_id>
    python -m engine.dependency_graph.cli upstream   <firm_id> <company_id> <period_id> <node_id>
    python -m engine.dependency_graph.cli downstream <firm_id> <company_id> <period_id> <node_id>
    python -m engine.dependency_graph.cli recompute  <firm_id> <company_id> <period_id> <payload_json>
    python -m engine.dependency_graph.cli trace      <firm_id> <company_id> <period_id> <account_id> [<period|cumulative>]

recompute's payload_json: {"overrides": {"<node_id>": "72000.00", ...}}
Only source (leaf) nodes can be overridden; amounts are rounded to 2 decimals.

Errors: {"error": "...", "status": 400|500} on stderr, non-zero exit.
"""
from __future__ import annotations

import json
import sys
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Dict
from uuid import UUID

from ..db.connection import tenant_connection
from .ledger_model import build_ledger_model
from .registry import GraphModel
from .trace import trace_account

CENTS = Decimal("0.01")


def _require_uuid(value: Any, label: str) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        raise ValueError(f"{label} is not a valid id")


def _parse_amount(node_id: str, raw: Any) -> Decimal:
    if isinstance(raw, bool) or raw is None:
        raise ValueError(f"override for {node_id!r} must be a number")
    try:
        amount = Decimal(str(raw))
    except InvalidOperation:
        raise ValueError(f"override for {node_id!r} is not a valid number")
    if not amount.is_finite():
        raise ValueError(f"override for {node_id!r} is not a valid number")
    return amount.quantize(CENTS, rounding=ROUND_HALF_UP)


def _graph_view(model: GraphModel) -> Dict[str, Any]:
    values = model.evaluate()
    return {
        "nodes": [model.describe_node(n, values) for n in model.graph.topological_order()],
        "edges": [{"from": u, "to": d} for u, d in model.graph.edges()],
    }


def main(argv: list[str]) -> int:
    if len(argv) < 5:
        print(json.dumps({"error": "usage: cli.py <graph|upstream|downstream|recompute|trace> <firm_id> <company_id> <period_id> [...]", "status": 400}), file=sys.stderr)
        return 2

    _, command, firm_id, company_id, period_id, *rest = argv

    try:
        firm_id = _require_uuid(firm_id, "firm_id")
        company_id = _require_uuid(company_id, "company_id")
        period_id = _require_uuid(period_id, "period_id")

        with tenant_connection(firm_id, company_id) as conn:
            if command == "trace":
                if len(rest) not in (1, 2):
                    raise ValueError("trace needs <account_id> [<period|cumulative>]")
                account_id = _require_uuid(rest[0], "account_id")
                result: Any = trace_account(conn, company_id, period_id, account_id, rest[1] if len(rest) == 2 else "period")
            else:
                model = build_ledger_model(conn, company_id, period_id)
                if command == "graph":
                    if rest:
                        raise ValueError("graph takes no extra arguments")
                    result = _graph_view(model)
                elif command in ("upstream", "downstream"):
                    if len(rest) != 1:
                        raise ValueError(f"{command} needs exactly one argument: <node_id>")
                    node_id = rest[0]
                    ids = model.graph.upstream_of(node_id) if command == "upstream" else model.graph.downstream_of(node_id)
                    values = model.evaluate()
                    result = {"node": model.describe_node(node_id, values),
                              command: [model.describe_node(n, values) for n in ids]}
                elif command == "recompute":
                    if len(rest) != 1:
                        raise ValueError("recompute needs exactly one argument: a JSON payload")
                    try:
                        payload = json.loads(rest[0])
                    except json.JSONDecodeError:
                        raise ValueError("recompute payload is not valid JSON")
                    raw = payload.get("overrides") if isinstance(payload, dict) else None
                    if not isinstance(raw, dict) or not raw:
                        raise ValueError("overrides must be a non-empty object of {nodeId: amount}")
                    result = model.recompute({k: _parse_amount(k, v) for k, v in raw.items()})
                else:
                    raise ValueError(f"unknown command: {command!r}")

    except ValueError as exc:
        print(json.dumps({"error": str(exc), "status": 400}), file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 -- anything else is a genuine, unexpected failure
        print(json.dumps({"error": str(exc), "status": 500}), file=sys.stderr)
        return 1

    print(json.dumps(result, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
