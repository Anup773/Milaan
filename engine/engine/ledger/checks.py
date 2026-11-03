"""
Checks BETWEEN statements, and a way to compare a set of printed statement figures with the ledger.

The two sample statements show why this matters: in Kalinchowk's, the cash flow ends at 29,346,013 while the balance
sheet and its cash note say 27,767,065, a gap of 1,578,948 that is the dividend paid (shown in the equity statement but
missing from the cash flow). Nothing inside a set of statements prepared by hand forces them to agree, so each pair
that should agree is checked, and a difference is reported with both figures, never smoothed over.

Comparison allows for rounding: a company whose statements are in whole units may differ from the ledger by up to 1
unit (policy.statement_rounding); a company with exact amounts may not differ at all.

Pure comparison helpers have no database; the functions that read the ledger take an open `conn`.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any, Dict, List, Mapping, Optional

from ..policy.repository import effective as effective_policy
from .equity import changes_in_equity
from .reports import _period_dates, balance_sheet, cash_flow, profit_and_loss
from .rounding import agree, tolerance

ZERO = Decimal("0")
PASS, ERROR, NOT_CHECKED = "PASS", "ERROR", "NOT_CHECKED"

# The figures a person can type in from a printed set of statements, and what each is called.
FIGURE_LABELS: Dict[str, str] = {
    "total_assets": "Total assets",
    "total_liabilities": "Total liabilities",
    "total_equity": "Total equity (including accumulated profit)",
    "total_income": "Total income",
    "total_expense": "Total expenses",
    "net_profit": "Net profit for the period",
    "opening_cash": "Cash and bank at the start of the period",
    "net_cash_flow": "Net movement in cash during the period",
    "closing_cash": "Cash and bank at the end of the period",
}


def _m(x: Decimal) -> str:
    return f"{x:,.2f}"


def compare(label: str, a: Decimal, b: Decimal, rounding: str, a_name: str, b_name: str) -> Dict[str, Any]:
    """Pure: one comparison of two figures, as a result row."""
    diff = Decimal(a) - Decimal(b)
    ok = agree(a, b, rounding)
    if ok:
        note = "agree" if diff == 0 else f"agree within rounding (they differ by {_m(abs(diff))})"
        message = f"{label}: {a_name} {_m(a)} and {b_name} {_m(b)} {note}."
    else:
        message = f"{label}: {a_name} is {_m(a)} but {b_name} is {_m(b)}, a difference of {_m(abs(diff))}."
    return {"status": PASS if ok else ERROR, "message": message, "first": a, "second": b, "difference": diff,
            "first_name": a_name, "second_name": b_name}


def _cash_balance(conn, company_id: str, *, on_or_before=None, before=None) -> Decimal:
    """Cash and bank (accounts flagged is_cash) at the end of `on_or_before`, or just before `before`. Asset: debit - credit."""
    cond, value = ("je.entry_date <= %s", on_or_before) if on_or_before is not None else ("je.entry_date < %s", before)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT COALESCE(SUM(jl.debit), 0) - COALESCE(SUM(jl.credit), 0)
            FROM journal_lines jl
            JOIN journal_entries je ON je.id = jl.journal_entry_id
            JOIN accounts a ON a.id = jl.account_id
            WHERE a.company_id = %s AND a.is_cash = true AND je.company_id = %s AND {cond}
            """,
            (company_id, company_id, value),
        )
        return cur.fetchone()[0]


