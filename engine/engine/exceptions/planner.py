"""
Decides what a detection run should DO with its findings -- pure logic, no
database (same split as mapping/planner.py + repository.py), so the rules for
"new / already known / come back / gone" are unit-tested on their own.

Given what the rules found and what is already on file for the period:

  new         a finding with no flag yet                          -> create a FLAGGED flag
  redetected  a finding whose flag was CLEARED earlier            -> back to FLAGGED
  known       a finding that already has a flag in any other state -> leave it as it is (a flag nobody has
              looked at yet, still FLAGGED, gets its wording/figures refreshed from this run)
  to_clear    a flag the rule used to raise, that the rule (which
              ran properly this time) no longer finds, and that
              nobody has decided yet                               -> CLEARED (kept, never deleted)

A person's decision is never overridden by detection: RETAINED, RESOLVED and
CORRECTION_PENDING flags are left alone even if the condition disappears. And a
rule that could not run (NOT_CHECKED or ERROR) clears nothing -- "we couldn't
look" is not "it's gone".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Sequence, Tuple

from .registry import CHECKED, Finding, RuleOutcome
from .state_machine import CLEARABLE_STATUSES, CLEARED


@dataclass(frozen=True)
class ExistingException:
    id: str
    fingerprint: str
    rule_id: str
    source: str   # DETECTED | MANUAL
    status: str


@dataclass
class DetectionPlan:
    new: List[Finding] = field(default_factory=list)
    redetected: List[Tuple[ExistingException, Finding]] = field(default_factory=list)
    known: List[Tuple[ExistingException, Finding]] = field(default_factory=list)
    to_clear: List[ExistingException] = field(default_factory=list)

    @property
    def findings_total(self) -> int:
        return len(self.new) + len(self.redetected) + len(self.known)


def plan_detection(outcomes: Sequence[RuleOutcome], existing: Mapping[str, ExistingException]) -> DetectionPlan:
    """`existing` is keyed by fingerprint."""
    plan = DetectionPlan()
    seen: Dict[str, Finding] = {}
    for outcome in outcomes:
        if outcome.status != CHECKED:
            continue
        for finding in outcome.findings:
            if finding.fingerprint in seen:
                continue  # the same finding twice in one run is still one finding
            seen[finding.fingerprint] = finding
            current = existing.get(finding.fingerprint)
            if current is None:
                plan.new.append(finding)
            elif current.status == CLEARED:
                plan.redetected.append((current, finding))
            else:
                plan.known.append((current, finding))

    ran_properly = {o.rule_id for o in outcomes if o.status == CHECKED}
    for current in existing.values():
        if (current.source == "DETECTED" and current.rule_id in ran_properly
                and current.fingerprint not in seen and current.status in CLEARABLE_STATUSES):
            plan.to_clear.append(current)
    return plan