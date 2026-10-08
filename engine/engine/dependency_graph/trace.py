"""
"Why does this number exist?" -- the lower half of the drill-down chain in
ARCHITECTURE.md §11: account -> transactions -> source file/row ->
adjustment. For one account, lists every ledger line behind its balance
and says where each came from:

  source_row   -- built from an uploaded file row (file name + row number)
  adjustment   -- a manual correction (reason, who proposed, who approved)
  depreciation -- posted by the fixed-asset schedule (which asset)
  manual       -- none of the above (no trace recorded)

Supporting evidence documents are a later phase and are not included.
"""
from __future__ import annotations

from typing import Any, Dict

from ..ledger.reports import _period_dates


def trace_account(conn, company_id: str, period_id: str, account_id: str, scope: str = "period") -> Dict[str, Any]:
    if scope not in ("period", "cumulative"):
        raise ValueError("scope must be 'period' or 'cumulative'")
    _, period_end, period_label = _period_dates(conn, company_id, period_id)

    with conn.cursor() as cur:
        cur.execute("SELECT code, name, account_type FROM accounts WHERE company_id = %s AND id = %s", (company_id, account_id))
        account = cur.fetchone()
        if account is None:
            raise ValueError(f"account {account_id} not found for company {company_id}")

        scope_filter = "je.accounting_period_id = %(p)s" if scope == "period" else "je.entry_date <= %(end)s"
        cur.execute(
            f"""
            SELECT je.id, je.entry_date, je.description, jl.debit, jl.credit,
                   sr.row_number, sf.id, sf.filename,
                   adj.id, adj.reason, adj.proposed_by, adj.reviewed_by,
                   fade.fixed_asset_id, fa.name
            FROM journal_lines jl
            JOIN journal_entries je ON je.id = jl.journal_entry_id
            LEFT JOIN source_rows sr ON sr.id = COALESCE(jl.source_row_id, je.source_row_id)
            LEFT JOIN source_files sf ON sf.id = sr.source_file_id
            LEFT JOIN adjustments adj ON adj.journal_entry_id = je.id
            LEFT JOIN fixed_asset_depreciation_entries fade ON fade.journal_entry_id = je.id
            LEFT JOIN fixed_assets fa ON fa.id = fade.fixed_asset_id
            WHERE je.company_id = %(c)s AND jl.account_id = %(a)s AND {scope_filter}
            ORDER BY je.entry_date, je.id
            """,
            {"c": company_id, "a": account_id, "p": period_id, "end": period_end},
        )
        rows = cur.fetchall()

    lines = []
    for (je_id, entry_date, description, debit, credit, row_number, file_id, filename,
         adj_id, adj_reason, adj_by, adj_reviewer, fa_id, fa_name) in rows:
        if adj_id is not None:
            origin = {"type": "adjustment", "adjustment_id": str(adj_id), "reason": adj_reason,
                      "proposed_by": str(adj_by), "reviewed_by": str(adj_reviewer) if adj_reviewer else None}
        elif fa_id is not None:
            origin = {"type": "depreciation", "fixed_asset_id": str(fa_id), "asset_name": fa_name}
        elif row_number is not None:
            origin = {"type": "source_row", "source_file_id": str(file_id), "filename": filename, "row_number": row_number}
        else:
            origin = {"type": "manual"}
        lines.append({
            "journal_entry_id": str(je_id), "entry_date": entry_date, "description": description,
            "debit": debit, "credit": credit, "origin": origin,
        })

    code, name, account_type = account
    return {
        "account_id": account_id, "code": code, "name": name, "account_type": account_type,
        "period_id": period_id, "period_label": period_label, "scope": scope, "lines": lines,
    }