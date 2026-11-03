"""
Command-line entry point for tax depreciation (Phase 24), invoked by the Node API as a subprocess -- same pattern as the
other engine CLIs.

Usage (every command starts: <command> <firm_id> <company_id> ...):
    get         <role> [<date>]                     the schedule for the fiscal year containing <date> (AD, YYYY-MM-DD; default today)
    add         <user_id> <role> <json>             one opening balance, addition or disposal
    add-many    <user_id> <role> <json_array>       several at once (all saved or none)
    update      <user_id> <role> <id> <json>        replace one
    delete      <user_id> <role> <id>               remove one
    rate-set    <user_id> <role> <json>             the company's own rate for a pool from a date
    rate-delete <user_id> <role> <id>

Errors: {"error": "...", "status": 400|403|500} on stderr, non-zero exit.
"""
from __future__ import annotations

import json
import sys
from decimal import Decimal
from typing import Any
from uuid import UUID

from ...db.connection import tenant_connection
from ...db.errors import error_payload
from ...policy import model
from . import service


def _uuid(value: Any, label: str) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        raise ValueError(f"{label} is not a valid id")


def _role(value: str) -> str:
    if value not in model.ROLES:
        raise ValueError(f"role must be one of {', '.join(model.ROLES)}")
    return value


def _json(value: str, kind: type, what: str) -> Any:
    try:
        data = json.loads(value, parse_float=Decimal)  # an amount must never pass through a binary float
    except json.JSONDecodeError:
        raise ValueError(f"{what} is not valid JSON")
    if not isinstance(data, kind):
        raise ValueError(f"{what} must be a JSON {'object' if kind is dict else 'array'}")
    return data


def _default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


def _run(command: str, firm_id: str, company_id: str, rest: list) -> Any:
    def need(low: int, high: int, usage: str) -> None:
        if not low <= len(rest) <= high:
            raise ValueError(f"{command} needs: {usage}")

    if command == "get":
        need(1, 2, "<role> [<date>]")
        role = _role(rest[0])
        with tenant_connection(firm_id, company_id) as conn:
            return service.schedule(conn, company_id, role, rest[1] if len(rest) > 1 and rest[1] else None)

    writers = {
        "add": (3, "<user_id> <role> <json>"), "add-many": (3, "<user_id> <role> <json_array>"),
        "update": (4, "<user_id> <role> <id> <json>"), "delete": (3, "<user_id> <role> <id>"),
        "rate-set": (3, "<user_id> <role> <json>"), "rate-delete": (3, "<user_id> <role> <id>"),
    }
    if command in writers:
        n, usage = writers[command]
        need(n, n, usage)
        user_id, role = _uuid(rest[0], "user_id"), _role(rest[1])
        common = {"company_id": company_id, "user_id": user_id, "role": role}
        with tenant_connection(firm_id, company_id, user_id) as conn:
            if command == "add":
                return service.add_movement(conn, data=_json(rest[2], dict, "the entry"), **common)
            if command == "add-many":
                return service.add_movements(conn, rows=_json(rest[2], list, "the rows"), **common)
            if command == "update":
                return service.update_movement(conn, movement_id=_uuid(rest[2], "id"), data=_json(rest[3], dict, "the entry"), **common)
            if command == "delete":
                return service.delete_movement(conn, movement_id=_uuid(rest[2], "id"), **common)
            if command == "rate-set":
                return service.set_rate(conn, data=_json(rest[2], dict, "the rate"), **common)
            return service.delete_rate(conn, rate_id=_uuid(rest[2], "id"), **common)
    raise ValueError(f"unknown command: {command!r}")


def main(argv: list) -> int:
    if len(argv) < 4:
        print(json.dumps({"error": "usage: cli.py <get|add|add-many|update|delete|rate-set|rate-delete> <firm_id> <company_id> [...]",
                          "status": 400}), file=sys.stderr)
        return 2
    _, command, firm_id, company_id, *rest = argv
    try:
        firm_id, company_id = _uuid(firm_id, "firm_id"), _uuid(company_id, "company_id")
        result = _run(command, firm_id, company_id, rest)
    except PermissionError as exc:
        print(json.dumps({"error": str(exc), "status": 403}), file=sys.stderr)
        return 1
    except ValueError as exc:
        print(json.dumps({"error": str(exc), "status": 400}), file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 -- anything else is a genuine, unexpected failure
        print(json.dumps(error_payload(exc)), file=sys.stderr)
        return 1
    print(json.dumps(result, default=_default))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))