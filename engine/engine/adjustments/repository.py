"""
Database-facing half of the adjustment engine. planner.py validates a
proposed set of lines; this module creates the proposal, lists/reads it,
and handles the two terminal actions -- approve (posts to the real
ledger) and reject (never does). This is the first place in the project
where "review before it reaches the ledger" is a real, enforced gate, not
just a described intention: propose_adjustment() never touches
journal_entries/journal_lines at all; only approve_adjustment() does,
and only after a successful, atomic claim.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional

from .planner import ProposedLine, validate_lines


def propose_adjustment(
    conn, *, company_id: str, period_id: str, entry_date, description: str, reason: str,
    lines: List[Dict[str, Any]], proposed_by: str,
) -> Dict[str, Any]:
    proposed_lines = [
        ProposedLine(account_id=l["account_id"], debit=Decimal(str(l["debit"])), credit=Decimal(str(l["credit"])))
        for l in lines
    ]
    is_valid, reasons = validate_lines(proposed_lines)
    if not is_valid:
        raise ValueError("; ".join(reasons))

    with conn.cursor() as cur:
        cur.execute("SELECT lock_status FROM accounting_periods WHERE company_id = %s AND id = %s", (company_id, period_id))
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"accounting period {period_id} not found for company {company_id}")
        if row[0] == "LOCKED":
            raise ValueError("accounting period is locked")

        cur.execute(
            """
            INSERT INTO adjustments (company_id, accounting_period_id, entry_date, description, reason, proposed_by)
            VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
            """,
            (company_id, period_id, entry_date, description, reason, proposed_by),
        )
        adjustment_id = cur.fetchone()[0]

        for line in proposed_lines:
            cur.execute(
                "INSERT INTO adjustment_lines (company_id, adjustment_id, account_id, debit, credit) VALUES (%s, %s, %s, %s, %s)",
                (company_id, adjustment_id, line.account_id, line.debit, line.credit),
            )

    return {"adjustment_id": str(adjustment_id), "status": "REVIEW_REQUIRED"}


def list_adjustments(conn, company_id: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
    query = """
        SELECT id, accounting_period_id, entry_date, description, reason, status,
               proposed_by, reviewed_by, reviewed_at, rejection_note, journal_entry_id, created_at
        FROM adjustments WHERE company_id = %s
    """
    params: List[Any] = [company_id]
    if status:
        query += " AND status = %s"
        params.append(status)
    query += " ORDER BY created_at DESC"

    with conn.cursor() as cur:
        cur.execute(query, params)
        rows = cur.fetchall()

    return [_row_to_dict(r) for r in rows]


def get_adjustment(conn, company_id: str, adjustment_id: str) -> Dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, accounting_period_id, entry_date, description, reason, status,
                   proposed_by, reviewed_by, reviewed_at, rejection_note, journal_entry_id, created_at
            FROM adjustments WHERE company_id = %s AND id = %s
            """,
            (company_id, adjustment_id),
        )
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"adjustment {adjustment_id} not found for company {company_id}")

        cur.execute("SELECT account_id, debit, credit FROM adjustment_lines WHERE adjustment_id = %s", (adjustment_id,))
        lines = cur.fetchall()

    result = _row_to_dict(row)
    result["lines"] = [{"account_id": str(a), "debit": d, "credit": c} for a, d, c in lines]
    return result


def _row_to_dict(row) -> Dict[str, Any]:
    (aid, period_id, entry_date, description, reason, status,
     proposed_by, reviewed_by, reviewed_at, rejection_note, journal_entry_id, created_at) = row
    return {
        "id": str(aid), "accounting_period_id": str(period_id), "entry_date": entry_date,
        "description": description, "reason": reason, "status": status,
        "proposed_by": str(proposed_by), "reviewed_by": str(reviewed_by) if reviewed_by else None,
        "reviewed_at": reviewed_at, "rejection_note": rejection_note,
        "journal_entry_id": str(journal_entry_id) if journal_entry_id else None, "created_at": created_at,
    }


