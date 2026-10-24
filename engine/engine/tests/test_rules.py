"""Phase 21 -- the rules registry: consistency of the built-in rule sets, filtering, and the CLI."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from engine import rules
from engine.rules import registry as reg
from engine.rules.registry import (ACTIVE, CATALOG_ONLY, FAMILIES, FULL, NONE, PARTIAL, RuleSet, applicable, catalog,
                                   checks_for, item)

ENGINE_DIR = Path(__file__).resolve().parents[2]


# --- the built-in rule sets ---------------------------------------------------------------------------------

def test_every_family_has_at_least_one_rule_set():
    for family in FAMILIES:
        assert applicable(family=family), family


def test_every_check_a_rule_names_really_exists():
    # The one test that stops the catalog from claiming a check that is not there.
    assert reg.unknown_check_references() == []


def test_coverage_is_honest():
    for rs in reg.RULE_SETS.values():
        for it in rs.items:
            assert (it.coverage == NONE) == (not it.checks), (rs.id, it.id)
            if it.coverage == PARTIAL:
                assert it.note, (rs.id, it.id)
        if rs.status == CATALOG_ONLY:
            assert not any(it.coverage == FULL for it in rs.items), rs.id


def test_only_the_milaan_own_sets_are_active_and_standards_are_catalog_only():
    active = {rs.id for rs in reg.RULE_SETS.values() if rs.status == ACTIVE}
    assert active == {"core-ledger", "internal-controls"}
    for sid in ("ifrs", "ind-as", "nfrs", "frs-102", "isa", "sa-india", "india-gst", "uk-vat", "uae-vat", "nepal-vat", "information-security"):
        assert reg.get(sid).status == CATALOG_ONLY, sid


def test_no_item_claims_a_standard_is_met_in_full():
    # Scope boundary (§12): nothing under a real standard or tax law may be FULL.
    for sid in ("ifrs", "ind-as", "nfrs", "frs-102", "isa", "sa-india", "india-gst", "india-tds", "uk-vat", "uae-vat", "nepal-vat"):
        assert all(it.coverage != FULL for it in reg.get(sid).items), sid


def test_iso_27001_is_listed_as_not_certified_and_not_an_accounting_rule():
    rs = reg.get("information-security")
    assert rs.family == "compliance"
    text = rs.description.lower()
    assert "not certified" in text and "not accounting or auditing rules" in text
    assert all(it.coverage == NONE for it in rs.items)


def test_isa_is_an_auditing_set_not_an_accounting_one():
    assert reg.get("isa").family == "auditing"
    assert "isa" not in {rs.id for rs in applicable(family="accounting")}


def test_ids_are_unique_and_items_are_unique_within_a_set():
    assert len(reg.RULE_SETS) == len({rs.id for rs in reg.RULE_SETS.values()})
    for rs in reg.RULE_SETS.values():
        ids = [i.id for i in rs.items]
        assert len(ids) == len(set(ids)), rs.id


# --- registering --------------------------------------------------------------------------------------------

def _set(**over):
    base = dict(id="x-set", family="tax", title="X", framework="VAT", jurisdiction="XX", authority="a", status=CATALOG_ONLY,
                description="d", items=(item("i1", "I", "d"),))
    base.update(over)
    return RuleSet(**base)


@pytest.fixture
def scratch():
    before = dict(reg.RULE_SETS)
    yield
    reg.RULE_SETS.clear()
    reg.RULE_SETS.update(before)


def test_a_new_rule_set_is_picked_up_without_other_changes(scratch):
    reg.register_rule_set(_set(id="xx-vat", jurisdiction="XX"))
    assert [r.id for r in applicable(jurisdiction="XX", family="tax")] == ["xx-vat"]
    assert "xx-vat" in {r["id"] for r in catalog()["rule_sets"]}


@pytest.mark.parametrize("over,message", [
    ({"id": "Bad Id"}, "lower-case"),
    ({"family": "banking"}, "family"),
    ({"status": "LIVE"}, "status"),
    ({"items": ()}, "no rule items"),
    ({"jurisdiction": ""}, "framework and a jurisdiction"),
    ({"items": (item("a", "A", "d"), item("a", "B", "d"))}, "appears twice"),
    ({"items": (item("a", "A", "d", coverage=FULL),)}, "NONE means no checks"),
    ({"items": (item("a", "A", "d", checks=[("feature", "audit_trail")]),)}, "NONE means no checks"),
    ({"items": (item("a", "A", "d", coverage=PARTIAL, checks=[("feature", "audit_trail")]),)}, "must say in the note"),
    ({"items": (item("a", "A", "d", coverage=FULL, checks=[("nonsense", "q")]),)}, "unknown check kind"),
    ({"items": (item("a", "A", "d", coverage=FULL, checks=[("feature", "teleporting")]),)}, "unknown feature"),
    ({"items": (item("a", "A", "d", coverage=FULL, checks=[("feature", "audit_trail")]),)}, "CATALOG_ONLY"),
])
def test_inconsistent_rule_sets_are_refused(scratch, over, message):
    with pytest.raises(ValueError, match=message):
        reg.register_rule_set(_set(**over))
    assert "x-set" not in reg.RULE_SETS


def test_registering_the_same_id_twice_is_refused(scratch):
    reg.register_rule_set(_set())
    with pytest.raises(ValueError, match="already registered"):
        reg.register_rule_set(_set())


def test_a_dangling_check_reference_is_reported(scratch):
    reg.register_rule_set(_set(status=ACTIVE, items=(item("a", "A", "d", coverage=FULL, checks=[("reconciliation", "no_such_rule")]),)))
    assert reg.unknown_check_references() == ["x-set/a -> reconciliation:no_such_rule"]


# --- asking the registry ------------------------------------------------------------------------------------

def test_jurisdiction_filter_keeps_international_sets():
    ids = {r.id for r in applicable(family="accounting", jurisdiction="IN")}
    assert {"core-ledger", "ifrs", "ind-as"} <= ids
    assert "nfrs" not in ids and "frs-102" not in ids


def test_framework_filter_keeps_sets_that_apply_under_any_framework():
    ids = {r.id for r in applicable(family="accounting", framework="ind as")}
    assert ids == {"core-ledger", "ind-as"}


def test_filters_ignore_case_and_blank_means_no_filter():
    assert applicable(jurisdiction="in") == applicable(jurisdiction="IN")
    assert applicable(jurisdiction="  ", framework="") == applicable()


def test_a_country_with_no_local_sets_still_gets_the_international_ones():
    ids = {r.id for r in applicable(jurisdiction="ZZ")}
    assert ids == {r.id for r in reg.RULE_SETS.values() if r.jurisdiction == "INTL"}
    assert "core-ledger" in ids


def test_status_filter():
    assert {r.id for r in applicable(status=ACTIVE)} == {"core-ledger", "internal-controls"}


def test_bad_filters_are_rejected():
    with pytest.raises(ValueError, match="family"):
        applicable(family="nope")
    with pytest.raises(ValueError, match="status"):
        applicable(status="nope")
    with pytest.raises(ValueError, match="no rule set called"):
        reg.get("nope")


def test_results_are_ordered_by_family_then_title():
    sets = applicable()
    keys = [(FAMILIES.index(r.family), r.title.lower()) for r in sets]
    assert keys == sorted(keys)


def test_checks_for_lists_each_check_once_in_a_stable_order():
    refs = checks_for(applicable(family="accounting", jurisdiction="IN"))
    pairs = [(r.kind, r.id) for r in refs]
    assert pairs == sorted(set(pairs))
    assert ("reconciliation", "fixed_asset_accumulated_depreciation") in pairs
    assert checks_for([]) == []


# --- the JSON shape -----------------------------------------------------------------------------------------

def test_catalog_shape_and_counts():
    c = catalog()
    assert c["notice"].startswith("This is a catalog")
    assert [f["id"] for f in c["families"]] == list(FAMILIES)
    assert sum(f["rule_sets"] for f in c["families"]) == len(reg.RULE_SETS)
    s = c["summary"]
    assert s["rule_sets"] == len(c["rule_sets"]) == s["active"] + s["catalog_only"]
    assert s["items"] == sum(len(r["items"]) for r in c["rule_sets"])
    assert s["items_with_checks"] == sum(1 for r in c["rule_sets"] for i in r["items"] if i["coverage"] != "NONE")
    for r in c["rule_sets"]:
        assert r["coverage"] == {k: sum(1 for i in r["items"] if i["coverage"] == k) for k in ("FULL", "PARTIAL", "NONE")}
        for i in r["items"]:
            for ch in i["checks"]:
                assert ch["title"], (r["id"], i["id"], ch)


def test_catalog_summary_counts_only_the_filtered_sets_but_families_count_everything():
    c = catalog(family="tax")
    assert {r["family"] for r in c["rule_sets"]} == {"tax"}
    assert c["summary"]["rule_sets"] == len(c["rule_sets"])
    assert sum(f["rule_sets"] for f in c["families"]) == len(reg.RULE_SETS)


def test_catalog_is_json_serialisable():
    json.dumps(catalog())


# --- the command line (what the API runs) ----------------------------------------------------------------------

def _cli(*args):
    return subprocess.run([sys.executable, "-m", "engine.rules.cli", *args], cwd=ENGINE_DIR, capture_output=True, text=True)


def test_cli_catalog_with_filters_and_skips():
    out = _cli("catalog", "tax", "-", "VAT")
    assert out.returncode == 0, out.stderr
    ids = {r["id"] for r in json.loads(out.stdout)["rule_sets"]}
    assert ids == {"nepal-vat", "uk-vat", "uae-vat"}


def test_cli_get():
    out = _cli("get", "isa")
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout)["family"] == "auditing"


@pytest.mark.parametrize("args", [("get", "nope"), ("get",), ("catalog", "banking"), ("catalog", "-", "-", "-", "LIVE"),
                                  ("catalog", "a", "b", "c", "d", "e"), ("frobnicate",)])
def test_cli_bad_input_is_a_400_on_stderr(args):
    out = _cli(*args)
    assert out.returncode != 0
    assert json.loads(out.stderr.strip().splitlines()[-1])["status"] == 400


def test_cli_without_a_command_is_a_usage_error():
    out = _cli()
    assert out.returncode == 2