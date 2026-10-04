"""
Command-line entry point for Phase 3's statement views, invoked by the
Node API as a subprocess -- same pattern as engine.ingestion.cli and
engine.mapping.cli.

Usage:
    python -m engine.ledger.cli trial-balance   <firm_id> <company_id> <period_id>
    python -m engine.ledger.cli profit-loss     <firm_id> <company_id> <period_id>
    python -m engine.ledger.cli balance-sheet   <firm_id> <company_id> <as_of_date YYYY-MM-DD>
    python -m engine.ledger.cli general-ledger  <firm_id> <company_id> <account_id> <period_id>
    python -m engine.ledger.cli cash-flow       <firm_id> <company_id> <period_id>

Prints one JSON object to stdout on success. Exits non-zero only for a
genuine failure (bad args, unknown period/account id, DB unreachable).
"""
from __future__ import annotations

import json
import sys
from datetime import date

from ..db.connection import tenant_connection
from .reports import balance_sheet, cash_flow, general_ledger, profit_and_loss, trial_balance


def main(argv: list[str]) -> int:
    if len(argv) < 4:
        print(json.dumps({
            "error": "usage: cli.py <trial-balance|profit-loss|balance-sheet|general-ledger|cash-flow> <firm_id> <company_id> [...]"
        }), file=sys.stderr)
        return 2

    _, command, firm_id, company_id, *rest = argv

    try:
        with tenant_connection(firm_id, company_id) as conn:
            if command == "trial-balance":
                result = trial_balance(conn, company_id, rest[0])
            elif command == "profit-loss":
                result = profit_and_loss(conn, company_id, rest[0])
            elif command == "balance-sheet":
                result = balance_sheet(conn, company_id, date.fromisoformat(rest[0]))
            elif command == "general-ledger":
                result = general_ledger(conn, company_id, rest[0], rest[1])
            elif command == "cash-flow":
                result = cash_flow(conn, company_id, rest[0])
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
        print(json.dumps({"error": str(exc), "status": 500}), file=sys.stderr)
        return 1

    print(json.dumps(result, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
