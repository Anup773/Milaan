"""
Command-line entry points for the register connector (sales, purchase and payroll registers), called by the Node
API as a subprocess.

    python -m engine.registers.cli templates
        The register types, the columns each one looks for, and the default account names.

    python -m engine.registers.cli preview <template> <file> <accounts_json> <date or -> <party_accounts 0|1> <firm_id> <company_id>
        Read the file and report what would be imported. Saves nothing.

    python -m engine.registers.cli import <template> <file> <accounts_json> <date or -> <party_accounts 0|1> <firm_id> <company_id> <source_file_id>
        Read the file and save its rows (one balanced voucher per register row).

`accounts_json` is a JSON object of role -> account name (any role left out uses its default name).
Both import commands print one JSON object like the other importers', plus a "register" block (counts and a
summary of totals). On failure they print {"error": "...", "status": 400|500} to stderr and exit non-zero (400 for
anything the person can fix; 500 for the unexpected).
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from typing import Dict, Optional

from ..bank.cli import existing_keys
from ..bank.statement import BankError
from ..ingestion.persist import persist_parse_result
from .register import RegisterError, RegisterParse, keys_of, mark_duplicates, parse_file
from .templates import describe_all

MAX_ISSUES_REPORTED = 25


def _fail(message: str, status: int) -> int:
    print(json.dumps({"error": message, "status": status}), file=sys.stderr)
    return 1


def _accounts(text: str) -> Dict[str, str]:
    try:
        value = json.loads(text)
    except ValueError as exc:
        raise RegisterError("the account names were not understood") from exc
    if not isinstance(value, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
        raise RegisterError("the account names were not understood")
    return value


def _default_date(text: str) -> Optional[date]:
    if text in ("", "-"):
        return None
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise RegisterError(f"the voucher date must look like 2026-03-31 (got {text!r})") from exc


def _summary(parsed: RegisterParse, preview: bool) -> dict:
    result = parsed.result
    errors = sum(1 for i in result.issues if i.severity.value == "ERROR")
    warnings = sum(1 for i in result.issues if i.severity.value == "WARNING")
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
        "register": {"template": parsed.template, **parsed.stats.as_dict()},
        "preview": preview,
    }


def _read(template: str, path: str, accounts_json: str, date_text: str, party_flag: str, firm_id: str, company_id: str, ref_tag: str) -> RegisterParse:
    parsed = parse_file(Path(path), template, _accounts(accounts_json), _default_date(date_text), party_flag == "1", ref_tag=ref_tag)
    mark_duplicates(parsed, existing_keys(firm_id, company_id, keys_of(parsed)))
    return parsed


def cmd_templates() -> int:
    print(json.dumps({"templates": describe_all()}))
    return 0


def cmd_preview(template: str, path: str, accounts_json: str, date_text: str, party_flag: str, firm_id: str, company_id: str) -> int:
    print(json.dumps(_summary(_read(template, path, accounts_json, date_text, party_flag, firm_id, company_id, "RG"), preview=True)))
    return 0


def cmd_import(template: str, path: str, accounts_json: str, date_text: str, party_flag: str, firm_id: str, company_id: str, source_file_id: str) -> int:
    parsed = _read(template, path, accounts_json, date_text, party_flag, firm_id, company_id, f"RG-{source_file_id[:6]}")
    persist_parse_result(firm_id=firm_id, company_id=company_id, source_file_id=source_file_id, result=parsed.result)
    print(json.dumps(_summary(parsed, preview=False)))
    return 0


def main(argv: list[str]) -> int:
    try:
        if len(argv) == 2 and argv[1] == "templates":
            return cmd_templates()
        if len(argv) == 9 and argv[1] == "preview":
            return cmd_preview(*argv[2:9])
        if len(argv) == 10 and argv[1] == "import":
            return cmd_import(*argv[2:10])
        return _fail("usage: templates | preview <template> <file> <accounts_json> <date|-> <party 0|1> <firm> <company> | import ... <source_file>", 500)
    except (RegisterError, BankError) as exc:
        return _fail(str(exc), 400)
    except Exception as exc:  # noqa: BLE001
        return _fail(str(exc), 500)


if __name__ == "__main__":
    sys.exit(main(sys.argv))