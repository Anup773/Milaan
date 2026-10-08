"""
The reconciliation framework -- ARCHITECTURE.md §7. A registry of rules;
each rule looks at the books and answers with one of four statuses, and no
answer is ever hidden:

    PASS         checked, and it agrees
    WARNING      checked, and something deserves a person's attention
    ERROR        checked, and the books disagree with themselves
    NOT_CHECKED  could not be checked (e.g. the company has no fixed assets)

A rule is a function that takes a ReconContext and returns a RuleResult.
Adding a check means registering one function; nothing else changes.

A rule that CRASHES is reported as ERROR ("could not run"), never skipped:
a check that fails to run must not look like a check that passed. Each rule
runs inside its own savepoint, so one rule's database error cannot spoil
the rules after it.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional

PASS, WARNING, ERROR, NOT_CHECKED = "PASS", "WARNING", "ERROR", "NOT_CHECKED"
STATUSES = (PASS, WARNING, ERROR, NOT_CHECKED)


@dataclass(frozen=True)
class RuleResult:
    rule_id: str
    title: str
    status: str
    message: str
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Rule:
    id: str
    title: str
    description: str
    scope: str  # 'ledger' (the books as posted) or 'scenario' (also respects what-if figures)
    fn: Callable[["ReconContext"], RuleResult]


RULES: Dict[str, Rule] = {}


def register_rule(rule_id: str, title: str, description: str, scope: str = "ledger"):
    """Decorator: @register_rule("id", "Title", "What it checks") on a function(ctx) -> RuleResult."""
    if scope not in ("ledger", "scenario"):
        raise ValueError("scope must be 'ledger' or 'scenario'")

    def wrap(fn: Callable[["ReconContext"], RuleResult]):
        if rule_id in RULES:
            raise ValueError(f"rule {rule_id!r} is already registered")
        RULES[rule_id] = Rule(rule_id, title, description, scope, fn)
        return fn

    return wrap


class ReconContext:
    """
    What a rule gets to look at: the database connection, the company and
    period, and (for scenario-aware rules) the dependency-graph model with
    any what-if `overrides` applied. The model is built only if a rule asks.
    """

    def __init__(self, conn, company_id: str, period_id: str,
                 overrides: Optional[Mapping[str, Decimal]] = None, model=None) -> None:
        self.conn = conn
        self.company_id = company_id
        self.period_id = period_id
        self.overrides = dict(overrides) if overrides else {}
        self._model = model
        self._values: Optional[Dict[str, Decimal]] = None
        self._dates = None

    @property
    def has_overrides(self) -> bool:
        return bool(self.overrides)

    @property
    def model(self):
        if self._model is None:
            from ..dependency_graph import build_ledger_model
            self._model = build_ledger_model(self.conn, self.company_id, self.period_id)
        return self._model

    def values(self) -> Dict[str, Decimal]:
        if self._values is None:
            self._values = self.model.evaluate(self.overrides)
        return self._values

    @property
    def period(self):
        """(period_start, period_end, label)"""
        if self._dates is None:
            from ..ledger.reports import _period_dates
            self._dates = _period_dates(self.conn, self.company_id, self.period_id)
        return self._dates

    @contextmanager
    def savepoint(self) -> Iterator[None]:
        """Run a rule so a database error rolls back only that rule's work."""
        if self.conn is None:
            yield
            return
        with self.conn.transaction():
            yield


def result(rule_id: str, status: str, message: str, **details: Any) -> RuleResult:
    """Convenience for rules: result(RULE_ID, PASS, 'text', key=value, ...) -- title is filled in by the runner."""
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}")
    return RuleResult(rule_id=rule_id, title="", status=status, message=message, details=details)


def run_rules(ctx: ReconContext, rule_ids: Optional[List[str]] = None) -> List[RuleResult]:
    ids = list(RULES) if rule_ids is None else rule_ids
    for rid in ids:
        if rid not in RULES:
            raise ValueError(f"unknown rule: {rid!r}")

    results: List[RuleResult] = []
    for rid in ids:
        rule = RULES[rid]
        try:
            with ctx.savepoint():
                out = rule.fn(ctx)
            if out.status not in STATUSES:
                raise ValueError(f"rule returned unknown status {out.status!r}")
            results.append(RuleResult(rule.id, rule.title, out.status, out.message, dict(out.details)))
        except Exception as exc:  # noqa: BLE001 -- a crashing check must show up, never vanish
            results.append(RuleResult(rule.id, rule.title, ERROR, f"this check could not run: {exc}", {"crashed": True}))
    return results


def summarize(results: List[RuleResult]) -> Dict[str, Any]:
    """Counts per status and the overall verdict: ERROR beats WARNING beats PASS.
    NOT_CHECKED does not by itself spoil a PASS (a company with no fixed assets
    simply has no fixed-asset check to run) but it is always counted and shown."""
    counts = {s: 0 for s in STATUSES}
    for r in results:
        counts[r.status] += 1
    overall = ERROR if counts[ERROR] else WARNING if counts[WARNING] else PASS
    return {"overall_status": overall, "counts": counts}


def catalog() -> List[Dict[str, str]]:
    return [{"id": r.id, "title": r.title, "description": r.description, "scope": r.scope} for r in RULES.values()]