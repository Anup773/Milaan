"""
Pure logic -- no database. Validates a proposed adjustment's lines before
anything is written: balanced, no negative or double-sided amounts, no
zero-amount lines, at least two lines. Mirrors the same checks Phase 5's
mapping planner applies to a voucher before it's allowed to post -- an
adjustment is structurally the same kind of thing: a balanced set of
debit/credit lines against real accounts.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import List, Tuple

ZERO = Decimal("0.00")


@dataclass(frozen=True)
class ProposedLine:
    account_id: str
    debit: Decimal
    credit: Decimal


def validate_lines(lines: List[ProposedLine]) -> Tuple[bool, List[str]]:
    """Returns (is_valid, reasons) -- empty reasons iff is_valid."""
    reasons: List[str] = []

    if len(lines) < 2:
        reasons.append("an adjustment needs at least two lines")

    for i, line in enumerate(lines, start=1):
        if line.debit < 0 or line.credit < 0:
            reasons.append(f"line {i} has a negative amount")
        if line.debit != 0 and line.credit != 0:
            reasons.append(f"line {i} has both a debit and a credit - use separate lines")
        if line.debit == 0 and line.credit == 0:
            reasons.append(f"line {i} has no amount")

    total_debit = sum((l.debit for l in lines), ZERO)
    total_credit = sum((l.credit for l in lines), ZERO)
    if total_debit != total_credit:
        reasons.append(f"does not balance: debits {total_debit} vs credits {total_credit}")

    return (len(reasons) == 0, reasons)