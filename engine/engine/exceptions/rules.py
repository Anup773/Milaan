"""
The built-in detectors. Importing this module registers them.

Each rule is a pure function over a list of EntryRow (see dataset.py) that
returns Findings -- the database is read once, before any rule runs. Each
finding is a NEUTRAL observation: the wording says what was seen and what it
"may" mean, and leaves the decision to the reviewer (§7). Nothing here ever
calls anything fraudulent, fake or wrong.

Categories from ARCHITECTURE.md §7 and what each rule actually looks at:

  DUPLICATE_INVOICE    same voucher/invoice reference + same accounts + same amount, on two or more entries (any date)
  DUPLICATE_AMOUNT     same accounts + same amount within a few days of each other, but NOT sharing one reference
  MISSING_EVIDENCE     an entry built from an upload (or a hand-made one) with no voucher/invoice reference at all
  VENDOR_MISMATCH      the same reference and amount posted against different payable (liability) accounts
  UNUSUAL_TRANSACTION  an income/expense posting many times the usual (median) size for that account
  PERIOD_CUTOFF        an entry dated outside its own accounting period, or dated in the future
  UNSUPPORTED_EXPENSE  an expense with no trace of where it came from, or with no reference and no description
  OTHER                raised by a person (repository.raise_manual), or by a rule you add

Known limits, stated rather than hidden:
  * "Evidence" today means a voucher/invoice reference on the uploaded row. Real
    supporting documents (the evidence/ area of the plan) are a later phase.
  * Ingestion has no vendor column, so a "vendor" is inferred from the payable
    (liability) account an entry credits. Receivables (customers) are not checked.
  * Two identical vouchers with the same date AND the same reference inside ONE
    uploaded file are merged into a single entry by Phase 5's grouping, so this
    pair of rules cannot see them as two entries.
"""
from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from statistics import median
from typing import Dict, List, Sequence, Tuple

from .dataset import (EntryRow, cluster_by_date, entry_signature, entry_summary)
from .registry import (DetectionContext, Finding, Thresholds, found, make_fingerprint, not_checked,
                       register_detector)

ZERO = Decimal("0.00")
MAX_MEMBERS_LISTED = 25  # a group with more members than this lists the first few, and says how many there are
_BUMP = {"LOW": "MEDIUM", "MEDIUM": "HIGH", "HIGH": "HIGH"}


def _m(x: Decimal) -> str:
    return f"{x:,.2f}"


def _priority(amount: Decimal, th: Thresholds, base: str) -> str:
    """The rule's usual priority, raised one level for a large amount."""
    return _BUMP[base] if amount >= th.large_amount else base


def _members(entries: Sequence[EntryRow]) -> List[dict]:
    return [entry_summary(e) for e in entries[:MAX_MEMBERS_LISTED]]


# ── 1. duplicate invoice ──────────────────────────────────────────────────
def find_duplicate_invoices(entries: Sequence[EntryRow], period_id: str, th: Thresholds) -> List[Finding]:
    groups: Dict[tuple, List[EntryRow]] = {}
    for e in entries:
        if e.origin == "depreciation" or e.ref_key is None or not e.lines:
            continue
        groups.setdefault((e.ref_key, entry_signature(e)), []).append(e)

    out: List[Finding] = []
    for (ref_key, _shape), members in groups.items():
        if len(members) < 2 or not any(m.period_id == period_id for m in members):
            continue
        members = sorted(members, key=lambda m: (m.entry_date, m.id))
        latest = members[-1]
        amount = latest.total
        dates = ", ".join(m.entry_date.isoformat() for m in members[:MAX_MEMBERS_LISTED])
        out.append(Finding(
            rule_id="duplicate_invoice", category="DUPLICATE_INVOICE",
            fingerprint=make_fingerprint("duplicate_invoice", *sorted(m.id for m in members)),
            title=f"Reference {latest.reference.strip()} is on {len(members)} identical entries",
            message=(f"{len(members)} entries carry the reference '{latest.reference.strip()}' and post the same amount "
                     f"({_m(amount)}) to the same accounts (dated {dates}). This may be one invoice entered more than "
                     f"once, or separate transactions that happen to reuse a reference; a reviewer needs to decide."),
            priority=_priority(amount, th, "MEDIUM"),
            journal_entry_id=latest.id, related_entry_ids=tuple(m.id for m in members), amount=amount,
            details={"reference": latest.reference.strip(), "normalized_reference": ref_key,
                     "entry_count": len(members), "entries": _members(members)},
        ))
    return sorted(out, key=lambda f: f.fingerprint)


