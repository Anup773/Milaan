from decimal import Decimal
from pathlib import Path

import pytest

from engine.ingestion import parse_file
from engine.ingestion.money_parse import parse_amount, parse_date

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_amount_handles_indian_grouping_and_parentheses():
    assert parse_amount("1,20,000.00") == Decimal("120000.00")
    assert parse_amount("(5,000.00)") == Decimal("-5000.00")
    assert parse_amount("") == Decimal("0")
    assert parse_amount(None) == Decimal("0")


def test_parse_amount_rejects_garbage():
    with pytest.raises(ValueError):
        parse_amount("not a number")


def test_parse_date_accepts_common_formats():
    assert parse_date("31-03-2026").isoformat() == "2026-03-31"
    assert parse_date("2026-03-31").isoformat() == "2026-03-31"
    assert parse_date("31/03/2026").isoformat() == "2026-03-31"


def test_parse_csv_journal_fixture():
    result = parse_file(FIXTURES / "sample_journal.csv")

    assert result.source_format == "csv"
    assert not result.has_errors
    assert len(result.rows) == 4
    assert result.total_debit == result.total_credit  # fixture is a balanced journal
    assert result.total_debit == Decimal("165000.00")


def test_parse_csv_flags_missing_account_name():
    result = parse_file(FIXTURES / "broken_journal.csv")

    assert result.has_errors
    messages = [i.message for i in result.issues]
    assert any("missing account name" in m for m in messages)


def test_parse_excel_journal_fixture():
    result = parse_file(FIXTURES / "sample_journal.xlsx")

    assert result.source_format == "xlsx"
    assert not result.has_errors
    assert len(result.rows) == 4
    assert result.total_debit == result.total_credit
    assert result.total_debit == Decimal("165000")
