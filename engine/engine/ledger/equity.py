"""
Statement of changes in equity -- ARCHITECTURE.md §3 again: read straight from the ledger, nothing stored separately.

For one accounting period, every equity account shows its opening balance, what was added (credits: shares issued,
transfers in), what was taken out (debits: dividends, transfers out) and its closing balance. There is one more
component, the profit of the business that no closing entry has moved into equity yet: Milaan has no closing-entry
process, so the balance sheet calls it "retained earnings" and computes it as all income minus all expense up to the
date. Here it is shown as its own line: opening (profit up to the day before the period), the profit of the period,
and closing (profit up to the end of the period).

Everything is computed by ENTRY DATE (period start to period end), the same basis as the balance sheet, so the
closing total of this statement equals the balance sheet's equity plus retained earnings at the period end. The profit
of the period is ALSO compared with the profit and loss statement, which is computed by the period an entry is
filed in: if an entry is dated outside the period it is filed in, the two differ and `profit_agrees` says so.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Dict, List

from .money import signed_balance
from .reports import _period_dates, balance_sheet, profit_and_loss

ZERO = Decimal("0")


def _sums(conn, company_id: str, start: date, end: date, *, before: bool) -> Dict[str, Any]:
    """Debit and credit totals per account. before=True: all entries dated before `start`; else dated start..end."""
    cond = "je.entry_date < %(start)s" if before else "je.entry_date BETWEEN %(start)s AND %(end)s"
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT a.id, a.code, a.name, a.account_type, COALESCE(SUM(jl.debit), 0), COALESCE(SUM(jl.credit), 0)
            FROM accounts a
            JOIN journal_lines jl ON jl.account_id = a.id
            JOIN journal_entries je ON je.id = jl.journal_entry_id
            WHERE a.company_id = %(company_id)s AND je.company_id = %(company_id)s AND {cond}
            GROUP BY a.id, a.code, a.name, a.account_type
            """,
            {"company_id": company_id, "start": start, "end": end},
        )
        return {str(r[0]): r[1:] for r in cur.fetchall()}


def changes_in_equity(conn, company_id: str, period_id: str) -> Dict[str, Any]:
    start, end, label = _period_dates(conn, company_id, period_id)
    before = _sums(conn, company_id, start, end, before=True)
    during = _sums(conn, company_id, start, end, before=False)

    components: List[Dict[str, Any]] = []
    profit_before = profit_during = ZERO
    for account_id in sorted(set(before) | set(during), key=lambda a: (before.get(a) or during.get(a))[0]):
        b = before.get(account_id)
        d = during.get(account_id)
        code, name, account_type = (b or d)[0], (b or d)[1], (b or d)[2]
        b_debit, b_credit = (b[3], b[4]) if b else (ZERO, ZERO)
        d_debit, d_credit = (d[3], d[4]) if d else (ZERO, ZERO)
        if account_type == "Income":
            profit_before += signed_balance("Income", b_debit, b_credit)
            profit_during += signed_balance("Income", d_debit, d_credit)
        elif account_type == "Expense":
            profit_before -= signed_balance("Expense", b_debit, b_credit)
            profit_during -= signed_balance("Expense", d_debit, d_credit)
        elif account_type == "Equity":
            opening = signed_balance("Equity", b_debit, b_credit)
            closing = signed_balance("Equity", b_debit + d_debit, b_credit + d_credit)
            if opening == 0 and d_debit == 0 and d_credit == 0 and closing == 0:
                continue
            components.append({
                "kind": "account", "account_id": account_id, "code": code, "name": name,
                "opening": opening, "increases": d_credit, "decreases": d_debit, "profit": ZERO, "closing": closing,
            })
    components.sort(key=lambda c: c["code"])

    components.append({
        "kind": "retained_profit", "account_id": None, "code": None,
        "name": "Profit and loss not yet closed to equity (accumulated)",
        "opening": profit_before, "increases": ZERO, "decreases": ZERO, "profit": profit_during,
        "closing": profit_before + profit_during,
    })

    totals = {k: sum((c[k] for c in components), ZERO) for k in ("opening", "increases", "decreases", "profit", "closing")}
    bs = balance_sheet(conn, company_id, end)
    pl = profit_and_loss(conn, company_id, period_id)
    return {
        "period_id": period_id, "period_label": label, "period_start": start, "period_end": end,
        "components": components, "totals": totals,
        "profit_for_period": profit_during,
        "balance_sheet_equity": bs["total_equity_and_retained_earnings"],
        "agrees_with_balance_sheet": totals["closing"] == bs["total_equity_and_retained_earnings"],
        "profit_and_loss_net_profit": pl["net_profit"],
        "profit_agrees": profit_during == pl["net_profit"],
        "rolls_forward": all(c["opening"] + c["increases"] - c["decreases"] + c["profit"] == c["closing"] for c in components),
    }