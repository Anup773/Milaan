"""
Whole-unit statements and the tolerance for comparing them -- pure logic, no database.

Real statements are often printed in whole rupees or dollars while the ledger keeps paisa or cents. Each line is
rounded on its own, so the printed lines can add up to a total that is a unit or two away from the printed total
(Upper Syange's balance sheet total is 625,737,702 while its own lines add to 625,737,703). That is rounding, not an error, so:

  * `agree()` says whether two figures agree allowing for the company's rounding: exact for a company that keeps
    exact amounts, within 1 unit for a company whose statements are in whole units.
  * `present_section()` rounds the lines of a section, rounds its exact total, and reports the footing difference
    (total minus the sum of the rounded lines) instead of hiding it.

Nothing is ever rounded in the ledger itself; this is only how a statement is shown and compared.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Iterable, List, Mapping, Sequence

ZERO = Decimal("0")
ONE = Decimal("1")
EXACT, WHOLE = "EXACT", "WHOLE"


def tolerance(rounding: str) -> Decimal:
    """How far apart two figures may be and still agree: nothing for exact amounts, 1 unit for whole-unit statements."""
    if rounding == EXACT:
        return ZERO
    if rounding == WHOLE:
        return ONE
    raise ValueError(f"rounding must be {EXACT} or {WHOLE}")


def agree(a: Decimal, b: Decimal, rounding: str = EXACT) -> bool:
    return abs(Decimal(a) - Decimal(b)) <= tolerance(rounding)


def round_unit(amount: Decimal) -> Decimal:
    """To the nearest whole unit, halves away from zero (what a person doing it by hand does)."""
    return Decimal(amount).quantize(ONE, rounding=ROUND_HALF_UP)


def present_section(amounts: Sequence[Decimal], exact_total: Decimal) -> Dict[str, Any]:
    """
    The lines of a section rounded to whole units, the exact total rounded the same way, and the footing difference:
    rounded total minus the sum of the rounded lines. `lines` keeps the input order.
    """
    lines = [round_unit(a) for a in amounts]
    total = round_unit(exact_total)
    return {"lines": lines, "total": total, "footing_difference": total - sum(lines, ZERO)}


def present_rows(rows: Sequence[Mapping[str, Any]], amount_key: str, total: Decimal) -> Dict[str, Any]:
    """present_section for a list of statement rows: the rows come back with `presented` added to each."""
    section = present_section([r[amount_key] for r in rows], total)
    return {
        "lines": [{**r, "presented": p} for r, p in zip(rows, section["lines"])],
        "total": section["total"], "footing_difference": section["footing_difference"],
    }


def present_balance_sheet(bs: Mapping[str, Any]) -> Dict[str, Any]:
    """A balance sheet (reports.balance_sheet) in whole units, with the footing differences shown."""
    assets = present_rows(bs["assets"], "balance", bs["total_assets"])
    liabilities = present_rows(bs["liabilities"], "balance", bs["total_liabilities"])
    total_equity = bs["total_equity_and_retained_earnings"] - bs["retained_earnings"]
    equity = present_rows(bs["equity"], "balance", total_equity)
    retained = round_unit(bs["retained_earnings"])
    equity_side_lines = sum((l["presented"] for l in equity["lines"]), ZERO)
    right_side_total = round_unit(bs["total_liabilities"] + bs["total_equity_and_retained_earnings"])
    right_side_lines = (sum((l["presented"] for l in liabilities["lines"]), ZERO) + equity_side_lines + retained)
    return {
        "unit": "1", "assets": assets, "liabilities": liabilities, "equity": equity, "retained_earnings": retained,
        "total_assets": assets["total"],
        "total_liabilities_and_equity": right_side_total,
        "footing_difference_liabilities_and_equity": right_side_total - right_side_lines,
        "assets_minus_liabilities_and_equity": assets["total"] - right_side_total,
    }


def present_profit_and_loss(pl: Mapping[str, Any]) -> Dict[str, Any]:
    income = present_rows(pl["income"], "balance", pl["total_income"])
    expense = present_rows(pl["expense"], "balance", pl["total_expense"])
    net = round_unit(pl["net_profit"])
    return {"unit": "1", "income": income, "expense": expense, "net_profit": net,
            "footing_difference": net - (income["total"] - expense["total"])}


def present_equity(eq: Mapping[str, Any]) -> Dict[str, Any]:
    """Each component's closing balance in whole units, with one rounding line so the closing total foots."""
    closing = present_rows(eq["components"], "closing", eq["totals"]["closing"])
    return {"unit": "1", "components": closing["lines"], "closing_total": closing["total"],
            "rounding": closing["footing_difference"]}