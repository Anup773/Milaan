from __future__ import annotations

import csv
from pathlib import Path

from .detect import detect_layout, find_header_row
from .models import ParseIssue, ParseResult, Severity
from .row_parser import build_row


def _sniff_dialect(sample: str) -> type[csv.Dialect]:
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        return csv.excel  # comma-delimited fallback


def parse_csv(path: Path, encoding: str = "utf-8-sig") -> ParseResult:
    with open(path, newline="", encoding=encoding) as f:
        sample = f.read(4096)
        f.seek(0)
        reader = csv.reader(f, _sniff_dialect(sample))
        rows = [row for row in reader]

    result = ParseResult(source_format="csv", sheet_name=None, detected_columns={})

    header_idx = find_header_row(rows)
    if header_idx is None:
        result.issues.append(ParseIssue(
            row_number=0, field="header",
            message=("Could not find a header row with recognizable date/account/debit/credit "
                      "columns in the first 10 rows. Add column aliases in detect.py for this export format."),
            severity=Severity.ERROR,
        ))
        return result

    layout = detect_layout(rows[header_idx])
    result.detected_columns = {f: rows[header_idx][i] for f, i in layout.columns.items()}

    for offset, row in enumerate(rows[header_idx + 1:], start=1):
        row_number = header_idx + offset + 1
        if all(cell.strip() == "" for cell in row):
            continue

        def get_cell(field: str, _row=row, _cols=layout.columns):
            idx = _cols.get(field)
            return _row[idx] if idx is not None and idx < len(_row) else ""

        build_row(result, row_number, get_cell, layout.columns)

    return result
