"""
Command-line entry point: parse a file and persist it, in one call, so the
Node API can invoke this as a subprocess without a Python HTTP service.

Usage:
    python -m engine.ingestion.cli <file_path> <firm_id> <company_id> <source_file_id>

Prints one JSON object to stdout on success:
    {"rows": 4, "errors": 0, "warnings": 0, "total_debit": "165000.00",
     "total_credit": "165000.00", "issues_total": 0, "issues": []}

`issues` lists (at most the first 25) problems found, each as
    {"row": 3, "field": "account", "severity": "ERROR", "message": "..."}
row 0 means "the file as a whole" (for example: no header row found).

Exits non-zero only for a genuine failure (bad args, file not found, DB
unreachable) -- row-level parsing errors are data-quality issues, not
script failures, and are reported inside the JSON, not as a crash.
"""
from __future__ import annotations

import json
import sys

from .parse import parse_file
from .persist import persist_parse_result

MAX_ISSUES_REPORTED = 25


def main(argv: list[str]) -> int:
    if len(argv) != 5:
        print(json.dumps({"error": "usage: cli.py <file_path> <firm_id> <company_id> <source_file_id>"}), file=sys.stderr)
        return 2

    _, file_path, firm_id, company_id, source_file_id = argv

    try:
        result = parse_file(file_path)
        persist_parse_result(
            firm_id=firm_id,
            company_id=company_id,
            source_file_id=source_file_id,
            result=result,
        )
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

    errors = sum(1 for i in result.issues if i.severity.value == "ERROR")
    warnings = sum(1 for i in result.issues if i.severity.value == "WARNING")
    print(json.dumps({
        "rows": len(result.rows),
        "errors": errors,
        "warnings": warnings,
        "total_debit": str(result.total_debit),
        "total_credit": str(result.total_credit),
        "issues_total": len(result.issues),
        "issues": [
            {"row": i.row_number, "field": i.field, "severity": i.severity.value, "message": i.message}
            for i in result.issues[:MAX_ISSUES_REPORTED]
        ],
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))