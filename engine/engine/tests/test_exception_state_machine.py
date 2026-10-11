
"""Pure-logic tests for engine.exceptions.state_machine -- no database."""
import pytest

from engine.exceptions import state_machine as sm


def walk(start, *actions):
    status = start
    for a in actions:
        status = sm.next_status(a, status)
    return status


def test_review_path_to_retained():
    assert walk("FLAGGED", "claim", "retain") == "RETAINED"


def test_nothing_is_decided_before_someone_claims_it():
    for action in ("retain", "correct", "reverse", "request_evidence", "resolve"):
        with pytest.raises(ValueError, match="FLAGGED"):
            sm.next_status(action, "FLAGGED")


def test_request_evidence_round_trip():
    assert walk("FLAGGED", "claim", "request_evidence") == "EVIDENCE_REQUESTED"
    assert walk("FLAGGED", "claim", "request_evidence", "evidence_received") == "UNDER_REVIEW"


def test_cannot_decide_while_waiting_for_evidence():
    for action in ("retain", "correct", "reverse"):
        with pytest.raises(ValueError):
            sm.next_status(action, "EVIDENCE_REQUESTED")


def test_correct_and_reverse_only_park_the_flag_until_an_adjustment_is_posted():
    assert walk("UNDER_REVIEW", "correct") == "CORRECTION_PENDING"
    assert walk("UNDER_REVIEW", "reverse") == "CORRECTION_PENDING"
    assert walk("UNDER_REVIEW", "reverse", "resolve") == "RESOLVED"


def test_resolve_only_from_correction_pending():
    for s in ("FLAGGED", "UNDER_REVIEW", "EVIDENCE_REQUESTED", "RETAINED", "RESOLVED", "CLEARED"):
        with pytest.raises(ValueError):
            sm.next_status("resolve", s)


def test_reopen_from_retained_or_correction_pending_only():
    assert sm.next_status("reopen", "RETAINED") == "UNDER_REVIEW"
    assert sm.next_status("reopen", "CORRECTION_PENDING") == "UNDER_REVIEW"
    for s in ("FLAGGED", "UNDER_REVIEW", "EVIDENCE_REQUESTED", "RESOLVED", "CLEARED"):
        with pytest.raises(ValueError):
            sm.next_status("reopen", s)


def test_resolved_and_cleared_are_terminal_for_people():
    for s in ("RESOLVED", "CLEARED"):
        assert sm.available_actions(s) == []


def test_detection_only_actions_cannot_be_called_by_people():
    for action in ("flag", "clear", "redetect"):
        with pytest.raises(ValueError, match="unknown action"):
            sm.next_status(action, "FLAGGED")


def test_detection_may_only_clear_flags_nobody_has_decided():
    assert sm.CLEARABLE_STATUSES == {"FLAGGED", "UNDER_REVIEW", "EVIDENCE_REQUESTED"}
    for decided in ("RETAINED", "CORRECTION_PENDING", "RESOLVED"):
        assert decided not in sm.CLEARABLE_STATUSES


def test_open_statuses():
    assert sm.OPEN_STATUSES == {"FLAGGED", "UNDER_REVIEW", "EVIDENCE_REQUESTED", "CORRECTION_PENDING"}


def test_the_four_decisions_of_section_7():
    assert set(sm.DECISION_FOR.values()) == {"RETAIN", "CORRECT", "REVERSE", "REQUEST_EVIDENCE"}


def test_notes_required_where_declared():
    for action in ("request_evidence", "evidence_received", "retain", "correct", "reverse", "reopen"):
        for blank in (None, "", "   "):
            with pytest.raises(ValueError, match="note is required"):
                sm.check_note(action, blank)
        sm.check_note(action, "because")
    sm.check_note("claim", None)
    sm.check_note("resolve", None)


def test_maker_checker_applies_to_decisions_on_manual_flags_only():
    for action in ("retain", "correct", "reverse"):
        with pytest.raises(ValueError, match="cannot also"):
            sm.check_maker_checker(action, "u1", "u1")
        sm.check_maker_checker(action, "u2", "u1")
        sm.check_maker_checker(action, "u1", None)  # detected flag: nobody to compare against
    sm.check_maker_checker("claim", "u1", "u1")


def test_only_actions_that_lead_to_an_adjustment_need_an_open_period():
    assert sm.REQUIRES_OPEN_PERIOD == {"correct", "reverse"}


def test_every_transition_uses_known_statuses_and_decision_actions_are_transitions():
    for _, (frm, to) in sm.TRANSITIONS.items():
        assert to in sm.ALL_STATUSES and frm <= sm.ALL_STATUSES
    assert set(sm.DECISION_FOR) <= set(sm.TRANSITIONS)
    assert sm.MAKER_CHECKER <= set(sm.TRANSITIONS) and sm.NEEDS_NOTE <= set(sm.TRANSITIONS)


def test_available_actions():
    assert sm.available_actions("FLAGGED") == ["claim"]
    assert sm.available_actions("UNDER_REVIEW") == ["correct", "request_evidence", "retain", "reverse"]