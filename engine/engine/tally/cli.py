"""
Command-line entry points for the Tally connector, called by the Node API as a subprocess.

    python -m engine.tally.cli status
        Is Tally reachable, and which companies does it have open? Always exits 0:
        {"reachable": true|false, "url": "...", "companies": [...], "message": "..."}

    python -m engine.tally.cli import-file <xml_path> <firm_id> <company_id> <source_file_id>
        Parse a Tally XML export (Day Book) and save its rows.

    python -m engine.tally.cli import-live <from YYYY-MM-DD> <to YYYY-MM-DD> <tally_company or -> <firm_id> <company_id> <source_file_id>
        Fetch the Day Book from a running Tally, then parse and save it.

Both import commands print one JSON object like the Excel/CSV importer's, plus a "tally" block with voucher counts.
On failure they print {"error": "...", "status": 400|500} to stderr and exit non-zero (400 for bad input or an
unreachable Tally, 500 for anything unexpected).
"""
from __future__ import annotations

import json
import sys
from datetime import date

from ..ingestion.persist import persist_parse_result
from . import client
from .parser import TallyError, TallyParse, parse_tally_xml

MAX_ISSUES_REPORTED = 25


def _fail(message: str, status: int) -> int:
    print(json.dumps({"error": message, "status": status}), file=sys.stderr)
    return 1


def _summary(parsed: TallyParse) -> dict:
    result = parsed.result
    errors = sum(1 for i in result.issues if i.severity.value == "ERROR")
    warnings = sum(1 for i in result.issues if i.severity.value == "WARNING")
    return {
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
        "tally": parsed.stats.as_dict(),
    }


def _iso(value: str, label: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise TallyError(f"{label} must be a date like 2025-04-01 (got {value!r})") from exc


def cmd_status() -> int:
    try:
        url = client.tally_url()
    except TallyError as exc:
        print(json.dumps({"reachable": False, "url": None, "companies": [], "message": str(exc)}))
        return 0
    try:
        companies = client.list_companies()
    except TallyError as exc:
        print(json.dumps({"reachable": False, "url": url, "companies": [], "message": str(exc)}))
        return 0
    print(json.dumps({"reachable": True, "url": url, "companies": companies, "message": "Connected to Tally."}))
    return 0


def cmd_import_file(path: str, firm_id: str, company_id: str, source_file_id: str) -> int:
    with open(path, "rb") as handle:
        parsed = parse_tally_xml(handle.read())
    persist_parse_result(firm_id=firm_id, company_id=company_id, source_file_id=source_file_id, result=parsed.result)
    print(json.dumps(_summary(parsed)))
    return 0


def cmd_import_live(from_text: str, to_text: str, tally_company: str, firm_id: str, company_id: str, source_file_id: str) -> int:
    start, end = _iso(from_text, "the start date"), _iso(to_text, "the end date")
    body = client.fetch_day_book(start, end, None if tally_company in ("", "-") else tally_company)
    parsed = parse_tally_xml(body)
    persist_parse_result(firm_id=firm_id, company_id=company_id, source_file_id=source_file_id, result=parsed.result)
    print(json.dumps(_summary(parsed)))
    return 0


def main(argv: list[str]) -> int:
    try:
        if len(argv) == 2 and argv[1] == "status":
            return cmd_status()
        if len(argv) == 6 and argv[1] == "import-file":
            return cmd_import_file(*argv[2:])
        if len(argv) == 8 and argv[1] == "import-live":
            return cmd_import_live(*argv[2:])
        return _fail("usage: status | import-file <xml> <firm> <company> <source_file> | import-live <from> <to> <tally_company|-> <firm> <company> <source_file>", 500)
    except TallyError as exc:
        return _fail(str(exc), 400)
    except Exception as exc:  # noqa: BLE001
        return _fail(str(exc), 500)


if __name__ == "__main__":
    sys.exit(main(sys.argv))