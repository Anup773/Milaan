"""
Command-line entry points for the Google Sheets connector, called by the Node API as a subprocess.

    python -m engine.sheets.cli status
        Which way sheets will be read, and (for a service account) the email to share sheets with. Always exits 0.

    python -m engine.sheets.cli check <link_or_id>
        Can the sheet be reached? Returns its title and tabs (tabs are only listed with a service account).

    python -m engine.sheets.cli import <link_or_id> <tab title or -> <firm_id> <company_id> <source_file_id>
        Read one tab, parse it with the normal import rules and save its rows.

On failure they print {"error": "...", "status": 400|500} to stderr and exit non-zero (400 for anything the person
can fix: a private sheet, a wrong tab, no header; 500 for the unexpected).
"""
from __future__ import annotations

import json
import sys
from typing import Optional

from ..ingestion.persist import persist_parse_result
from . import client
from .parser import parse_rows
from .source import SheetsError, parse_sheet_reference

MAX_ISSUES_REPORTED = 25


def _fail(message: str, status: int) -> int:
    print(json.dumps({"error": message, "status": status}), file=sys.stderr)
    return 1


def cmd_status() -> int:
    try:
        account = client.load_service_account()
    except SheetsError as exc:
        print(json.dumps({"mode": "service_account_error", "service_account_email": None, "message": str(exc)}))
        return 0
    if account:
        message = f"Private sheets work: share a sheet with {account.email} (Viewer is enough)."
        print(json.dumps({"mode": "service_account", "service_account_email": account.email, "message": message}))
    else:
        message = "No service account is set up, so only sheets shared as 'Anyone with the link can view' can be read (one tab at a time)."
        print(json.dumps({"mode": "public_link", "service_account_email": None, "message": message}))
    return 0


def cmd_check(link: str) -> int:
    ref = parse_sheet_reference(link)
    account = client.load_service_account()
    if account:
        info = client.get_sheet_info(ref, account)
        chosen = next((t for t in info.tabs if t.gid == ref.gid), None)
        print(json.dumps({
            "mode": "service_account",
            "title": info.title,
            "tabs": [{"title": t.title, "gid": t.gid} for t in info.tabs],
            "suggested_tab": (chosen or info.tabs[0]).title,
        }))
        return 0
    rows = client.fetch_public_csv_rows(ref)  # proves the sheet is reachable and public
    print(json.dumps({"mode": "public_link", "title": None, "tabs": [], "suggested_tab": None, "rows_seen": len(rows), "gid": ref.gid if ref.gid is not None else 0}))
    return 0


def cmd_import(link: str, tab: str, firm_id: str, company_id: str, source_file_id: str) -> int:
    ref = parse_sheet_reference(link)
    account = client.load_service_account()
    tab_title: Optional[str]
    if account:
        info = client.get_sheet_info(ref, account)
        if tab not in ("", "-"):
            match = next((t for t in info.tabs if t.title == tab), None)
            if match is None:
                raise SheetsError(f"this spreadsheet has no tab called {tab!r}")
        else:
            match = next((t for t in info.tabs if t.gid == ref.gid), None) or info.tabs[0]
        values = client.fetch_tab_values(ref, match.title, account)
        tab_title, sheet_title, mode = match.title, info.title, "service_account"
        label = f"Google Sheet: {sheet_title} / {tab_title}"
    else:
        values = client.fetch_public_csv_rows(ref)
        tab_title, sheet_title, mode = None, None, "public_link"
        label = f"Google Sheet {ref.sheet_id[:8]}... (tab {ref.gid if ref.gid is not None else 0})"

    result = parse_rows(values, tab_title)
    persist_parse_result(firm_id=firm_id, company_id=company_id, source_file_id=source_file_id, result=result)

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
        "sheet": {"mode": mode, "title": sheet_title, "tab": tab_title, "label": label},
    }))
    return 0


def main(argv: list[str]) -> int:
    try:
        if len(argv) == 2 and argv[1] == "status":
            return cmd_status()
        if len(argv) == 3 and argv[1] == "check":
            return cmd_check(argv[2])
        if len(argv) == 7 and argv[1] == "import":
            return cmd_import(*argv[2:])
        return _fail("usage: status | check <link> | import <link> <tab|-> <firm> <company> <source_file>", 500)
    except SheetsError as exc:
        return _fail(str(exc), 400)
    except Exception as exc:  # noqa: BLE001
        return _fail(str(exc), 500)


if __name__ == "__main__":
    sys.exit(main(sys.argv))