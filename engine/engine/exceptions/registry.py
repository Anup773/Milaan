"""
The detector registry -- ARCHITECTURE.md §7's "other review flags (open-ended,
rule-extendable)". A detector is a function that takes a DetectionContext and
returns a Detection; registering one function adds a check and nothing else
changes. Same idea, and same rules, as the Phase 11 reconciliation registry:

  * every rule reports an outcome -- CHECKED, NOT_CHECKED or ERROR -- so a check
    that could not run is never mistaken for a check that found nothing;
  * a rule that CRASHES is reported as ERROR ("could not run"), never skipped,
    and runs in its own savepoint so one rule's database error cannot spoil
    the rules after it.

A detector only ever FLAGS. Its wording says "may be" / "appears", never "is a
duplicate" or "is wrong": what a flag means is the reviewer's call (§7 design
principle). Nothing is ever labelled fake or fraudulent.
"""
from __future__ import annotations

import hashlib
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional, Tuple

CATEGORIES = (
    "DUPLICATE_INVOICE", "DUPLICATE_AMOUNT", "MISSING_EVIDENCE", "VENDOR_MISMATCH",
    "UNUSUAL_TRANSACTION", "PERIOD_CUTOFF", "UNSUPPORTED_EXPENSE", "OTHER",
)
PRIORITIES = ("LOW", "MEDIUM", "HIGH")
PRIORITY_RANK = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}

CHECKED, NOT_CHECKED, ERROR = "CHECKED", "NOT_CHECKED", "ERROR"


@dataclass(frozen=True)
class Thresholds:
    """
    Defaults for the detectors. These are starting points, not accounting
    truths: when per-company accounting policy exists (ARCHITECTURE.md §13,
    Phase 22) they belong there. Amounts are in the company's own currency.
    """
    min_amount: Decimal = Decimal("1000.00")        # ignore smaller entries: not worth a reviewer's time
    large_amount: Decimal = Decimal("100000.00")    # at/above this a flag is raised one priority level
    duplicate_window_days: int = 7                  # "same entry again" means within this many days
    unusual_factor: Decimal = Decimal("5")          # a posting this many times the account's typical (median) size
    unusual_high_factor: Decimal = Decimal("10")    # ...and this many times is HIGH priority
    unusual_min_history: int = 5                    # other postings needed on the account before comparing at all


@dataclass(frozen=True)
class Finding:
    rule_id: str
    category: str
    fingerprint: str
    title: str
    message: str
    priority: str
    journal_entry_id: str                  # the entry the flag is about
    related_entry_ids: Tuple[str, ...]     # every entry involved (includes journal_entry_id)
    amount: Optional[Decimal]
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Detection:
    """What a detector returns: findings, or the reason it could not check anything."""
    findings: Tuple[Finding, ...] = ()
    not_checked_reason: Optional[str] = None


def found(findings: List[Finding]) -> Detection:
    return Detection(findings=tuple(findings))


def not_checked(reason: str) -> Detection:
    return Detection(not_checked_reason=reason)


@dataclass(frozen=True)
class RuleOutcome:
    rule_id: str
    category: str
    title: str
    status: str                      # CHECKED | NOT_CHECKED | ERROR
    message: str
    findings: Tuple[Finding, ...] = ()


@dataclass(frozen=True)
class Detector:
    id: str
    category: str
    title: str
    description: str
    fn: Callable[["DetectionContext"], Detection]


DETECTORS: Dict[str, Detector] = {}


def register_detector(rule_id: str, category: str, title: str, description: str):
    """Decorator: @register_detector("id", "CATEGORY", "Title", "What it looks for") on a function(ctx) -> Detection."""
    if category not in CATEGORIES:
        raise ValueError(f"unknown category {category!r}; must be one of {CATEGORIES}")
    if rule_id == "manual":
        raise ValueError("'manual' is reserved for flags a person raises")

    def wrap(fn: Callable[["DetectionContext"], Detection]):
        if rule_id in DETECTORS:
            raise ValueError(f"detector {rule_id!r} is already registered")
        DETECTORS[rule_id] = Detector(rule_id, category, title, description, fn)
        return fn

    return wrap


def make_fingerprint(rule_id: str, *parts: Any) -> str:
    """A stable key for one exact finding: same rule + same entries/inputs => same key, every run."""
    digest = hashlib.sha256("\x1f".join([rule_id, *map(str, parts)]).encode("utf-8")).hexdigest()[:32]
    return f"{rule_id}:{digest}"


class DetectionContext:
    """
    What a detector gets to look at: the period, the thresholds, today's date,
    and the ledger as an EntryDataset (read once, only if a rule asks). Pass
    `dataset=` to run detectors with no database at all (the unit tests do).
    """

    def __init__(self, conn, company_id: str, period_id: str, today: Optional[date] = None,
                 thresholds: Optional[Thresholds] = None, dataset=None) -> None:
        self.conn = conn
        self.company_id = company_id
        self.period_id = period_id
        self.today = today or date.today()
        self.thresholds = thresholds or Thresholds()
        self._dataset = dataset

    @property
    def dataset(self):
        if self._dataset is None:
            from .dataset import load_dataset
            self._dataset = load_dataset(self.conn, self.company_id, self.period_id)
        return self._dataset

    @contextmanager
    def savepoint(self) -> Iterator[None]:
        """Run a rule so a database error rolls back only that rule's work."""
        if self.conn is None:
            yield
            return
        with self.conn.transaction():
            yield


def run_detectors(ctx: DetectionContext, rule_ids: Optional[List[str]] = None) -> List[RuleOutcome]:
    ids = list(DETECTORS) if rule_ids is None else rule_ids
    for rid in ids:
        if rid not in DETECTORS:
            raise ValueError(f"unknown rule: {rid!r}")

    outcomes: List[RuleOutcome] = []
    for rid in ids:
        det = DETECTORS[rid]
        try:
            with ctx.savepoint():
                out = det.fn(ctx)
            if not isinstance(out, Detection):
                raise TypeError("a detector must return a Detection")
            for f in out.findings:
                if f.rule_id != det.id or f.category != det.category:
                    raise ValueError(f"finding {f.fingerprint!r} does not belong to rule {det.id!r}")
                if f.priority not in PRIORITIES:
                    raise ValueError(f"finding has unknown priority {f.priority!r}")
                if f.journal_entry_id not in f.related_entry_ids:
                    raise ValueError("a finding's related entries must include the entry it is about")
            if out.not_checked_reason is not None:
                if out.findings:
                    raise ValueError("a rule that was not checked cannot also report findings")
                outcomes.append(RuleOutcome(det.id, det.category, det.title, NOT_CHECKED, out.not_checked_reason))
            else:
                n = len(out.findings)
                msg = "Nothing flagged." if n == 0 else f"{n} item(s) flagged for review."
                outcomes.append(RuleOutcome(det.id, det.category, det.title, CHECKED, msg, out.findings))
        except Exception as exc:  # noqa: BLE001 -- a crashing check must show up, never vanish
            outcomes.append(RuleOutcome(det.id, det.category, det.title, ERROR, f"this check could not run: {exc}"))
    return outcomes


def catalog() -> List[Dict[str, str]]:
    return [{"id": d.id, "category": d.category, "title": d.title, "description": d.description}
            for d in DETECTORS.values()]