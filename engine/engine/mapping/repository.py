"""
Database-facing half of Phase 5. planner.py is pure logic with no database
calls (so it's cheaply unit-testable); this module is the thin layer that
loads real rows/mappings/periods from Postgres, calls the planner, and
writes the result back -- the three functions the handoff doc calls for:
find_unmapped_refs, confirm_mapping, materialize_source_file.

Every function here takes an already-open `conn` from
engine.db.connection.tenant_connection(firm_id, company_id) -- it does not
open connections itself, so the CLI (or a future direct API) controls the
transaction boundary and which tenant it's scoped to.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .planner import Period, SourceRow, normalize_ref, plan_entries

VALID_ACCOUNT_TYPES = {"Asset", "Liability", "Equity", "Income", "Expense"}


def find_unmapped_refs(conn, company_id: str) -> List[Dict[str, Any]]:
    """
    One entry per distinct account, after normalization -- so 'Bank Account'
    and 'bank  account' (voice-dictated spacing, inconsistent capitalisation)
    collapse into a single item instead of two, however many source files or
    rows they appear across. `sample_text` is the exact text from the
    earliest-appearing row, for display; `row_count` is the total across all
    spelling variants of that same key.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT account_ref, count(*), min(row_number)
            FROM source_rows
            WHERE company_id = %s AND btrim(account_ref) <> ''
            GROUP BY account_ref
            """,
            (company_id,),
        )
        raw_groups = cur.fetchall()

        cur.execute("SELECT account_ref_key FROM account_mappings WHERE company_id = %s", (company_id,))
        mapped_keys = {row[0] for row in cur.fetchall()}

    grouped: Dict[str, Dict[str, Any]] = {}
    for account_ref, row_count, first_row_number in raw_groups:
        key = normalize_ref(account_ref)
        if key in mapped_keys:
            continue
        bucket = grouped.setdefault(key, {
            "account_ref_key": key,
            "sample_text": account_ref,
            "row_count": 0,
            "first_row_number": first_row_number,
        })
        bucket["row_count"] += row_count
        if first_row_number < bucket["first_row_number"]:
            bucket["first_row_number"] = first_row_number
            bucket["sample_text"] = account_ref

    return sorted(grouped.values(), key=lambda g: g["first_row_number"])


def confirm_mapping(
    conn,
    *,
    company_id: str,
    account_ref: str,
    confirmed_by: Optional[str],
    account_id: Optional[str] = None,
    new_account: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Exactly one of account_id / new_account must be given. Returns the
    account id the mapping now points to (as a string).

    Confirming the same account_ref again re-points the mapping rather than
    erroring, since correcting an earlier mistake is a normal thing for a CA
    to need to do. A voucher already posted under the old account keeps its
    original journal_lines untouched -- reposting under a corrected mapping
    is a job for the reconciliation/adjustment phases, not this function.
    """
    if (account_id is None) == (new_account is None):
        raise ValueError("pass exactly one of account_id or new_account")

    key = normalize_ref(account_ref)

    with conn.cursor() as cur:
        if new_account is not None:
            account_type = new_account["account_type"]
            if account_type not in VALID_ACCOUNT_TYPES:
                raise ValueError(f"invalid account_type {account_type!r}; must be one of {sorted(VALID_ACCOUNT_TYPES)}")
            cur.execute(
                """
                INSERT INTO accounts (company_id, code, name, account_type, parent_account_id)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
                """,
                (company_id, new_account["code"], new_account["name"], account_type, new_account.get("parent_account_id")),
            )
            account_id = str(cur.fetchone()[0])
        else:
            cur.execute("SELECT id FROM accounts WHERE company_id = %s AND id = %s", (company_id, account_id))
            if cur.fetchone() is None:
                raise ValueError(f"account {account_id} does not belong to company {company_id}")

        cur.execute(
            """
            INSERT INTO account_mappings (company_id, account_ref, account_ref_key, account_id, confirmed_by)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (company_id, account_ref_key)
            DO UPDATE SET account_id = EXCLUDED.account_id,
                          account_ref = EXCLUDED.account_ref,
                          confirmed_by = EXCLUDED.confirmed_by,
                          confirmed_at = now()
            """,
            (company_id, account_ref, key, account_id, confirmed_by),
        )

    return account_id


