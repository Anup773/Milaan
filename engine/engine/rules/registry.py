"""
The rules registry -- ARCHITECTURE.md §12. Rule sets (accounting, auditing, tax, compliance) get their own
extensible home instead of `if depreciation... if tax...` logic scattered through the engine. A rule set is
DATA: it names a standard or regime, says where it applies, and lists the requirements in it. The engine asks
the registry which sets apply to a company (`applicable`) and which of Milaan's existing checks bear on them
(`checks_for`); adding a standard or a country means registering one more rule set and nothing else changes.

What this is NOT (the §12 scope boundary): Milaan does not implement or certify IFRS, ISA, any tax or
jurisdiction law, or ISO/IEC 27001. Most rule sets here are CATALOG_ONLY: they say what exists and that
Milaan does not check it yet. A rule item claims coverage only where an existing, named check really does
it, and the tests prove every named check exists:

    FULL     a Milaan check tests this requirement itself
    PARTIAL  a Milaan check bears on it but does not test all of it (the note says what is left)
    NONE     nothing in Milaan tests it yet (no checks listed)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

FAMILIES: Tuple[str, ...] = ("accounting", "auditing", "tax", "compliance")
FAMILY_INFO: Dict[str, Dict[str, str]] = {
    "accounting": {"title": "Accounting", "description": "Financial reporting standards and local GAAP: how transactions are recognised, measured and presented."},
    "auditing": {"title": "Auditing", "description": "Auditing standards: how an audit is planned, evidenced and documented. These are not accounting standards."},
    "tax": {"title": "Tax", "description": "GST, VAT, income tax and other jurisdiction-specific tax rules."},
    "compliance": {"title": "Compliance", "description": "Internal controls and other local or regulatory requirements."},
}

ACTIVE, CATALOG_ONLY = "ACTIVE", "CATALOG_ONLY"
STATUSES = (ACTIVE, CATALOG_ONLY)
FULL, PARTIAL, NONE = "FULL", "PARTIAL", "NONE"
COVERAGES = (FULL, PARTIAL, NONE)

# A rule set that applies in every jurisdiction / under every framework says so with these.
INTERNATIONAL = "INTL"
ANY_FRAMEWORK = "ANY"

# The kinds of existing Milaan check a rule item may point at, and where each is registered.
CHECK_KINDS = ("reconciliation", "exception", "feature")
# Controls that are product features rather than registered checks. Each is real and in the product today.
FEATURES: Dict[str, str] = {
    "approval_workflow": "Approval workflow: a change reaches the books only after the required approvals",
    "period_locking": "Period locking: a finalised period is locked and can only be reopened with approval",
    "audit_trail": "Audit trail: every change is recorded in an append-only log",
}

NOTICE = (
    "This is a catalog of what exists and what Milaan checks today. Milaan does not implement or certify IFRS, "
    "ISA, tax or jurisdiction-specific law, or ISO/IEC 27001. Where a requirement shows no check, nothing in "
    "Milaan tests it yet."
)


@dataclass(frozen=True)
class CheckRef:
    kind: str  # one of CHECK_KINDS
    id: str


@dataclass(frozen=True)
class RuleItem:
    id: str
    title: str
    description: str
    coverage: str = NONE
    checks: Tuple[CheckRef, ...] = ()
    reference: str = ""  # the clause or section in the source, e.g. "IAS 16"
    note: str = ""       # what the listed checks do not cover


@dataclass(frozen=True)
class RuleSet:
    id: str
    family: str
    title: str
    framework: str      # e.g. "IFRS", "Ind AS", "GST"; ANY_FRAMEWORK for sets that apply under any framework
    jurisdiction: str   # ISO 3166 country code ("IN", "NP", "GB", "AE") or INTERNATIONAL
    authority: str      # who issues it
    status: str
    description: str
    items: Tuple[RuleItem, ...]


RULE_SETS: Dict[str, RuleSet] = {}


def _validate(rs: RuleSet) -> None:
    if not rs.id or rs.id != rs.id.lower() or " " in rs.id:
        raise ValueError(f"rule set id {rs.id!r} must be lower-case with no spaces")
    if rs.id in RULE_SETS:
        raise ValueError(f"rule set {rs.id!r} is already registered")
    if rs.family not in FAMILIES:
        raise ValueError(f"rule set {rs.id!r}: family must be one of {', '.join(FAMILIES)}")
    if rs.status not in STATUSES:
        raise ValueError(f"rule set {rs.id!r}: status must be one of {', '.join(STATUSES)}")
    if not rs.items:
        raise ValueError(f"rule set {rs.id!r} has no rule items")
    if not rs.jurisdiction or not rs.framework:
        raise ValueError(f"rule set {rs.id!r} needs a framework and a jurisdiction")
    seen = set()
    for item in rs.items:
        if item.id in seen:
            raise ValueError(f"rule set {rs.id!r}: item {item.id!r} appears twice")
        seen.add(item.id)
        if item.coverage not in COVERAGES:
            raise ValueError(f"{rs.id}/{item.id}: coverage must be one of {', '.join(COVERAGES)}")
        if (item.coverage == NONE) != (len(item.checks) == 0):
            raise ValueError(f"{rs.id}/{item.id}: coverage NONE means no checks, and any other coverage needs at least one")
        if item.coverage == PARTIAL and not item.note:
            raise ValueError(f"{rs.id}/{item.id}: PARTIAL coverage must say in the note what is not covered")
        for ref in item.checks:
            if ref.kind not in CHECK_KINDS:
                raise ValueError(f"{rs.id}/{item.id}: unknown check kind {ref.kind!r}")
            if ref.kind == "feature" and ref.id not in FEATURES:
                raise ValueError(f"{rs.id}/{item.id}: unknown feature {ref.id!r}")
    if rs.status == CATALOG_ONLY and any(i.coverage == FULL for i in rs.items):
        raise ValueError(f"rule set {rs.id!r} is CATALOG_ONLY, so no item can have FULL coverage")


def register_rule_set(rs: RuleSet) -> RuleSet:
    """Add a rule set to the registry. Raises ValueError for anything inconsistent, so a bad entry fails at import."""
    _validate(rs)
    RULE_SETS[rs.id] = rs
    return rs


def item(id: str, title: str, description: str, *, reference: str = "", coverage: str = NONE,
         checks: Iterable[Tuple[str, str]] = (), note: str = "") -> RuleItem:
    """Shorthand used by the rule-set files: item("ias-16", ..., checks=[("reconciliation", "some_rule")])."""
    return RuleItem(id=id, title=title, description=description, coverage=coverage, reference=reference, note=note,
                    checks=tuple(CheckRef(k, i) for k, i in checks))


# --- what the checks are called today ---------------------------------------------------------------------

def _check_titles() -> Dict[Tuple[str, str], str]:
    """Titles of every registered check, read from the live registries (importing them registers the built-ins)."""
    from .. import exceptions as _ex  # noqa: F401  registers the detectors
    from .. import reconciliation as _rec  # noqa: F401
    from ..reconciliation import repository as _rec_repo  # noqa: F401  registers the reconciliation rules
    from ..exceptions.registry import DETECTORS
    from ..reconciliation.registry import RULES

    titles: Dict[Tuple[str, str], str] = {}
    for rid, rule in RULES.items():
        titles[("reconciliation", rid)] = rule.title
    for did, det in DETECTORS.items():
        titles[("exception", did)] = det.title
    for fid, text in FEATURES.items():
        titles[("feature", fid)] = text
    return titles


def unknown_check_references() -> List[str]:
    """Every check a rule item names that is not actually registered. Always empty unless someone broke a link."""
    known = _check_titles()
    bad = []
    for rs in RULE_SETS.values():
        for it in rs.items:
            for ref in it.checks:
                if (ref.kind, ref.id) not in known:
                    bad.append(f"{rs.id}/{it.id} -> {ref.kind}:{ref.id}")
    return bad


# --- asking the registry ------------------------------------------------------------------------------------

def _norm(value: Optional[str]) -> Optional[str]:
    value = (value or "").strip()
    return value.upper() if value else None


def applicable(family: Optional[str] = None, framework: Optional[str] = None, jurisdiction: Optional[str] = None,
               status: Optional[str] = None) -> List[RuleSet]:
    """
    The rule sets that apply to a company. This is what the engine consults (and what the Phase 22 company
    policy will call with its framework and jurisdiction). A set applies when:
      * family matches (if given);
      * its jurisdiction is INTL, or equals the one asked for (if given);
      * its framework is ANY, or equals the one asked for (if given), compared ignoring case.
    A filter left as None does not narrow the answer. Order: family, then title.
    """
    if family is not None and family not in FAMILIES:
        raise ValueError(f"family must be one of {', '.join(FAMILIES)}")
    if status is not None and status not in STATUSES:
        raise ValueError(f"status must be one of {', '.join(STATUSES)}")
    fw, jur = _norm(framework), _norm(jurisdiction)
    out = []
    for rs in RULE_SETS.values():
        if family is not None and rs.family != family:
            continue
        if status is not None and rs.status != status:
            continue
        if jur is not None and rs.jurisdiction.upper() not in (INTERNATIONAL, jur):
            continue
        if fw is not None and rs.framework.upper() not in (ANY_FRAMEWORK, fw):
            continue
        out.append(rs)
    out.sort(key=lambda r: (FAMILIES.index(r.family), r.title.lower()))
    return out


def checks_for(rule_sets: Iterable[RuleSet]) -> List[CheckRef]:
    """The distinct Milaan checks that bear on the given rule sets, in a stable order."""
    seen: Dict[Tuple[str, str], CheckRef] = {}
    for rs in rule_sets:
        for it in rs.items:
            for ref in it.checks:
                seen.setdefault((ref.kind, ref.id), ref)
    return sorted(seen.values(), key=lambda r: (r.kind, r.id))


def get(rule_set_id: str) -> RuleSet:
    try:
        return RULE_SETS[rule_set_id]
    except KeyError:
        raise ValueError(f"there is no rule set called {rule_set_id!r}") from None


# --- the JSON shape the API returns -----------------------------------------------------------------------------

def _plain_item(it: RuleItem, titles: Dict[Tuple[str, str], str]) -> Dict[str, Any]:
    return {
        "id": it.id, "reference": it.reference, "title": it.title, "description": it.description,
        "coverage": it.coverage, "note": it.note,
        "checks": [{"kind": c.kind, "id": c.id, "title": titles.get((c.kind, c.id))} for c in it.checks],
    }


def plain(rs: RuleSet, titles: Optional[Dict[Tuple[str, str], str]] = None) -> Dict[str, Any]:
    titles = titles if titles is not None else _check_titles()
    items = [_plain_item(i, titles) for i in rs.items]
    coverage = {c: sum(1 for i in rs.items if i.coverage == c) for c in COVERAGES}
    return {
        "id": rs.id, "family": rs.family, "title": rs.title, "framework": rs.framework, "jurisdiction": rs.jurisdiction,
        "authority": rs.authority, "status": rs.status, "description": rs.description,
        "coverage": coverage, "items": items,
    }


def catalog(family: Optional[str] = None, framework: Optional[str] = None, jurisdiction: Optional[str] = None,
            status: Optional[str] = None) -> Dict[str, Any]:
    """Everything the Rules screen and GET /rules show: the families, the matching rule sets, and the scope notice."""
    titles = _check_titles()
    sets = applicable(family, framework, jurisdiction, status)
    all_sets = list(RULE_SETS.values())
    return {
        "notice": NOTICE,
        "families": [{"id": f, **FAMILY_INFO[f], "rule_sets": sum(1 for r in all_sets if r.family == f)} for f in FAMILIES],
        "rule_sets": [plain(r, titles) for r in sets],
        "summary": {
            "rule_sets": len(sets),
            "active": sum(1 for r in sets if r.status == ACTIVE),
            "catalog_only": sum(1 for r in sets if r.status == CATALOG_ONLY),
            "items": sum(len(r.items) for r in sets),
            "items_with_checks": sum(1 for r in sets for i in r.items if i.coverage != NONE),
        },
        "filters": {"jurisdictions": sorted({r.jurisdiction for r in all_sets}),
                    "frameworks": sorted({r.framework for r in all_sets})},
    }