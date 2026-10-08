
"""
The built-in reconciliation rules. Importing this module registers them.

Two kinds, and each rule says which (RULES[...].scope):
  ledger   -- looks at the books as actually posted. A what-if scenario
              cannot change these answers (the scenario isn't posted yet).
  scenario -- evaluated on the dependency-graph figures, so it also checks a
              scenario's what-if numbers when overrides are supplied.

Numbers are Decimal, never float. Money is shown to 2 decimals.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Tuple

from ..schedules.fixed_assets import compute_period_depreciation
from ..schedules.repository import _accumulated_before, _load_assets
from .registry import ERROR, NOT_CHECKED, PASS, WARNING, ReconContext, RuleResult, register_rule, result

ZERO = Decimal("0.00")
EXAMPLES = 10  # how many example rows a rule lists in its details


def _m(x: Decimal) -> str:
    return f"{x:,.2f}"


def compare_account_totals(schedule: Dict[str, Decimal], ledger: Dict[str, Decimal],
                           names: Dict[str, str]) -> List[Dict[str, Any]]:
    """Pure: accounts where the schedule's total and the ledger balance differ."""
    out = []
    for account_id in sorted(schedule, key=lambda a: names.get(a, a)):
        s, l = schedule[account_id], ledger.get(account_id, ZERO)
        if s != l:
            out.append({"account": names.get(account_id, account_id), "account_id": account_id,
                        "schedule": s, "ledger": l, "difference": l - s})
    return out


# ── 1. trial balance ─────────────────────────────────────────────────────
@register_rule("trial_balance_balanced", "Trial balance: debits equal credits",
               "Total debits and total credits posted in the period must be equal.")
def trial_balance_balanced(ctx: ReconContext) -> RuleResult:
    with ctx.conn.cursor() as cur:
        cur.execute(
            """
            SELECT COALESCE(SUM(jl.debit), 0), COALESCE(SUM(jl.credit), 0), COUNT(*)
            FROM journal_lines jl JOIN journal_entries je ON je.id = jl.journal_entry_id
            WHERE je.company_id = %s AND je.accounting_period_id = %s
            """,
            (ctx.company_id, ctx.period_id),
        )
        debit, credit, n = cur.fetchone()
    if n == 0:
        return result("trial_balance_balanced", NOT_CHECKED, "No ledger lines are posted in this period yet.")
    if debit != credit:
        return result("trial_balance_balanced", ERROR,
                      f"Debits {_m(debit)} and credits {_m(credit)} differ by {_m(abs(debit - credit))}.",
                      total_debit=debit, total_credit=credit, lines=n)
    return result("trial_balance_balanced", PASS, f"Debits and credits both total {_m(debit)} across {n} lines.",
                  total_debit=debit, total_credit=credit, lines=n)


# ── 2. balance sheet ─────────────────────────────────────────────────────
@register_rule("balance_sheet_balanced", "Balance sheet: assets = liabilities + equity",
               "Assets must equal liabilities plus equity plus retained earnings. "
               "With what-if figures supplied, this checks the scenario's balance sheet.",
               scope="scenario")
def balance_sheet_balanced(ctx: ReconContext) -> RuleResult:
    if "bs:check" not in ctx.model.specs:
        return result("balance_sheet_balanced", NOT_CHECKED, "No balance sheet is available to check.")
    v = ctx.values()
    diff = v["bs:check"]
    basis = "scenario " if ctx.has_overrides else ""
    if diff != 0:
        return result("balance_sheet_balanced", ERROR,
                      f"The {basis}balance sheet is out of balance by {_m(abs(diff))}.",
                      assets=v["bs:total_assets"], liabilities=v["bs:total_liabilities"],
                      equity=v["bs:total_equity"], retained_earnings=v["bs:retained_earnings"], difference=diff)
    return result("balance_sheet_balanced", PASS,
                  f"The {basis}balance sheet balances: assets {_m(v['bs:total_assets'])}.",
                  assets=v["bs:total_assets"], liabilities=v["bs:total_liabilities"],
                  equity=v["bs:total_equity"], retained_earnings=v["bs:retained_earnings"])


# ── 3. fixed assets vs ledger ────────────────────────────────────────────
@register_rule("fixed_asset_accumulated_depreciation", "Fixed assets: schedule agrees with the ledger",
               "For each accumulated-depreciation account, the depreciation the schedule has posted "
               "(all assets sharing that account added together) must equal the account's ledger balance.")