@register_detector("duplicate_invoice", "DUPLICATE_INVOICE", "Duplicate invoice: same reference, accounts and amount",
                   "Entries that carry the same voucher/invoice reference and post the same amount to the same "
                   "accounts, in this period or any earlier one.")
def duplicate_invoice(ctx: DetectionContext):
    ds = ctx.dataset
    if not ds.in_scope:
        return not_checked("No ledger entries are posted in this period yet.")
    if not any(e.ref_key for e in ds.in_scope):
        return not_checked("No entry in this period carries a usable voucher/invoice reference to compare.")
    return found(find_duplicate_invoices(ds.entries, ds.period_id, ctx.thresholds))


# ── 2. duplicate amount ───────────────────────────────────────────────────
def find_duplicate_amounts(entries: Sequence[EntryRow], period_id: str, th: Thresholds) -> List[Finding]:
    by_shape: Dict[tuple, List[EntryRow]] = {}
    for e in entries:
        if e.origin == "depreciation" or not e.lines or e.total < th.min_amount:
            continue
        by_shape.setdefault(entry_signature(e), []).append(e)

    out: List[Finding] = []
    for group in by_shape.values():
        if len(group) < 2:
            continue
        for cluster in cluster_by_date(group, th.duplicate_window_days):
            if len(cluster) < 2 or not any(m.period_id == period_id for m in cluster):
                continue
            keys = {m.ref_key for m in cluster}
            if len(keys) == 1 and None not in keys:
                continue  # all share one usable reference: that is the duplicate_invoice rule's finding
            latest = cluster[-1]
            amount = latest.total
            dates = ", ".join(m.entry_date.isoformat() for m in cluster[:MAX_MEMBERS_LISTED])
            out.append(Finding(
                rule_id="duplicate_amount", category="DUPLICATE_AMOUNT",
                fingerprint=make_fingerprint("duplicate_amount", *sorted(m.id for m in cluster)),
                title=f"{len(cluster)} entries of {_m(amount)} to the same accounts within {th.duplicate_window_days} days",
                message=(f"{len(cluster)} entries post {_m(amount)} to the same accounts on {dates}, without sharing one "
                         f"voucher/invoice reference. This may be a payment or expense entered twice, or a genuine repeat; "
                         f"a reviewer needs to decide."),
                priority=_priority(amount, th, "MEDIUM"),
                journal_entry_id=latest.id, related_entry_ids=tuple(m.id for m in cluster), amount=amount,
                details={"window_days": th.duplicate_window_days, "entry_count": len(cluster), "entries": _members(cluster)},
            ))
    return sorted(out, key=lambda f: f.fingerprint)


@register_detector("duplicate_amount", "DUPLICATE_AMOUNT", "Duplicate amount: same accounts and amount, close together",
                   "Entries that post the same amount to the same accounts within a few days of each other without "
                   "sharing a voucher/invoice reference (entries that do share one are covered by the duplicate-invoice rule).")
def duplicate_amount(ctx: DetectionContext):
    ds = ctx.dataset
    if not ds.in_scope:
        return not_checked("No ledger entries are posted in this period yet.")
    if not any(e.total >= ctx.thresholds.min_amount and e.origin != "depreciation" for e in ds.in_scope):
        return not_checked(f"No entry in this period is at least {_m(ctx.thresholds.min_amount)}.")
    return found(find_duplicate_amounts(ds.entries, ds.period_id, ctx.thresholds))


