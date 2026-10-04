"""Pure-logic tests for engine.ledger.money -- ARCHITECTURE.md §3's formulas."""
from decimal import Decimal

import pytest

from engine.ledger.money import NormalBalance, normal_balance, signed_balance


def test_asset_and_expense_are_debit_normal():
    assert normal_balance("Asset") is NormalBalance.DEBIT
    assert normal_balance("Expense") is NormalBalance.DEBIT


def test_liability_equity_income_are_credit_normal():
    assert normal_balance("Liability") is NormalBalance.CREDIT
    assert normal_balance("Equity") is NormalBalance.CREDIT
    assert normal_balance("Income") is NormalBalance.CREDIT


def test_unknown_type_raises():
    with pytest.raises(ValueError):
        normal_balance("NotARealType")


def test_asset_signed_balance_is_debit_minus_credit():
    assert signed_balance("Asset", Decimal("1000"), Decimal("200")) == Decimal("800")


def test_liability_signed_balance_is_credit_minus_debit():
    assert signed_balance("Liability", Decimal("50"), Decimal("1000")) == Decimal("950")


def test_income_signed_balance_is_credit_minus_debit():
    assert signed_balance("Income", Decimal("0"), Decimal("5000")) == Decimal("5000")


def test_expense_signed_balance_is_debit_minus_credit():
    assert signed_balance("Expense", Decimal("1200"), Decimal("0")) == Decimal("1200")


def test_signed_balance_can_go_negative_when_unusual():
    assert signed_balance("Asset", Decimal("100"), Decimal("300")) == Decimal("-200")

