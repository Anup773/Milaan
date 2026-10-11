"""Pure-logic tests for engine.versions (matcher + normalisation) -- no database."""
import random
from datetime import date
from decimal import Decimal

import pytest

from engine.versions import matcher
from engine.versions.matcher import diff_rows
from engine.versions.models import ADDED, CHANGED, REMOVED, UNCHANGED, RowVersion

D = Decimal


def row(rid, n, account="Bank", d=(2026, 3, 5), desc="", debit="0", credit="0", ref="", status="OK"):
    return RowVersion(rid, n, account, date(*d) if d else None, desc, D(debit), D(credit), ref, status)


def kinds(changes):
    return sorted((c.kind, (c.old.id if c.old else None), (c.new.id if c.new else None)) for c in changes)


def only(changes, kind):
    return [c for c in changes if c.kind == kind]


# ── identical / cosmetic ──
def test_identical_files_are_all_unchanged():
    rows = [row("a", 1, debit="100", ref="V1"), row("b", 2, "Sales", credit="100", ref="V1")]
    changes = diff_rows(rows, [row("a2", 1, debit="100", ref="V1"), row("b2", 2, "Sales", credit="100", ref="V1")])
    assert {c.kind for c in changes} == {UNCHANGED} and {c.matched_by for c in changes} == {"EXACT"}


def test_renumbering_alone_is_not_a_change():
    old = [row("a", 1, debit="100", ref="V1"), row("b", 2, "Sales", credit="100", ref="V1")]
    new = [row("x", 1, "Cash", debit="5", ref="V0", desc="new first line"), row("a2", 2, debit="100", ref="V1"), row("b2", 3, "Sales", credit="100", ref="V1")]
    changes = diff_rows(old, new)
    assert [c.kind for c in changes if c.kind != UNCHANGED] == [ADDED] and len(only(changes, UNCHANGED)) == 2
    assert {c.matched_by for c in only(changes, UNCHANGED)} == {"EXACT"}  # found by content, not by position


def test_case_spacing_and_reference_punctuation_are_not_changes():
    old = [row("a", 1, "Bank  Account", debit="100", ref="INV-001", desc="Rent  paid")]
    new = [row("b", 9, "bank account", debit="100", ref="inv 001", desc="rent paid")]
    [c] = diff_rows(old, new)
    assert c.kind == UNCHANGED


def test_amounts_compare_as_numbers_not_text():
    [c] = diff_rows([row("a", 1, debit="10")], [row("b", 1, debit="10.00")])
    assert c.kind == UNCHANGED


# ── pairing passes ──
def test_changed_amount_on_the_same_voucher_is_one_changed_row_with_the_field():
    [c] = diff_rows([row("a", 1, debit="100", ref="V1")], [row("b", 1, debit="150", ref="V1")])
    assert c.kind == CHANGED and c.matched_by == "VOUCHER"
    assert [(f.field, f.old, f.new) for f in c.fields] == [("debit", D("100"), D("150"))]


def test_changed_date_and_description_are_reported_together():
    [c] = diff_rows([row("a", 1, debit="100", ref="V1", d=(2026, 3, 5), desc="rent")],
                    [row("b", 1, debit="100", ref="V1", d=(2026, 4, 2), desc="rent march")])
    assert c.kind == CHANGED and {f.field for f in c.fields} == {"date", "description"}


def test_a_debit_turned_into_a_credit_is_still_the_same_voucher():
    [c] = diff_rows([row("a", 1, debit="100", ref="V1")], [row("b", 1, credit="100", ref="V1")])
    assert c.kind == CHANGED and c.matched_by == "VOUCHER" and {f.field for f in c.fields} == {"debit", "credit"}


def test_a_different_account_with_the_same_voucher_date_and_amount():
    [c] = diff_rows([row("a", 1, "Bank", debit="100", ref="V1")], [row("b", 1, "Cash", debit="100", ref="V1")])
    assert c.kind == CHANGED and c.matched_by == "VOUCHER_ACCOUNT_CHANGED" and [f.field for f in c.fields] == ["account"]


def test_without_a_reference_same_account_date_and_description_pairs_a_changed_amount():
    [c] = diff_rows([row("a", 1, debit="100", desc="taxi")], [row("b", 1, debit="120", desc="taxi")])
    assert c.kind == CHANGED and c.matched_by == "ACCOUNT_DATE_TEXT" and [f.field for f in c.fields] == ["debit"]


def test_a_reworded_description_with_the_same_account_date_and_amount():
    [c] = diff_rows([row("a", 1, debit="100", desc="taxi")], [row("b", 1, debit="100", desc="cab fare")])
    assert c.kind == CHANGED and c.matched_by == "ACCOUNT_DATE_AMOUNT" and [f.field for f in c.fields] == ["description"]


def test_rows_with_nothing_in_common_are_removed_and_added_never_merged():
    changes = diff_rows([row("a", 1, "Bank", debit="100", d=(2026, 3, 5), desc="x")],
                        [row("b", 1, "Sales", credit="999", d=(2026, 6, 9), desc="y")])
    assert kinds(changes) == [(ADDED, None, "b"), (REMOVED, "a", None)]


def test_placeholder_references_do_not_pair_unrelated_rows():
    changes = diff_rows([row("a", 1, "Bank", debit="100", ref="NA", d=(2026, 3, 1))],
                        [row("b", 1, "Bank", debit="999", ref="NA", d=(2026, 5, 1))])
    assert kinds(changes) == [(ADDED, None, "b"), (REMOVED, "a", None)]


