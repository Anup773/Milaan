"""Pure-logic tests for engine.scenarios.state_machine -- no database."""
import pytest

from engine.scenarios import state_machine as sm


def walk(start, *actions):
    status = start
    for a in actions:
        status = sm.next_status(a, status)
    return status


def test_happy_path_to_posted():
    assert walk("DRAFT", "simulate", "submit", "approve", "post") == "POSTED"


def test_finalize_ends_in_finalized_and_auto_locks():
    assert sm.next_status("finalize", "POSTED") == "FINALIZED"
    assert sm.AUTO_NEXT["FINALIZED"] == "LOCKED"


def test_no_path_from_draft_straight_to_posted():
    for action in sm.TRANSITIONS:
        for start in ("DRAFT", "SIMULATED"):
            try:
                assert sm.next_status(action, start) != "POSTED"
            except ValueError:
                pass


def test_every_scenario_must_pass_review_required_before_approved():
    with pytest.raises(ValueError):
        sm.next_status("approve", "SIMULATED")
    with pytest.raises(ValueError):
        sm.next_status("approve", "DRAFT")


def test_cannot_post_unless_approved():
    for s in ("DRAFT", "SIMULATED", "REVIEW_REQUIRED", "POSTED", "LOCKED"):
        with pytest.raises(ValueError):
            sm.next_status("post", s)


def test_reject_sends_back_to_draft_and_it_can_run_again():
    assert walk("REVIEW_REQUIRED", "reject") == "DRAFT"
    assert walk("REVIEW_REQUIRED", "reject", "simulate") == "SIMULATED"


def test_revise_returns_a_simulated_scenario_to_draft():
    assert walk("SIMULATED", "revise") == "DRAFT"


def test_can_resimulate():
    assert walk("SIMULATED", "simulate") == "SIMULATED"


def test_discard_only_before_approval():
    for s in ("DRAFT", "SIMULATED", "REVIEW_REQUIRED"):
        assert sm.next_status("discard", s) == "DISCARDED"
    for s in ("APPROVED", "POSTED", "FINALIZED", "LOCKED", "REOPEN_REQUESTED", "DISCARDED"):
        with pytest.raises(ValueError):
            sm.next_status("discard", s)


def test_discarded_is_terminal():
    for action in sm.TRANSITIONS:
        with pytest.raises(ValueError):
            sm.next_status(action, "DISCARDED")


def test_reopen_cycle():
    assert walk("LOCKED", "request_reopen") == "REOPEN_REQUESTED"
    assert walk("LOCKED", "request_reopen", "deny_reopen") == "LOCKED"
    assert walk("LOCKED", "request_reopen", "approve_reopen") == "LOCKED"


def test_cannot_request_reopen_unless_locked():
    for s in ("DRAFT", "POSTED", "FINALIZED", "REOPEN_REQUESTED"):
        with pytest.raises(ValueError):
            sm.next_status("request_reopen", s)


def test_locked_scenario_cannot_be_edited_by_normal_actions():
    for action in ("simulate", "submit", "approve", "reject", "post", "finalize", "revise"):
        with pytest.raises(ValueError):
            sm.next_status(action, "LOCKED")


def test_unknown_action_rejected():
    with pytest.raises(ValueError):
        sm.next_status("teleport", "DRAFT")


def test_error_message_names_the_status():
    with pytest.raises(ValueError, match="REVIEW_REQUIRED"):
        sm.next_status("post", "REVIEW_REQUIRED")


def test_maker_checker_blocks_same_person():
    with pytest.raises(ValueError):
        sm.check_maker_checker("approve", "u1", "u1")
    sm.check_maker_checker("approve", "u2", "u1")
    with pytest.raises(ValueError):
        sm.check_maker_checker("approve_reopen", "u1", "u1")
    with pytest.raises(ValueError):
        sm.check_maker_checker("deny_reopen", "u1", "u1")


def test_notes_required_where_declared():
    for action in ("reject", "request_reopen", "deny_reopen"):
        with pytest.raises(ValueError):
            sm.check_note(action, "   ")
        with pytest.raises(ValueError):
            sm.check_note(action, None)
        sm.check_note(action, "because")
    sm.check_note("approve", None)  # optional there


def test_available_actions_for_a_status():
    assert sm.available_actions("DRAFT") == ["discard", "simulate"]
    assert sm.available_actions("LOCKED") == ["request_reopen"]
    assert sm.available_actions("DISCARDED") == []


def test_every_status_is_known():
    for _, (frm, to) in sm.TRANSITIONS.items():
        assert to in sm.ALL_STATUSES and frm <= sm.ALL_STATUSES