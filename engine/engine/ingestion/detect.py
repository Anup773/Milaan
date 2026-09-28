from __future__ import annotations

from dataclasses import dataclass

CANONICAL_FIELDS = ("date", "account", "description", "debit", "credit", "reference")
REQUIRED_FIELDS = ("date", "account", "debit", "credit")

# Extend this when a new export format uses column names we don't recognize yet.
ALIASES: dict[str, tuple[str, ...]] = {
    "date": ("date", "txn date", "transaction date", "voucher date"),
    "account": ("account", "account name", "particulars", "ledger", "ledger name", "account code"),
    "description": ("description", "narration", "details", "remarks"),
    "debit": ("debit", "debit amount", "dr", "dr amount"),
    "credit": ("credit", "credit amount", "cr", "cr amount"),
    "reference": ("reference", "ref", "voucher no", "voucher no.", "vch no", "vch no.", "invoice no", "invoice no."),
}


def _normalize(header) -> str:
    return " ".join(str(header).strip().lower().replace("_", " ").split())


@dataclass
class DetectedLayout:
    columns: dict[str, int]
    missing_required: list[str]

    @property
    def is_usable(self) -> bool:
        return not self.missing_required


def detect_layout(header_cells: list[str]) -> DetectedLayout:
    normalized = [_normalize(h) for h in header_cells]
    columns: dict[str, int] = {}

    for canonical, aliases in ALIASES.items():
        for idx, cell in enumerate(normalized):
            if cell in aliases:
                columns[canonical] = idx
                break

    missing = [f for f in REQUIRED_FIELDS if f not in columns]
    return DetectedLayout(columns=columns, missing_required=missing)


def find_header_row(rows: list[list[str]], max_scan: int = 10) -> int | None:
    """
    Tally/Excel exports often have a title or company-name row above the
    real header. Scan the first `max_scan` rows and return the index of the
    first one that resolves every required field.
    """
    for i, row in enumerate(rows[:max_scan]):
        if detect_layout(row).is_usable:
            return i
    return None