def test_undated_rows_are_not_paired_by_the_date_passes():
    changes = diff_rows([row("a", 1, d=None, debit="100", desc="x")], [row("b", 1, d=None, debit="200", desc="x")])
    assert kinds(changes) == [(ADDED, None, "b"), (REMOVED, "a", None)]


def test_the_closest_candidate_wins_inside_a_bucket():
    old = [row("a1", 1, debit="100", ref="V1"), row("a2", 2, debit="500", ref="V1")]
    new = [row("b1", 1, debit="505", ref="V1"), row("b2", 2, debit="95", ref="V1")]
    pairs = {c.old.id: c.new.id for c in diff_rows(old, new)}
    assert pairs == {"a1": "b2", "a2": "b1"}


def test_identical_duplicate_rows_pair_one_for_one_and_the_extra_one_is_added():
    old = [row("a1", 1, debit="100", ref="V1"), row("a2", 2, debit="100", ref="V1")]
    new = [row("b1", 1, debit="100", ref="V1"), row("b2", 2, debit="100", ref="V1"), row("b3", 3, debit="100", ref="V1")]
    changes = diff_rows(old, new)
    assert len(only(changes, UNCHANGED)) == 2 and len(only(changes, ADDED)) == 1


def test_an_exact_match_is_never_stolen_by_a_looser_pass():
    old = [row("a1", 1, debit="100", ref="V1"), row("a2", 2, debit="300", ref="V1")]
    new = [row("b1", 1, debit="300", ref="V1")]
    changes = diff_rows(old, new)
    assert [(c.kind, c.old.id, c.new.id) for c in changes if c.kind == UNCHANGED] == [(UNCHANGED, "a2", "b1")]
    assert [(c.kind, c.old.id) for c in changes if c.kind == REMOVED] == [(REMOVED, "a1")]


def test_a_huge_bucket_falls_back_to_ordered_pairing(monkeypatch):
    monkeypatch.setattr(matcher, "MAX_PAIR_COMPARISONS", 4)
    old = [row(f"a{i}", i, debit=str(100 + i), ref="V1") for i in range(1, 6)]
    new = [row(f"b{i}", i, debit=str(200 + i), ref="V1") for i in range(1, 6)]
    changes = diff_rows(old, new)
    assert len(only(changes, CHANGED)) == 5 and not only(changes, ADDED) and not only(changes, REMOVED)


# ── invariants ──
def test_every_row_appears_exactly_once_whatever_the_data():
    rng = random.Random(7)
    accounts, refs, descs = ["Bank", "Cash", "Sales", "Rent"], ["", "V1", "V2", "NA", "INV-9"], ["", "taxi", "rent"]

    def make(prefix, n):
        return [row(f"{prefix}{i}", i, rng.choice(accounts), d=(2026, 3, rng.randint(1, 4)), desc=rng.choice(descs),
                    debit=str(rng.choice([0, 100, 200])), credit=str(rng.choice([0, 100])), ref=rng.choice(refs)) for i in range(n)]

    for _ in range(40):
        old, new = make("o", rng.randint(0, 25)), make("n", rng.randint(0, 25))
        changes = diff_rows(old, new)
        seen_old = [c.old.id for c in changes if c.old]
        seen_new = [c.new.id for c in changes if c.new]
        assert sorted(seen_old) == sorted(r.id for r in old) and sorted(seen_new) == sorted(r.id for r in new)
        for c in changes:
            assert (c.kind == ADDED) == (c.old is None) and (c.kind == REMOVED) == (c.new is None)
            assert (c.kind == CHANGED) == bool(c.fields)


def test_the_result_does_not_depend_on_the_order_the_rows_arrive_in():
    rng = random.Random(3)
    old = [row(f"o{i}", i, rng.choice(["Bank", "Cash"]), d=(2026, 3, rng.randint(1, 3)), debit=str(rng.choice([100, 200])), ref=rng.choice(["", "V1", "V2"])) for i in range(15)]
    new = [row(f"n{i}", i, rng.choice(["Bank", "Cash"]), d=(2026, 3, rng.randint(1, 3)), debit=str(rng.choice([100, 200, 300])), ref=rng.choice(["", "V1", "V2"])) for i in range(15)]
    base = kinds(diff_rows(old, new))
    for seed in range(5):
        a, b = old[:], new[:]
        random.Random(seed).shuffle(a)
        random.Random(seed + 1).shuffle(b)
        assert kinds(diff_rows(a, b)) == base


def test_changed_rows_are_listed_before_added_removed_and_unchanged():
    old = [row("u", 1, debit="1", ref="U1"), row("c", 2, debit="100", ref="V1"), row("r", 3, "Rent", d=(2026, 1, 1), debit="9", desc="gone")]
    new = [row("u2", 1, debit="1", ref="U1"), row("c2", 2, debit="150", ref="V1"), row("n", 3, "Sales", d=(2026, 8, 8), credit="9", desc="fresh")]
    assert [c.kind for c in diff_rows(old, new)] == [CHANGED, ADDED, REMOVED, UNCHANGED]


# ── normalisation stays in step with the rest of the engine ──
def test_references_are_normalised_like_the_exceptions_package():
    from engine.exceptions.dataset import has_reference, normalize_reference
    from engine.versions.normalize import reference_key

    for text in ("INV-001", "inv 001", "NA", "n/a", "Opening Balance", "CASH", "", None, "V1", "0001", "  Bill "):
        expected = normalize_reference(text) if has_reference(text) else ""
        assert reference_key(text) == expected, text


def test_account_keys_match_the_mapping_planner():
    from engine.mapping.planner import normalize_ref
    from engine.versions.normalize import account_key

    for text in ("Bank  Account", " bank account ", "BANK ACCOUNT", "1000"):
        assert account_key(text) == normalize_ref(text)
