"""
Turns a sales, purchase or payroll register into balanced source rows, one voucher per register row.

Every register row becomes one voucher of several lines, built from fixed rules (see templates.py), for example a
sales invoice:

    Dr Customer            invoice total
        Cr Sales               taxable value
        Cr Output CGST / SGST / IGST   each tax amount
        Cr/Dr Round off        only if the invoice total differs from taxable + taxes by up to 1.00

What is checked, and never skipped silently:
  * the invoice total against taxable value + taxes (a bigger gap is an ERROR and the voucher is not posted),
  * payroll: gross pay minus deductions must equal net pay (same rule),
  * GST sanity: CGST and SGST should match, IGST should not appear with CGST/SGST, GSTIN shape,
  * rows that cannot be read become ERROR rows and are not posted,
  * rows already imported from an earlier file are marked ERROR so they are not posted twice.

Nothing here touches the database.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from ..bank.statement import BankError, _blank, _norm, _text, clean_account_name, read_amount, read_date, read_rows
from ..ingestion.models import ParsedSourceRow, ParseIssue, ParseResult, Severity
from .templates import TEMPLATES, Template

ZERO = Decimal("0")
ROUND_OFF_LIMIT = Decimal("1.00")
HEADER_SCAN_ROWS = 40
# The database keeps one source row per (file, row number), so line number k of a voucher is numbered
# <register row> + k * this offset. Problems are always reported against the register's own row number.
LINE_ROW_OFFSET = 1_000_000
GSTIN = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
_TOTAL_LABEL = re.compile(r"^\s*(grand\s+total|sub\s*total|total|totals|\*+)", re.IGNORECASE)


class RegisterError(ValueError):
    """Bad input or an unreadable register. A ValueError so the API reports it as a 400 the person can fix."""


# ---- columns ---------------------------------------------------------------------------------------------------------

def detect_columns(header_cells: Sequence[Any], template: Template) -> Dict[str, int]:
    normalized = [_norm(h) for h in header_cells]
    columns: Dict[str, int] = {}
    taken: Set[int] = set()
    for field_name, names in template.fields.items():
        for alias in names:
            hit = next((i for i, cell in enumerate(normalized) if cell == alias and i not in taken), None)
            if hit is not None:
                columns[field_name] = hit
                taken.add(hit)  # one column serves one field only
                break
    return columns


def _usable(columns: Dict[str, int], template: Template, has_default_date: bool) -> bool:
    needed = [f for f in template.required if not (f == "date" and has_default_date)]
    return all(f in columns for f in needed)


def find_header_row(rows: Sequence[Sequence[Any]], template: Template, has_default_date: bool) -> Optional[int]:
    for index, row in enumerate(rows[:HEADER_SCAN_ROWS]):
        if _usable(detect_columns(row, template), template, has_default_date):
            return index
    return None


# ---- the parsed register ----------------------------------------------------------------------------------------------

@dataclass
class Record:
    row_number: int
    txn_date: Optional[date]
    description: str
    lines: List[Tuple[str, Decimal]]  # (account name, signed amount): positive = debit, negative = credit
    figures: Dict[str, Decimal] = field(default_factory=dict)  # what the summary adds up
    readable: bool = True
    key: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RegisterStats:
    records: int = 0
    unreadable_rows: int = 0
    skipped_rows: int = 0
    duplicates: int = 0
    round_off_rows: int = 0
    credit_notes: int = 0
    first_date: Optional[date] = None
    last_date: Optional[date] = None
    date_from_default: int = 0
    summary: List[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "records": self.records,
            "unreadable_rows": self.unreadable_rows,
            "skipped_rows": self.skipped_rows,
            "duplicates": self.duplicates,
            "round_off_rows": self.round_off_rows,
            "credit_notes": self.credit_notes,
            "first_date": self.first_date.isoformat() if self.first_date else None,
            "last_date": self.last_date.isoformat() if self.last_date else None,
            "date_from_default": self.date_from_default,
            "summary": self.summary,
        }


@dataclass
class RegisterParse:
    result: ParseResult
    stats: RegisterStats
    records: List[Record] = field(default_factory=list)
    template: str = ""


def resolve_accounts(template: Template, given: Optional[Dict[str, str]]) -> Dict[str, str]:
    """The account name for every role: what the person typed, else the default. Unknown roles are refused."""
    given = dict(given or {})
    known = {r.key for r in template.roles}
    unknown = sorted(set(given) - known)
    if unknown:
        raise RegisterError(f"unknown account role(s) for a {template.label}: {', '.join(unknown)}")
    out: Dict[str, str] = {}
    for role in template.roles:
        value = given.get(role.key)
        out[role.key] = clean_account_name(value if value not in (None, "") else role.default, f"the {role.label.lower()} account name")
    return out


# ---- building one voucher ---------------------------------------------------------------------------------------------

def _money(issues: List[ParseIssue], row_number: int, name: str, value: Any) -> Decimal:
    try:
        return read_amount(value)
    except ValueError as exc:
        issues.append(ParseIssue(row_number, name, str(exc), Severity.ERROR))
        return ZERO


def _date_of(cell, columns: Dict[str, int], default_date: Optional[date], issues: List[ParseIssue], row_number: int, stats: RegisterStats) -> Optional[date]:
    if "date" in columns:
        value = cell("date")
        found = read_date(value)
        if found is None:
            issues.append(ParseIssue(row_number, "date", f"unreadable or missing date: {value!r}", Severity.ERROR))
        return found
    if default_date is None:
        issues.append(ParseIssue(row_number, "date", "this register has no date column and no date was given", Severity.ERROR))
        return None
    stats.date_from_default += 1
    return default_date


def _invoice_record(template: Template, accounts: Dict[str, str], party_accounts: bool, cell, columns, default_date, row_number, stats) -> Optional[Record]:
    issues: List[ParseIssue] = []
    raw_amounts = {f: cell(f) for f in ("taxable", "cgst", "sgst", "igst", "total") if f in columns}
    if all(_blank(v) for v in raw_amounts.values()):
        return None  # not a data row (a heading line, a note...)

    party = _text(cell("party"))
    invoice = _text(cell("invoice")) if "invoice" in columns else ""
    gstin = _text(cell("gstin")).upper() if "gstin" in columns else ""
    txn_date = _date_of(cell, columns, default_date, issues, row_number, stats)
    if not party:
        issues.append(ParseIssue(row_number, "party", "missing customer/supplier name", Severity.ERROR))

    taxable = _money(issues, row_number, "taxable", cell("taxable"))
    cgst = _money(issues, row_number, "cgst", cell("cgst")) if "cgst" in columns else ZERO
    sgst = _money(issues, row_number, "sgst", cell("sgst")) if "sgst" in columns else ZERO
    igst = _money(issues, row_number, "igst", cell("igst")) if "igst" in columns else ZERO
    computed = taxable + cgst + sgst + igst
    has_total = "total" in columns and not _blank(cell("total"))
    total = _money(issues, row_number, "total", cell("total")) if has_total else computed
    diff = total - computed

    readable = not any(i.severity == Severity.ERROR for i in issues)
    if readable:
        if abs(diff) > ROUND_OFF_LIMIT:
            issues.append(ParseIssue(row_number, "total", f"the invoice total {total} is {abs(diff)} {'more' if diff > 0 else 'less'} than taxable value plus taxes ({computed}); check the row", Severity.ERROR))
            readable = False
        elif diff != 0:
            issues.append(ParseIssue(row_number, "total", f"the invoice total differs from taxable value plus taxes by {diff}; booked to the round off account", Severity.WARNING))
            stats.round_off_rows += 1
        if cgst != 0 and sgst != 0 and cgst != sgst:
            issues.append(ParseIssue(row_number, "sgst", f"CGST ({cgst}) and SGST ({sgst}) are different; they are normally equal", Severity.WARNING))
        if igst != 0 and (cgst != 0 or sgst != 0):
            issues.append(ParseIssue(row_number, "igst", "IGST appears together with CGST/SGST; an invoice normally has one or the other", Severity.WARNING))
        if gstin and not GSTIN.match(gstin):
            issues.append(ParseIssue(row_number, "gstin", f"the GSTIN {gstin!r} is not in the right format (15 characters)", Severity.WARNING))
        if total == 0 and computed == 0:
            issues.append(ParseIssue(row_number, "taxable", "every amount is zero, so nothing was posted for this row", Severity.WARNING))
            stats.skipped_rows += 1
            return Record(row_number, txn_date, "", [], readable=False, raw={"_skip": True, "_issues": issues})

    label = ("Inv " if template.key == "sales" else "Bill ") + invoice if invoice else ("Invoice" if template.key == "sales" else "Bill")
    description = f"{label} - {party}" if party else label
    d = 1 if template.key == "sales" else -1  # the customer is debited on a sale; the supplier is credited on a purchase
    party_account = party if (party_accounts and party) else accounts["party"]
    lines: List[Tuple[str, Decimal]] = [
        (party_account, d * total),
        (accounts["main"], -d * taxable),
        (accounts["cgst"], -d * cgst),
        (accounts["sgst"], -d * sgst),
        (accounts["igst"], -d * igst),
        (accounts["round_off"], -d * diff),
    ]
    record = Record(
        row_number, txn_date, description, lines, readable=readable,
        figures={"taxable": taxable, "cgst": cgst, "sgst": sgst, "igst": igst, "total": total},
        raw={"party": party, "invoice": invoice, "gstin": gstin, **{k: _text(v) for k, v in raw_amounts.items()}},
    )
    record.raw["_issues"] = issues
    if template.kind == "invoice" and taxable < 0:
        record.raw["_credit_note"] = True
    material = "|".join([template.key, txn_date.isoformat() if txn_date else "", _norm(invoice), _norm(party), str(taxable), str(cgst), str(sgst), str(igst), str(total)])
    record.key = material  # hashed (with an occurrence count) once the whole file is read
    return record


def _payroll_record(template: Template, accounts: Dict[str, str], cell, columns, default_date, row_number, stats) -> Optional[Record]:
    issues: List[ParseIssue] = []
    parts = ("gross", "pf", "esi", "tds", "ptax", "other", "total_deductions", "net")
    raw_amounts = {f: cell(f) for f in parts if f in columns}
    if all(_blank(v) for v in raw_amounts.values()):
        return None

    employee = _text(cell("employee"))
    txn_date = _date_of(cell, columns, default_date, issues, row_number, stats)
    if not employee:
        issues.append(ParseIssue(row_number, "employee", "missing employee name", Severity.ERROR))

    gross = _money(issues, row_number, "gross", cell("gross"))
    pf = _money(issues, row_number, "pf", cell("pf")) if "pf" in columns else ZERO
    esi = _money(issues, row_number, "esi", cell("esi")) if "esi" in columns else ZERO
    tds = _money(issues, row_number, "tds", cell("tds")) if "tds" in columns else ZERO
    ptax = _money(issues, row_number, "ptax", cell("ptax")) if "ptax" in columns else ZERO
    other = _money(issues, row_number, "other", cell("other")) if "other" in columns else ZERO
    has_total_ded = "total_deductions" in columns and not _blank(cell("total_deductions"))
    total_ded_file = _money(issues, row_number, "total_deductions", cell("total_deductions")) if has_total_ded else ZERO
    components = pf + esi + tds + ptax + other
    if has_total_ded and not any(f in columns for f in ("pf", "esi", "tds", "ptax", "other")):
        other = total_ded_file  # only a total was given: it is booked as other deductions
        components = other

    readable = not any(i.severity == Severity.ERROR for i in issues)
    has_net = "net" in columns and not _blank(cell("net"))
    net_file = _money(issues, row_number, "net", cell("net")) if has_net else ZERO
    readable = readable and not any(i.severity == Severity.ERROR for i in issues)
    net = net_file if has_net else gross - components
    diff = gross - components - net
    if readable:
        if min(gross, pf, esi, tds, ptax, other, net) < 0:
            issues.append(ParseIssue(row_number, "gross", "a negative amount in a payroll row", Severity.ERROR))
            readable = False
        elif abs(diff) > ROUND_OFF_LIMIT:
            issues.append(ParseIssue(row_number, "net", f"gross pay {gross} minus deductions {components} is {gross - components}, but the net pay is {net}; check the row", Severity.ERROR))
            readable = False
        elif diff != 0:
            issues.append(ParseIssue(row_number, "net", f"net pay differs from gross minus deductions by {diff}; booked to the round off account", Severity.WARNING))
            stats.round_off_rows += 1
        if readable and has_total_ded and components != total_ded_file and any(f in columns for f in ("pf", "esi", "tds", "ptax", "other")):
            issues.append(ParseIssue(row_number, "total_deductions", f"the deductions listed add up to {components}, but the total deductions column says {total_ded_file}", Severity.WARNING))
        if readable and gross == 0 and components == 0 and net == 0:
            issues.append(ParseIssue(row_number, "gross", "every amount is zero, so nothing was posted for this row", Severity.WARNING))
            stats.skipped_rows += 1
            return Record(row_number, txn_date, "", [], readable=False, raw={"_skip": True, "_issues": issues})

    lines: List[Tuple[str, Decimal]] = [
        (accounts["main"], gross),
        (accounts["pf"], -pf),
        (accounts["esi"], -esi),
        (accounts["tds"], -tds),
        (accounts["ptax"], -ptax),
        (accounts["other"], -other),
        (accounts["net"], -net),
        (accounts["round_off"], -diff),
    ]
    record = Record(
        row_number, txn_date, f"Salary - {employee}" if employee else "Salary", lines, readable=readable,
        figures={"gross": gross, "pf": pf, "esi": esi, "tds": tds, "ptax": ptax, "other": other, "net": net},
        raw={"employee": employee, **{k: _text(v) for k, v in raw_amounts.items()}},
    )
    record.raw["_issues"] = issues
    record.key = "|".join([template.key, txn_date.isoformat() if txn_date else "", _norm(employee), str(gross), str(net)])
    return record


# ---- the whole register -------------------------------------------------------------------------------------------------

def parse_table(
    rows: List[List[Any]],
    template_key: str,
    accounts: Optional[Dict[str, str]] = None,
    default_date: Optional[date] = None,
    party_accounts: bool = False,
    ref_tag: str = "RG",
    source_format: str = "register",
) -> RegisterParse:
    template = TEMPLATES.get(template_key)
    if template is None:
        raise RegisterError(f"unknown register type {template_key!r} (expected one of: {', '.join(TEMPLATES)})")
    names = resolve_accounts(template, accounts)
    if party_accounts and not template.party_accounts_option:
        raise RegisterError("separate accounts per customer/supplier do not apply to this register")

    header_idx = find_header_row(rows, template, default_date is not None)
    if header_idx is None:
        wanted = [f for f in template.required if not (f == "date" and default_date is not None)]
        shown = ", ".join(f"{f} ({' / '.join(template.fields[f][:3])})" for f in wanted)
        raise RegisterError(f"could not find the column headings of a {template.label.lower()} in the first {HEADER_SCAN_ROWS} rows. Needed: {shown}")
    columns = detect_columns(rows[header_idx], template)
    result = ParseResult(source_format=source_format, sheet_name=None, detected_columns={f: str(rows[header_idx][i]) for f, i in columns.items()})
    stats = RegisterStats()
    records: List[Record] = []

    for offset, row in enumerate(rows[header_idx + 1:], start=1):
        row_number = header_idx + offset + 1  # the row number a person sees in the file
        if all(_blank(c) for c in row):
            continue

        def cell(name: str, _row=row):
            idx = columns.get(name)
            return _row[idx] if idx is not None and idx < len(_row) else None

        first_text = next((_text(c) for c in row if not _blank(c)), "")
        if _TOTAL_LABEL.match(first_text) or _TOTAL_LABEL.match(_text(cell("party") if template.kind == "invoice" else cell("employee"))):
            stats.skipped_rows += 1  # a Total line
            continue
        if template.kind == "invoice":
            record = _invoice_record(template, names, party_accounts, cell, columns, default_date, row_number, stats)
        else:
            record = _payroll_record(template, names, cell, columns, default_date, row_number, stats)
        if record is None:
            stats.skipped_rows += 1
            continue
        for issue in record.raw.pop("_issues", []):
            result.issues.append(issue)
        if record.raw.pop("_skip", False):
            continue
        records.append(record)

    if not records:
        raise RegisterError("the headings were found but there are no rows under them")
    if records[-1].row_number >= LINE_ROW_OFFSET:
        raise RegisterError(f"this file has too many rows (the limit is {LINE_ROW_OFFSET:,}). Split it")

    seen: Dict[str, int] = {}
    for rec in records:
        if rec.readable:
            seen[rec.key] = seen.get(rec.key, 0) + 1
            rec.key = hashlib.sha256(f"{rec.key}|{seen[rec.key] - 1}".encode("utf-8")).hexdigest()
        else:
            rec.key = ""
    _summarise(template, stats, records)
    for rec in records:
        _add_lines(result, rec, names, ref_tag)
    return RegisterParse(result, stats, records, template_key)


def _add_lines(result: ParseResult, rec: Record, names: Dict[str, str], ref_tag: str) -> None:
    """
    The voucher's lines. Any problem is saved on the first line (the register's own row number); that is enough to
    keep the whole voucher from being posted, because a voucher with an error row is blocked.
    """
    reference = f"{ref_tag}-{rec.row_number}"
    lines = rec.lines or [(names.get("party") or names["main"], ZERO)]
    emitted = 0
    for index, (account, amount) in enumerate(lines):
        if index > 0 and amount == 0:
            continue
        if not rec.readable and index > 0:
            continue  # an unreadable row keeps one blocked line, so it stays visible and nothing half-built is saved
        debit, credit = (amount, ZERO) if amount > 0 else (ZERO, -amount)
        raw = {**rec.raw, "txn_key": rec.key, "line": index}
        result.rows.append(ParsedSourceRow(rec.row_number + emitted * LINE_ROW_OFFSET, account, rec.txn_date, rec.description or "Register row", debit, credit, reference, raw))
        emitted += 1


def _fmt(value: Decimal) -> str:
    return str(value)


def _summarise(template: Template, stats: RegisterStats, records: List[Record]) -> None:
    good = [r for r in records if r.readable]
    stats.records = len(good)
    stats.unreadable_rows = len(records) - len(good)
    dates = [r.txn_date for r in good if r.txn_date]
    if dates:
        stats.first_date, stats.last_date = min(dates), max(dates)

    def total(name: str) -> Decimal:
        return sum((r.figures.get(name, ZERO) for r in good), ZERO)

    def money(label: str, value: Decimal) -> dict:
        return {"label": label, "value": _fmt(value), "kind": "money"}

    if template.kind == "invoice":
        stats.credit_notes = sum(1 for r in good if r.figures.get("taxable", ZERO) < 0)
        noun = "Invoices" if template.key == "sales" else "Bills"
        stats.summary = [
            {"label": noun, "value": str(len(good)), "kind": "text"},
            money("Taxable value", total("taxable")),
            money("CGST", total("cgst")),
            money("SGST", total("sgst")),
            money("IGST", total("igst")),
            money("Total value", total("total")),
        ]
    else:
        deductions = sum((total(k) for k in ("pf", "esi", "tds", "ptax", "other")), ZERO)
        stats.summary = [
            {"label": "Employees", "value": str(len(good)), "kind": "text"},
            money("Gross pay", total("gross")),
            money("PF", total("pf")),
            money("ESI", total("esi")),
            money("TDS", total("tds")),
            money("Professional tax", total("ptax")),
            money("Other deductions", total("other")),
            money("Total deductions", deductions),
            money("Net pay", total("net")),
        ]


# ---- duplicates -------------------------------------------------------------------------------------------------------

def keys_of(parsed: RegisterParse) -> List[str]:
    return [r.key for r in parsed.records if r.readable and r.key]


def mark_duplicates(parsed: RegisterParse, existing_keys: Set[str]) -> int:
    """
    Marks every row an earlier import already holds as an ERROR (so it is not posted twice) and returns how many
    there were. Raises RegisterError when every readable row was already imported.
    """
    if not existing_keys:
        return 0
    readable = [r for r in parsed.records if r.readable]
    duplicates = [r for r in readable if r.key in existing_keys]
    if duplicates and len(duplicates) == len(readable):
        raise RegisterError(f"this file was already imported: all {len(readable)} rows are in an earlier import. Nothing was saved")
    for rec in duplicates:
        parsed.result.issues.append(ParseIssue(
            rec.row_number, "duplicate",
            "this row is already in an earlier import (same date, number, name and amounts), so it will not be posted again",
            Severity.ERROR,
        ))
    parsed.stats.duplicates = len(duplicates)
    return len(duplicates)


# ---- files ------------------------------------------------------------------------------------------------------------

def parse_file(path: Path, template_key: str, accounts: Optional[Dict[str, str]] = None, default_date: Optional[date] = None, party_accounts: bool = False, ref_tag: str = "RG") -> RegisterParse:
    try:
        rows, fmt = read_rows(path)
    except BankError as exc:
        raise RegisterError(str(exc).replace("bank statement", "file")) from exc
    return parse_table(rows, template_key, accounts, default_date, party_accounts, ref_tag=ref_tag, source_format=fmt.replace("bank", "register"))