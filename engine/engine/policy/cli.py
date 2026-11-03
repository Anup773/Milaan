
"""
Command-line entry point for Phase 22 (the company accounting policy), invoked by the Node API as a
subprocess -- same pattern as the other engine CLIs.

Usage (every command starts: <command> <firm_id> <company_id> ...):
    get  <role>                              the policy, the defaults, the drop-down options and the rule sets that apply
    put  <user_id> <role> <policy_json>      set up or replace the policy; the JSON holds every setting, plus an
                                             optional "reason" (required when changing an existing policy)

Errors: {"error": "...", "status": 400|403|500} on stderr, non-zero exit.
"""
from __future__ import annotations

import json
import sys
from decimal import Decimal
from typing import Any
from uuid import UUID

from ..db.connection import tenant_connection
from ..db.errors import error_payload
from . import describe, model, put_policy


def _uuid(value: Any, label: str) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        raise ValueError(f"{label} is not a valid id")


def _role(value: str) -> str:
    if value not in model.ROLES:
        raise ValueError(f"role must be one of {', '.join(model.ROLES)}")
    return value


def _json(value: str) -> dict:
    try:
        # parse_float=Decimal: an amount like 1000.10 must never pass through a binary float
        data = json.loads(value, parse_float=Decimal)
    except json.JSONDecodeError:
        raise ValueError("the policy is not valid JSON")
    if not isinstance(data, dict):
        raise ValueError("the policy must be a JSON object")
    return data


def _default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")  # money travels as text, so no precision is lost
    return str(value)


def _run(command: str, firm_id: str, company_id: str, rest: list) -> Any:
    def need(n: int, usage: str) -> None:
        if len(rest) != n:
            raise ValueError(f"{command} needs: {usage}")

    if command == "get":
        need(1, "<role>")
        role = _role(rest[0])
        with tenant_connection(firm_id, company_id) as conn:
            return describe(conn, company_id, role)
    if command == "put":
        need(3, "<user_id> <role> <policy_json>")
        user_id, role, data = _uuid(rest[0], "user_id"), _role(rest[1]), _json(rest[2])
        with tenant_connection(firm_id, company_id, user_id) as conn:
            return put_policy(conn, company_id=company_id, user_id=user_id, role=role, data=data)
    raise ValueError(f"unknown command: {command!r}")


def main(argv: list) -> int:
    if len(argv) < 4:
        print(json.dumps({"error": "usage: cli.py <get|put> <firm_id> <company_id> [...]", "status": 400}), file=sys.stderr)
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