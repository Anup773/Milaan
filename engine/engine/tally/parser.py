"""
Reads Tally voucher XML (a Day Book export, from a file or from Tally's own HTTP interface) and turns it into the
same ParseResult an Excel/CSV import produces, so mapping, posting, reconciliation and everything after it work
unchanged.

How a Tally voucher becomes rows
  * One source row per ledger line of a voucher. Lines can sit directly under the voucher (LEDGERENTRIES.LIST or
    ALLLEDGERENTRIES.LIST) or, for item invoices, inside the stock lines (ACCOUNTINGALLOCATIONS.LIST).
  * Tally writes a debit as a NEGATIVE amount and a credit as a POSITIVE amount. A debit becomes `debit`, a credit
    becomes `credit`. Amounts stay exact decimals; nothing here uses a float.
  * The reference is "<voucher type> <voucher number>" (for example "Payment 12"), because Tally numbers restart per
    voucher type, and the mapping step groups rows by date + reference.
  * Cancelled and optional vouchers, and voucher types that do not touch the books (orders, delivery notes and so
    on), are left out and counted, never silently lost.
  * A voucher whose debits and credits differ gets an ERROR on each of its rows, so it cannot be posted half-way.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from ..ingestion.models import ParsedSourceRow, ParseIssue, ParseResult, Severity

# Voucher types that record intent or stock movement, not accounting entries.
NON_ACCOUNTING_VOUCHER_TYPES = {
    "sales order",
    "purchase order",
    "delivery note",
    "receipt note",
    "rejections in",
    "rejections out",
    "stock journal",
    "memorandum",
    "physical stock",
    "job work in order",
    "job work out order",
    "material in",
    "material out",
}

LEDGER_LINE_TAGS = ("LEDGERENTRIES.LIST", "ALLLEDGERENTRIES.LIST", "ACCOUNTINGALLOCATIONS.LIST")

# Tally sometimes writes characters XML does not allow, such as &#4; -- the standard parser refuses those.
_BAD_CHAR_REF = re.compile(r"&#(?:x([0-9a-fA-F]+)|([0-9]+));")
_BAD_RAW_CHARS = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")
_XML_DECLARATION = re.compile(r"^\s*<\?xml[^>]*\?>", re.IGNORECASE)
_DANGEROUS_DECLARATIONS = re.compile(r"<!\s*(DOCTYPE|ENTITY)", re.IGNORECASE)

MAX_ISSUES_PER_KIND = 50


class TallyError(ValueError):
    """Bad input or unusable response. A ValueError so the API reports it as a 400, not a crash."""


@dataclass
class TallyStats:
    vouchers_seen: int = 0
    vouchers_imported: int = 0
    skipped_cancelled: int = 0
    skipped_optional: int = 0
    skipped_non_accounting: int = 0
    skipped_no_ledger_lines: int = 0
    zero_amount_lines_skipped: int = 0
    unbalanced_vouchers: int = 0
    first_date: Optional[date] = None
    last_date: Optional[date] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "vouchers_seen": self.vouchers_seen,
            "vouchers_imported": self.vouchers_imported,
            "skipped_cancelled": self.skipped_cancelled,
            "skipped_optional": self.skipped_optional,
            "skipped_non_accounting": self.skipped_non_accounting,
            "skipped_no_ledger_lines": self.skipped_no_ledger_lines,
            "zero_amount_lines_skipped": self.zero_amount_lines_skipped,
            "unbalanced_vouchers": self.unbalanced_vouchers,
            "first_date": self.first_date.isoformat() if self.first_date else None,
            "last_date": self.last_date.isoformat() if self.last_date else None,
        }


@dataclass
class TallyParse:
    result: ParseResult
    stats: TallyStats = field(default_factory=TallyStats)


def decode_xml_bytes(data: bytes) -> str:
    """Tally exports are often UTF-16 on Windows; other times UTF-8. Decode either, never crash on a stray byte."""
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        return data.decode("utf-16", errors="replace")
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", errors="replace")
    # UTF-16 without a byte-order mark: every other byte is NUL for plain text.
    if len(data) >= 4 and data[1:2] == b"\x00" and data[3:4] == b"\x00":
        return data.decode("utf-16-le", errors="replace")
    if len(data) >= 4 and data[0:1] == b"\x00" and data[2:3] == b"\x00":
        return data.decode("utf-16-be", errors="replace")
    return data.decode("utf-8", errors="replace")


def clean_xml_text(text: str) -> str:
    """Drops what the XML parser cannot accept, and refuses documents that declare entities (expansion attacks)."""
    if _DANGEROUS_DECLARATIONS.search(text):
        raise TallyError("this XML declares a DOCTYPE or ENTITY, which is not accepted for safety")
    text = _XML_DECLARATION.sub("", text, count=1)

    def fix(match: "re.Match[str]") -> str:
        code = int(match.group(1), 16) if match.group(1) else int(match.group(2))
        if code in (9, 10, 13) or 32 <= code <= 0xD7FF or 0xE000 <= code <= 0xFFFD or 0x10000 <= code <= 0x10FFFF:
            return match.group(0)
        return ""

    text = _BAD_CHAR_REF.sub(fix, text)
    return _BAD_RAW_CHARS.sub("", text)


def _text(element: Optional[ET.Element], tag: str) -> str:
    if element is None:
        return ""
    child = element.find(tag)
    if child is None or child.text is None:
        return ""
    return child.text.strip()


def _is_yes(element: ET.Element, tag: str) -> bool:
    return _text(element, tag).lower() == "yes"


def _parse_tally_date(raw: str) -> Optional[date]:
    raw = raw.strip()
    if re.fullmatch(r"\d{8}", raw):
        try:
            return datetime.strptime(raw, "%Y%m%d").date()
        except ValueError:
            return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d-%b-%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _parse_amount(raw: str) -> Decimal:
    """Tally amounts are plain numbers, sometimes with a unit suffix or thousands separators on stock lines."""
    text = raw.strip().replace(",", "")
    if not text:
        return Decimal("0")
    # keep the leading sign and digits; ignore trailing text such as "5 Nos"
    match = re.match(r"^[+-]?\d+(?:\.\d+)?|^[+-]?\.\d+", text)
    if not match:
        raise ValueError(f"could not read amount {raw!r}")
    try:
        return Decimal(match.group(0))
    except InvalidOperation as exc:
        raise ValueError(f"could not read amount {raw!r}") from exc


def _ledger_lines(voucher: ET.Element) -> List[ET.Element]:
    lines: List[ET.Element] = []
    for tag in LEDGER_LINE_TAGS:
        for element in voucher.iter(tag):
            if element.find("LEDGERNAME") is not None and element.find("AMOUNT") is not None:
                lines.append(element)
    return lines


def _issue(result: ParseResult, row_number: int, field_name: str, message: str, severity: Severity) -> None:
    result.issues.append(ParseIssue(row_number, field_name, message, severity))


def parse_tally_xml(data: bytes | str) -> TallyParse:
    text = decode_xml_bytes(data) if isinstance(data, (bytes, bytearray)) else data
    text = clean_xml_text(text)
    if not text.strip():
        raise TallyError("the file is empty")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise TallyError(f"this is not valid XML: {exc}") from exc

    # Tally can answer an error as <RESPONSE>...</RESPONSE> or <LINEERROR>.
    for tag in ("LINEERROR",):
        error = root.find(f".//{tag}")
        if error is not None and (error.text or "").strip():
            raise TallyError(f"Tally reported an error: {(error.text or '').strip()}")

    vouchers = list(root.iter("VOUCHER"))
    result = ParseResult(source_format="tally-xml", sheet_name=None, detected_columns={})
    stats = TallyStats()
    if not vouchers:
        raise TallyError("no vouchers were found in this XML. Export the Day Book from Tally as XML and try again")

    row_number = 0
    unnumbered = 0
    for voucher in vouchers:
        stats.vouchers_seen += 1
        vch_type = (voucher.get("VCHTYPE") or _text(voucher, "VOUCHERTYPENAME")).strip()
        if _is_yes(voucher, "ISCANCELLED"):
            stats.skipped_cancelled += 1
            continue
        if _is_yes(voucher, "ISOPTIONAL"):
            stats.skipped_optional += 1
            continue
        if vch_type.lower() in NON_ACCOUNTING_VOUCHER_TYPES:
            stats.skipped_non_accounting += 1
            continue

        lines = _ledger_lines(voucher)
        if not lines:
            stats.skipped_no_ledger_lines += 1
            continue

        number = _text(voucher, "VOUCHERNUMBER")
        if number:
            reference = f"{vch_type} {number}".strip()
        else:
            unnumbered += 1
            reference = f"{vch_type or 'Voucher'} (no number #{unnumbered})"
        narration = _text(voucher, "NARRATION")
        txn_date = _parse_tally_date(_text(voucher, "DATE"))

        voucher_rows: List[ParsedSourceRow] = []
        voucher_row_numbers: List[int] = []
        for line in lines:
            ledger = _text(line, "LEDGERNAME")
            try:
                amount = _parse_amount(_text(line, "AMOUNT"))
            except ValueError as exc:
                row_number += 1
                _issue(result, row_number, "amount", f"{reference}: {exc}", Severity.ERROR)
                voucher_row_numbers.append(row_number)
                voucher_rows.append(ParsedSourceRow(row_number, ledger, txn_date, narration, Decimal("0"), Decimal("0"), reference, {"voucher_type": vch_type, "amount": _text(line, "AMOUNT")}))
                continue
            if amount == 0:
                stats.zero_amount_lines_skipped += 1
                continue

            row_number += 1
            debit = -amount if amount < 0 else Decimal("0")
            credit = amount if amount > 0 else Decimal("0")
            if txn_date is None:
                _issue(result, row_number, "date", f"{reference}: missing or unreadable date {_text(voucher, 'DATE')!r}", Severity.ERROR)
            if not ledger:
                _issue(result, row_number, "account", f"{reference}: a line has no ledger name", Severity.ERROR)
            voucher_row_numbers.append(row_number)
            voucher_rows.append(
                ParsedSourceRow(
                    row_number=row_number,
                    account_ref=ledger,
                    transaction_date=txn_date,
                    description=narration,
                    debit=debit,
                    credit=credit,
                    reference=reference,
                    raw={
                        "source": "tally",
                        "voucher_type": vch_type,
                        "voucher_number": number,
                        "amount": _text(line, "AMOUNT"),
                        "is_deemed_positive": _text(line, "ISDEEMEDPOSITIVE"),
                        "guid": _text(voucher, "GUID"),
                        "party": _text(voucher, "PARTYLEDGERNAME"),
                    },
                )
            )

        if not voucher_rows:
            stats.skipped_no_ledger_lines += 1
            continue

        total_debit = sum((r.debit for r in voucher_rows), Decimal("0"))
        total_credit = sum((r.credit for r in voucher_rows), Decimal("0"))
        if total_debit != total_credit:
            stats.unbalanced_vouchers += 1
            for n in voucher_row_numbers:
                _issue(
                    result,
                    n,
                    "debit/credit",
                    f"{reference}: voucher does not balance (debits {total_debit}, credits {total_credit})",
                    Severity.ERROR,
                )
        result.rows.extend(voucher_rows)
        stats.vouchers_imported += 1
        if txn_date is not None:
            stats.first_date = txn_date if stats.first_date is None else min(stats.first_date, txn_date)
            stats.last_date = txn_date if stats.last_date is None else max(stats.last_date, txn_date)

    if not result.rows:
        raise TallyError(
            "vouchers were found but none could be imported "
            f"({stats.skipped_cancelled} cancelled, {stats.skipped_optional} optional, "
            f"{stats.skipped_non_accounting} not accounting entries, {stats.skipped_no_ledger_lines} without ledger lines)"
        )
    return TallyParse(result=result, stats=stats)