"""Pure-logic tests for engine.approvals.policy -- no database."""
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from engine.approvals import policy as pol
from engine.scenarios import state_machine as sm

ME, OTHER = "user-me", "user-other"


def reasons(kind, decision, role="ca", actor=ME, maker=OTHER, locked=False):
    return pol.blocking_reasons(kind, decision, actor_id=actor, actor_role=role, maker_id=maker, period_locked=locked)


# ── who may decide ──
def test_every_kind_has_a_spec_and_only_known_roles():
    assert set(pol.SPECS) == set(pol.KINDS)
    for spec in pol.SPECS.values():
        assert spec.roles <= set(pol.ROLES) and set(spec.decisions) <= {pol.APPROVE, pol.REJECT}
        assert spec.maker_checked <= set(spec.decisions) and spec.needs_open_period <= set(spec.decisions)


def test_a_plain_accountant_can_never_approve_anything():
    for kind in pol.KINDS:
        for d in pol.SPECS[kind].decisions:
            assert reasons(kind, d, role="accountant"), (kind, d)


def test_a_permitted_person_who_did_not_make_it_can_decide():
    assert reasons(pol.KIND_ADJUSTMENT, "approve", role="senior_accountant") == []
    assert reasons(pol.KIND_SCENARIO_REVIEW, "approve", role="reviewer") == []
    assert reasons(pol.KIND_FINALIZATION, "approve", role="ca", maker=None) == []
    assert reasons(pol.KIND_REOPEN, "reject", role="admin") == []


def test_the_role_message_says_which_roles_could():
    [msg] = reasons(pol.KIND_FINALIZATION, "approve", role="reviewer", maker=None)
    assert "reviewer" in msg and "admin, ca" in msg


def test_the_second_person_rule_blocks_the_maker():
    for kind in (pol.KIND_ADJUSTMENT, pol.KIND_REOPEN):
        for d in (pol.APPROVE, pol.REJECT):
            [msg] = reasons(kind, d, role="ca", actor=ME, maker=ME)
            assert "someone else" in msg
    assert reasons(pol.KIND_SCENARIO_REVIEW, "approve", role="ca", actor=ME, maker=ME)


def test_a_creator_may_still_reject_their_own_scenario_as_the_state_machine_allows():
    assert reasons(pol.KIND_SCENARIO_REVIEW, "reject", role="ca", actor=ME, maker=ME) == []


def test_finalisation_has_no_second_person_rule():
    assert reasons(pol.KIND_FINALIZATION, "approve", role="ca", actor=ME, maker=ME) == []


def test_a_locked_period_blocks_only_what_needs_it_open():
    assert reasons(pol.KIND_ADJUSTMENT, "approve", locked=True)
    assert reasons(pol.KIND_ADJUSTMENT, "reject", locked=True) == []
    assert reasons(pol.KIND_SCENARIO_REVIEW, "approve", locked=True) and reasons(pol.KIND_SCENARIO_REVIEW, "reject", locked=True)
    assert reasons(pol.KIND_FINALIZATION, "approve", locked=True, maker=None)
    assert reasons(pol.KIND_REOPEN, "approve", locked=True) == [] and reasons(pol.KIND_REOPEN, "reject", locked=True) == []


def test_all_reasons_are_reported_together():
    assert len(reasons(pol.KIND_ADJUSTMENT, "approve", role="accountant", actor=ME, maker=ME, locked=True)) == 3


def test_permission_and_state_reasons_are_kept_apart():
    assert pol.permission_reasons(pol.KIND_ADJUSTMENT, "approve", actor_id=ME, actor_role="ca", maker_id=OTHER) == []
    assert pol.state_reasons(pol.KIND_ADJUSTMENT, "approve", period_locked=True)
    assert pol.state_reasons(pol.KIND_ADJUSTMENT, "approve", period_locked=False) == []


def test_unknown_kind_or_a_decision_the_kind_does_not_have():
    with pytest.raises(ValueError, match="kind must be one of"):
        pol.spec_for("nonsense")
    with pytest.raises(ValueError, match="can only be: approve"):
        pol.check_decision(pol.KIND_FINALIZATION, "reject")


def test_rejecting_needs_a_note_approving_does_not():
    for blank in (None, "", "   "):
        with pytest.raises(ValueError, match="note"):
            pol.check_note("reject", blank)
    pol.check_note("reject", "figures do not agree")
    pol.check_note("approve", None)


