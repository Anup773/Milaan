"""Pure-logic tests for engine.exceptions.rules / dataset -- no database."""
from datetime import date
from decimal import Decimal

import pytest

from engine.exceptions import rules
from engine.exceptions.dataset import (EntryDataset, EntryRow, LineRow, cluster_by_date, entry_signature,
                                       has_reference, normalize_reference, reference_key)
from engine.exceptions.registry import DetectionContext, Thresholds, run_detectors

D = Decimal
TH = Thresholds()
P = "p-march"


def line(account, atype, debit="0", credit="0", name=None):
    return LineRow(account, account, name or account, atype, D(debit), D(credit))


def entry(eid, day, *lines, ref="", desc="", origin="source_row", period=P, month=3, file="m.csv", row=1):
    return EntryRow(id=eid, entry_date=date(2026, month, day), description=desc, period_id=period, origin=origin,
                    reference=ref, source_file=file if origin == "source_row" else None,
                    source_row=row if origin == "source_row" else None, lines=tuple(lines))


def purchase(eid, day, amount="50000", ref="INV-100", vendor="vendorA", **kw):
    return entry(eid, day, line("purchases", "Expense", debit=amount), line(vendor, "Liability", credit=amount), ref=ref, desc="goods", **kw)


# ── references ──
def test_references_ignore_case_spaces_and_punctuation():
    assert normalize_reference(" INV-001 ") == normalize_reference("inv 001") == normalize_reference("INV/001") == "inv001"


def test_placeholders_and_blank_are_not_references():
    for text in (None, "", "  ", "NA", "n/a", "Nil", "-", "Opening Balance", "CASH"):
        assert not has_reference(text), text
    assert has_reference("V1") and has_reference("0001")


def test_short_references_are_real_evidence_but_too_weak_to_match_on():
    assert has_reference("V1") and reference_key("V1") is None
    assert reference_key("INV-1") == "inv1"


def test_signature_ignores_line_order():
    a = entry("a", 1, line("x", "Expense", debit="10"), line("y", "Liability", credit="10"))
    b = entry("b", 2, line("y", "Liability", credit="10.00"), line("x", "Expense", debit="10.00"))
    assert entry_signature(a) == entry_signature(b)


def test_cluster_by_date_splits_on_gaps():
    es = [entry(str(i), d, line("x", "Expense", debit="10")) for i, d in enumerate((1, 3, 9, 30))]
    assert [[e.entry_date.day for e in c] for c in cluster_by_date(es, 7)] == [[1, 3, 9], [30]]


# ── duplicate invoice ──
def test_same_reference_accounts_and_amount_is_flagged_on_the_later_entry():
    [f] = rules.find_duplicate_invoices([purchase("a", 5), purchase("b", 10, ref="inv 100")], P, TH)
    assert f.category == "DUPLICATE_INVOICE" and f.journal_entry_id == "b" and set(f.related_entry_ids) == {"a", "b"}
    assert f.amount == D("50000.00") and f.priority == "MEDIUM"
    assert "may be" in f.message and "fraud" not in f.message.lower()


def test_large_amounts_raise_the_priority():
    [f] = rules.find_duplicate_invoices([purchase("a", 5, amount="150000"), purchase("b", 10, amount="150000")], P, TH)
    assert f.priority == "HIGH"


def test_an_invoice_and_its_payment_sharing_a_reference_are_not_duplicates():
    pay = entry("pay", 12, line("vendorA", "Liability", debit="50000"), line("bank", "Asset", credit="50000"), ref="INV-100")
    assert rules.find_duplicate_invoices([purchase("a", 5), pay], P, TH) == []


def test_same_reference_but_different_amount_is_not_a_duplicate_invoice():
    assert rules.find_duplicate_invoices([purchase("a", 5), purchase("b", 10, amount="40000")], P, TH) == []


def test_placeholder_references_never_match():
    assert rules.find_duplicate_invoices([purchase("a", 5, ref="NA"), purchase("b", 10, ref="NA")], P, TH) == []


def test_a_duplicate_pair_entirely_in_older_periods_is_not_this_periods_flag():
    old = [purchase("a", 5, period="feb", month=2), purchase("b", 6, period="feb", month=2)]
    assert rules.find_duplicate_invoices(old, P, TH) == []


def test_depreciation_entries_are_never_duplicates():
    a = purchase("a", 5, origin="depreciation"); b = purchase("b", 5, origin="depreciation")
    assert rules.find_duplicate_invoices([a, b], P, TH) == []


