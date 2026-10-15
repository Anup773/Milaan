"""
Command-line entry point for Phase 15 (audit trail), invoked by the Node API as a subprocess --
same pattern as the other engine CLIs. Every command starts: <command> <firm_id> <company_id> ...

    catalog                                            labels, filters and who may do what (for the UI)
    list     <role> [<filters_json>]                   {"periodId","actorId","action","objectType","objectId",
                                                        "from","to","search","limit","offset"}
    get      <role> <event_id>                         one event, with the events either side of it
    history  <role> <object_type> <object_id> [<filters_json>]    {"limit","offset"}; oldest first
    summary  <role> [<filters_json>]                   counts for the dashboard card
    verify   <role>                                    walk the hash chain
    export   <actor_id> <role> [<filters_json>]        CSV text; itself recorded as an audit event

Errors: {"error": "...", "status": 400|403|500} on stderr, non-zero exit
(400 = bad input, 403 = this role may not do this).
"""
from __future__ import annotations

import json
import sys
from typing import Any
from uuid import UUID

from ..db.connection import tenant_connection
from ..db.errors import error_payload
from . import policy as pol
from . import repository as repo


def _uuid(value: Any, label: str) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        raise ValueError(f"{label} is not a valid id")


def _json_object(raw: str, label: str) -> dict:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError(f"{label} is not valid JSON")
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _dispatch(conn, command: str, company_id: str, rest: list) -> Any:
    def need(lo: int, hi: int, usage: str) -> None:
        if not (lo <= len(rest) <= hi):
            raise ValueError(f"{command} needs: {usage}")

    if command == "catalog":
        need(0, 0, "no arguments")
        return pol.catalog()
    if command == "list":
        need(1, 2, "<role> [<filters_json>]")
        pol.check_role(rest[0], pol.READ_ROLES, "read the audit trail")
        return repo.list_events(conn, company_id, _json_object(rest[1], "filters") if len(rest) == 2 else {})
    if command == "get":
        need(2, 2, "<role> <event_id>")
        pol.check_role(rest[0], pol.READ_ROLES, "read the audit trail")
        return repo.get_event(conn, company_id, _uuid(rest[1], "event_id"))
    if command == "history":
        need(3, 4, "<role> <object_type> <object_id> [<filters_json>]")
        pol.check_role(rest[0], pol.READ_ROLES, "read the audit trail")
        f = _json_object(rest[3], "filters") if len(rest) == 4 else {}
        return repo.object_history(conn, company_id, rest[1], _uuid(rest[2], "object_id"),
                                   limit=f.get("limit", pol.MAX_LIMIT), offset=f.get("offset", 0))
    if command == "summary":
        need(1, 2, "<role> [<filters_json>]")
        pol.check_role(rest[0], pol.READ_ROLES, "read the audit trail")
        return repo.summary(conn, company_id, _json_object(rest[1], "filters") if len(rest) == 2 else {})
    if command == "verify":
        need(1, 1, "<role>")
        pol.check_role(rest[0], pol.VERIFY_ROLES, "verify the audit trail")
        return repo.verify(conn, company_id)
    if command == "export":
        need(2, 3, "<actor_id> <role> [<filters_json>]")
        return repo.export_csv(conn, company_id, actor_id=_uuid(rest[0], "actor_id"), actor_role=rest[1],
                               raw_filters=_json_object(rest[2], "filters") if len(rest) == 3 else {})
    raise ValueError(f"unknown command: {command!r}")


def main(argv: list) -> int:
    if len(argv) < 4:
        print(json.dumps({"error": "usage: cli.py <command> <firm_id> <company_id> [...]", "status": 400}), file=sys.stderr)
        return 2
    _, command, firm_id, company_id, *rest = argv
    try:
        firm_id, company_id = _uuid(firm_id, "firm_id"), _uuid(company_id, "company_id")
        with tenant_connection(firm_id, company_id) as conn:
            result = _dispatch(conn, command, company_id, rest)
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