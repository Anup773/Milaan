"""
Normalized intermediate representation produced by the ingestion parsers.

Nothing in this package writes to Postgres. Ingestion's job stops at:
raw file -> validated, normalized rows in memory. Persistence is a
separate, thin layer (see persist_stub.py) so the parsing logic can be
unit-tested without a database, and can be adjusted independently of
however `source_rows` actually looks in your real migration 0001.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Optional


class Severity(str, Enum):
    ERROR = "ERROR"
    WARNING = "WARNING"


@dataclass(frozen=True)
class ParseIssue:
    row_number: int  # 1-based, matches what a human sees in Excel/CSV
    field: str        # e.g. "debit", "date", "account"
    message: str
    severity: Severity


@dataclass(frozen=True)
class ParsedSourceRow:
    row_number: int
    account_ref: str  # raw account name/code as it appears in the source file --
                       # NOT yet resolved to accounts.id, that's Phase 5 (mapping)
    transaction_date: Optional[date]
    description: str
    debit: Decimal
    credit: Decimal
    reference: str = ""  # voucher/invoice number, if present
    raw: dict = field(default_factory=dict)  # original cell values, kept for audit/debug


@dataclass
class ParseResult:
    source_format: str  # "csv" | "xlsx"
    sheet_name: Optional[str]
    detected_columns: dict
    rows: list[ParsedSourceRow] = field(default_factory=list)
    issues: list[ParseIssue] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return any(i.severity == Severity.ERROR for i in self.issues)

    @property
    def total_debit(self) -> Decimal:
        return sum((r.debit for r in self.rows), Decimal("0"))

    @property
    def total_credit(self) -> Decimal:
        return sum((r.credit for r in self.rows), Decimal("0"))
