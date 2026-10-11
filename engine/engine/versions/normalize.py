"""
How rows are compared: text is compared after dropping case, extra spaces and
(for references) punctuation, so a re-export that merely re-cased "Bank  Account"
or wrote "inv 001" instead of "INV-001" is not reported as a change.

The account and reference rules deliberately match the ones the rest of the
engine already uses (mapping.planner.normalize_ref, exceptions.dataset), so a
row is "the same account" / "the same reference" here exactly when it is
elsewhere. tests/test_version_matcher.py checks that they stay in step.
"""
from __future__ import annotations

from typing import Optional

from ..mapping.planner import normalize_ref

# Not real voucher numbers: matching rows to each other on these would pair unrelated rows.
PLACEHOLDER_REFERENCES = frozenset({
    "na", "nil", "none", "null", "nan", "tbd", "ob", "opening", "openingbalance",
    "cash", "ref", "refno", "noref", "noreference", "bill", "invoice", "voucher",
})


def account_key(text: Optional[str]) -> str:
    return normalize_ref(text or "")


def reference_key(text: Optional[str]) -> str:
    """Letters and digits only, lower-cased; '' for blank or placeholder references."""
    norm = "".join(ch for ch in str(text or "").casefold() if ch.isalnum())
    return "" if norm in PLACEHOLDER_REFERENCES else norm


def description_key(text: Optional[str]) -> str:
    return " ".join(str(text or "").split()).casefold()