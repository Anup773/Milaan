"""
The exception review state machine -- ARCHITECTURE.md §7, as pure logic (no
database). The one place that knows which action is allowed from which status,
so the repository and the API never re-invent the rules. Same shape as
scenarios/state_machine.py.

    FLAGGED --claim--> UNDER_REVIEW --retain------------------> RETAINED
                          |  ^  |  \\
        request_evidence  |  |  |   +--correct / reverse--> CORRECTION_PENDING --resolve--> RESOLVED
                          v  |  |                                   |
                  EVIDENCE_REQUESTED  +<------reopen---------------+   (reopen also from RETAINED)
              (evidence_received returns it to UNDER_REVIEW)

    Detection (not a person) also moves flags:
        flag      -> FLAGGED       a new finding
        clear     -> CLEARED       the condition is no longer detected (never deleted)
        redetect  -> FLAGGED       a CLEARED finding is detected again

The four decisions a reviewer can make are exactly the ones in §7:
Retain / Correct / Reverse / Request evidence. Correct and Reverse do not
change the books by themselves: they park the flag in CORRECTION_PENDING until
a Phase 7 adjustment (second-person approved) has actually been posted.
"""
from __future__ import annotations

from typing import Dict, FrozenSet, Optional, Tuple

FLAGGED, UNDER_REVIEW, EVIDENCE_REQUESTED = "FLAGGED", "UNDER_REVIEW", "EVIDENCE_REQUESTED"
RETAINED, CORRECTION_PENDING, RESOLVED, CLEARED = "RETAINED", "CORRECTION_PENDING", "RESOLVED", "CLEARED"

ALL_STATUSES: FrozenSet[str] = frozenset({
    FLAGGED, UNDER_REVIEW, EVIDENCE_REQUESTED, RETAINED, CORRECTION_PENDING, RESOLVED, CLEARED,
})

# Still needs a person's attention (or, for CORRECTION_PENDING, the ledger is not yet corrected).
OPEN_STATUSES: FrozenSet[str] = frozenset({FLAGGED, UNDER_REVIEW, EVIDENCE_REQUESTED, CORRECTION_PENDING})

# A detection run may mark these CLEARED when the condition has gone away.
# RETAINED / RESOLVED are decisions a person made and are never touched by detection;
# CORRECTION_PENDING is waiting on an adjustment and is closed by a person (resolve).
CLEARABLE_STATUSES: FrozenSet[str] = frozenset({FLAGGED, UNDER_REVIEW, EVIDENCE_REQUESTED})

# action -> (statuses it may start from, status it ends in)
TRANSITIONS: Dict[str, Tuple[FrozenSet[str], str]] = {
    "claim":             (frozenset({FLAGGED}), UNDER_REVIEW),
    "request_evidence":  (frozenset({UNDER_REVIEW}), EVIDENCE_REQUESTED),
    "evidence_received": (frozenset({EVIDENCE_REQUESTED}), UNDER_REVIEW),
    "retain":            (frozenset({UNDER_REVIEW}), RETAINED),
    "correct":           (frozenset({UNDER_REVIEW}), CORRECTION_PENDING),
    "reverse":           (frozenset({UNDER_REVIEW}), CORRECTION_PENDING),
    "resolve":           (frozenset({CORRECTION_PENDING}), RESOLVED),
    "reopen":            (frozenset({RETAINED, CORRECTION_PENDING}), UNDER_REVIEW),
}

# What detection does by itself (the repository applies these; people cannot call them).
SYSTEM_TRANSITIONS: Dict[str, Tuple[Optional[FrozenSet[str]], str]] = {
    "flag":     (None, FLAGGED),
    "clear":    (CLEARABLE_STATUSES, CLEARED),
    "redetect": (frozenset({CLEARED}), FLAGGED),
}

# The decision recorded on the flag when the action is taken.
DECISION_FOR: Dict[str, str] = {
    "request_evidence": "REQUEST_EVIDENCE",
    "retain": "RETAIN",
    "correct": "CORRECT",
    "reverse": "REVERSE",
}

# Actions that need a written reason. A decision nobody explained is not a review.
NEEDS_NOTE = frozenset({"request_evidence", "evidence_received", "retain", "correct", "reverse", "reopen"})

# Maker-checker: the person who raised a MANUAL flag cannot also decide it.
# (A flag raised by detection has no person to compare against.)
MAKER_CHECKER = frozenset({"retain", "correct", "reverse"})

# Actions that lead to an adjustment, which cannot be proposed in a LOCKED period.
# (Retaining, asking for evidence and closing out paperwork change no ledger figure, so they stay possible.)
REQUIRES_OPEN_PERIOD = frozenset({"correct", "reverse"})


def next_status(action: str, current: str) -> str:
    """The status `action` leads to from `current`, or ValueError if it isn't allowed."""
    if action not in TRANSITIONS:
        raise ValueError(f"unknown action: {action!r}")
    allowed_from, to_status = TRANSITIONS[action]
    if current not in allowed_from:
        raise ValueError(f"cannot {action.replace('_', ' ')} an exception that is {current}")
    return to_status


def available_actions(current: str) -> list:
    return sorted(a for a, (frm, _) in TRANSITIONS.items() if current in frm)


def check_note(action: str, note: Optional[str]) -> None:
    if action in NEEDS_NOTE and not (note and note.strip()):
        raise ValueError(f"a note is required to {action.replace('_', ' ')}")


def check_maker_checker(action: str, actor_id: str, raised_by: Optional[str]) -> None:
    if action in MAKER_CHECKER and raised_by is not None and str(actor_id) == str(raised_by):
        raise ValueError(f"the person who raised this flag cannot also {action.replace('_', ' ')} it")