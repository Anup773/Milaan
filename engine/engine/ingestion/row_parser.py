"""
Row-level parsing shared by the Excel and CSV readers. Both readers reduce
their native row representation down to a `get_cell(field) -> Any` callable
before calling into `build_row`, so the actual field parsing / validation
logic lives in exactly one place.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Callable

from .models import ParsedSourceRow, ParseIssue, ParseResult, Severity
from .money_parse import parse_amount, parse_date

GetCell = Callable[[str], Any]


def _as_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _as_amount(value: Any) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    if isinstance(value, (int, float, Decimal)):
        # Cell already numeric (typical for .xlsx) -- go via str() so we
        # never build a Decimal straight from a float's binary representation.
        return Decimal(str(value))
    return parse_amount(str(value))


def _as_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):  # check before `date` -- datetime is a date subclass
        return value.date()
    if isinstance(value, date):
        return value
    return parse_date(str(value))


def build_row(result: ParseResult, row_number: int, get_cell: GetCell, columns: dict[str, int]) -> None:
    txn_date = _as_date(get_cell("date"))
    if txn_date is None:
        result.issues.append(ParseIssue(row_number, "date", f"unparseable or missing date: {get_cell('date')!r}", Severity.ERROR))

    account_ref = _as_text(get_cell("account"))
    if not account_ref:
        result.issues.append(ParseIssue(row_number, "account", "missing account name", Severity.ERROR))

    debit = _parse_amount_field(result, row_number, "debit", get_cell("debit"))
    credit = _parse_amount_field(result, row_number, "credit", get_cell("credit"))

    if debit == 0 and credit == 0:
        result.issues.append(ParseIssue(row_number, "debit/credit", "both debit and credit are zero/blank", Severity.WARNING))
    if debit != 0 and credit != 0:
        result.issues.append(ParseIssue(row_number, "debit/credit", "both debit and credit are non-zero on one line", Severity.WARNING))

    result.rows.append(ParsedSourceRow(
        row_number=row_number,
        account_ref=account_ref,
        transaction_date=txn_date,
        description=_as_text(get_cell("description")),
        debit=debit,
        credit=credit,
        reference=_as_text(get_cell("reference")),
        raw={field: get_cell(field) for field in columns},
    ))


def _parse_amount_field(result: ParseResult, row_number: int, field: str, raw: Any) -> Decimal:
    try:
        return _as_amount(raw)
    except ValueError as exc:
        result.issues.append(ParseIssue(row_number, field, str(exc), Severity.ERROR))
        return Decimal("0")
