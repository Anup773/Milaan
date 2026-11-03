"""
Command-line entry point for fiscal years and periods (Phase 24), invoked by the Node API as a subprocess.

Usage (every command starts: <command> <firm_id> <company_id> ...):
    preview <date> <MONTHLY|YEARLY>                       the fiscal year containing <date> (AD, YYYY-MM-DD) and the periods it would create
    create  <user_id> <role> <date> <MONTHLY|YEARLY>      create them (all or none; refused if any overlaps an existing period)

Errors: {"error": "...", "status": 400|403|500} on stderr, non-zero exit.
"""
from __future__ import annotations

import json
import sys
from typing import Any
from uuid import UUID

from ..db.connection import tenant_connection
from ..db.errors import error_payload
from . import fiscal, model


def _uuid(value: Any, label: str) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        raise ValueError(f"{label} is not a valid id")


def _date(value: str) -> str:
    from datetime import date
    try:
        date.fromisoformat(value)
    except ValueError:
        raise ValueError("the date must be a real date written YYYY-MM-DD (an AD date)") from None
    return value


def _run(command: str, firm_id: str, company_id: str, rest: list) -> Any:
    if command == "preview":
        if len(rest) != 2:
            raise ValueError("preview needs: <date> <MONTHLY|YEARLY>")
        with tenant_connection(firm_id, company_id) as conn:
            return fiscal.preview(conn, company_id, _date(rest[0]), rest[1])
    if command == "create":
        if len(rest) != 4:
            raise ValueError("create needs: <user_id> <role> <date> <MONTHLY|YEARLY>")
        user_id, role = _uuid(rest[0], "user_id"), rest[1]
        if role not in model.ROLES:
            raise ValueError(f"role must be one of {', '.join(model.ROLES)}")
        with tenant_connection(firm_id, company_id, user_id) as conn:
            return fiscal.create(conn, company_id=company_id, user_id=user_id, role=role, on_date=_date(rest[2]), split=rest[3])
    raise ValueError(f"unknown command: {command!r}")


def main(argv: list) -> int:
    if len(argv) < 4:
        print(json.dumps({"error": "usage: cli.py <preview|create> <firm_id> <company_id> [...]", "status": 400}), file=sys.stderr)
        return 2
    _, command, firm_id, company_id, *rest = argv
    try:
        result = _run(command, _uuid(firm_id, "firm_id"), _uuid(company_id, "company_id"), rest)
    except PermissionError as exc:
        print(json.dumps({"error": str(exc), "status": 403}), file=sys.stderr)
        return 1
    except ValueError as exc:
        print(json.dumps({"error": str(exc), "status": 400}), file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 -- anything else is a genuine, unexpected failure
        print(json.dumps(error_payload(exc)), file=sys.stderr)
        return 1
    print(json.dumps(result, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))