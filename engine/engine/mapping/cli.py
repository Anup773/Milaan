"""
Command-line entry point for Phase 5, invoked by the Node API as a
subprocess -- same pattern as engine.ingestion.cli (see that file's
docstring for why: no long-running Python service, one process per call).

Usage:
    python -m engine.mapping.cli unmapped <firm_id> <company_id>
    python -m engine.mapping.cli confirm <firm_id> <company_id> <payload_json>
    python -m engine.mapping.cli materialize <firm_id> <company_id> <source_file_id> [<created_by>]

confirm's payload_json is one JSON object, either:
    {"accountRef": "Bank Account", "accountId": "<uuid>", "confirmedBy": "<uuid-or-null>"}
or:
    {"accountRef": "Bank Account",
     "newAccount": {"code": "1010", "name": "Bank Account", "accountType": "Asset", "parentAccountId": null},
     "confirmedBy": "<uuid-or-null>"}

Prints one JSON object to stdout on success. Exits non-zero only for a
genuine failure (bad args, DB unreachable, an account_id that doesn't
belong to this company, an unknown account_type) -- never because
`materialize` found blocked or skipped vouchers, which is normal expected
output, not a script failure.
"""
from __future__ import annotations

import json
import sys
from typing import Optional

from ..db.connection import tenant_connection
from .repository import confirm_mapping, find_unmapped_refs, materialize_source_file


def _cmd_unmapped(firm_id: str, company_id: str) -> dict:
    with tenant_connection(firm_id, company_id) as conn:
        return {"unmapped": find_unmapped_refs(conn, company_id)}


def _cmd_confirm(firm_id: str, company_id: str, payload_json: str) -> dict:
    payload = json.loads(payload_json)
    new_account = payload.get("newAccount")

    with tenant_connection(firm_id, company_id) as conn:
        resolved_id = confirm_mapping(
            conn,
            company_id=company_id,
            account_ref=payload["accountRef"],
            confirmed_by=payload.get("confirmedBy") or None,
            account_id=payload.get("accountId"),
            new_account=({
                "code": new_account["code"],
                "name": new_account["name"],
                "account_type": new_account["accountType"],
                "parent_account_id": new_account.get("parentAccountId"),
            } if new_account else None),
        )
    return {"accountId": resolved_id}


def _cmd_materialize(firm_id: str, company_id: str, source_file_id: str, created_by: Optional[str]) -> dict:
    with tenant_connection(firm_id, company_id) as conn:
        return materialize_source_file(conn, company_id=company_id, source_file_id=source_file_id, created_by=created_by)


def main(argv: list[str]) -> int:
    if len(argv) < 4:
        print(json.dumps({"error": "usage: cli.py <unmapped|confirm|materialize> <firm_id> <company_id> [...]"}), file=sys.stderr)
        return 2

    _, command, firm_id, company_id, *rest = argv

    try:
        if command == "unmapped":
            result = _cmd_unmapped(firm_id, company_id)
        elif command == "confirm":
            if len(rest) != 1:
                raise ValueError("confirm needs exactly one argument: a JSON payload")
            result = _cmd_confirm(firm_id, company_id, rest[0])
        elif command == "materialize":
            if len(rest) not in (1, 2):
                raise ValueError("materialize needs <source_file_id> [<created_by>]")
            created_by = rest[1] if len(rest) == 2 and rest[1] else None
            result = _cmd_materialize(firm_id, company_id, rest[0], created_by)
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