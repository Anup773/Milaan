"""
Writes a ParseResult into Postgres, using the real schema from migration
0001 -- this replaces the earlier persist_stub.py draft now that the
schema is real and tested (see engine/migrations/0001_init_canonical_schema.sql
and its README for the RLS design this relies on).
"""
from __future__ import annotations

from psycopg.types.json import Jsonb

from .models import ParseResult
from ..db.connection import tenant_connection


def persist_parse_result(*, firm_id: str, company_id: str, source_file_id: str, result: ParseResult) -> None:
    row_has_error = {
        issue.row_number
        for issue in result.issues
        if issue.severity.value == "ERROR"
    }

    with tenant_connection(firm_id, company_id) as conn:
        for row in result.rows:
            status = "ERROR" if row.row_number in row_has_error else "OK"
            conn.execute(
                """
                INSERT INTO source_rows
                    (company_id, source_file_id, row_number, account_ref, transaction_date,
                     description, debit, credit, reference, raw_json, status)
                VALUES
                    (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    company_id, source_file_id, row.row_number, row.account_ref, row.transaction_date,
                    row.description, row.debit, row.credit, row.reference,
                    Jsonb(row.raw), status,
                ),
            )