# ── 3. missing evidence ───────────────────────────────────────────────────
def find_missing_evidence(entries: Sequence[EntryRow], period_id: str, th: Thresholds) -> List[Finding]:
    out: List[Finding] = []
    for e in entries:
        if (e.period_id != period_id or e.origin not in ("source_row", "manual")
                or e.has_reference or e.total < th.min_amount):
            continue
        where = f" (file {e.source_file}, row {e.source_row})" if e.source_file else ""
        out.append(Finding(
            rule_id="missing_evidence", category="MISSING_EVIDENCE",
            fingerprint=make_fingerprint("missing_evidence", e.id),
            title=f"No voucher/invoice reference on an entry of {_m(e.total)}",
            message=(f"The entry dated {e.entry_date.isoformat()} for {_m(e.total)}{where} has no voucher or invoice "
                     f"reference, so there is nothing to tie it to a document. That may be perfectly fine (for example a "
                     f"bank charge), or it may need supporting evidence; a reviewer needs to decide."),
            priority=_priority(e.total, th, "LOW"),
            journal_entry_id=e.id, related_entry_ids=(e.id,), amount=e.total,
            details={"entry": entry_summary(e)},
        ))
    return sorted(out, key=lambda f: f.fingerprint)


@register_detector("missing_evidence", "MISSING_EVIDENCE", "Missing evidence: no voucher/invoice reference",
                   "Entries built from an uploaded file (or made by hand) that carry no voucher/invoice reference. "
                   "Until supporting documents are tracked, a reference is what 'evidence' means here.")
def missing_evidence(ctx: DetectionContext):
    ds = ctx.dataset
    if not any(e.origin in ("source_row", "manual") for e in ds.in_scope):
        return not_checked("No entries in this period came from an uploaded file or were made by hand.")
    return found(find_missing_evidence(ds.entries, ds.period_id, ctx.thresholds))


# ── 4. vendor mismatch ────────────────────────────────────────────────────
def _party_accounts(entry: EntryRow) -> Dict[str, str]:
    """The payable (liability) accounts an entry touches: account_id -> 'code name'."""
    return {l.account_id: f"{l.code} {l.name}" for l in entry.lines
            if l.account_type == "Liability" and (l.debit > 0 or l.credit > 0)}


def find_vendor_mismatches(entries: Sequence[EntryRow], period_id: str, th: Thresholds) -> List[Finding]:
    groups: Dict[tuple, List[EntryRow]] = {}
    for e in entries:
        if e.origin == "depreciation" or e.ref_key is None or e.total < th.min_amount or not _party_accounts(e):
            continue
        groups.setdefault((e.ref_key, f"{e.total:.2f}"), []).append(e)

    out: List[Finding] = []
    for (ref_key, _amount), members in groups.items():
        if len(members) < 2 or not any(m.period_id == period_id for m in members):
            continue
        parties = [set(_party_accounts(m)) for m in members]
        if set.intersection(*parties):
            continue  # at least one payable account is common to every entry: they agree on the vendor
        members = sorted(members, key=lambda m: (m.entry_date, m.id))
        latest = members[-1]
        names: Dict[str, str] = {}
        for m in members:
            names.update(_party_accounts(m))
        shown = ", ".join(sorted(names.values()))
        out.append(Finding(
            rule_id="vendor_mismatch", category="VENDOR_MISMATCH",
            fingerprint=make_fingerprint("vendor_mismatch", *sorted(m.id for m in members)),
            title=f"Reference {latest.reference.strip()} is posted against different payable accounts",
            message=(f"{len(members)} entries share the reference '{latest.reference.strip()}' and the amount "
                     f"{_m(latest.total)}, but post to different payable accounts ({shown}). This may be an invoice "
                     f"booked to one vendor and paid to another, or two vendors that happen to use the same number; "
                     f"a reviewer needs to decide."),
            priority=_priority(latest.total, th, "MEDIUM"),
            journal_entry_id=latest.id, related_entry_ids=tuple(m.id for m in members), amount=latest.total,
            details={"reference": latest.reference.strip(), "normalized_reference": ref_key,
                     "payable_accounts": sorted(names.values()), "entries": _members(members)},
        ))
    return sorted(out, key=lambda f: f.fingerprint)


@register_detector("vendor_mismatch", "VENDOR_MISMATCH", "Vendor mismatch: same reference, different payable account",
                   "Entries with the same voucher/invoice reference and the same amount that post to different payable "
                   "(liability) accounts -- the vendor is inferred from the payable account, as uploads have no vendor column.")
