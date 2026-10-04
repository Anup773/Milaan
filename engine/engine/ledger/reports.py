"""
Trial Balance, Profit & Loss, Balance Sheet, General Ledger, and a
simplified Cash Flow -- read/aggregation queries over the SAME rows
(accounts, journal_entries, journal_lines) every time, per ARCHITECTURE.md
§3: "no separate 'statements' data structure, no risk of the displayed
numbers drifting from the ledger."

Every function takes an already-open `conn` from
engine.db.connection.tenant_connection -- same pattern as mapping/repository.py.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Dict, Tuple

from .money import signed_balance

ZERO = Decimal("0")


def _period_dates(conn, company_id: str, period_id: str) -> Tuple[date, date, str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT period_start, period_end, label FROM accounting_periods WHERE company_id = %s AND id = %s",
            (company_id, period_id),
        )
        row = cur.fetchone()
    if row is None:
        raise ValueError(f"accounting period {period_id} not found for company {company_id}")
    return row[0], row[1], row[2]


def trial_balance(conn, company_id: str, period_id: str) -> Dict[str, Any]:
    """
    Every account with any activity in this period: total debit, total
    credit, and the signed balance in the account's own normal direction.
    Sum of signed debit-normal balances always equals sum of signed
    credit-normal balances -- not asserted here, but guaranteed by
    migration 0002's balance-enforcing trigger on every posted entry.
    """
    period_start, period_end, period_label = _period_dates(conn, company_id, period_id)

    with conn.cursor() as cur:
        cur.execute(
            """
            WITH period_lines AS (
                SELECT jl.account_id, jl.debit, jl.credit
                FROM journal_lines jl
                JOIN journal_entries je ON je.id = jl.journal_entry_id
                WHERE je.company_id = %(company_id)s AND je.accounting_period_id = %(period_id)s
            )
            SELECT a.id, a.code, a.name, a.account_type,
                   COALESCE(SUM(pl.debit), 0) AS total_debit,
                   COALESCE(SUM(pl.credit), 0) AS total_credit
            FROM accounts a
            LEFT JOIN period_lines pl ON pl.account_id = a.id
            WHERE a.company_id = %(company_id)s
            GROUP BY a.id, a.code, a.name, a.account_type
            HAVING COALESCE(SUM(pl.debit), 0) <> 0 OR COALESCE(SUM(pl.credit), 0) <> 0
            ORDER BY a.code
            """,
            {"company_id": company_id, "period_id": period_id},
        )
        rows = cur.fetchall()

    lines = []
    for account_id, code, name, account_type, total_debit, total_credit in rows:
        lines.append({
            "account_id": str(account_id), "code": code, "name": name, "account_type": account_type,
            "total_debit": total_debit, "total_credit": total_credit,
            "balance": signed_balance(account_type, total_debit, total_credit),
        })

    return {
        "period_id": period_id, "period_label": period_label,
        "period_start": period_start, "period_end": period_end,
        "lines": lines,
        "total_debit": sum((l["total_debit"] for l in lines), ZERO),
        "total_credit": sum((l["total_credit"] for l in lines), ZERO),
    }


def profit_and_loss(conn, company_id: str, period_id: str) -> Dict[str, Any]:
    """Income accounts' balances minus Expense accounts' balances, for exactly this period."""
    tb = trial_balance(conn, company_id, period_id)
    income = [l for l in tb["lines"] if l["account_type"] == "Income"]
    expense = [l for l in tb["lines"] if l["account_type"] == "Expense"]
    total_income = sum((l["balance"] for l in income), ZERO)
    total_expense = sum((l["balance"] for l in expense), ZERO)
    return {
        "period_id": period_id, "period_label": tb["period_label"],
        "period_start": tb["period_start"], "period_end": tb["period_end"],
        "income": income, "expense": expense,
        "total_income": total_income, "total_expense": total_expense,
        "net_profit": total_income - total_expense,
    }


def balance_sheet(conn, company_id: str, as_of_date: date) -> Dict[str, Any]:
    """
    Point-in-time snapshot across ALL activity up to and including
    as_of_date -- not scoped to one period, since a balance sheet never is.
    "Retained earnings" isn't a real account yet (no closing-entry process
    exists -- that's Phase 9+), so it's computed here as cumulative net
    profit (all Income minus all Expense, ever, up to as_of_date). This
    makes Assets = Liabilities + Equity + Retained Earnings hold as an
    identity, not an approximation: every journal entry is balanced
    (migration 0002's trigger enforces it), so summed across literally
    every account, debit-normal minus credit-normal totals must net to
    zero company-wide -- `balances` below is computed, never assumed.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH lines_to_date AS (
                SELECT jl.account_id, jl.debit, jl.credit
                FROM journal_lines jl
                JOIN journal_entries je ON je.id = jl.journal_entry_id
                WHERE je.company_id = %(company_id)s AND je.entry_date <= %(as_of_date)s
            )
            SELECT a.id, a.code, a.name, a.account_type,
                   COALESCE(SUM(lt.debit), 0) AS total_debit,
                   COALESCE(SUM(lt.credit), 0) AS total_credit
            FROM accounts a
            LEFT JOIN lines_to_date lt ON lt.account_id = a.id
            WHERE a.company_id = %(company_id)s
            GROUP BY a.id, a.code, a.name, a.account_type
            HAVING COALESCE(SUM(lt.debit), 0) <> 0 OR COALESCE(SUM(lt.credit), 0) <> 0
            ORDER BY a.code
            """,
            {"company_id": company_id, "as_of_date": as_of_date},
        )
        rows = cur.fetchall()

    def line(account_id, code, name, account_type, total_debit, total_credit):
        return {
            "account_id": str(account_id), "code": code, "name": name,
            "balance": signed_balance(account_type, total_debit, total_credit),
        }

    assets = [line(*r) for r in rows if r[3] == "Asset"]
    liabilities = [line(*r) for r in rows if r[3] == "Liability"]
    equity = [line(*r) for r in rows if r[3] == "Equity"]
    income_total = sum((signed_balance("Income", r[4], r[5]) for r in rows if r[3] == "Income"), ZERO)
    expense_total = sum((signed_balance("Expense", r[4], r[5]) for r in rows if r[3] == "Expense"), ZERO)
    retained_earnings = income_total - expense_total

    total_assets = sum((l["balance"] for l in assets), ZERO)
    total_liabilities = sum((l["balance"] for l in liabilities), ZERO)
    total_equity = sum((l["balance"] for l in equity), ZERO)

    return {
        "as_of_date": as_of_date,
        "assets": assets, "liabilities": liabilities, "equity": equity,
        "retained_earnings": retained_earnings,
        "total_assets": total_assets,
        "total_liabilities": total_liabilities,
        "total_equity_and_retained_earnings": total_equity + retained_earnings,
        "balances": total_assets == (total_liabilities + total_equity + retained_earnings),
    }


def general_ledger(conn, company_id: str, account_id: str, period_id: str) -> Dict[str, Any]:
    """
    Every line affecting one account within one period, in date order,
    with a running balance in the account's own normal direction --
    starting from the account's balance immediately before the period
    (all activity strictly before period_start), the way a real general
    ledger reads: opening balance, then each transaction, ending at
    exactly the figure trial_balance() reports for this account+period.
    """
    period_start, period_end, period_label = _period_dates(conn, company_id, period_id)

    with conn.cursor() as cur:
        cur.execute("SELECT code, name, account_type FROM accounts WHERE company_id = %s AND id = %s", (company_id, account_id))
        account_row = cur.fetchone()
        if account_row is None:
            raise ValueError(f"account {account_id} not found for company {company_id}")
        code, name, account_type = account_row

        cur.execute(
            """
            SELECT COALESCE(SUM(jl.debit), 0), COALESCE(SUM(jl.credit), 0)
            FROM journal_lines jl
            JOIN journal_entries je ON je.id = jl.journal_entry_id
            WHERE je.company_id = %s AND jl.account_id = %s AND je.entry_date < %s
            """,
            (company_id, account_id, period_start),
        )
        opening_debit, opening_credit = cur.fetchone()
        opening_balance = signed_balance(account_type, opening_debit, opening_credit)

        cur.execute(
            """
            SELECT je.entry_date, je.description, jl.debit, jl.credit, je.id
            FROM journal_lines jl
            JOIN journal_entries je ON je.id = jl.journal_entry_id
            WHERE je.company_id = %s AND jl.account_id = %s AND je.accounting_period_id = %s
            ORDER BY je.entry_date, je.id
            """,
            (company_id, account_id, period_id),
        )
        activity_rows = cur.fetchall()

    running = opening_balance
    lines = []
    for entry_date, description, debit, credit, journal_entry_id in activity_rows:
        running += signed_balance(account_type, debit, credit)
        lines.append({
            "entry_date": entry_date, "description": description,
            "debit": debit, "credit": credit,
            "journal_entry_id": str(journal_entry_id),
            "running_balance": running,
        })

    return {
        "account_id": account_id, "code": code, "name": name, "account_type": account_type,
        "period_id": period_id, "period_label": period_label,
        "period_start": period_start, "period_end": period_end,
        "opening_balance": opening_balance,
        "lines": lines,
        "closing_balance": running,
    }


def cash_flow(conn, company_id: str, period_id: str) -> Dict[str, Any]:
    """
    Net cash flow for the period: total movement, in each account's own
    normal direction, summed across every account flagged is_cash=true
    (migration 0003) -- by construction, exactly equal to the actual
    change in cash and bank balances over the period. This is a single
    net total, not yet broken into operating/investing/financing -- that
    categorization needs either per-transaction tagging or a comparative
    balance sheet plus non-cash adjustments (the indirect method), neither
    of which exists yet. Flagged here, not hidden.
    """
    period_start, period_end, period_label = _period_dates(conn, company_id, period_id)

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT a.id, a.code, a.name, a.account_type,
                   COALESCE(SUM(jl.debit), 0) AS total_debit,
                   COALESCE(SUM(jl.credit), 0) AS total_credit
            FROM accounts a
            JOIN journal_lines jl ON jl.account_id = a.id
            JOIN journal_entries je ON je.id = jl.journal_entry_id AND je.accounting_period_id = %(period_id)s
            WHERE a.company_id = %(company_id)s AND a.is_cash = true
            GROUP BY a.id, a.code, a.name, a.account_type
            ORDER BY a.code
            """,
            {"company_id": company_id, "period_id": period_id},
        )
        rows = cur.fetchall()

    lines = [
        {
            "account_id": str(account_id), "code": code, "name": name,
            "net_movement": signed_balance(account_type, total_debit, total_credit),
        }
        for account_id, code, name, account_type, total_debit, total_credit in rows
    ]

    return {
        "period_id": period_id, "period_label": period_label,
        "period_start": period_start, "period_end": period_end,
        "cash_accounts": lines,
        "net_cash_flow": sum((l["net_movement"] for l in lines), ZERO),
        "note": "total net movement across accounts flagged is_cash; not yet broken into operating/investing/financing",
    }