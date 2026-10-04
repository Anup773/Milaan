"""
Writes a ParseResult into Postgres, using the real schema from migration
0001 (source_rows).

Two things this file is careful about:

* Excel cells arrive as datetime/date objects, which plain JSON can't store.
  They are converted to ISO text before being saved in raw_json.
* Every row's status is saved truthfully: ERROR if the row had an error,
  WARNING if it only had warnings, OK otherwise. The messages themselves are
  saved inside raw_json under "_issues", so the reason a row was flagged is
  never lost (Phase 5 shows these reasons when it blocks a voucher).
"""
from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any, List, Tuple

from psycopg.types.json import Jsonb

from .models import ParsedSourceRow, ParseIssue, ParseResult, Severity
from ..db.connection import tenant_connection


def _json_default(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def _dumps(obj: Any) -> str:
    return json.dumps(obj, default=_json_default)


def build_row_record(row: ParsedSourceRow, issues: List[ParseIssue]) -> Tuple[str, dict]:
    """Returns (status, raw_json_dict) for one parsed row."""
    if any(i.severity == Severity.ERROR for i in issues):
        status = "ERROR"
    elif issues:
        status = "WARNING"
    else:
        status = "OK"

    raw = dict(row.raw)
    if issues:
        raw["_issues"] = [f"{i.severity.value}: {i.field}: {i.message}" for i in issues]
    return status, raw


def persist_parse_result(*, firm_id: str, company_id: str, source_file_id: str, result: ParseResult) -> None:
    issues_by_row: dict = {}
    for issue in result.issues:
        issues_by_row.setdefault(issue.row_number, []).append(issue)

    params = []
    for row in result.rows:
        status, raw = build_row_record(row, issues_by_row.get(row.row_number, []))
        params.append((
            company_id, source_file_id, row.row_number, row.account_ref, row.transaction_date,
            row.description, row.debit, row.credit, row.reference,
            Jsonb(raw, dumps=_dumps), status,
        ))

    with tenant_connection(firm_id, company_id) as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO source_rows
                    (company_id, source_file_id, row_number, account_ref, transaction_date,
                     description, debit, credit, reference, raw_json, status)
                VALUES
                    (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                params,
            )
