"""Pure-logic tests for engine.exceptions.planner -- no database."""
from engine.exceptions.planner import ExistingException, plan_detection
from engine.exceptions.registry import CHECKED, ERROR, NOT_CHECKED, Finding, RuleOutcome


def finding(rule, key, entry="e1"):
    return Finding(rule_id=rule, category="OTHER", fingerprint=f"{rule}:{key}", title="t", message="m", priority="LOW",
                   journal_entry_id=entry, related_entry_ids=(entry,), amount=None)


def outcome(rule, status=CHECKED, *findings):
    return RuleOutcome(rule, "OTHER", rule, status, "m", tuple(findings))


def ex(rule, key, status="FLAGGED", source="DETECTED"):
    return ExistingException(f"id-{rule}-{key}", f"{rule}:{key}", rule, source, status)


def existing(*items):
    return {i.fingerprint: i for i in items}


def test_a_finding_with_no_flag_is_new():
    plan = plan_detection([outcome("r", CHECKED, finding("r", "a"))], {})
    assert [f.fingerprint for f in plan.new] == ["r:a"] and plan.findings_total == 1


def test_a_finding_that_already_has_a_flag_is_known_whatever_state_it_is_in():
    for status in ("FLAGGED", "UNDER_REVIEW", "EVIDENCE_REQUESTED", "RETAINED", "CORRECTION_PENDING", "RESOLVED"):
        plan = plan_detection([outcome("r", CHECKED, finding("r", "a"))], existing(ex("r", "a", status)))
        assert plan.new == [] and [c.status for c, _ in plan.known] == [status] and plan.to_clear == []


def test_a_cleared_flag_that_is_detected_again_is_redetected_not_duplicated():
    plan = plan_detection([outcome("r", CHECKED, finding("r", "a"))], existing(ex("r", "a", "CLEARED")))
    assert plan.new == [] and len(plan.redetected) == 1 and plan.known == []


def test_a_flag_whose_condition_is_gone_is_cleared_if_nobody_decided_it():
    for status in ("FLAGGED", "UNDER_REVIEW", "EVIDENCE_REQUESTED"):
        plan = plan_detection([outcome("r", CHECKED)], existing(ex("r", "a", status)))
        assert [c.status for c in plan.to_clear] == [status]


def test_a_persons_decision_is_never_overridden_by_detection():
    for status in ("RETAINED", "CORRECTION_PENDING", "RESOLVED", "CLEARED"):
        assert plan_detection([outcome("r", CHECKED)], existing(ex("r", "a", status))).to_clear == []


def test_a_rule_that_could_not_run_clears_nothing():
    for status in (NOT_CHECKED, ERROR):
        assert plan_detection([outcome("r", status)], existing(ex("r", "a"))).to_clear == []


def test_a_manual_flag_is_never_cleared_by_detection():
    assert plan_detection([outcome("r", CHECKED)], existing(ex("manual", "x", source="MANUAL"))).to_clear == []


def test_only_the_rule_that_ran_clears_its_own_flags():
    plan = plan_detection([outcome("r1", CHECKED), outcome("r2", NOT_CHECKED)], existing(ex("r1", "a"), ex("r2", "b")))
    assert [c.rule_id for c in plan.to_clear] == ["r1"]


def test_the_same_finding_twice_in_one_run_is_one_finding():
    plan = plan_detection([outcome("r", CHECKED, finding("r", "a"), finding("r", "a"))], {})
    assert len(plan.new) == 1