# ── history vocabulary ──
def test_scenario_transitions_map_to_decisions():
    assert pol.actions_for(None, None) == ["approve", "approve_reopen", "deny_reopen", "finalize", "reject"]
    assert pol.actions_for(pol.KIND_REOPEN, None) == ["approve_reopen", "deny_reopen"]
    assert pol.actions_for(None, pol.REJECTED) == ["deny_reopen", "reject"]
    assert pol.actions_for(pol.KIND_FINALIZATION, pol.FINALIZED) == ["finalize"]
    assert pol.actions_for(pol.KIND_FINALIZATION, pol.APPROVED) == []


def test_adjustment_statuses_map_to_decisions():
    assert pol.adjustment_statuses_for(None, None) == ["POSTED", "REJECTED"]
    assert pol.adjustment_statuses_for(pol.KIND_ADJUSTMENT, pol.APPROVED) == ["POSTED"]
    assert pol.adjustment_statuses_for(pol.KIND_REOPEN, None) == []


def test_waiting_days():
    now = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
    assert pol.waiting_days(None, now) is None
    assert pol.waiting_days(now - timedelta(days=2, hours=12), now) == 2.5
    assert pol.waiting_days(now + timedelta(hours=3), now) == 0.0


# ── the policy agrees with the code that actually enforces the rules ──
def test_policy_matches_the_scenario_state_machine():
    assert pol.SPECS[pol.KIND_SCENARIO_REVIEW].maker_checked == {a for a in ("approve",) if a in sm.MAKER_CHECKER}
    assert sm.MAKER_CHECKER["approve"] == "created_by" and "reject" not in sm.MAKER_CHECKER
    reopen = pol.SPECS[pol.KIND_REOPEN]
    assert set(sm.MAKER_CHECKER) >= {"approve_reopen", "deny_reopen"} and reopen.maker_checked == {pol.APPROVE, pol.REJECT}
    assert sm.MAKER_CHECKER["approve_reopen"] == sm.MAKER_CHECKER["deny_reopen"] == "reopen_requested_by"
    for action in ("approve", "reject", "finalize"):
        assert action not in sm.ALLOWED_WHEN_LOCKED
    assert {"approve_reopen", "deny_reopen"} <= sm.ALLOWED_WHEN_LOCKED
    assert pol.SPECS[pol.KIND_SCENARIO_REVIEW].needs_open_period == {pol.APPROVE, pol.REJECT}
    assert pol.SPECS[pol.KIND_FINALIZATION].needs_open_period == {pol.APPROVE} and pol.SPECS[pol.KIND_REOPEN].needs_open_period == set()
    assert pol.SPECS[pol.KIND_SCENARIO_REVIEW].pending_status == "REVIEW_REQUIRED" and pol.SPECS[pol.KIND_FINALIZATION].pending_status == "POSTED"
    assert pol.SPECS[pol.KIND_REOPEN].pending_status == "REOPEN_REQUESTED"
    assert set(pol.SCENARIO_ACTION_OUTCOMES) <= set(sm.TRANSITIONS) | {"approve_reopen"}


API = Path(__file__).resolve().parents[3] / "api" / "src" / "modules"


def _roles(text):
    return set(re.findall(r'"(\w+)"', text))


@pytest.mark.skipif(not (API / "scenarios" / "routes.ts").exists(), reason="api/ not next to engine/")
def test_policy_roles_match_the_roles_the_api_routes_enforce():
    scenarios = (API / "scenarios" / "routes.ts").read_text()
    reviewers = _roles(re.search(r"const REVIEWERS: Role\[\] = \[(.*?)\];", scenarios).group(1))
    finalizers = _roles(re.search(r"const FINALIZERS: Role\[\] = \[(.*?)\];", scenarios).group(1))
    assert pol.SPECS[pol.KIND_SCENARIO_REVIEW].roles == reviewers
    assert pol.SPECS[pol.KIND_FINALIZATION].roles == finalizers and pol.SPECS[pol.KIND_REOPEN].roles == finalizers
    adjustments = (API / "adjustments" / "routes.ts").read_text()
    for route in ("approve", "reject"):
        m = re.search(rf'adjustments/:adjustmentId/{route}",\s*authenticate,\s*requireRole\((.*?)\)', adjustments, re.S)
        assert m and _roles(m.group(1)) == pol.SPECS[pol.KIND_ADJUSTMENT].roles, route