def test_fingerprint_is_stable_and_depends_on_exactly_the_members():
    es = [purchase("a", 5), purchase("b", 10)]
    f1 = rules.find_duplicate_invoices(es, P, TH)[0].fingerprint
    f2 = rules.find_duplicate_invoices(list(reversed(es)), P, TH)[0].fingerprint
    f3 = rules.find_duplicate_invoices(es + [purchase("c", 11)], P, TH)[0].fingerprint
    assert f1 == f2 and f1 != f3


# ── duplicate amount ──
def rent(eid, day, ref="", amount="8000"):
    return entry(eid, day, line("rent", "Expense", debit=amount), line("bank", "Asset", credit=amount), ref=ref, desc="rent")


def test_same_accounts_and_amount_close_together_without_a_shared_reference():
    [f] = rules.find_duplicate_amounts([rent("a", 20, "R1X"), rent("b", 22, "R2X")], P, TH)
    assert f.category == "DUPLICATE_AMOUNT" and f.journal_entry_id == "b"


def test_far_apart_is_a_normal_recurring_payment():
    assert rules.find_duplicate_amounts([rent("a", 1), rent("b", 25)], P, TH) == []


def test_entries_sharing_one_reference_are_left_to_the_duplicate_invoice_rule():
    assert rules.find_duplicate_amounts([rent("a", 20, "R1X"), rent("b", 22, "r-1x")], P, TH) == []


def test_small_amounts_are_ignored():
    assert rules.find_duplicate_amounts([rent("a", 20, amount="500"), rent("b", 21, amount="500")], P, TH) == []


# ── missing evidence ──
def test_entry_without_a_reference_is_flagged_but_adjustments_and_depreciation_are_not():
    bare = entry("a", 15, line("misc", "Expense", debit="5000"), line("bank", "Asset", credit="5000"))
    adj = entry("b", 15, line("misc", "Expense", debit="5000"), line("bank", "Asset", credit="5000"), origin="adjustment")
    dep = entry("c", 15, line("misc", "Expense", debit="5000"), line("bank", "Asset", credit="5000"), origin="depreciation")
    out = rules.find_missing_evidence([bare, adj, dep], P, TH)
    assert [f.journal_entry_id for f in out] == ["a"] and out[0].priority == "LOW"
    assert "m.csv" in out[0].message


def test_a_short_reference_still_counts_as_evidence():
    e = entry("a", 15, line("misc", "Expense", debit="5000"), line("bank", "Asset", credit="5000"), ref="V1")
    assert rules.find_missing_evidence([e], P, TH) == []


# ── vendor mismatch ──
def pay(eid, day, vendor, ref="PAY-9", amount="20000"):
    return entry(eid, day, line(vendor, "Liability", debit=amount), line("bank", "Asset", credit=amount), ref=ref)


def test_same_reference_and_amount_paid_to_different_payables_is_flagged():
    [f] = rules.find_vendor_mismatches([pay("a", 12, "vendorA"), pay("b", 13, "vendorB")], P, TH)
    assert f.category == "VENDOR_MISMATCH" and "vendorA" in f.message and "vendorB" in f.message


def test_invoice_and_payment_to_the_same_vendor_agree():
    assert rules.find_vendor_mismatches([purchase("a", 5, amount="20000", ref="PAY-9"), pay("b", 13, "vendorA")], P, TH) == []


def test_different_amounts_are_not_compared():
    assert rules.find_vendor_mismatches([pay("a", 12, "vendorA"), pay("b", 13, "vendorB", amount="999999")], P, TH) == []


# ── unusual ──
def sale(eid, day, amount, period=P, month=3):
    return entry(eid, day, line("bank", "Asset", debit=amount), line("sales", "Income", credit=amount), ref=f"S-{eid}", desc="sale", period=period, month=month)


def history():
    return [sale(f"h{i}", i + 1, "10000", period="feb", month=2) for i in range(6)]


def test_a_posting_far_above_the_accounts_median_is_flagged_with_the_numbers():
    findings, evaluated = rules.find_unusual(history() + [sale("big", 25, "200000")], P, TH)
    [f] = findings
    assert evaluated == 1 and f.journal_entry_id == "big" and f.priority == "HIGH"
    assert f.details["unusual_lines"][0]["times_typical"] == D("20.0")


def test_moderately_large_is_medium():
    [f], _ = rules.find_unusual(history() + [sale("m", 25, "60000")], P, TH)
    assert f.priority == "MEDIUM"


def test_not_enough_history_means_not_checked_rather_than_clean():
    findings, evaluated = rules.find_unusual([sale("a", 1, "10000"), sale("b", 2, "900000")], P, TH)
    assert findings == [] and evaluated == 0


