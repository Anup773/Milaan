"""
The ledger as the detectors see it: one read of the company's journal, turned
into plain objects (no database after this point), so every detection rule is
a pure function over a list of entries and can be unit-tested without Postgres.

Scope. "In scope" entries are the ones belonging to the period being reviewed
(journal_entries.accounting_period_id). History -- every entry dated on or
before the period's end -- is loaded too, because duplicates and "unusual for
this account" only make sense against what came before.

Origin of an entry, decided in the same order trace.py uses:
  adjustment    -- created by an approved Phase 7 adjustment
  depreciation  -- posted by the fixed-asset schedule
  source_row    -- built from an uploaded file (it has a source row behind it)
  manual        -- none of the above: no trace of where it came from

References. A voucher/invoice number is compared after dropping case, spaces
and punctuation ("INV-001", "inv 001" and "INV001" are the same reference).
Placeholders such as "NA" or "Opening" and references shorter than 3
characters are never used to match entries to each other -- too many
unrelated entries would share them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

ZERO = Decimal("0.00")

MIN_REFERENCE_LENGTH = 3
PLACEHOLDER_REFERENCES = frozenset({
    "na", "nil", "none", "null", "nan", "tbd", "ob", "opening", "openingbalance",
    "cash", "ref", "refno", "noref", "noreference", "bill", "invoice", "voucher",
})

ORIGINS = ("adjustment", "depreciation", "source_row", "manual")


# ── references ────────────────────────────────────────────────────────────
def normalize_reference(text: Optional[str]) -> str:
    """Letters and digits only, lower-cased: 'INV-001 ' -> 'inv001'."""
    return "".join(ch for ch in str(text or "").casefold() if ch.isalnum())


def has_reference(text: Optional[str]) -> bool:
    """True when there is a real voucher/invoice reference (not blank, not a placeholder)."""
    norm = normalize_reference(text)
    return norm != "" and norm not in PLACEHOLDER_REFERENCES


def reference_key(text: Optional[str]) -> Optional[str]:
    """The normalized reference to match entries on, or None if it is too weak to match on."""
    norm = normalize_reference(text)
    if has_reference(text) and len(norm) >= MIN_REFERENCE_LENGTH:
        return norm
    return None


# ── plain objects ─────────────────────────────────────────────────────────
@dataclass(frozen=True)
class LineRow:
    account_id: str
    code: str
    name: str
    account_type: str  # Asset | Liability | Equity | Income | Expense
    debit: Decimal
    credit: Decimal

    @property
    def amount(self) -> Decimal:
        return self.debit if self.debit > 0 else self.credit

    @property
    def side(self) -> str:
        return "D" if self.debit > 0 else "C"


@dataclass(frozen=True)
class EntryRow:
    id: str
    entry_date: date
    description: str
    period_id: str
    origin: str
    reference: str = ""
    source_file: Optional[str] = None
    source_row: Optional[int] = None
    lines: Tuple[LineRow, ...] = ()

    @property
    def ref_key(self) -> Optional[str]:
        return reference_key(self.reference)

    @property
    def has_reference(self) -> bool:
        return has_reference(self.reference)

    @property
    def total(self) -> Decimal:
        return sum((l.debit for l in self.lines), ZERO)

    @property
    def expense_debit(self) -> Decimal:
        return sum((l.debit for l in self.lines if l.account_type == "Expense"), ZERO)


@dataclass
class EntryDataset:
    period_id: str
    period_start: date
    period_end: date
    period_label: str
    entries: List[EntryRow] = field(default_factory=list)

    @property
    def in_scope(self) -> List[EntryRow]:
        return [e for e in self.entries if e.period_id == self.period_id]


# ── small pure helpers shared by the rules ────────────────────────────────
def entry_signature(entry: EntryRow) -> Tuple[Tuple[str, str, str], ...]:
    """Which accounts, on which side, for how much -- the 'shape' of an entry, order-independent."""
    return tuple(sorted((l.account_id, l.side, f"{l.amount:.2f}") for l in entry.lines if l.debit > 0 or l.credit > 0))


def entry_summary(entry: EntryRow) -> Dict[str, Any]:
    """What the reviewer needs to find the entry again: who, when, how much, and which uploaded row it came from."""
    return {
        "journal_entry_id": entry.id, "entry_date": entry.entry_date.isoformat(), "description": entry.description,
        "amount": entry.total, "reference": entry.reference or None, "origin": entry.origin,
        "source_file": entry.source_file, "source_row": entry.source_row,
    }


def cluster_by_date(entries: List[EntryRow], window_days: int) -> List[List[EntryRow]]:
    """Groups entries (sorted by date, then id) so that neighbours are at most `window_days` apart."""
    ordered = sorted(entries, key=lambda e: (e.entry_date, e.id))
    clusters: List[List[EntryRow]] = []
    for entry in ordered:
        if clusters and (entry.entry_date - clusters[-1][-1].entry_date).days <= window_days:
            clusters[-1].append(entry)
        else:
            clusters.append([entry])
    return clusters


# ── the one database read ─────────────────────────────────────────────────
def load_dataset(conn, company_id: str, period_id: str) -> EntryDataset:
    from ..ledger.reports import _period_dates  # raises ValueError if the period isn't this company's

    start, end, label = _period_dates(conn, company_id, period_id)
    scope = {"c": company_id, "p": period_id, "end": end}

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT je.id, je.entry_date, je.description, je.accounting_period_id,
                   sr.reference, sf.filename, sr.row_number,
                   je.source_row_id IS NOT NULL, adj.id IS NOT NULL, fade.id IS NOT NULL
            FROM journal_entries je
            LEFT JOIN source_rows sr ON sr.id = je.source_row_id
            LEFT JOIN source_files sf ON sf.id = sr.source_file_id
            LEFT JOIN adjustments adj ON adj.journal_entry_id = je.id
            LEFT JOIN fixed_asset_depreciation_entries fade ON fade.journal_entry_id = je.id
            WHERE je.company_id = %(c)s AND (je.accounting_period_id = %(p)s OR je.entry_date <= %(end)s)
            ORDER BY je.entry_date, je.id
            """,
            scope,
        )
        head_rows = cur.fetchall()

        cur.execute(
            """
            SELECT jl.journal_entry_id, jl.account_id, a.code, a.name, a.account_type, jl.debit, jl.credit
            FROM journal_lines jl
            JOIN journal_entries je ON je.id = jl.journal_entry_id
            JOIN accounts a ON a.id = jl.account_id
            WHERE je.company_id = %(c)s AND (je.accounting_period_id = %(p)s OR je.entry_date <= %(end)s)
            ORDER BY jl.journal_entry_id, a.code, jl.id
            """,
            scope,
        )
        line_rows = cur.fetchall()

    lines_by_entry: Dict[str, List[LineRow]] = {}
    for entry_id, account_id, code, name, account_type, debit, credit in line_rows:
        lines_by_entry.setdefault(str(entry_id), []).append(
            LineRow(str(account_id), code, name, account_type, debit, credit))

    entries: Dict[str, EntryRow] = {}
    for (eid, entry_date, description, pid, reference, filename, row_number,
         from_source, is_adjustment, is_depreciation) in head_rows:
        key = str(eid)
        if key in entries:  # a join fan-out must never double-count an entry
            continue
        origin = ("adjustment" if is_adjustment else "depreciation" if is_depreciation
                  else "source_row" if from_source else "manual")
        entries[key] = EntryRow(
            id=key, entry_date=entry_date, description=description or "", period_id=str(pid), origin=origin,
            reference=reference or "", source_file=filename, source_row=row_number,
            lines=tuple(lines_by_entry.get(key, ())),
        )

    return EntryDataset(period_id=str(period_id), period_start=start, period_end=end, period_label=label,
                        entries=list(entries.values()))
