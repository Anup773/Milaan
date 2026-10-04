
"""Pure-logic tests for engine.adjustments.planner -- no database."""
from decimal import Decimal

from engine.adjustments.planner import ProposedLine, validate_lines


def line(account_id, debit="0", credit="0"):
    return ProposedLine(account_id=account_id, debit=Decimal(debit), credit=Decimal(credit))


def test_balanced_two_line_adjustment_is_valid():
    is_valid, reasons = validate_lines([line("acc-a", debit="500"), line("acc-b", credit="500")])
    assert is_valid
    assert reasons == []


def test_balanced_multi_line_adjustment_is_valid():
    lines = [line("acc-a", debit="300"), line("acc-b", debit="200"), line("acc-c", credit="500")]
    is_valid, _ = validate_lines(lines)
    assert is_valid


def test_unbalanced_adjustment_is_invalid():
    is_valid, reasons = validate_lines([line("acc-a", debit="500"), line("acc-b", credit="400")])
    assert not is_valid
    assert any("does not balance" in r for r in reasons)


def test_single_line_is_invalid():
    is_valid, reasons = validate_lines([line("acc-a", debit="500")])
    assert not is_valid
    assert any("at least two lines" in r for r in reasons)


def test_negative_amount_is_invalid():
    is_valid, reasons = validate_lines([line("acc-a", debit="-500"), line("acc-b", credit="500")])
    assert not is_valid
    assert any("negative" in r for r in reasons)


def test_both_sides_on_one_line_is_invalid():
    lines = [line("acc-a", debit="500", credit="100"), line("acc-b", credit="400")]
    is_valid, reasons = validate_lines(lines)
    assert not is_valid
    assert any("both a debit and a credit" in r for r in reasons)


def test_zero_amount_line_is_invalid():
    is_valid, reasons = validate_lines([line("acc-a"), line("acc-b")])
    assert not is_valid
    assert any("no amount" in r for r in reasons)
