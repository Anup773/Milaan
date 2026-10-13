"""
Phase 14 approval policy -- pure logic, no database.

Four kinds of thing wait for somebody's decision in Milaan, each already
implemented by an earlier phase. This module is the one place that says, for
each of them, WHICH decisions exist, WHO may take them, and WHICH second-person
rule applies -- mirroring exactly what the earlier phases enforce, so the
approvals inbox can tell a person up front "you can approve this" or "you
can't, because you proposed it", instead of letting them find out by failing.

  scenario_review   REVIEW_REQUIRED scenario        approve / reject   (Phase 9)
  finalization      POSTED scenario                 approve = finalize (Phase 9)
  reopen_request    REOPEN_REQUESTED scenario       approve / reject   (Phase 9, ARCHITECTURE.md §5)
  adjustment        REVIEW_REQUIRED adjustment      approve / reject   (Phase 7)

The role lists below are the ones the Node routes use (scenarios/routes.ts,
adjustments/routes.ts); tests/test_approval_policy.py reads those files and
fails if the two ever drift apart.

Rejecting always needs a written reason through this module (a decision nobody
explained is not a review), even where an older endpoint allowed a bare reject.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, FrozenSet, List, Optional, Tuple

KIND_SCENARIO_REVIEW = "scenario_review"
KIND_FINALIZATION = "finalization"
KIND_REOPEN = "reopen_request"
KIND_ADJUSTMENT = "adjustment"
KINDS: Tuple[str, ...] = (KIND_SCENARIO_REVIEW, KIND_FINALIZATION, KIND_REOPEN, KIND_ADJUSTMENT)

APPROVE, REJECT = "approve", "reject"

ROLES: Tuple[str, ...] = ("accountant", "senior_accountant", "ca", "reviewer", "admin")

APPROVED, REJECTED, FINALIZED = "APPROVED", "REJECTED", "FINALIZED"
OUTCOMES: Tuple[str, ...] = (APPROVED, REJECTED, FINALIZED)


@dataclass(frozen=True)
class KindSpec:
    kind: str
    label: str
    pending_status: str                       # the status of the thing while it waits
    decisions: Tuple[str, ...]
    roles: FrozenSet[str]                     # who may take part in this decision at all
    maker_checked: FrozenSet[str]             # decisions the person who made it may NOT take
    needs_open_period: FrozenSet[str]         # decisions that cannot be taken while the period is LOCKED
    maker_phrase: str                         # for the message: "you <phrase> this"


SPECS: Dict[str, KindSpec] = {
    KIND_SCENARIO_REVIEW: KindSpec(
        KIND_SCENARIO_REVIEW, "Scenario review", "REVIEW_REQUIRED", (APPROVE, REJECT),
        frozenset({"reviewer", "ca", "admin"}), frozenset({APPROVE}), frozenset({APPROVE, REJECT}),
        "created this scenario"),
    KIND_FINALIZATION: KindSpec(
        KIND_FINALIZATION, "Finalisation", "POSTED", (APPROVE,),
        frozenset({"ca", "admin"}), frozenset(), frozenset({APPROVE}),
        "created this scenario"),
    KIND_REOPEN: KindSpec(
        KIND_REOPEN, "Reopen request", "REOPEN_REQUESTED", (APPROVE, REJECT),
        frozenset({"ca", "admin"}), frozenset({APPROVE, REJECT}), frozenset(),
        "requested this reopen"),
    KIND_ADJUSTMENT: KindSpec(
        KIND_ADJUSTMENT, "Adjustment", "REVIEW_REQUIRED", (APPROVE, REJECT),
        frozenset({"senior_accountant", "ca", "reviewer", "admin"}), frozenset({APPROVE, REJECT}), frozenset({APPROVE}),
        "proposed this adjustment"),
}

# What each earlier-phase transition counts as in the decision history.
SCENARIO_ACTION_OUTCOMES: Dict[str, Tuple[str, str]] = {
    "approve": (KIND_SCENARIO_REVIEW, APPROVED),
    "reject": (KIND_SCENARIO_REVIEW, REJECTED),
    "finalize": (KIND_FINALIZATION, FINALIZED),
    "approve_reopen": (KIND_REOPEN, APPROVED),
    "deny_reopen": (KIND_REOPEN, REJECTED),
}
ADJUSTMENT_STATUS_OUTCOMES: Dict[str, str] = {"POSTED": APPROVED, "REJECTED": REJECTED}


def spec_for(kind: str) -> KindSpec:
    if kind not in SPECS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    return SPECS[kind]


def check_decision(kind: str, decision: str) -> None:
    spec = spec_for(kind)
    if decision not in spec.decisions:
        raise ValueError(f"a {spec.label.lower()} can only be: {', '.join(spec.decisions)} (got {decision!r})")


def permission_reasons(kind: str, decision: str, *, actor_id: str, actor_role: str, maker_id: Optional[str]) -> List[str]:
    """Reasons this PERSON may not take this decision: their role, or the second-person rule. Empty = allowed."""
    spec = spec_for(kind)
    check_decision(kind, decision)
    reasons: List[str] = []
    if actor_role not in spec.roles:
        reasons.append(f"your role ({actor_role}) cannot {decision} a {spec.label.lower()}; "
                       f"allowed roles: {', '.join(sorted(spec.roles))}")
    if decision in spec.maker_checked and maker_id is not None and str(actor_id) == str(maker_id):
        reasons.append(f"you {spec.maker_phrase}, so someone else must {decision} it")
    return reasons


def state_reasons(kind: str, decision: str, *, period_locked: bool) -> List[str]:
    """Reasons the decision cannot be taken by ANYONE right now (as opposed to by this person)."""
    spec = spec_for(kind)
    check_decision(kind, decision)
    if period_locked and decision in spec.needs_open_period:
        return ["the accounting period is LOCKED; it must be reopened before this can be done"]
    return []


def blocking_reasons(kind: str, decision: str, *, actor_id: str, actor_role: str, maker_id: Optional[str],
                     period_locked: bool) -> List[str]:
    """Everything standing between this person and this decision. An empty list means they can take it."""
    return (permission_reasons(kind, decision, actor_id=actor_id, actor_role=actor_role, maker_id=maker_id)
            + state_reasons(kind, decision, period_locked=period_locked))


def check_note(decision: str, note: Optional[str]) -> None:
    if decision == REJECT and not (note and note.strip()):
        raise ValueError("a note explaining the rejection is required")


def waiting_days(since: Optional[datetime], now: datetime) -> Optional[float]:
    """How long something has been waiting, in days to one decimal place (never negative)."""
    if since is None:
        return None
    return max(0.0, round((now - since).total_seconds() / 86400, 1))


def actions_for(kind: Optional[str], outcome: Optional[str]) -> List[str]:
    """The scenario transitions that count as a decision of this kind/outcome (None = any)."""
    return sorted(a for a, (k, o) in SCENARIO_ACTION_OUTCOMES.items()
                  if (kind is None or k == kind) and (outcome is None or o == outcome))


def adjustment_statuses_for(kind: Optional[str], outcome: Optional[str]) -> List[str]:
    if kind not in (None, KIND_ADJUSTMENT):
        return []
    return sorted(s for s, o in ADJUSTMENT_STATUS_OUTCOMES.items() if outcome is None or o == outcome)