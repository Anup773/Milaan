"""
Command-line entry point for Phase 14 (approvals), invoked by the Node API as a subprocess --
same pattern as the other engine CLIs. Every command starts: <command> <firm_id> <company_id> ...

    policy                                                      who may decide what (for the UI)
    inbox     <actor_id> <role> [<filters_json>]                {"periodId","kind","scope":"all|mine|waiting"}
    summary   <actor_id> <role> [<period_id>]
    detail    <kind> <item_id> <actor_id> <role>                the review packet
    history   [<filters_json>]                                  {"periodId","kind","outcome","limit","offset"}
    decide    <kind> <item_id> <decision> <actor_id> <role> [<note>]     decision: approve | reject

kind: scenario_review | finalization | reopen_request | adjustment
Errors: {"error": "...", "status": 400|403|500} on stderr, non-zero exit
(400 = bad input / wrong state, 403 = this person may not take this decision).
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


def _policy() -> dict:
    return {"kinds": [{"kind": s.kind, "label": s.label, "waiting_status": s.pending_status, "decisions": list(s.decisions),
                       "roles": sorted(s.roles), "second_person_rule_applies_to": sorted(s.maker_checked),
                       "needs_open_period_for": sorted(s.needs_open_period)} for s in pol.SPECS.values()],
            "roles": list(pol.ROLES), "rejecting_needs_a_note": True}


def _dispatch(conn, command: str, company_id: str, rest: list) -> Any:
    def need(lo: int, hi: int, usage: str) -> None:
        if not (lo <= len(rest) <= hi):
            raise ValueError(f"{command} needs: {usage}")

    if command == "policy":
        need(0, 0, "no arguments")
        return _policy()
    if command == "inbox":
        need(2, 3, "<actor_id> <role> [<filters_json>]")
        f = _json_object(rest[2], "filters") if len(rest) == 3 else {}
        return repo.inbox(conn, company_id, actor_id=_uuid(rest[0], "actor_id"), actor_role=rest[1],
                          period_id=_uuid(f["periodId"], "periodId") if f.get("periodId") else None,
                          kind=f.get("kind"), scope=f.get("scope", "all"))
    if command == "summary":
        need(2, 3, "<actor_id> <role> [<period_id>]")
        return repo.summary(conn, company_id, actor_id=_uuid(rest[0], "actor_id"), actor_role=rest[1],
                            period_id=_uuid(rest[2], "period_id") if len(rest) == 3 else None)
    if command == "detail":
        need(4, 4, "<kind> <item_id> <actor_id> <role>")
        return repo.detail(conn, company_id, kind=rest[0], item_id=_uuid(rest[1], "item_id"),
                           actor_id=_uuid(rest[2], "actor_id"), actor_role=rest[3])
    if command == "history":
        need(0, 1, "[<filters_json>]")
        f = _json_object(rest[0], "filters") if rest else {}
        return repo.history(conn, company_id, period_id=_uuid(f["periodId"], "periodId") if f.get("periodId") else None,
                            kind=f.get("kind"), outcome=f.get("outcome"), limit=f.get("limit", 50), offset=f.get("offset", 0))
    if command == "decide":
        need(5, 6, "<kind> <item_id> <decision> <actor_id> <role> [<note>]")
        return repo.decide(conn, company_id=company_id, kind=rest[0], item_id=_uuid(rest[1], "item_id"), decision=rest[2],
                           actor_id=_uuid(rest[3], "actor_id"), actor_role=rest[4], note=rest[5] if len(rest) == 6 else None)
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