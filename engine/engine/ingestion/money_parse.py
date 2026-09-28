"""
Parsing raw spreadsheet text into safe, exact types.

Kept separate from engine/ledger/money.py -- that module is normal-balance
arithmetic on values already in the ledger; this module is "turn a messy
cell string into a Decimal/date without ever touching a float." If
engine.ledger.money already exposes an equivalent amount parser, prefer
that one and delete the duplicate here.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

_AMOUNT_JUNK = re.compile(r"[,\s\u20b9$]")  # commas, whitespace, ₹, $

_DATE_FORMATS = (
    "%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%b-%Y", "%d %b %Y",
    "%m/%d/%Y", "%d.%m.%Y",
)


def parse_amount(raw: str | None) -> Decimal:
    """
    '1,20,000.00' -> Decimal('120000.00')
    '(5,000.00)'  -> Decimal('-5000.00')   (parens = negative, standard accounting notation)
    '' / None / '-' -> Decimal('0')
    Raises ValueError on anything else unparseable, so the caller can turn
    it into a row-level ParseIssue instead of silently writing a wrong number.
    """
    if raw is None:
        return Decimal("0")

    text = str(raw).strip()
    if text in ("", "-", "\u2013", "\u2014"):
        return Decimal("0")

    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]

    text = _AMOUNT_JUNK.sub("", text)
    if text in ("", "-"):
        return Decimal("0")

    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"could not parse amount: {raw!r}") from exc

    return -value if negative else value


def parse_date(raw: str | None) -> date | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None

    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None
