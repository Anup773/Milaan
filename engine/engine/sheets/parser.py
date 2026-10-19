"""
Turns the cells of a sheet (a list of rows) into the same ParseResult an Excel/CSV import produces, using the same
header detection and row rules, so mapping, posting and every check after it work unchanged.

Cells come in two shapes: real values from the Sheets API (numbers, text) or plain text from a CSV export. Dates are
the one tricky part. The API sends a date cell as a day number (days since 30 Dec 1899); that is converted here to an
exact calendar date, which avoids any day/month ambiguity. Dates that are already text go through the normal date
parser, which reads day-first formats (31-03-2026, 31/03/2026) before month-first ones.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, List

from ..ingestion.detect import detect_layout, find_header_row
from ..ingestion.models import ParseResult
from ..ingestion.row_parser import build_row
from .source import SheetsError

_SERIAL_EPOCH = date(1899, 12, 30)
_MIN_SERIAL, _MAX_SERIAL = 1, 73415  # 1899-12-31 .. 2100-12-31


def serial_to_date(value: float) -> date | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value < _MIN_SERIAL or value > _MAX_SERIAL:
        return None
    return _SERIAL_EPOCH + timedelta(days=int(value))


def _header_text(value: Any) -> str:
    return "" if value is None else str(value)


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def parse_rows(values: List[List[Any]], tab_title: str | None) -> ParseResult:
    header_texts = [[_header_text(c) for c in row] for row in values]
    header_idx = find_header_row(header_texts)
    if header_idx is None:
        raise SheetsError(
            "could not find a header row with recognisable date, account, debit and credit columns in the first "
            "10 rows of this tab. Check you picked the right tab, or rename the headers (for example Date, Particulars, Debit, Credit)"
        )

    layout = detect_layout(header_texts[header_idx])
    result = ParseResult(source_format="gsheet", sheet_name=tab_title, detected_columns={})
    result.detected_columns = {f: header_texts[header_idx][i] for f, i in layout.columns.items()}

    for offset, row in enumerate(values[header_idx + 1 :], start=1):
        row_number = header_idx + offset + 1  # the row number a person sees in the sheet
        if all(_is_blank(c) for c in row):
            continue

        def get_cell(field: str, _row=row, _cols=layout.columns):
            idx = _cols.get(field)
            value = _row[idx] if idx is not None and idx < len(_row) else None
            if field == "date" and isinstance(value, (int, float)) and not isinstance(value, bool):
                converted = serial_to_date(value)
                return converted if converted is not None else value
            return value

        build_row(result, row_number, get_cell, layout.columns)

    if not result.rows:
        raise SheetsError("the header was found but there are no data rows under it")
    return result