def entries_outside_period(conn, company_id: str, period_id: str) -> Dict[str, Any]:
    """Entries filed in this period whose date falls outside it, and entries dated inside it but filed elsewhere."""
    start, end, _ = _period_dates(conn, company_id, period_id)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) FILTER (WHERE accounting_period_id = %(p)s AND entry_date NOT BETWEEN %(s)s AND %(e)s),
                   COUNT(*) FILTER (WHERE accounting_period_id <> %(p)s AND entry_date BETWEEN %(s)s AND %(e)s)
            FROM journal_entries WHERE company_id = %(c)s
            """,
            {"p": period_id, "s": start, "e": end, "c": company_id},
        )
        filed_here, dated_here = cur.fetchone()
    return {"filed_here_dated_elsewhere": filed_here, "dated_here_filed_elsewhere": dated_here}


def statement_ties(conn, company_id: str, period_id: str) -> List[Dict[str, Any]]:
    """The checks between statements for one period. Each row: id, title, status, message and the figures compared."""
    rounding = effective_policy(conn, company_id).statement_rounding
    start, end, _ = _period_dates(conn, company_id, period_id)
    checks: List[Dict[str, Any]] = []

    # 1. entries dated in the period they are filed in (the others depend on it)
    stray = entries_outside_period(conn, company_id, period_id)
    n_stray = stray["filed_here_dated_elsewhere"] + stray["dated_here_filed_elsewhere"]
    checks.append({
        "id": "entries_dated_in_period", "title": "Entries are dated inside the period they are filed in",
        "status": PASS if n_stray == 0 else ERROR,
        "message": ("Every entry is dated inside the period it is filed in." if n_stray == 0 else
                    f"{stray['filed_here_dated_elsewhere']} entries are filed in this period but dated outside it, and "
                    f"{stray['dated_here_filed_elsewhere']} are dated inside it but filed in another period. The profit and loss "
                    "(by period) and the balance sheet (by date) will not agree until these are fixed."),
        **stray,
    })

    equity = changes_in_equity(conn, company_id, period_id)
    # 2. equity statement against the balance sheet
    c = compare("Equity", equity["totals"]["closing"], equity["balance_sheet_equity"], rounding,
                "the statement of changes in equity", "the balance sheet")
    checks.append({"id": "equity_ties_to_balance_sheet", "title": "Statement of changes in equity agrees with the balance sheet", **c})
    # 3. the profit in the equity statement against the profit and loss statement
    pl = profit_and_loss(conn, company_id, period_id)
    c = compare("Profit for the period", equity["profit_for_period"], pl["net_profit"], rounding,
                "the statement of changes in equity", "the profit and loss statement")
    checks.append({"id": "profit_ties_to_equity", "title": "Profit in the equity statement agrees with the profit and loss", **c})
    # 4. cash: opening + net movement = closing
    cash_accounts = cash_flow(conn, company_id, period_id)["cash_accounts"]
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM accounts WHERE company_id = %s AND is_cash = true", (company_id,))
        n_cash = cur.fetchone()[0]
    if n_cash == 0:
        checks.append({"id": "cash_ties_to_balance_sheet", "title": "Cash flow agrees with the cash on the balance sheet",
                       "status": NOT_CHECKED, "message": "No account is flagged as cash or bank, so there is no cash to check."})
    else:
        opening = _cash_balance(conn, company_id, before=start)
        closing = _cash_balance(conn, company_id, on_or_before=end)
        movement = cash_flow(conn, company_id, period_id)["net_cash_flow"]
        c = compare("Cash", opening + movement, closing, rounding,
                    f"the opening cash {_m(opening)} plus the cash flow {_m(movement)}", "the balance sheet's closing cash")
        checks.append({"id": "cash_ties_to_balance_sheet", "title": "Cash flow agrees with the cash on the balance sheet",
                       "opening_cash": opening, "net_cash_flow": movement, "closing_cash": closing, **c})
    # 5. the balance sheet balances
    bs = balance_sheet(conn, company_id, end)
    c = compare("Balance sheet", bs["total_assets"], bs["total_liabilities"] + bs["total_equity_and_retained_earnings"], rounding,
                "total assets", "liabilities plus equity")
    checks.append({"id": "balance_sheet_balances", "title": "Balance sheet balances", **c})
    return checks


def compare_figures(conn, company_id: str, period_id: str, figures: Mapping[str, Any]) -> Dict[str, Any]:
    """
    Compares printed statement figures with the ledger. `figures` maps a key from FIGURE_LABELS to the amount printed
    (a Decimal or text such as '1,25,000'). Unknown keys and unreadable amounts are refused (ValueError), so a typo is
    never silently skipped. The ledger side is computed by the same code as the statements.
    """
    from ..ingestion.money_parse import parse_amount

    if not isinstance(figures, Mapping) or not figures:
        raise ValueError("give at least one figure to compare")
    unknown = sorted(set(figures) - set(FIGURE_LABELS))
    if unknown:
        raise ValueError(f"unknown figure(s): {', '.join(unknown)}; allowed: {', '.join(FIGURE_LABELS)}")
    given: Dict[str, Decimal] = {}
    for key, raw in figures.items():
        try:
            given[key] = parse_amount(str(raw)) if not isinstance(raw, Decimal) else raw
        except ValueError:
            raise ValueError(f"{FIGURE_LABELS[key]}: {raw!r} is not an amount") from None

    policy = effective_policy(conn, company_id)
    start, end, label = _period_dates(conn, company_id, period_id)
    bs = balance_sheet(conn, company_id, end)
    pl = profit_and_loss(conn, company_id, period_id)
    ledger: Dict[str, Decimal] = {
        "total_assets": bs["total_assets"], "total_liabilities": bs["total_liabilities"],
        "total_equity": bs["total_equity_and_retained_earnings"],
        "total_income": pl["total_income"], "total_expense": pl["total_expense"], "net_profit": pl["net_profit"],
        "opening_cash": _cash_balance(conn, company_id, before=start),
        "net_cash_flow": cash_flow(conn, company_id, period_id)["net_cash_flow"],
        "closing_cash": _cash_balance(conn, company_id, on_or_before=end),
    }
    rows = []
    for key in FIGURE_LABELS:
        if key not in given:
            continue
        c = compare(FIGURE_LABELS[key], given[key], ledger[key], policy.statement_rounding, "the printed figure", "the ledger")
        rows.append({"key": key, "label": FIGURE_LABELS[key], "printed": given[key], "ledger": ledger[key],
                     "difference": c["difference"], "agrees": c["status"] == PASS, "message": c["message"]})
    return {
        "period_id": period_id, "period_label": label, "rounding": policy.statement_rounding,
        "tolerance": tolerance(policy.statement_rounding), "rows": rows,
        "all_agree": all(r["agrees"] for r in rows),
    }