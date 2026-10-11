"""
Database-facing half of Phase 13: loads two imports, hands them to the pure diff
engine, and adds what only the database knows -- which rows are already posted to
the ledger, which accounts are mapped, which periods are locked.

Strictly READ-ONLY. Nothing here writes to any table, so there is no migration
for this phase and nothing to roll back: source rows are never edited after import
(Phase 4 writes them once), so a comparison is a pure function of the two files
and is simply recomputed each time. Turning a difference into a ledger change is
deliberately not done here -- that is what Phase 7 adjustments (with their
second-person approval) are for.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from ..mapping.planner import Period
from . import impact as imp
from .matcher import count_kinds, diff_rows
from .models import CHANGED, KINDS, REMOVED, UNCHANGED, RowChange, RowVersion

DEFAULT_LIMIT = 500
MAX_LIMIT = 2000


def _file_meta(conn, company_id: str, file_ids: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT sf.id, sf.filename, sf.uploaded_at, sf.status, sf.uploaded_by,
                   COUNT(sr.id), COUNT(sr.id) FILTER (WHERE sr.status = 'ERROR'), COUNT(sr.id) FILTER (WHERE sr.status = 'WARNING'),
                   COALESCE(SUM(sr.debit) FILTER (WHERE sr.status <> 'ERROR'), 0),
                   COALESCE(SUM(sr.credit) FILTER (WHERE sr.status <> 'ERROR'), 0),
                   MIN(sr.transaction_date), MAX(sr.transaction_date)
            FROM source_files sf LEFT JOIN source_rows sr ON sr.source_file_id = sf.id
            WHERE sf.company_id = %s AND sf.id = ANY(%s::uuid[])
            GROUP BY sf.id
            """,
            (company_id, list(file_ids)),
        )
        rows = cur.fetchall()
        cur.execute(
            """
            SELECT sr.source_file_id, COUNT(DISTINCT jl.source_row_id)
            FROM journal_lines jl JOIN source_rows sr ON sr.id = jl.source_row_id
            WHERE jl.company_id = %s AND sr.source_file_id = ANY(%s::uuid[])
            GROUP BY sr.source_file_id
            """,
            (company_id, list(file_ids)),
        )
        posted = {str(fid): n for fid, n in cur.fetchall()}
    out: Dict[str, Dict[str, Any]] = {}
    for fid, name, at, status, by, n, n_err, n_warn, debit, credit, first, last in rows:
        fid = str(fid)
        out[fid] = {"id": fid, "filename": name, "uploaded_at": at, "status": status,
                    "uploaded_by": str(by) if by else None, "rows": n, "rows_with_errors": n_err,
                    "rows_with_warnings": n_warn, "total_debit": debit, "total_credit": credit,
                    "first_date": first, "last_date": last, "rows_posted_to_ledger": posted.get(fid, 0)}
    return out


def list_files(conn, company_id: str) -> List[Dict[str, Any]]:
    """Every import for the company, newest first: what you can choose to compare."""
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM source_files WHERE company_id = %s", (company_id,))
        ids = [str(r[0]) for r in cur.fetchall()]
    if not ids:
        return []
    meta = _file_meta(conn, company_id, ids)
    return sorted(meta.values(), key=lambda f: (f["uploaded_at"], f["id"]), reverse=True)


def _load_rows(conn, company_id: str, file_id: str) -> List[RowVersion]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, row_number, account_ref, transaction_date, description, debit, credit, reference, status
            FROM source_rows WHERE company_id = %s AND source_file_id = %s ORDER BY row_number, id
            """,
            (company_id, file_id),
        )
        return [RowVersion(str(i), n, ref or "", d, desc or "", debit, credit, reference or "", status)
                for i, n, ref, d, desc, debit, credit, reference, status in cur.fetchall()]


def _posted_row_ids(conn, company_id: str, file_ids: Sequence[str]) -> set:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT jl.source_row_id FROM journal_lines jl JOIN source_rows sr ON sr.id = jl.source_row_id
            WHERE jl.company_id = %s AND sr.source_file_id = ANY(%s::uuid[])
            """,
            (company_id, list(file_ids)),
        )
        return {str(r[0]) for r in cur.fetchall()}


