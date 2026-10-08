"""
Command-line entry point for Phase 7 (adjustments), invoked by the Node API
as a subprocess -- same pattern as engine.mapping.cli and
engine.schedules.cli: one process per call, no long-running Python service.

Usage:
    python -m engine.adjustments.cli list    <firm_id> <company_id> [<status>]
    python -m engine.adjustments.cli get     <firm_id> <company_id> <adjustment_id>
    python -m engine.adjustments.cli propose <firm_id> <company_id> <payload_json>
    python -m engine.adjustments.cli approve <firm_id> <company_id> <adjustment_id> <reviewed_by>
    python -m engine.adjustments.cli reject  <firm_id> <company_id> <adjustment_id> <reviewed_by> [<note>]

propose's payload_json is one JSON object:
    {"periodId": "<uuid>", "entryDate": "2026-03-31", "description": "...",
     "reason": "...", "proposedBy": "<uuid>",
     "lines": [{"accountId": "<uuid>", "debit": 500, "credit": 0},
               {"accountId": "<uuid>", "debit": 0,   "credit": 500}]}

Prints one JSON object (or list, for `list`) to stdout on success. On
failure prints {"error": "...", "status": 400|500} to stderr and exits
non-zero: status 400 for a business-rule rejection (bad input, wrong
state, not found, same person approving their own proposal), 500 for
anything unexpected.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from typing import Any, Dict, List
from uuid import UUID

from ..db.connection import tenant_connection
from ..db.errors import error_payload
from .repository import (
    approve_adjustment,
    get_adjustment,
    list_adjustments,
    propose_adjustment,
    reject_adjustment,
)

VALID_STATUSES = ("REVIEW_REQUIRED", "POSTED", "REJECTED")


def _require_uuid(value: Any, label: str) -> str:
    """Bad ids are the caller's fault -> ValueError (400), not a DB crash (500)."""
    try:
        return str(UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        raise ValueError(f"{label} is not a valid id")


def _cmd_propose(firm_id: str, company_id: str, payload_json: str) -> Dict[str, Any]:
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError:
        raise ValueError("propose payload is not valid JSON")
    if not isinstance(payload, dict):
        raise ValueError("propose payload must be a JSON object")

    period_id = _require_uuid(payload.get("periodId"), "periodId")
    proposed_by = _require_uuid(payload.get("proposedBy"), "proposedBy")

    try:
        entry_date = date.fromisoformat(str(payload.get("entryDate")))
    except ValueError:
        raise ValueError("entryDate must be a date in YYYY-MM-DD form")

    description = str(payload.get("description") or "").strip()
    reason = str(payload.get("reason") or "").strip()
    if not description or not reason:
        raise ValueError("description and reason are required")

    raw_lines = payload.get("lines")
    if not isinstance(raw_lines, list):
        raise ValueError("lines must be a list")
    lines: List[Dict[str, Any]] = []
    for i, raw in enumerate(raw_lines, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"line {i} must be an object")
        lines.append({
            "account_id": _require_uuid(raw.get("accountId"), f"line {i} accountId"),
            "debit": raw.get("debit") or 0,
            "credit": raw.get("credit") or 0,
        })

    with tenant_connection(firm_id, company_id) as conn:
        return propose_adjustment(
            conn,
            company_id=company_id,
            period_id=period_id,
            entry_date=entry_date,
            description=description,
            reason=reason,
            lines=lines,
            proposed_by=proposed_by,
        )


def main(argv: list[str]) -> int:
    if len(argv) < 4:
        print(json.dumps({"error": "usage: cli.py <list|get|propose|approve|reject> <firm_id> <company_id> [...]", "status": 400}), file=sys.stderr)
        return 2

    _, command, firm_id, company_id, *rest = argv

    try:
        firm_id = _require_uuid(firm_id, "firm_id")
        company_id = _require_uuid(company_id, "company_id")

        if command == "list":
            if len(rest) > 1:
                raise ValueError("list takes at most one argument: [<status>]")
            status = rest[0] if rest else None
            if status is not None and status not in VALID_STATUSES:
                raise ValueError(f"status must be one of {', '.join(VALID_STATUSES)}")
            with tenant_connection(firm_id, company_id) as conn:
                result: Any = {"adjustments": list_adjustments(conn, company_id, status)}

        elif command == "get":
            if len(rest) != 1:
                raise ValueError("get needs exactly one argument: <adjustment_id>")
            adjustment_id = _require_uuid(rest[0], "adjustment_id")
            with tenant_connection(firm_id, company_id) as conn:
                result = get_adjustment(conn, company_id, adjustment_id)

        elif command == "propose":
            if len(rest) != 1:
                raise ValueError("propose needs exactly one argument: a JSON payload")
            result = _cmd_propose(firm_id, company_id, rest[0])

        elif command == "approve":
            if len(rest) != 2:
                raise ValueError("approve needs <adjustment_id> <reviewed_by>")
            adjustment_id = _require_uuid(rest[0], "adjustment_id")
            reviewed_by = _require_uuid(rest[1], "reviewed_by")
            with tenant_connection(firm_id, company_id) as conn:
                result = approve_adjustment(conn, company_id=company_id, adjustment_id=adjustment_id, reviewed_by=reviewed_by)

        elif command == "reject":
            if len(rest) not in (2, 3):
                raise ValueError("reject needs <adjustment_id> <reviewed_by> [<note>]")
            adjustment_id = _require_uuid(rest[0], "adjustment_id")
            reviewed_by = _require_uuid(rest[1], "reviewed_by")
            note = rest[2] if len(rest) == 3 and rest[2] else None
            with tenant_connection(firm_id, company_id) as conn:
                result = reject_adjustment(conn, company_id=company_id, adjustment_id=adjustment_id, reviewed_by=reviewed_by, rejection_note=note)

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