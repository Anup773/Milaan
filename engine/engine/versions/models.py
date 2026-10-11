"""
Plain objects for Phase 13 (version comparison). No database, no side effects.

A "version" here is one imported file: the set of source_rows ingestion saved
for it. Source rows are never edited after import, so comparing two files is a
pure function of their rows -- the same two files always give the same diff.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

from .normalize import account_key, description_key, reference_key


@dataclass(frozen=True)
class RowVersion:
    id: str
    row_number: int
    account_ref: str
    transaction_date: Optional[date]
    description: str
    debit: Decimal
    credit: Decimal
    reference: str
    status: str  # OK | WARNING | ERROR (as saved by ingestion)

    @property
    def account_key(self) -> str:
        return account_key(self.account_ref)

    @property
    def ref_key(self) -> str:
        """'' when the row has no usable voucher/invoice reference."""
        return reference_key(self.reference)

    @property
    def desc_key(self) -> str:
        return description_key(self.description)

    @property
    def amount(self) -> Decimal:
        return self.debit + self.credit

    @property
    def side(self) -> str:
        return "D" if self.debit > 0 else "C" if self.credit > 0 else "Z"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "row_number": self.row_number, "account_ref": self.account_ref,
            "transaction_date": self.transaction_date, "description": self.description,
            "debit": self.debit, "credit": self.credit, "reference": self.reference or None, "status": self.status,
        }


ADDED, REMOVED, CHANGED, UNCHANGED = "ADDED", "REMOVED", "CHANGED", "UNCHANGED"
KINDS: Tuple[str, ...] = (CHANGED, ADDED, REMOVED, UNCHANGED)


@dataclass(frozen=True)
class FieldChange:
    field: str  # account | date | reference | description | debit | credit
    old: Any
    new: Any

    def to_dict(self) -> Dict[str, Any]:
        return {"field": self.field, "old": self.old, "new": self.new}


@dataclass(frozen=True)
class RowChange:
    kind: str
    old: Optional[RowVersion]
    new: Optional[RowVersion]
    matched_by: Optional[str] = None            # how an old row was paired with a new one; None for ADDED/REMOVED
    fields: Tuple[FieldChange, ...] = ()
