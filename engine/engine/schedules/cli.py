"""
Command-line entry point for the fixed-asset schedule, invoked by the
Node API as a subprocess -- same pattern as the other engine CLIs.
Fixed-asset CREATION is plain CRUD and lives in Node directly (same
pattern as Phase 5's accounts/periods); this CLI is only for the actual
schedule logic.

Usage:
    python -m engine.schedules.cli rollforward <firm_id> <company_id> <period_id>
    python -m engine.schedules.cli post        <firm_id> <company_id> <period_id> [<created_by>]
    python -m engine.schedules.cli reconcile   <firm_id> <company_id> <period_id>
"""
from __future__ import annotations

import json
import sys

from ..db.connection import tenant_connection
from ..db.errors import error_payload
from .repository import post_depreciation, reconcile_against_ledger, rollforward


def main(argv: list[str]) -> int:
    if len(argv) < 4:
        print(json.dumps({"error": "usage: cli.py <rollforward|post|reconcile> <firm_id> <company_id> <period_id> [created_by]"}), file=sys.stderr)
        return 2

    _, command, firm_id, company_id, *rest = argv

    try:
        with tenant_connection(firm_id, company_id) as conn:
            if command == "rollforward":
                result = rollforward(conn, company_id, rest[0])
            elif command == "post":
                created_by = rest[1] if len(rest) > 1 and rest[1] else None
                result = post_depreciation(conn, company_id=company_id, period_id=rest[0], created_by=created_by)
            elif command == "reconcile":
                result = reconcile_against_ledger(conn, company_id, rest[0])
            else:
                raise ValueError(f"unknown command: {command!r}")
    except ValueError as exc:
        # Business-rule rejection (bad input, wrong state, not found) --
        # the caller's fault, not the server's. status:400 lets Node's
        # runEngineCli report the right HTTP code instead of defaulting
        # every engine-side error to 500.
        print(json.dumps({"error": str(exc), "status": 400}), file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 -- anything else is a genuine, unexpected failure
        print(json.dumps(error_payload(exc)), file=sys.stderr)
        return 1

    print(json.dumps(result, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
