from __future__ import annotations

from pathlib import Path

from .csv_parser import parse_csv
from .excel_parser import parse_excel
from .models import ParseResult

SUPPORTED_EXCEL = (".xlsx", ".xlsm")
SUPPORTED_CSV = (".csv",)


def parse_file(path: str | Path, sheet_name: str | None = None) -> ParseResult:
    path = Path(path)
    suffix = path.suffix.lower()

    if suffix in SUPPORTED_EXCEL:
        return parse_excel(path, sheet_name=sheet_name)
    if suffix in SUPPORTED_CSV:
        return parse_csv(path)

    raise ValueError(f"unsupported file type: {suffix!r} (expected one of {SUPPORTED_EXCEL + SUPPORTED_CSV})")
