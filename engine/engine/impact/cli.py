"""
Command-line entry point for Phase 10 (impact analysis), invoked by the
Node API as a subprocess. READ-ONLY: nothing is ever written.

Usage:
    python -m engine.impact.cli scenario <firm_id> <company_id> <scenario_id>
    python -m engine.impact.cli preview  <firm_id> <company_id> <period_id> <payload_json>

preview's payload_json: {"overrides": {"<node_id>": "3000.00", ...}}

Errors: {"error": "...", "status": 400|500} on stderr, non-zero exit.
"""
from __future__ import annotations

import json
import sys
from typing import Any
from uuid import UUID

from ..db.connection import tenant_connection
from ..db.errors import error_payload
from .repository import preview_impact, scenario_impact


def _uuid(value: Any, label: str) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        raise ValueError(f"{label} is not a valid id")


def main(argv: list) -> int:
    if len(argv) < 5:
        print(json.dumps({"error": "usage: cli.py <scenario|preview> <firm_id> <company_id> <scenario_id|period_id> [payload]", "status": 400}), file=sys.stderr)
        return 2
    _, command, firm_id, company_id, target, *rest = argv
    try:
        firm_id, company_id = _uuid(firm_id, "firm_id"), _uuid(company_id, "company_id")
        with tenant_connection(firm_id, company_id) as conn:
            if command == "scenario":
                if rest:
                    raise ValueError("scenario takes no extra arguments")
                result: Any = scenario_impact(conn, company_id, _uuid(target, "scenario_id"))
            elif command == "preview":
                if len(rest) != 1:
                    raise ValueError("preview needs exactly one argument: a JSON payload")
                try:
                    payload = json.loads(rest[0])
                except json.JSONDecodeError:
                    raise ValueError("preview payload is not valid JSON")
                if not isinstance(payload, dict):
                    raise ValueError("preview payload must be a JSON object")
                result = preview_impact(conn, company_id, _uuid(target, "period_id"), payload.get("overrides"))
            else:
                raise ValueError(f"unknown command: {command!r}")
    except ValueError as exc:
        print(json.dumps({"error": str(exc), "status": 400}), file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(json.dumps(error_payload(exc)), file=sys.stderr)
        return 1
    print(json.dumps(result, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))