def fixed_asset_accumulated_depreciation(ctx: ReconContext) -> RuleResult:
    rid = "fixed_asset_accumulated_depreciation"
    _, period_end, _ = ctx.period
    with ctx.conn.cursor() as cur:
        cur.execute(
            """
            SELECT fa.accumulated_depreciation_account_id, a.code || ' ' || a.name,
                   COALESCE(SUM(fade.amount), 0)
            FROM fixed_assets fa
            JOIN accounts a ON a.id = fa.accumulated_depreciation_account_id
            LEFT JOIN fixed_asset_depreciation_entries fade
                   ON fade.fixed_asset_id = fa.id
                  AND fade.accounting_period_id IN (
                        SELECT id FROM accounting_periods WHERE company_id = %(c)s AND period_end <= %(end)s)
            WHERE fa.company_id = %(c)s
            GROUP BY fa.accumulated_depreciation_account_id, a.code, a.name
            """,
            {"c": ctx.company_id, "end": period_end},
        )
        rows = cur.fetchall()
        if not rows:
            return result(rid, NOT_CHECKED, "This company has no fixed assets to check.")
        schedule = {str(r[0]): r[2] for r in rows}
        names = {str(r[0]): r[1] for r in rows}

        cur.execute(
            """
            SELECT jl.account_id, COALESCE(SUM(jl.credit), 0) - COALESCE(SUM(jl.debit), 0)
            FROM journal_lines jl JOIN journal_entries je ON je.id = jl.journal_entry_id
            WHERE je.company_id = %s AND je.entry_date <= %s AND jl.account_id = ANY(%s)
            GROUP BY jl.account_id
            """,
            (ctx.company_id, period_end, list(schedule)),
        )
        ledger = {str(r[0]): r[1] for r in cur.fetchall()}

    bad = compare_account_totals(schedule, ledger, names)
    if bad:
        worst = bad[0]
        return result(rid, ERROR,
                      f"{len(bad)} accumulated-depreciation account(s) disagree with the schedule; "
                      f"{worst['account']}: schedule {_m(worst['schedule'])}, ledger {_m(worst['ledger'])}.",
                      mismatches=bad, accounts_checked=len(schedule))
    return result(rid, PASS, f"{len(schedule)} accumulated-depreciation account(s) agree with the schedule.",
                  accounts_checked=len(schedule))


# ── 4. depreciation due but not posted ───────────────────────────────────
@register_rule("depreciation_posted_for_period", "Fixed assets: depreciation posted for the period",
               "Every asset with depreciation due in the period should have it posted to the ledger.")
def depreciation_posted_for_period(ctx: ReconContext) -> RuleResult:
    rid = "depreciation_posted_for_period"
    period_start, period_end, label = ctx.period
    assets = _load_assets(ctx.conn, ctx.company_id)
    if not assets:
        return result(rid, NOT_CHECKED, "This company has no fixed assets to check.")

    due: List[Dict[str, Any]] = []
    with ctx.conn.cursor() as cur:
        for item in assets:
            asset = item["asset"]
            cur.execute("SELECT 1 FROM fixed_asset_depreciation_entries WHERE fixed_asset_id = %s AND accounting_period_id = %s",
                        (asset.id, ctx.period_id))
            if cur.fetchone() is not None:
                continue
            amount = compute_period_depreciation(asset, period_start, period_end,
                                                 _accumulated_before(ctx.conn, asset.id, period_start))
            if amount > ZERO:
                due.append({"asset": asset.name, "fixed_asset_id": str(asset.id), "amount_due": amount})
    if due:
        total = sum((d["amount_due"] for d in due), ZERO)
        return result(rid, WARNING,
                      f"{len(due)} asset(s) have depreciation of {_m(total)} due for {label} that is not posted yet.",
                      assets_due=due, total_due=total)
    return result(rid, PASS, f"Depreciation for {label} is posted for every asset that has any due.",
                  assets_checked=len(assets))


# ── 5 & 6. uploaded data vs ledger ───────────────────────────────────────
@register_rule("source_rows_with_errors", "Uploaded data: rows with errors",
               "Source rows that failed validation are not in the ledger; they should be fixed or consciously left out.")
