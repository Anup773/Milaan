"""
Command-line entry points for the bank statement connector, called by the Node API as a subprocess.

    python -m engine.bank.cli preview <file> <bank account> <suspense account> <firm_id> <company_id>
        Read the statement and report what would be imported. Saves nothing.

    python -m engine.bank.cli import <file> <bank account> <suspense account> <firm_id> <company_id> <source_file_id>
        Read the statement and save its rows (two balanced lines per transaction).

Both print one JSON object like the other importers', plus a "bank" block (counts, totals, opening and closing
balance, the running-balance check, and how many transactions were already imported earlier).
On failure they print {"error": "...", "status": 400|500} to stderr and exit non-zero (400 for anything the person
can fix: a wrong file, no headings, a statement that was already imported; 500 for the unexpected).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Set

from ..db.connection import tenant_connection
from ..ingestion.persist import persist_parse_result
from .statement import BankError, BankParse, keys_of, mark_duplicates, parse_file

MAX_ISSUES_REPORTED = 25


def _fail(message: str, status: int) -> int:
    print(json.dumps({"error": message, "status": status}), file=sys.stderr)
    return 1


def existing_keys(firm_id: str, company_id: str, keys: list[str]) -> Set[str]:
    """Which of these transaction fingerprints did an earlier import already save for this company?"""
    if not keys:
        return set()
    found: Set[str] = set()
    with tenant_connection(firm_id, company_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT raw_json->>'txn_key' FROM source_rows WHERE company_id = %s AND raw_json->>'txn_key' = ANY(%s)",
                (company_id, keys),
            )
            found.update(row[0] for row in cur.fetchall() if row[0])
    return found


def _summary(parsed: BankParse, preview: bool) -> dict:
    result = parsed.result
    errors = sum(1 for i in result.issues if i.severity.value == "ERROR")
    warnings = sum(1 for i in result.issues if i.severity.value == "WARNING")
    # Show the problems that matter first: errors, then warnings, each in row order.
    ordered = sorted(result.issues, key=lambda i: (0 if i.severity.value == "ERROR" else 1, i.row_number))
    return {
        "rows": len(result.rows),
        "errors": errors,
        "warnings": warnings,
        "total_debit": str(result.total_debit),
        "total_credit": str(result.total_credit),
        "issues_total": len(result.issues),
        "issues": [
            {"row": i.row_number, "field": i.field, "severity": i.severity.value, "message": i.message}
            for i in ordered[:MAX_ISSUES_REPORTED]
        ],
        "bank": parsed.stats.as_dict(),
        "preview": preview,
    }


def _read(path: str, bank: str, suspense: str, firm_id: str, company_id: str, ref_tag: str) -> BankParse:
    parsed = parse_file(Path(path), bank, suspense, ref_tag=ref_tag)
    mark_duplicates(parsed, existing_keys(firm_id, company_id, keys_of(parsed)))
    return parsed


def cmd_preview(path: str, bank: str, suspense: str, firm_id: str, company_id: str) -> int:
    print(json.dumps(_summary(_read(path, bank, suspense, firm_id, company_id, "BS"), preview=True)))
    return 0


def cmd_import(path: str, bank: str, suspense: str, firm_id: str, company_id: str, source_file_id: str) -> int:
    parsed = _read(path, bank, suspense, firm_id, company_id, f"BS-{source_file_id[:6]}")
    persist_parse_result(firm_id=firm_id, company_id=company_id, source_file_id=source_file_id, result=parsed.result)
    print(json.dumps(_summary(parsed, preview=False)))
    return 0


def main(argv: list[str]) -> int:
    try:
        if len(argv) == 7 and argv[1] == "preview":
            return cmd_preview(*argv[2:7])
        if len(argv) == 8 and argv[1] == "import":
            return cmd_import(*argv[2:8])
        return _fail("usage: preview <file> <bank> <suspense> <firm> <company> | import <file> <bank> <suspense> <firm> <company> <source_file>", 500)
    except BankError as exc:
        return _fail(str(exc), 400)
    except Exception as exc:  # noqa: BLE001
        return _fail(str(exc), 500)


if __name__ == "__main__":
    sys.exit(main(sys.argv))