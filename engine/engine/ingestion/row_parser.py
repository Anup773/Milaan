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

from ..calendars.dates import ParsedDate, adjust_native, parse_date_detailed
from .models import ParsedSourceRow, ParseIssue, ParseResult, Severity
from .money_parse import parse_amount

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


def _read_date(value: Any) -> ParsedDate:
    """A date cell under the company's date rules (calendar and date order): see engine.calendars.dates."""
    if value is None or value == "":
        return ParsedDate(None)
    if isinstance(value, (datetime, date)):  # an Excel date cell (datetime is a date subclass)
        return adjust_native(value)
    return parse_date_detailed(str(value))


def build_row(result: ParseResult, row_number: int, get_cell: GetCell, columns: dict[str, int]) -> None:
    parsed_date = _read_date(get_cell("date"))
    txn_date = parsed_date.value
    if txn_date is None:
        reason = f" ({parsed_date.problem})" if parsed_date.problem else ""
        result.issues.append(ParseIssue(row_number, "date", f"unparseable or missing date: {get_cell('date')!r}{reason}", Severity.ERROR))
    for warning in parsed_date.warnings:
        result.issues.append(ParseIssue(row_number, "date", warning, Severity.WARNING))

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