def vendor_mismatch(ctx: DetectionContext):
    ds = ctx.dataset
    if not ds.in_scope:
        return not_checked("No ledger entries are posted in this period yet.")
    if not any(e.ref_key and _party_accounts(e) for e in ds.in_scope):
        return not_checked("No entry in this period has both a usable reference and a payable account to compare.")
    return found(find_vendor_mismatches(ds.entries, ds.period_id, ctx.thresholds))


# ── 5. unusual transaction ────────────────────────────────────────────────
def _normal_side_amount(account_type: str, debit: Decimal, credit: Decimal) -> Decimal:
    """Expense accounts are looked at on their debit side, income accounts on their credit side."""
    if account_type == "Expense":
        return debit
    if account_type == "Income":
        return credit
    return ZERO


def find_unusual(entries: Sequence[EntryRow], period_id: str, th: Thresholds) -> Tuple[List[Finding], int]:
    """Returns (findings, how many in-period postings had enough history to be compared at all)."""
    history: Dict[str, List[Decimal]] = {}
    for e in entries:
        for l in e.lines:
            amt = _normal_side_amount(l.account_type, l.debit, l.credit)
            if amt > 0:
                history.setdefault(l.account_id, []).append(amt)
    typical = {acc: median(v) for acc, v in history.items() if len(v) >= th.unusual_min_history + 1}

    evaluated = 0
    out: List[Finding] = []
    for e in entries:
        if e.period_id != period_id or e.origin == "depreciation":
            continue
        hits = []
        for l in e.lines:
            amt = _normal_side_amount(l.account_type, l.debit, l.credit)
            if amt <= 0 or l.account_id not in typical:
                continue
            evaluated += 1
            med = typical[l.account_id]
            if med > 0 and amt >= th.min_amount and amt >= th.unusual_factor * med:
                hits.append({"account": f"{l.code} {l.name}", "account_id": l.account_id, "amount": amt,
                             "typical_amount": med.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
                             "times_typical": (amt / med).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP),
                             "postings_compared": len(history[l.account_id])})
        if not hits:
            continue
        top = max(hits, key=lambda h: h["amount"])
        highest = max(h["times_typical"] for h in hits)
        out.append(Finding(
            rule_id="unusual_transaction", category="UNUSUAL_TRANSACTION",
            fingerprint=make_fingerprint("unusual_transaction", e.id, *sorted(h["account_id"] for h in hits)),
            title=f"{top['account']}: {_m(top['amount'])} is {top['times_typical']}x the usual posting",
            message=(f"The entry dated {e.entry_date.isoformat()} posts {_m(top['amount'])} to {top['account']}, about "
                     f"{top['times_typical']} times the typical (median) posting of {_m(top['typical_amount'])} "
                     f"across {top['postings_compared']} postings to that account. That may be a genuine one-off; "
                     f"a reviewer needs to decide."),
            priority="HIGH" if highest >= th.unusual_high_factor else "MEDIUM",
            journal_entry_id=e.id, related_entry_ids=(e.id,), amount=top["amount"],
            details={"entry": entry_summary(e), "unusual_lines": hits},
        ))
    return sorted(out, key=lambda f: f.fingerprint), evaluated


@register_detector("unusual_transaction", "UNUSUAL_TRANSACTION", "Unusual transaction: far above the account's usual size",
                   "Income or expense postings that are several times the typical (median) posting to that account. "
                   "Needs some posting history on the account before it compares anything.")
def unusual_transaction(ctx: DetectionContext):
    ds = ctx.dataset
    if not ds.in_scope:
        return not_checked("No ledger entries are posted in this period yet.")
    findings, evaluated = find_unusual(ds.entries, ds.period_id, ctx.thresholds)
    if evaluated == 0:
        return not_checked("No income or expense account has enough posting history yet to tell what is unusual.")
    return found(findings)


# ── 6. period / cut-off ───────────────────────────────────────────────────
def cutoff_reasons(entry_date: date, start: date, end: date, today: date) -> List[str]:
    reasons = []
    if entry_date < start or entry_date > end:
        reasons.append("outside_period")
    if entry_date > today:
        reasons.append("future_dated")
    return reasons


