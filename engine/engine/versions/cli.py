"""
Command-line entry point for Phase 13 (version comparison), invoked by the Node
API as a subprocess -- same pattern as the other engine CLIs. Read-only.

Usage (every command starts: <command> <firm_id> <company_id> ...):
    files                                                  every import, newest first
    compare   <base_file_id> <compare_file_id> [<options_json>]
              options: {"kinds": ["CHANGED","ADDED","REMOVED","UNCHANGED"], "includeUnchanged": bool,
                        "limit": n, "offset": n}

Errors: {"error": "...", "status": 400|500} on stderr, non-zero exit (400 = bad input).
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
    if command == "files":
        if rest:
            raise ValueError("files takes no arguments")
        return {"files": repo.list_files(conn, company_id)}
    if command == "compare":
        if not (2 <= len(rest) <= 3):
            raise ValueError("compare needs: <base_file_id> <compare_file_id> [<options_json>]")
        opts: Any = {}
        if len(rest) == 3:
            try:
                opts = json.loads(rest[2])
            except json.JSONDecodeError:
                raise ValueError("options is not valid JSON")
            if not isinstance(opts, dict):
                raise ValueError("options must be a JSON object")
        kinds = opts.get("kinds")
        if kinds is not None and not isinstance(kinds, list):
            raise ValueError("kinds must be a list")
        return repo.compare(
            conn, company_id=company_id, base_file_id=_uuid(rest[0], "base_file_id"),
            compare_file_id=_uuid(rest[1], "compare_file_id"), kinds=kinds,
            include_unchanged=bool(opts.get("includeUnchanged")),
            limit=opts.get("limit", repo.DEFAULT_LIMIT), offset=opts.get("offset", 0))
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