def approve_adjustment(conn, *, company_id: str, adjustment_id: str, reviewed_by: str) -> Dict[str, Any]:
    """
    The claim (the UPDATE below) happens BEFORE anything is posted, and is
    both the race guard (two concurrent approvals can't both succeed --
    only one UPDATE can match status='REVIEW_REQUIRED') and the
    maker-checker check (proposed_by <> reviewed_by), combined into one
    atomic statement rather than check-then-act. If the period turns out
    to be locked, this function simply raises -- tenant_connection wraps
    the whole call in one transaction, so raising rolls back the claim
    along with everything else, not just the parts after it.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE adjustments SET status = 'POSTED', reviewed_by = %s, reviewed_at = now()
            WHERE company_id = %s AND id = %s AND status = 'REVIEW_REQUIRED' AND proposed_by <> %s
            RETURNING accounting_period_id, entry_date, description
            """,
            (reviewed_by, company_id, adjustment_id, reviewed_by),
        )
        claimed = cur.fetchone()
        if claimed is None:
            _raise_why_approval_failed(cur, company_id, adjustment_id, reviewed_by)

        period_id, entry_date, description = claimed

        cur.execute("SELECT lock_status FROM accounting_periods WHERE id = %s", (period_id,))
        if cur.fetchone()[0] == "LOCKED":
            raise ValueError("accounting period is now locked -- cannot post")

        cur.execute("SELECT account_id, debit, credit FROM adjustment_lines WHERE adjustment_id = %s", (adjustment_id,))
        lines = cur.fetchall()

        cur.execute(
            """
            INSERT INTO journal_entries (company_id, accounting_period_id, entry_date, description, created_by)
            VALUES (%s, %s, %s, %s, %s) RETURNING id
            """,
            (company_id, period_id, entry_date, description, reviewed_by),
        )
        journal_entry_id = cur.fetchone()[0]

        for account_id, debit, credit in lines:
            cur.execute(
                "INSERT INTO journal_lines (company_id, journal_entry_id, account_id, debit, credit) VALUES (%s, %s, %s, %s, %s)",
                (company_id, journal_entry_id, account_id, debit, credit),
            )

        cur.execute("UPDATE adjustments SET journal_entry_id = %s WHERE id = %s", (journal_entry_id, adjustment_id))

    return {"adjustment_id": str(adjustment_id), "status": "POSTED", "journal_entry_id": str(journal_entry_id)}


def reject_adjustment(conn, *, company_id: str, adjustment_id: str, reviewed_by: str, rejection_note: Optional[str]) -> Dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE adjustments SET status = 'REJECTED', reviewed_by = %s, reviewed_at = now(), rejection_note = %s
            WHERE company_id = %s AND id = %s AND status = 'REVIEW_REQUIRED' AND proposed_by <> %s
            RETURNING id
            """,
            (reviewed_by, rejection_note, company_id, adjustment_id, reviewed_by),
        )
        if cur.fetchone() is None:
            _raise_why_approval_failed(cur, company_id, adjustment_id, reviewed_by)

    return {"adjustment_id": str(adjustment_id), "status": "REJECTED"}


def _raise_why_approval_failed(cur, company_id: str, adjustment_id: str, reviewed_by: str) -> None:
    """Shared, read-only diagnosis for why an approve/reject claim matched zero rows."""
    cur.execute("SELECT status, proposed_by FROM adjustments WHERE company_id = %s AND id = %s", (company_id, adjustment_id))
    existing = cur.fetchone()
    if existing is None:
        raise ValueError(f"adjustment {adjustment_id} not found for company {company_id}")
    status, proposed_by = existing
    if str(proposed_by) == str(reviewed_by):
        raise ValueError("the reviewer must be different from whoever proposed this adjustment")
    raise ValueError(f"adjustment is {status}, not REVIEW_REQUIRED -- nothing to do")