def find_cutoff_anomalies(entries: Sequence[EntryRow], period_id: str, start: date, end: date, label: str,
                          today: date, th: Thresholds) -> List[Finding]:
    out: List[Finding] = []
    for e in entries:
        if e.period_id != period_id or e.total < th.min_amount:
            continue
        reasons = cutoff_reasons(e.entry_date, start, end, today)
        if not reasons:
            continue
        parts = []
        if "outside_period" in reasons:
            parts.append(f"is dated {e.entry_date.isoformat()} but is posted in {label} ({start.isoformat()} to {end.isoformat()})")
        if "future_dated" in reasons:
            parts.append(f"is dated {e.entry_date.isoformat()}, which is after today ({today.isoformat()})")
        title = {("outside_period",): "Entry date falls outside its accounting period",
                 ("future_dated",): "Entry is dated in the future"}.get(tuple(reasons), "Entry date is outside its period and in the future")
        out.append(Finding(
            rule_id="period_cutoff", category="PERIOD_CUTOFF",
            fingerprint=make_fingerprint("period_cutoff", e.id),
            title=title,
            message=(f"An entry of {_m(e.total)} " + " and ".join(parts) + ". This may be a posting to the wrong period, "
                     "a date typed wrongly, or a genuine advance entry; a reviewer needs to decide."),
            priority=_priority(e.total, th, "MEDIUM"),
            journal_entry_id=e.id, related_entry_ids=(e.id,), amount=e.total,
            details={"reasons": reasons, "entry": entry_summary(e), "period_start": start, "period_end": end,
                     "period_label": label, "today": today},
        ))
    return sorted(out, key=lambda f: f.fingerprint)


@register_detector("period_cutoff", "PERIOD_CUTOFF", "Period cut-off: date outside the period, or in the future",
                   "Entries whose date falls outside the accounting period they are posted in, or after today's date.")
def period_cutoff(ctx: DetectionContext):
    ds = ctx.dataset
    if not ds.in_scope:
        return not_checked("No ledger entries are posted in this period yet.")
    return found(find_cutoff_anomalies(ds.entries, ds.period_id, ds.period_start, ds.period_end, ds.period_label,
                                       ctx.today, ctx.thresholds))


# ── 7. unsupported expense ────────────────────────────────────────────────
def unsupported_reasons(e: EntryRow) -> List[str]:
    reasons = []
    if e.origin == "manual":
        reasons.append("manual_entry_without_origin")
    elif e.origin == "source_row" and not e.has_reference and not e.description.strip():
        reasons.append("no_reference_or_description")
    return reasons


def find_unsupported_expenses(entries: Sequence[EntryRow], period_id: str, th: Thresholds) -> List[Finding]:
    out: List[Finding] = []
    for e in entries:
        spent = e.expense_debit
        if e.period_id != period_id or spent < th.min_amount:
            continue
        reasons = unsupported_reasons(e)
        if not reasons:
            continue
        what = {"manual_entry_without_origin": "was made by hand, with no uploaded row, adjustment or schedule behind it",
                "no_reference_or_description": "has no voucher/invoice reference and no description"}
        out.append(Finding(
            rule_id="unsupported_expense", category="UNSUPPORTED_EXPENSE",
            fingerprint=make_fingerprint("unsupported_expense", e.id),
            title=f"Expense of {_m(spent)} with nothing to support it",
            message=(f"An expense of {_m(spent)} dated {e.entry_date.isoformat()} " + " and ".join(what[r] for r in reasons)
                     + ". That may be an entry whose paperwork is simply elsewhere; a reviewer needs to decide."),
            priority=_priority(spent, th, "MEDIUM"),
            journal_entry_id=e.id, related_entry_ids=(e.id,), amount=spent,
            details={"reasons": reasons, "expense_amount": spent, "entry": entry_summary(e)},
        ))
    return sorted(out, key=lambda f: f.fingerprint)


@register_detector("unsupported_expense", "UNSUPPORTED_EXPENSE", "Unsupported expense: nothing explains it",
                   "Expense entries made by hand with no trace of where they came from, or built from an upload with no "
                   "voucher/invoice reference and no description.")
def unsupported_expense(ctx: DetectionContext):
    ds = ctx.dataset
    if not any(e.expense_debit >= ctx.thresholds.min_amount for e in ds.in_scope):
        return not_checked(f"No entry in this period debits an expense account by at least {_m(ctx.thresholds.min_amount)}.")
    return found(find_unsupported_expenses(ds.entries, ds.period_id, ctx.thresholds))