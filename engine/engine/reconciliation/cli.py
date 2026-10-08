"""
Command-line entry point for Phase 11 (reconciliation), invoked by the Node
API as a subprocess -- same pattern as the other engine CLIs.

Usage (every command starts: <command> <firm_id> <company_id> ...):
    rules
    run     <period_id> <run_by>      run every check on the books as posted; the run is saved
    latest  <period_id>               the most recent saved run for the period (or {"run": null})
    list    <period_id>               history of saved runs for the period
    get     <run_id>                  one saved run with all its results

Errors: {"error": "...", "status": 400|500} on stderr, non-zero exit.
"""
from __future__ import annotations

import json
import sys
from typing import Any
from uuid import UUID

from ..db.connection import tenant_connection
from ..db.errors import error_payload
from . import repository as repo


def _uuid(value: Any, label: str) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        raise ValueError(f"{label} is not a valid id")


def _dispatch(conn, command: str, company_id: str, rest: list) -> Any:
    def need(n: int, usage: str) -> None:
        if len(rest) != n:
            raise ValueError(f"{command} needs: {usage}")

    if command == "rules":
        need(0, "no arguments")
        return {"rules": repo.rule_catalog()}
    if command == "run":
        need(2, "<period_id> <run_by>")
        return repo.run_reconciliation(conn, company_id=company_id, period_id=_uuid(rest[0], "period_id"),
                                       run_by=_uuid(rest[1], "run_by"))
    if command == "latest":
        need(1, "<period_id>")
        return {"run": repo.latest_run(conn, company_id, _uuid(rest[0], "period_id"))}
    if command == "list":
        need(1, "<period_id>")
        return {"runs": repo.list_runs(conn, company_id, _uuid(rest[0], "period_id"))}
    if command == "get":
        need(1, "<run_id>")
        return repo.get_run(conn, company_id, _uuid(rest[0], "run_id"))
    raise ValueError(f"unknown command: {command!r}")


def main(argv: list) -> int:
    if len(argv) < 4:
        print(json.dumps({"error": "usage: cli.py <rules|run|latest|list|get> <firm_id> <company_id> [...]", "status": 400}), file=sys.stderr)
        return 2
    _, command, firm_id, company_id, *rest = argv
    try:
        firm_id, company_id = _uuid(firm_id, "firm_id"), _uuid(company_id, "company_id")
        with tenant_connection(firm_id, company_id) as conn:
            result = _dispatch(conn, command, company_id, rest)
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