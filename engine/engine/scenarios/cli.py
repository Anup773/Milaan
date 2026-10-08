
"""
Command-line entry point for Phase 9 (scenarios), invoked by the Node API
as a subprocess -- same pattern as the other engine CLIs.

Usage (every command starts: <command> <firm_id> <company_id> ...):
    create          <payload_json>        {"periodId","title","description","overrides":{nodeId:amount},"createdBy"}
    list            [<status>]
    get             <scenario_id>
    edit            <scenario_id> <actor_id> <overrides_json>
    simulate        <scenario_id> <actor_id>
    revise          <scenario_id> <actor_id>
    submit          <scenario_id> <actor_id>
    approve         <scenario_id> <actor_id> [<note>]
    reject          <scenario_id> <actor_id> <note>
    link            <scenario_id> <actor_id> <adjustment_id>
    post            <scenario_id> <actor_id>
    finalize        <scenario_id> <actor_id>
    discard         <scenario_id> <actor_id> [<note>]
    request-reopen  <scenario_id> <actor_id> <reason>
    decide-reopen   <scenario_id> <actor_id> <approve|deny> [<note>]

Prints one JSON object on success. On failure prints
{"error": "...", "status": 400|500} to stderr and exits non-zero (400 =
business-rule rejection, 500 = unexpected).
"""
from __future__ import annotations

import json
import sys
from typing import Any
from uuid import UUID

from ..db.connection import tenant_connection
from . import repository as repo


def _uuid(value: Any, label: str) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        raise ValueError(f"{label} is not a valid id")


def _json(raw: str, label: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError(f"{label} is not valid JSON")


def _dispatch(conn, command: str, company_id: str, rest: list) -> Any:
    def need(n_min: int, n_max: int, usage: str) -> None:
        if not (n_min <= len(rest) <= n_max):
            raise ValueError(f"{command} needs: {usage}")

    if command == "create":
        need(1, 1, "<payload_json>")
        p = _json(rest[0], "payload")
        if not isinstance(p, dict):
            raise ValueError("payload must be a JSON object")
        return repo.create_scenario(
            conn, company_id=company_id, period_id=_uuid(p.get("periodId"), "periodId"),
            title=str(p.get("title") or ""), description=str(p.get("description") or ""),
            overrides=p.get("overrides"), created_by=_uuid(p.get("createdBy"), "createdBy"),
        )
    if command == "list":
        need(0, 1, "[<status>]")
        return {"scenarios": repo.list_scenarios(conn, company_id, rest[0] if rest else None)}
    if command == "get":
        need(1, 1, "<scenario_id>")
        return repo.get_scenario(conn, company_id, _uuid(rest[0], "scenario_id"))

    # everything below acts: <scenario_id> <actor_id> ...
    if len(rest) < 2:
        raise ValueError(f"{command} needs <scenario_id> <actor_id> ...")
    scenario_id, actor_id, extra = _uuid(rest[0], "scenario_id"), _uuid(rest[1], "actor_id"), rest[2:]
    base = dict(company_id=company_id, scenario_id=scenario_id)

    if command == "edit":
        need(3, 3, "<scenario_id> <actor_id> <overrides_json>")
        return repo.update_overrides(conn, **base, actor_id=actor_id, overrides=_json(extra[0], "overrides"))
    if command in ("simulate", "revise", "submit", "post", "finalize"):
        need(2, 2, "<scenario_id> <actor_id>")
        return getattr(repo, command)(conn, **base, actor_id=actor_id)
    if command == "approve":
        need(2, 3, "<scenario_id> <actor_id> [<note>]")
        return repo.approve(conn, **base, actor_id=actor_id, note=extra[0] if extra else None)
    if command == "reject":
        need(3, 3, "<scenario_id> <actor_id> <note>")
        return repo.reject(conn, **base, actor_id=actor_id, note=extra[0])
    if command == "discard":
        need(2, 3, "<scenario_id> <actor_id> [<note>]")
        return repo.discard(conn, **base, actor_id=actor_id, note=extra[0] if extra else None)
    if command == "link":
        need(3, 3, "<scenario_id> <actor_id> <adjustment_id>")
        return repo.link_adjustment(conn, **base, actor_id=actor_id, adjustment_id=_uuid(extra[0], "adjustment_id"))
    if command == "request-reopen":
        need(3, 3, "<scenario_id> <actor_id> <reason>")
        return repo.request_reopen(conn, **base, actor_id=actor_id, reason=extra[0])
    if command == "decide-reopen":
        need(3, 4, "<scenario_id> <actor_id> <approve|deny> [<note>]")
        if extra[0] not in ("approve", "deny"):
            raise ValueError("decision must be 'approve' or 'deny'")
        return repo.decide_reopen(conn, **base, actor_id=actor_id, approve_it=extra[0] == "approve",
                                  note=extra[1] if len(extra) > 1 else None)
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