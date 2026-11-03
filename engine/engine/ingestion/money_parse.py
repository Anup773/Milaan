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
from datetime import date
from decimal import Decimal, InvalidOperation

from ..calendars.dates import DateRules, parse_date_detailed

_AMOUNT_JUNK = re.compile(r"[,\s₹$]")  # commas, whitespace, ₹, $


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
    if text in ("", "-", "–", "—"):
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


def parse_date(raw: str | None, rules: DateRules | None = None) -> date | None:
    """
    The AD date in `raw`, or None when it can not be read. How the text is read follows the company's date rules
    (calendar AD/BS, day-first or month-first): the rules passed in, else the ones in force for this piece of work
    (see engine.calendars.dates.use_rules), else the legacy rules for a company with no policy. A date is never
    guessed: 2082-04-01 is refused in an AD company (it is a BS year), and read as 16 July 2025 in a BS company.
    Callers that need to say WHY a date was refused use engine.calendars.dates.parse_date_detailed.
    """
    return parse_date_detailed(raw, rules).value