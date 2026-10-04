"""
Normal-balance math -- ARCHITECTURE.md §3, implemented exactly as specified
there, nothing more. No database calls; pure functions over numbers already
in hand, so trial_balance/profit_and_loss/balance_sheet (reports.py) can
all share one place that knows which direction is "normal" for a type.
"""
from __future__ import annotations

from decimal import Decimal
from enum import Enum

ZERO = Decimal("0")

DEBIT_NORMAL_TYPES = {"Asset", "Expense"}
CREDIT_NORMAL_TYPES = {"Liability", "Equity", "Income"}


class NormalBalance(str, Enum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


def normal_balance(account_type: str) -> NormalBalance:
    """
    normal_balance(a) = Debit   if type(a) in {Asset, Expense}
    normal_balance(a) = Credit  if type(a) in {Liability, Equity, Income}
    """
    if account_type in DEBIT_NORMAL_TYPES:
        return NormalBalance.DEBIT
    if account_type in CREDIT_NORMAL_TYPES:
        return NormalBalance.CREDIT
    raise ValueError(f"unknown account_type: {account_type!r}")


def signed_balance(account_type: str, total_debit: Decimal, total_credit: Decimal) -> Decimal:
    """
    balance(a) = total_debit - total_credit   if normal_balance(a) = Debit
    balance(a) = total_credit - total_debit   if normal_balance(a) = Credit

    Positive means "more of what this account normally holds" -- an Asset
    with debit=1000, credit=200 has signed_balance=800 (a normal debit
    balance, as expected for cash you actually have); a Liability with
    debit=50, credit=1000 has signed_balance=950 (a normal credit balance,
    as expected for money you actually owe). This is the number every
    statement in reports.py reports per account -- never raw debit/credit
    totals on their own.
    """
    if normal_balance(account_type) is NormalBalance.DEBIT:
        return total_debit - total_credit
    return total_credit - total_debit