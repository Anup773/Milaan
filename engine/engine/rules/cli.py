"""
Command-line entry point for Phase 21 (the rules catalog), invoked by the Node API as a subprocess -- same pattern
as the other engine CLIs. The catalog is the same for every firm, so unlike the other CLIs it takes no firm or
company id and never touches the database.

Usage:
    catalog [family] [jurisdiction] [framework] [status]   each argument optional; use - to skip one
    get     <rule_set_id>

Errors: {"error": "...", "status": 400|500} on stderr, non-zero exit.
"""
from __future__ import annotations

import json
import sys
from typing import Any, List, Optional

from ..db.errors import error_payload
from . import catalog, get, plain


def _arg(rest: List[str], index: int) -> Optional[str]:
    if index >= len(rest):
        return None
    value = rest[index].strip()
    return None if value in ("", "-") else value


def _dispatch(command: str, rest: List[str]) -> Any:
    if command == "catalog":
        if len(rest) > 4:
            raise ValueError("catalog takes at most: [family] [jurisdiction] [framework] [status]")
        return catalog(family=_arg(rest, 0), jurisdiction=_arg(rest, 1), framework=_arg(rest, 2), status=_arg(rest, 3))
    if command == "get":
        if len(rest) != 1:
            raise ValueError("get needs: <rule_set_id>")
        return plain(get(rest[0]))
    raise ValueError(f"unknown command: {command!r}")


def main(argv: list) -> int:
    if len(argv) < 2:
        print(json.dumps({"error": "usage: cli.py <catalog|get> [...]", "status": 400}), file=sys.stderr)
        return 2
    _, command, *rest = argv
    try:
        result = _dispatch(command, rest)
    except ValueError as exc:
        print(json.dumps({"error": str(exc), "status": 400}), file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(json.dumps(error_payload(exc)), file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))