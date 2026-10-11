"""
What a diff means in numbers -- pure logic, no database.

Two things matter to the person comparing imports: how the totals moved (overall,
per account, per accounting period) and whether any change lands in a period that
has already been finalised and LOCKED (those cannot simply be re-imported over).

Rows with status ERROR are left out of every total: ingestion could not read them
properly and Phase 5 never posts them, so they cannot move the ledger. They still
show in the row-by-row diff, with their status, so nothing is hidden.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ..mapping.planner import Period
from .models import UNCHANGED, RowChange, RowVersion

ZERO = Decimal("0.00")
NO_PERIOD = "No period (undated, or outside every accounting period)"


def find_period(d: Optional[date], periods: Sequence[Period]) -> Optional[Period]:
    if d is None:
        return None
    for p in periods:
        if p.start <= d <= p.end:
            return p
    return None


def _counts(rows: Sequence[RowVersion]) -> Dict[str, Any]:
    counted = [r for r in rows if r.status != "ERROR"]
    debit = sum((r.debit for r in counted), ZERO)
    credit = sum((r.credit for r in counted), ZERO)
    return {"rows": len(rows), "rows_with_errors": len(rows) - len(counted), "rows_with_warnings": sum(1 for r in rows if r.status == "WARNING"),
            "total_debit": debit, "total_credit": credit, "in_balance": debit == credit}


def totals(old_rows: Sequence[RowVersion], new_rows: Sequence[RowVersion]) -> Dict[str, Any]:
    old, new = _counts(old_rows), _counts(new_rows)
    return {"base": old, "compare": new,
            "delta_debit": new["total_debit"] - old["total_debit"],
            "delta_credit": new["total_credit"] - old["total_credit"]}


def by_account(old_rows: Sequence[RowVersion], new_rows: Sequence[RowVersion], changes: Sequence[RowChange],
               mapped_accounts: Mapping[str, Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """
    One entry per account (as named in the files, after normalisation). `mapped_accounts` maps
    an account key to the chart-of-accounts account it is confirmed to, if any. Accounts with no
    difference at all are left out; the list is ordered by how far the account's net moved.
    """
    acc: Dict[str, Dict[str, Any]] = {}

    def slot(row: RowVersion) -> Dict[str, Any]:
        key = row.account_key
        if key not in acc:
            mapped = mapped_accounts.get(key)
            acc[key] = {"account_key": key, "label": row.account_ref, "account": dict(mapped) if mapped else None,
                        "base_debit": ZERO, "base_credit": ZERO, "compare_debit": ZERO, "compare_credit": ZERO,
                        "changed_rows": 0}
        return acc[key]

    for r in old_rows:
        if r.status != "ERROR":
            s = slot(r)
            s["base_debit"] += r.debit
            s["base_credit"] += r.credit
    for r in new_rows:
        if r.status != "ERROR":
            s = slot(r)
            s["compare_debit"] += r.debit
            s["compare_credit"] += r.credit
    for c in changes:
        if c.kind == UNCHANGED:
            continue
        for row in {r.account_key: r for r in (c.old, c.new) if r is not None}.values():
            slot(row)["changed_rows"] += 1

    out = []
    for s in acc.values():
        s["net_change"] = (s["compare_debit"] - s["compare_credit"]) - (s["base_debit"] - s["base_credit"])
        if s["net_change"] != 0 or s["base_debit"] != s["compare_debit"] or s["base_credit"] != s["compare_credit"] or s["changed_rows"]:
            out.append(s)
    return sorted(out, key=lambda s: (-abs(s["net_change"]), s["label"].casefold(), s["account_key"]))


def by_period(old_rows: Sequence[RowVersion], new_rows: Sequence[RowVersion], changes: Sequence[RowChange],
              periods: Sequence[Period]) -> List[Dict[str, Any]]:
    """Totals per accounting period on each side, and which periods a change touches (including a locked one)."""
    slots: Dict[Optional[str], Dict[str, Any]] = {}

    def slot(d: Optional[date]) -> Dict[str, Any]:
        p = find_period(d, periods)
        pid = p.id if p else None
        if pid not in slots:
            slots[pid] = {"period_id": pid, "label": p.label if p else NO_PERIOD, "start": p.start if p else None,
                          "end": p.end if p else None, "locked": bool(p and p.locked),
                          "base_debit": ZERO, "base_credit": ZERO, "compare_debit": ZERO, "compare_credit": ZERO,
                          "changed_rows": 0}
        return slots[pid]

    for r in old_rows:
        if r.status != "ERROR":
            s = slot(r.transaction_date)
            s["base_debit"] += r.debit
            s["base_credit"] += r.credit
    for r in new_rows:
        if r.status != "ERROR":
            s = slot(r.transaction_date)
            s["compare_debit"] += r.debit
            s["compare_credit"] += r.credit
    for c in changes:
        if c.kind == UNCHANGED:
            continue
        touched = {find_period(r.transaction_date, periods).id if find_period(r.transaction_date, periods) else None: r
                   for r in (c.old, c.new) if r is not None}
        for row in touched.values():
            slot(row.transaction_date)["changed_rows"] += 1

    out = []
    for s in slots.values():
        s["net_change"] = (s["compare_debit"] - s["compare_credit"]) - (s["base_debit"] - s["base_credit"])
        s["affected"] = bool(s["changed_rows"] or s["base_debit"] != s["compare_debit"] or s["base_credit"] != s["compare_credit"])
        out.append(s)
    return sorted(out, key=lambda s: (s["start"] is None, s["start"] or date.max, s["label"]))


def locked_periods_affected(period_rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    return [{"period_id": p["period_id"], "label": p["label"]} for p in period_rows if p["locked"] and p["affected"]]