def _mapped_accounts(conn, company_id: str) -> Dict[str, Dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT m.account_ref_key, a.id, a.code, a.name, a.account_type
            FROM account_mappings m JOIN accounts a ON a.id = m.account_id
            WHERE m.company_id = %s
            """,
            (company_id,),
        )
        return {key: {"id": str(i), "code": code, "name": name, "account_type": t} for key, i, code, name, t in cur.fetchall()}


def _periods(conn, company_id: str) -> List[Period]:
    with conn.cursor() as cur:
        cur.execute("SELECT id, label, period_start, period_end, lock_status FROM accounting_periods WHERE company_id = %s", (company_id,))
        return [Period(id=str(i), label=l, start=s, end=e, locked=(st == "LOCKED")) for i, l, s, e, st in cur.fetchall()]


def _change_dict(c: RowChange, posted: set) -> Dict[str, Any]:
    return {"kind": c.kind, "matched_by": c.matched_by,
            "old": c.old.to_dict() if c.old else None, "new": c.new.to_dict() if c.new else None,
            "fields": [f.to_dict() for f in c.fields],
            "old_posted": (c.old.id in posted) if c.old else None,
            "new_posted": (c.new.id in posted) if c.new else None}


def compare(conn, *, company_id: str, base_file_id: str, compare_file_id: str, kinds: Optional[Sequence[str]] = None,
            include_unchanged: bool = False, limit: int = DEFAULT_LIMIT, offset: int = 0) -> Dict[str, Any]:
    """
    Compares an older import (base) with a newer one (compare). `kinds` filters the row list
    (default: every changed, added and removed row; UNCHANGED rows only with include_unchanged
    or kinds=["UNCHANGED"]). The summary always counts every row, whatever is listed.
    """
    if base_file_id == compare_file_id:
        raise ValueError("choose two different imports to compare")
    if kinds is not None:
        bad = [k for k in kinds if k not in KINDS]
        if bad:
            raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    limit, offset = max(1, min(int(limit), MAX_LIMIT)), max(0, int(offset))

    meta = _file_meta(conn, company_id, [base_file_id, compare_file_id])
    for label, fid in (("base", base_file_id), ("compare", compare_file_id)):
        if fid not in meta:
            raise ValueError(f"{label} import {fid} not found for company {company_id}")

    old_rows, new_rows = _load_rows(conn, company_id, base_file_id), _load_rows(conn, company_id, compare_file_id)
    changes = diff_rows(old_rows, new_rows)
    kind_counts = count_kinds(changes)
    posted = _posted_row_ids(conn, company_id, [base_file_id, compare_file_id])
    periods = _periods(conn, company_id)

    period_rows = imp.by_period(old_rows, new_rows, changes, periods)
    already_posted_changes = sum(1 for c in changes if c.kind in (CHANGED, REMOVED) and c.old.id in posted)
    posted_in_both = sum(1 for c in changes if c.old and c.new and c.old.id in posted and c.new.id in posted)

    warnings: List[str] = []
    for label, fid in (("base", base_file_id), ("compare", compare_file_id)):
        if meta[fid]["status"] != "PROCESSED":
            warnings.append(f"The {label} import is {meta[fid]['status']}, not PROCESSED; its rows may be incomplete.")
        if meta[fid]["rows_with_errors"]:
            warnings.append(f"The {label} import has {meta[fid]['rows_with_errors']} row(s) with errors; they are listed but left out of every total.")
    if meta[compare_file_id]["uploaded_at"] < meta[base_file_id]["uploaded_at"]:
        warnings.append("The compare import was uploaded before the base import; differences read as changes from the later file to the earlier one.")
    if posted_in_both:
        warnings.append(f"{posted_in_both} matched row(s) have been posted to the ledger from BOTH imports, which may count them twice; review before relying on the ledger.")
    if already_posted_changes:
        warnings.append(f"{already_posted_changes} changed or removed row(s) were already posted to the ledger from the base import; "
                        "the ledger does not follow a re-import, so a correction needs an adjustment.")
    for p in imp.locked_periods_affected(period_rows):
        warnings.append(f"Period {p['label']} is LOCKED and is touched by these differences; it must be reopened before any correction.")

    if kinds is not None:
        wanted = set(kinds)
    else:
        wanted = {CHANGED, "ADDED", REMOVED} | ({UNCHANGED} if include_unchanged else set())
    listed = [c for c in changes if c.kind in wanted]

    return {
        "base": meta[base_file_id], "compare": meta[compare_file_id],
        "summary": {"base_rows": len(old_rows), "compare_rows": len(new_rows),
                    "unchanged": kind_counts[UNCHANGED], "changed": kind_counts[CHANGED],
                    "added": kind_counts["ADDED"], "removed": kind_counts[REMOVED],
                    "already_posted_changes": already_posted_changes, "posted_in_both": posted_in_both},
        "totals": imp.totals(old_rows, new_rows),
        "by_account": imp.by_account(old_rows, new_rows, changes, _mapped_accounts(conn, company_id)),
        "by_period": period_rows,
        "locked_periods_affected": imp.locked_periods_affected(period_rows),
        "warnings": warnings,
        "changes": [_change_dict(c, posted) for c in listed[offset:offset + limit]],
        "changes_total": len(listed), "limit": limit, "offset": offset,
    }