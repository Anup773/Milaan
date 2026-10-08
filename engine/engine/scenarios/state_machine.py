"""
The scenario state machine -- ARCHITECTURE.md §5, as pure logic (no
database). The one place that knows which action is allowed from which
status, so the repository and the API never re-invent the rules.

    DRAFT --simulate--> SIMULATED --submit--> REVIEW_REQUIRED
      ^                    |                    |  \\
      +------revise--------+      reject (back to DRAFT)   approve
                                                              v
    POSTED <--post-- APPROVED          (needs approved Phase 7 adjustments)
      |
    finalize --> FINALIZED --(automatic, same step)--> LOCKED
                                                         |
                       deny <-- REOPEN_REQUESTED <--request_reopen
                       approve_reopen: period reopens, a NEW DRAFT version
                       is created, the locked version is kept, never edited.

DRAFT, SIMULATED and REVIEW_REQUIRED scenarios can be discarded. There is
no action that goes from a draft straight to POSTED: every scenario must
pass REVIEW_REQUIRED, seen by a second person.
"""
from __future__ import annotations

from typing import Dict, FrozenSet, Optional, Tuple

DRAFT, SIMULATED, REVIEW_REQUIRED, APPROVED, POSTED = "DRAFT", "SIMULATED", "REVIEW_REQUIRED", "APPROVED", "POSTED"
FINALIZED, LOCKED, REOPEN_REQUESTED, DISCARDED = "FINALIZED", "LOCKED", "REOPEN_REQUESTED", "DISCARDED"

ALL_STATUSES: FrozenSet[str] = frozenset({
    DRAFT, SIMULATED, REVIEW_REQUIRED, APPROVED, POSTED, FINALIZED, LOCKED, REOPEN_REQUESTED, DISCARDED,
})

# action -> (statuses it may start from, status it ends in)
TRANSITIONS: Dict[str, Tuple[FrozenSet[str], str]] = {
    "simulate":       (frozenset({DRAFT, SIMULATED}), SIMULATED),
    "revise":         (frozenset({SIMULATED}), DRAFT),
    "submit":         (frozenset({SIMULATED}), REVIEW_REQUIRED),
    "approve":        (frozenset({REVIEW_REQUIRED}), APPROVED),
    "reject":         (frozenset({REVIEW_REQUIRED}), DRAFT),
    "post":           (frozenset({APPROVED}), POSTED),
    "finalize":       (frozenset({POSTED}), FINALIZED),      # then auto-locks: see AUTO_NEXT
    "discard":        (frozenset({DRAFT, SIMULATED, REVIEW_REQUIRED}), DISCARDED),
    "request_reopen": (frozenset({LOCKED}), REOPEN_REQUESTED),
    "deny_reopen":    (frozenset({REOPEN_REQUESTED}), LOCKED),
    "approve_reopen": (frozenset({REOPEN_REQUESTED}), LOCKED),  # stays locked + superseded; new DRAFT version made
}

# A status that immediately continues to another in the same step.
AUTO_NEXT: Dict[str, str] = {FINALIZED: LOCKED}

# Actions that need a written reason / note.
NEEDS_NOTE = frozenset({"reject", "request_reopen", "deny_reopen"})

# Actions where the person acting must differ from the person who made the
# thing being decided (maker-checker). value = which earlier actor to compare to.
MAKER_CHECKER: Dict[str, str] = {
    "approve": "created_by",
    "approve_reopen": "reopen_requested_by",
    "deny_reopen": "reopen_requested_by",
}

# Actions allowed while the period is LOCKED (everything else needs it OPEN).
ALLOWED_WHEN_LOCKED = frozenset({"discard", "request_reopen", "deny_reopen", "approve_reopen"})


def next_status(action: str, current: str) -> str:
    """The status `action` leads to from `current`, or ValueError if it isn't allowed."""
    if action not in TRANSITIONS:
        raise ValueError(f"unknown action: {action!r}")
    allowed_from, to_status = TRANSITIONS[action]
    if current not in allowed_from:
        raise ValueError(f"cannot {action.replace('_', ' ')} a scenario that is {current}")
    return to_status


def available_actions(current: str) -> list:
    return sorted(a for a, (frm, _) in TRANSITIONS.items() if current in frm)


def check_maker_checker(action: str, actor_id: str, earlier_actor_id: Optional[str]) -> None:
    if action in MAKER_CHECKER and earlier_actor_id is not None and str(actor_id) == str(earlier_actor_id):
        raise ValueError(f"the person who {'created' if action == 'approve' else 'requested the reopen of'} this scenario cannot also {action.replace('_', ' ')} it")


def check_note(action: str, note: Optional[str]) -> None:
    if action in NEEDS_NOTE and not (note and note.strip()):
        raise ValueError(f"a note/reason is required to {action.replace('_', ' ')}")