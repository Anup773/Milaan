"""
Phase 5 planner -- pure logic, no database.

Given the rows of one uploaded file, the confirmed account mappings and the
company's accounting periods, decide for every voucher (a group of rows with
the same date + reference) whether it can become a balanced journal entry, or
must be blocked -- and say exactly why. Nothing is ever fixed silently.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

ZERO = Decimal("0")


def normalize_ref(text: str) -> str:
    """
    The key used to match an account name/code from a file to a confirmed mapping:
    surrounding spaces trimmed, runs of spaces collapsed, upper/lower case ignored.
    """
    return " ".join(str(text).split()).casefold()


@dataclass(frozen=True)
class SourceRow:
    id: str
    row_number: int
    account_ref: str
    transaction_date: Optional[date]
    description: str
    debit: Decimal
    credit: Decimal
    reference: str
    status: str                       # OK | WARNING | ERROR (as saved by ingestion)
    issues: Tuple[str, ...] = ()      # messages saved by ingestion in raw_json["_issues"]


@dataclass(frozen=True)
class Period:
    id: str
    label: str
    start: date
    end: date
    locked: bool


@dataclass(frozen=True)
class PlannedLine:
    source_row_id: str
    account_id: str
    debit: Decimal
    credit: Decimal


@dataclass(frozen=True)
class PlannedEntry:
    key: str
    row_numbers: Tuple[int, ...]
    anchor_row_id: str                # first source row of the voucher; makes posting repeatable
    period_id: str
    entry_date: date
    description: str
    lines: Tuple[PlannedLine, ...]
    warnings: Tuple[str, ...] = ()

    @property
    def total(self) -> Decimal:
        return sum((line.debit for line in self.lines), ZERO)


@dataclass(frozen=True)
class BlockedGroup:
    key: str
    row_numbers: Tuple[int, ...]
    reasons: Tuple[str, ...]


@dataclass(frozen=True)
class SkippedGroup:
    key: str
    row_numbers: Tuple[int, ...]
    reason: str


@dataclass
class Plan:
    entries: List[PlannedEntry] = field(default_factory=list)
    blocked: List[BlockedGroup] = field(default_factory=list)
    skipped: List[SkippedGroup] = field(default_factory=list)


def plan_entries(rows: List[SourceRow], mapping: Dict[str, str], periods: List[Period]) -> Plan:
    """
    mapping: normalized account_ref -> account id.
    Groups rows by (date, reference). Groups are reported in the order of their first row.
    """
    groups: Dict[Tuple[Optional[date], str], List[SourceRow]] = {}
    for row in sorted(rows, key=lambda r: r.row_number):
        groups.setdefault((row.transaction_date, row.reference.strip()), []).append(row)

    plan = Plan()
    for (txn_date, reference), members in groups.items():
        key = f"{txn_date.isoformat() if txn_date else '(no date)'} / {reference or '(no reference)'}"
        row_numbers = tuple(r.row_number for r in members)
        has_error_row = any(r.status == "ERROR" for r in members)

        # A voucher whose every amount is zero has nothing to post.
        if not has_error_row and all(r.debit == 0 and r.credit == 0 for r in members):
            plan.skipped.append(SkippedGroup(key, row_numbers, "all amounts are zero - nothing to post"))
            continue

        reasons: List[str] = []
        unmapped_seen = set()
        for r in members:
            if r.status == "ERROR":
                detail = "; ".join(r.issues) if r.issues else "see the uploaded file"
                reasons.append(f"row {r.row_number} could not be read properly ({detail}) - fix the file and upload it again")
                continue
            if r.debit < 0 or r.credit < 0:
                reasons.append(f"row {r.row_number} has a negative amount")
            if r.debit != 0 and r.credit != 0:
                reasons.append(f"row {r.row_number} has both a debit and a credit - put them on separate rows")
            ref_text = " ".join(r.account_ref.split())
            if not ref_text:
                reasons.append(f"row {r.row_number} has no account name")
            elif normalize_ref(ref_text) not in mapping and normalize_ref(ref_text) not in unmapped_seen:
                unmapped_seen.add(normalize_ref(ref_text))
                reasons.append(f"account not mapped yet: '{ref_text}'")

        if txn_date is None and not has_error_row:
            reasons.append("the date is missing")

        total_debit = sum((r.debit for r in members), ZERO)
        total_credit = sum((r.credit for r in members), ZERO)
        if not has_error_row and total_debit != total_credit:
            reasons.append(f"does not balance: debits {total_debit} vs credits {total_credit}")

        period: Optional[Period] = None
        if txn_date is not None:
            matches = [p for p in periods if p.start <= txn_date <= p.end]
            if not matches:
                reasons.append(f"no accounting period covers {txn_date.isoformat()} - create one first")
            elif len(matches) > 1:
                labels = ", ".join(p.label for p in matches)
                reasons.append(f"more than one accounting period covers {txn_date.isoformat()} ({labels}) - fix the periods")
            elif matches[0].locked:
                reasons.append(f"accounting period '{matches[0].label}' is locked")
            else:
                period = matches[0]

        if reasons or period is None or txn_date is None:
            plan.blocked.append(BlockedGroup(key, row_numbers, tuple(reasons)))
            continue

        lines: List[PlannedLine] = []
        warnings: List[str] = []
        for r in members:
            if r.debit == 0 and r.credit == 0:
                warnings.append(f"row {r.row_number} has zero amounts - no ledger line was created for it")
                continue
            lines.append(PlannedLine(r.id, mapping[normalize_ref(r.account_ref)], r.debit, r.credit))
        if not reference:
            warnings.append("these rows have no voucher/reference, so they were grouped by date only")

        narration = next((r.description.strip() for r in members if r.description.strip()), "")
        description = " | ".join(part for part in (reference, narration) if part)
        plan.entries.append(PlannedEntry(
            key=key,
            row_numbers=row_numbers,
            anchor_row_id=members[0].id,
            period_id=period.id,
            entry_date=txn_date,
            description=description,
            lines=tuple(lines),
            warnings=tuple(warnings),
        ))

    return plan