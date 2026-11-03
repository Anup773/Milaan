"""
Reconciliation rules for the checks BETWEEN statements (Phase 24). Importing this module registers them. The checks
themselves live in engine/ledger/checks.py (also used by the statement comparison screen); each rule here only runs one of
them for the period being reconciled, so a difference shows up on the Reconciliation screen like any other.
"""
from __future__ import annotations

from ..ledger.checks import ERROR as _ERROR, NOT_CHECKED as _NOT_CHECKED, statement_ties
from .registry import ERROR, NOT_CHECKED, PASS, ReconContext, RuleResult, register_rule, result

_STATUS = {"PASS": PASS, "ERROR": ERROR, "NOT_CHECKED": NOT_CHECKED}
_CHECKS = {
    "entries_dated_in_period": ("statement_entries_dated_in_period", "Entries are dated inside the period they are filed in",
                                "Every entry filed in the period is dated inside it, and no entry dated inside it is filed elsewhere. "
                                "Otherwise the profit and loss (by period) and the balance sheet (by date) cannot agree."),
    "equity_ties_to_balance_sheet": ("statement_equity_ties", "Statement of changes in equity agrees with the balance sheet",
                                     "The closing total of the statement of changes in equity equals the balance sheet's equity plus accumulated profit."),
    "profit_ties_to_equity": ("statement_profit_ties", "Profit in the equity statement agrees with the profit and loss",
                              "The profit that the statement of changes in equity carries into equity equals the profit and loss statement's net profit."),
    "cash_ties_to_balance_sheet": ("statement_cash_ties", "Cash flow agrees with the cash on the balance sheet",
                                   "Opening cash plus the period's net cash movement equals the cash and bank on the balance sheet at the end. "
                                   "A company whose statements are in whole units may differ by up to 1 unit."),
}


def _make(check_id: str, rule_id: str):
    def run(ctx: ReconContext) -> RuleResult:
        found = [c for c in statement_ties(ctx.conn, ctx.company_id, ctx.period_id) if c["id"] == check_id]
        c = found[0]
        details = {k: v for k, v in c.items() if k not in ("id", "title", "status", "message")}
        return result(rule_id, _STATUS[c["status"]], c["message"], **details)
    return run


for _check_id, (_rule_id, _title, _description) in _CHECKS.items():
    register_rule(_rule_id, _title, _description)(_make(_check_id, _rule_id))