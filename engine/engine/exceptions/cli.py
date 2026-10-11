"""
Command-line entry point for Phase 12 (exception & transaction review), invoked
by the Node API as a subprocess -- same pattern as the other engine CLIs.

Usage (every command starts: <command> <firm_id> <company_id> ...):
    rules
    detect             <period_id> <run_by>              run every detector on the period; flags are brought up to date
    summary            <period_id>                       counts for the dashboard card
    list               [<filters_json>]                  {"periodId","status","category","priority","openOnly","limit","offset"}
    get                <exception_id>                    one flag with its history, linked adjustments and entries
    runs               <period_id>                       history of detection runs
    run                <run_id>                          one detection run
    raise              <payload_json>                    {"journalEntryId","note","title","priority","raisedBy"}
    claim | request-evidence | evidence-received | retain | correct | reverse | resolve | reopen
                       <exception_id> <actor_id> [<note>]
    link               <exception_id> <actor_id> <adjustment_id>
    propose-reversal   <exception_id> <actor_id> [<payload_json>]   {"entryDate","reason","journalEntryId"}

Errors: {"error": "...", "status": 400|500} on stderr, non-zero exit (400 = business-rule rejection).
"""
from __future__ import annotations

import json
import sys
from typing import Any
from uuid import UUID

from ..db.connection import tenant_connection
from ..db.errors import error_payload
from . import repository as repo

ACTIONS = {"claim": "claim", "request-evidence": "request_evidence", "evidence-received": "evidence_received",
           "retain": "retain", "correct": "correct", "reverse": "reverse", "resolve": "resolve", "reopen": "reopen"}


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
    def need(n_min: int, n_max: int, usage: str) -> None:
        if not (n_min <= len(rest) <= n_max):
            raise ValueError(f"{command} needs: {usage}")

    if command == "rules":
        need(0, 0, "no arguments")
        return repo.rule_catalog()
    if command == "detect":
        need(2, 2, "<period_id> <run_by>")
        return repo.detect(conn, company_id=company_id, period_id=_uuid(rest[0], "period_id"), run_by=_uuid(rest[1], "run_by"))
    if command == "summary":
        need(1, 1, "<period_id>")
        return repo.summary(conn, company_id, _uuid(rest[0], "period_id"))
    if command == "list":
        need(0, 1, "[<filters_json>]")
        f = _json_object(rest[0], "filters") if rest else {}
        return repo.list_exceptions(
            conn, company_id,
            period_id=_uuid(f["periodId"], "periodId") if f.get("periodId") else None,
            status=f.get("status"), category=f.get("category"), priority=f.get("priority"),
            open_only=bool(f.get("openOnly")), limit=f.get("limit", 200), offset=f.get("offset", 0))
    if command == "get":
        need(1, 1, "<exception_id>")
        return repo.get_exception(conn, company_id, _uuid(rest[0], "exception_id"))
    if command == "runs":
        need(1, 1, "<period_id>")
        return {"runs": repo.list_runs(conn, company_id, _uuid(rest[0], "period_id"))}
    if command == "run":
        need(1, 1, "<run_id>")
        return repo.get_run(conn, company_id, _uuid(rest[0], "run_id"))
    if command == "raise":
        need(1, 1, "<payload_json>")
        p = _json_object(rest[0], "payload")
        return repo.raise_manual(
            conn, company_id=company_id, journal_entry_id=_uuid(p.get("journalEntryId"), "journalEntryId"),
            note=str(p.get("note") or ""), raised_by=_uuid(p.get("raisedBy"), "raisedBy"),
            title=str(p["title"]) if p.get("title") else None, priority=str(p.get("priority") or "MEDIUM"))

    # everything below acts on one exception: <exception_id> <actor_id> ...
    if len(rest) < 2:
        raise ValueError(f"{command} needs <exception_id> <actor_id> ...")
    exception_id, actor_id, extra = _uuid(rest[0], "exception_id"), _uuid(rest[1], "actor_id"), rest[2:]
    base = dict(company_id=company_id, exception_id=exception_id)

    if command in ACTIONS:
        need(2, 3, "<exception_id> <actor_id> [<note>]")
        return repo.act(conn, **base, action=ACTIONS[command], actor_id=actor_id, note=extra[0] if extra else None)
    if command == "link":
        need(3, 3, "<exception_id> <actor_id> <adjustment_id>")
        return repo.link_adjustment(conn, **base, actor_id=actor_id, adjustment_id=_uuid(extra[0], "adjustment_id"))
    if command == "propose-reversal":
        need(2, 3, "<exception_id> <actor_id> [<payload_json>]")
        p = _json_object(extra[0], "payload") if extra else {}
        return repo.propose_reversal(
            conn, **base, actor_id=actor_id, entry_date=p.get("entryDate") or None, reason=p.get("reason") or None,
            journal_entry_id=_uuid(p["journalEntryId"], "journalEntryId") if p.get("journalEntryId") else None)
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
        print(json.dumps(error_payload(exc)), file=sys.stderr)
        return 1
    print(json.dumps(result, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
