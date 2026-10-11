"""
The diff engine: pairs the rows of an older import with the rows of a newer one
and says, for every row, whether it is UNCHANGED, CHANGED (and which fields),
ADDED (only in the newer file) or REMOVED (only in the older file).

Pure logic, no database. Row numbers are NOT used to decide whether two rows are
the same row -- a re-export that inserts one line renumbers everything below it
-- only to break ties. Rows are paired in passes, strictest first; a row can be
paired only once, and only rows left over from earlier passes are considered:

  1 EXACT                     same account, date, reference, amounts and description
  2 VOUCHER                   same reference + same account            (amount / date / description changed)
  3 VOUCHER_ACCOUNT_CHANGED   same reference + date + amounts           (posted to a different account)
  4 ACCOUNT_DATE_TEXT         same account + date + description         (amount / reference changed)
  5 ACCOUNT_DATE_AMOUNT       same account + date + amounts             (description / reference changed)

Passes 2-5 are judgement calls, which is why every pairing records `matched_by`:
a reviewer can see how sure the match is, and a pairing that is wrong shows up
as one REMOVED plus one ADDED row, never as a silently merged one. Inside a
bucket of candidates, the closest pair wins (same side, then nearest amount,
then same date, then nearest row number).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .models import ADDED, CHANGED, REMOVED, UNCHANGED, FieldChange, RowChange, RowVersion

EXACT = "EXACT"
VOUCHER = "VOUCHER"
VOUCHER_ACCOUNT_CHANGED = "VOUCHER_ACCOUNT_CHANGED"
ACCOUNT_DATE_TEXT = "ACCOUNT_DATE_TEXT"
ACCOUNT_DATE_AMOUNT = "ACCOUNT_DATE_AMOUNT"

# A bucket of candidates larger than this (old x new) is paired in sorted order instead of by
# pairwise closeness, so one pathological bucket (thousands of rows, same account, same voucher
# number) cannot make a comparison crawl.
MAX_PAIR_COMPARISONS = 50_000

_KIND_RANK = {CHANGED: 0, ADDED: 1, REMOVED: 2, UNCHANGED: 3}

KeyFn = Callable[[RowVersion], Optional[tuple]]


def _exact_key(r: RowVersion) -> tuple:
    return (r.account_key, r.transaction_date, r.ref_key, r.debit, r.credit, r.desc_key)


def _voucher_key(r: RowVersion) -> Optional[tuple]:
    return (r.ref_key, r.account_key) if r.ref_key else None


def _voucher_account_changed_key(r: RowVersion) -> Optional[tuple]:
    return (r.ref_key, r.transaction_date, r.debit, r.credit) if r.ref_key else None


def _account_date_text_key(r: RowVersion) -> Optional[tuple]:
    return (r.account_key, r.transaction_date, r.desc_key) if r.transaction_date and r.desc_key else None


def _account_date_amount_key(r: RowVersion) -> Optional[tuple]:
    return (r.account_key, r.transaction_date, r.debit, r.credit) if r.transaction_date else None


_PASSES: Tuple[Tuple[str, KeyFn], ...] = (
    (VOUCHER, _voucher_key),
    (VOUCHER_ACCOUNT_CHANGED, _voucher_account_changed_key),
    (ACCOUNT_DATE_TEXT, _account_date_text_key),
    (ACCOUNT_DATE_AMOUNT, _account_date_amount_key),
)


def _closeness(old: RowVersion, new: RowVersion) -> tuple:
    return (0 if old.side == new.side else 1, abs(old.amount - new.amount),
            0 if old.transaction_date == new.transaction_date else 1, abs(old.row_number - new.row_number))


def _pair_bucket(olds: List[RowVersion], news: List[RowVersion]) -> List[Tuple[RowVersion, RowVersion]]:
    if len(olds) * len(news) > MAX_PAIR_COMPARISONS:
        def order(r: RowVersion):
            return (r.transaction_date or date.min, r.side, r.amount, r.row_number)
        return list(zip(sorted(olds, key=order), sorted(news, key=order)))

    candidates = sorted(((_closeness(o, n), o.row_number, n.row_number, i, j)
                         for i, o in enumerate(olds) for j, n in enumerate(news)))
    used_old, used_new, pairs = set(), set(), []
    for _, _, _, i, j in candidates:
        if i in used_old or j in used_new:
            continue
        used_old.add(i)
        used_new.add(j)
        pairs.append((olds[i], news[j]))
    return pairs


def field_changes(old: RowVersion, new: RowVersion) -> Tuple[FieldChange, ...]:
    out: List[FieldChange] = []
    if old.account_key != new.account_key:
        out.append(FieldChange("account", old.account_ref, new.account_ref))
    if old.transaction_date != new.transaction_date:
        out.append(FieldChange("date", old.transaction_date, new.transaction_date))
    if old.ref_key != new.ref_key:
        out.append(FieldChange("reference", old.reference or None, new.reference or None))
    if old.desc_key != new.desc_key:
        out.append(FieldChange("description", old.description, new.description))
    if old.debit != new.debit:
        out.append(FieldChange("debit", old.debit, new.debit))
    if old.credit != new.credit:
        out.append(FieldChange("credit", old.credit, new.credit))
    return tuple(out)


def diff_rows(old_rows: Sequence[RowVersion], new_rows: Sequence[RowVersion]) -> List[RowChange]:
    """Every old row and every new row appears in exactly one RowChange."""
    changes: List[RowChange] = []
    left_old = sorted(old_rows, key=lambda r: (r.row_number, r.id))
    left_new = sorted(new_rows, key=lambda r: (r.row_number, r.id))

    # pass 1: identical rows pair off one-for-one (two identical rows in both files pair twice)
    buckets: Dict[tuple, Tuple[List[RowVersion], List[RowVersion]]] = defaultdict(lambda: ([], []))
    for r in left_old:
        buckets[_exact_key(r)][0].append(r)
    for r in left_new:
        buckets[_exact_key(r)][1].append(r)
    paired_old, paired_new = set(), set()
    for olds, news in buckets.values():
        for o, n in zip(olds, news):
            changes.append(RowChange(UNCHANGED, o, n, EXACT))
            paired_old.add(o.id)
            paired_new.add(n.id)
    left_old = [r for r in left_old if r.id not in paired_old]
    left_new = [r for r in left_new if r.id not in paired_new]

    # passes 2-5: progressively looser identities, on what is left
    for name, key_fn in _PASSES:
        if not left_old or not left_new:
            break
        pass_buckets: Dict[tuple, Tuple[List[RowVersion], List[RowVersion]]] = defaultdict(lambda: ([], []))
        for r in left_old:
            k = key_fn(r)
            if k is not None:
                pass_buckets[k][0].append(r)
        for r in left_new:
            k = key_fn(r)
            if k is not None:
                pass_buckets[k][1].append(r)
        paired_old, paired_new = set(), set()
        for olds, news in pass_buckets.values():
            if not olds or not news:
                continue
            for o, n in _pair_bucket(olds, news):
                fields = field_changes(o, n)
                changes.append(RowChange(CHANGED if fields else UNCHANGED, o, n, name, fields))
                paired_old.add(o.id)
                paired_new.add(n.id)
        left_old = [r for r in left_old if r.id not in paired_old]
        left_new = [r for r in left_new if r.id not in paired_new]

    changes.extend(RowChange(REMOVED, o, None) for o in left_old)
    changes.extend(RowChange(ADDED, None, n) for n in left_new)
    return sorted(changes, key=_sort_key)


def _sort_key(c: RowChange) -> tuple:
    anchor = c.new if c.new is not None else c.old
    return (_KIND_RANK[c.kind], anchor.row_number, c.old.row_number if c.old else 0, anchor.id)


def count_kinds(changes: Sequence[RowChange]) -> Dict[str, int]:
    counts = {CHANGED: 0, ADDED: 0, REMOVED: 0, UNCHANGED: 0}
    for c in changes:
        counts[c.kind] += 1
    return counts