def _load_rows_for_file(conn, company_id: str, source_file_id: str) -> List[SourceRow]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, row_number, account_ref, transaction_date, description,
                   debit, credit, reference, status, raw_json
            FROM source_rows
            WHERE company_id = %s AND source_file_id = %s
            ORDER BY row_number
            """,
            (company_id, source_file_id),
        )
        rows = cur.fetchall()

    out = []
    for row_id, row_number, account_ref, txn_date, description, debit, credit, reference, status, raw_json in rows:
        issues = tuple(raw_json.get("_issues", [])) if isinstance(raw_json, dict) else ()
        out.append(SourceRow(
            id=str(row_id), row_number=row_number, account_ref=account_ref or "",
            transaction_date=txn_date, description=description or "",
            debit=debit, credit=credit, reference=reference or "",
            status=status, issues=issues,
        ))
    return out


def _load_mappings(conn, company_id: str) -> Dict[str, str]:
    with conn.cursor() as cur:
        cur.execute("SELECT account_ref_key, account_id FROM account_mappings WHERE company_id = %s", (company_id,))
        return {key: str(account_id) for key, account_id in cur.fetchall()}


def _load_periods(conn, company_id: str) -> List[Period]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, label, period_start, period_end, lock_status FROM accounting_periods WHERE company_id = %s",
            (company_id,),
        )
        return [
            Period(id=str(pid), label=label, start=start, end=end, locked=(lock_status == "LOCKED"))
            for pid, label, start, end, lock_status in cur.fetchall()
        ]


def materialize_source_file(conn, *, company_id: str, source_file_id: str, created_by: Optional[str]) -> Dict[str, Any]:
    """
    Turns every postable voucher in one uploaded file into a real,
    balanced journal_entries + journal_lines pair. Never partially posts a
    voucher: a group either becomes one complete entry with every line, or
    it is reported under "blocked" and nothing is written for it.

    Idempotent: re-running this on a file already materialized posts
    nothing new for the groups already posted (matched via
    journal_entries.source_row_id) -- safe to call again after confirming
    more mappings, or simply retry.
    """
    rows = _load_rows_for_file(conn, company_id, source_file_id)
    mapping = _load_mappings(conn, company_id)
    periods = _load_periods(conn, company_id)
    plan = plan_entries(rows, mapping, periods)

    posted = 0
    already_posted = 0
    with conn.cursor() as cur:
        for entry in plan.entries:
            cur.execute("SELECT id FROM journal_entries WHERE source_row_id = %s", (entry.anchor_row_id,))
            if cur.fetchone() is not None:
                already_posted += 1
                continue

            cur.execute(
                """
                INSERT INTO journal_entries
                    (company_id, accounting_period_id, entry_date, description, source_row_id, created_by)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (company_id, entry.period_id, entry.entry_date, entry.description, entry.anchor_row_id, created_by),
            )
            journal_entry_id = cur.fetchone()[0]

            for line in entry.lines:
                cur.execute(
                    """
                    INSERT INTO journal_lines
                        (company_id, journal_entry_id, account_id, debit, credit, source_row_id)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (company_id, journal_entry_id, line.account_id, line.debit, line.credit, line.source_row_id),
                )
            posted += 1

    return {
        "posted": posted,
        "already_posted": already_posted,
        "blocked": [
            {"key": b.key, "row_numbers": list(b.row_numbers), "reasons": list(b.reasons)}
            for b in plan.blocked
        ],
        "skipped": [
            {"key": s.key, "row_numbers": list(s.row_numbers), "reason": s.reason}
            for s in plan.skipped
        ],
        "posted_with_warnings": [
            {"key": e.key, "row_numbers": list(e.row_numbers), "warnings": list(e.warnings)}
            for e in plan.entries if e.warnings
        ],
    }