def source_rows_with_errors(ctx: ReconContext) -> RuleResult:
    rid = "source_rows_with_errors"
    start, end, _ = ctx.period
    with ctx.conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*), COUNT(*) FILTER (WHERE status = 'ERROR')
            FROM source_rows
            WHERE company_id = %s AND (transaction_date IS NULL OR transaction_date BETWEEN %s AND %s)
            """,
            (ctx.company_id, start, end),
        )
        total, errors = cur.fetchone()
        if total == 0:
            return result(rid, NOT_CHECKED, "No uploaded rows fall in this period.")
        if errors == 0:
            return result(rid, PASS, f"None of the {total} uploaded rows has a validation error.", rows=total)
        cur.execute(
            """
            SELECT sf.filename, sr.row_number, sr.account_ref FROM source_rows sr
            JOIN source_files sf ON sf.id = sr.source_file_id
            WHERE sr.company_id = %s AND sr.status = 'ERROR'
              AND (sr.transaction_date IS NULL OR sr.transaction_date BETWEEN %s AND %s)
            ORDER BY sf.filename, sr.row_number LIMIT %s
            """,
            (ctx.company_id, start, end, EXAMPLES),
        )
        examples = [{"file": f, "row": n, "account": a} for f, n, a in cur.fetchall()]
    return result(rid, WARNING, f"{errors} of {total} uploaded rows have validation errors and are not in the ledger.",
                  rows=total, rows_with_errors=errors, examples=examples)


@register_rule("source_rows_in_ledger", "Uploaded data: valid rows reached the ledger",
               "Every valid uploaded row with an amount, dated in the period, should appear in the ledger.")
def source_rows_in_ledger(ctx: ReconContext) -> RuleResult:
    rid = "source_rows_in_ledger"
    start, end, _ = ctx.period
    where = """
        sr.company_id = %s AND sr.status <> 'ERROR' AND (sr.debit <> 0 OR sr.credit <> 0)
        AND sr.transaction_date BETWEEN %s AND %s
    """
    with ctx.conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM source_rows sr WHERE {where}", (ctx.company_id, start, end))
        usable = cur.fetchone()[0]
        if usable == 0:
            return result(rid, NOT_CHECKED, "No valid uploaded rows with an amount fall in this period.")
        cur.execute(
            f"""
            SELECT COUNT(*) FROM source_rows sr WHERE {where}
              AND NOT EXISTS (SELECT 1 FROM journal_lines jl WHERE jl.source_row_id = sr.id)
            """,
            (ctx.company_id, start, end),
        )
        missing = cur.fetchone()[0]
        if missing == 0:
            return result(rid, PASS, f"All {usable} valid uploaded rows are in the ledger.", rows=usable)
        cur.execute(
            f"""
            SELECT sf.filename, sr.row_number, sr.account_ref, sr.debit, sr.credit
            FROM source_rows sr JOIN source_files sf ON sf.id = sr.source_file_id
            WHERE {where} AND NOT EXISTS (SELECT 1 FROM journal_lines jl WHERE jl.source_row_id = sr.id)
            ORDER BY sf.filename, sr.row_number LIMIT %s
            """,
            (ctx.company_id, start, end, EXAMPLES),
        )
        examples = [{"file": f, "row": n, "account": a, "debit": d, "credit": c} for f, n, a, d, c in cur.fetchall()]
    return result(rid, WARNING,
                  f"{missing} of {usable} valid uploaded rows are not in the ledger yet (for example, accounts not mapped).",
                  rows=usable, rows_not_in_ledger=missing, examples=examples)


# ── 7. adjustments waiting for a second person ───────────────────────────
@register_rule("adjustments_pending_review", "Adjustments: none waiting for approval",
               "Proposed adjustments are not in the ledger until a second person approves them.")
def adjustments_pending_review(ctx: ReconContext) -> RuleResult:
    rid = "adjustments_pending_review"
    with ctx.conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, description, entry_date FROM adjustments
            WHERE company_id = %s AND accounting_period_id = %s AND status = 'REVIEW_REQUIRED'
            ORDER BY created_at LIMIT %s
            """,
            (ctx.company_id, ctx.period_id, EXAMPLES),
        )
        pending = [{"adjustment_id": str(i), "description": d, "entry_date": e} for i, d, e in cur.fetchall()]
    if pending:
        return result(rid, WARNING, f"{len(pending)} adjustment(s) are waiting for a second person's approval and are not in the ledger.",
                      pending=pending)
    return result(rid, PASS, "No adjustments are waiting for approval in this period.")