def test_only_income_and_expense_accounts_are_compared():
    big_bank = [entry(f"e{i}", i + 1, line("bank", "Asset", debit="10000"), line("cap", "Equity", credit="10000"), period="feb", month=2) for i in range(6)]
    big_bank.append(entry("x", 25, line("bank", "Asset", debit="900000"), line("cap", "Equity", credit="900000")))
    assert rules.find_unusual(big_bank, P, TH) == ([], 0)


# ── cut-off ──
def test_cutoff_reasons():
    start, end, today = date(2026, 3, 1), date(2026, 3, 31), date(2026, 4, 1)
    assert rules.cutoff_reasons(date(2026, 3, 15), start, end, today) == []
    assert rules.cutoff_reasons(date(2026, 4, 1), start, end, today) == ["outside_period"]
    assert rules.cutoff_reasons(date(2026, 4, 2), start, end, today) == ["outside_period", "future_dated"]
    assert rules.cutoff_reasons(date(2026, 3, 20), start, end, date(2026, 3, 10)) == ["future_dated"]


def test_cutoff_flag_keeps_its_identity_when_only_the_reasons_change():
    e = entry("a", 2, line("misc", "Expense", debit="3000"), line("bank", "Asset", credit="3000"), month=4)
    f1, = rules.find_cutoff_anomalies([e], P, date(2026, 3, 1), date(2026, 3, 31), "Mar 2026", date(2026, 4, 1), TH)
    f2, = rules.find_cutoff_anomalies([e], P, date(2026, 3, 1), date(2026, 3, 31), "Mar 2026", date(2026, 9, 1), TH)
    assert f1.fingerprint == f2.fingerprint and f1.details["reasons"] == ["outside_period", "future_dated"] and f2.details["reasons"] == ["outside_period"]


# ── unsupported expense ──
def test_manual_expense_and_unexplained_upload_expense_are_flagged():
    manual = entry("m", 5, line("misc", "Expense", debit="3000"), line("bank", "Asset", credit="3000"), origin="manual")
    bare = entry("b", 6, line("misc", "Expense", debit="3000"), line("bank", "Asset", credit="3000"))
    described = entry("d", 7, line("misc", "Expense", debit="3000"), line("bank", "Asset", credit="3000"), desc="taxi")
    referenced = entry("r", 8, line("misc", "Expense", debit="3000"), line("bank", "Asset", credit="3000"), ref="BILL-7", desc="BILL-7")
    adj = entry("a", 9, line("misc", "Expense", debit="3000"), line("bank", "Asset", credit="3000"), origin="adjustment")
    out = rules.find_unsupported_expenses([manual, bare, described, referenced, adj], P, TH)
    assert sorted(f.journal_entry_id for f in out) == ["b", "m"]


def test_non_expense_entries_are_never_unsupported_expenses():
    e = entry("a", 5, line("bank", "Asset", debit="9000"), line("sales", "Income", credit="9000"), origin="manual")
    assert rules.find_unsupported_expenses([e], P, TH) == []


# ── registered detectors, through the registry (no database) ──
def ctx_for(entries):
    ds = EntryDataset(P, date(2026, 3, 1), date(2026, 3, 31), "Mar 2026", entries)
    return DetectionContext(None, "c", P, today=date(2026, 4, 1), dataset=ds)


def test_every_registered_detector_is_not_checked_on_an_empty_period():
    outcomes = run_detectors(ctx_for([]))
    assert [o.status for o in outcomes if o.rule_id != "unsupported_expense"] == ["NOT_CHECKED"] * 6
    assert {o.status for o in outcomes} == {"NOT_CHECKED"}


def test_detectors_run_end_to_end_on_a_small_book():
    outcomes = {o.rule_id: o for o in run_detectors(ctx_for([purchase("a", 5), purchase("b", 10)] + history()))}
    assert outcomes["duplicate_invoice"].status == "CHECKED" and len(outcomes["duplicate_invoice"].findings) == 1
    assert set(outcomes) == {"duplicate_invoice", "duplicate_amount", "missing_evidence", "vendor_mismatch",
                             "unusual_transaction", "period_cutoff", "unsupported_expense"}


def test_findings_use_neutral_language():
    es = [purchase("a", 5), purchase("b", 10), rent("r1", 20), rent("r2", 21), pay("p1", 12, "vendorA"), pay("p2", 13, "vendorB")]
    es += history() + [sale("big", 25, "200000"), entry("bare", 15, line("misc", "Expense", debit="5000"), line("bank", "Asset", credit="5000"))]
    for o in run_detectors(ctx_for(es)):
        for f in o.findings:
            text = (f.title + " " + f.message).lower()
            assert "reviewer" in text or "may" in text
            for banned in ("fraud", "fake", "forged", "stolen", "is a duplicate", "is wrong", "illegal"):
                assert banned not in text
