"""
Database-facing half of the accounting policy. model.py decides what a policy is; this module reads and writes
the row (migration 0012) and hands the rest of the engine the values it should act on.

Other parts of the engine only ever need `effective()`: the company's own settings, or the built-in defaults when
the company has not set its policy up. That is the one door through which schedules and detectors read policy, so
a schedule never has to know whether a row exists.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Iterator, List, Mapping, Optional

from ..calendars.dates import LEGACY_RULES, DateRules, use_rules
from ..rules import registry as rules_registry
from . import countries, model

_COLUMNS = model.FIELDS
_SELECT = f"SELECT {', '.join(_COLUMNS)}, change_reason, updated_by, created_at, updated_at FROM accounting_policies"


@dataclass(frozen=True)
class EffectivePolicy:
    """What the engine acts on for one company."""
    configured: bool
    depreciation_method: str
    depreciation_start: str
    default_useful_life_months: Optional[int]
    capitalization_threshold: Decimal
    inventory_valuation_method: str
    review_min_amount: Decimal
    review_large_amount: Decimal
    calendar: str = "AD"
    date_order: str = "DMY"
    number_grouping: str = "INDIAN"
    statement_rounding: str = "EXACT"

    @property
    def depreciation_starts_next_month(self) -> bool:
        return self.depreciation_start == "NEXT_MONTH"

    @property
    def date_rules(self) -> DateRules:
        """How this company's dates are read. A company with no policy keeps the legacy rules (see calendars/dates.py)."""
        return DateRules(self.calendar, self.date_order) if self.configured else LEGACY_RULES

    @property
    def rounding_tolerance(self) -> Decimal:
        """How far two figures may differ and still count as agreeing: 0 for exact amounts, 1 unit for whole-unit statements."""
        return Decimal("1") if self.statement_rounding == "WHOLE" else Decimal("0")


def _row_to_policy(row) -> Dict[str, Any]:
    values = dict(zip(_COLUMNS, row[:len(_COLUMNS)]))
    reason, updated_by, created_at, updated_at = row[len(_COLUMNS):]
    values.update(change_reason=reason, updated_by=str(updated_by) if updated_by else None,
                  created_at=created_at, updated_at=updated_at)
    return values


def get_policy(conn, company_id: str, *, lock: bool = False) -> Optional[Dict[str, Any]]:
    """The company's saved policy, or None when it has not been set up."""
    with conn.cursor() as cur:
        cur.execute(_SELECT + " WHERE company_id = %s" + (" FOR UPDATE" if lock else ""), (company_id,))
        row = cur.fetchone()
    return _row_to_policy(row) if row else None


def effective(conn, company_id: str) -> EffectivePolicy:
    policy = get_policy(conn, company_id)
    v = model.effective_values(policy)
    return EffectivePolicy(configured=policy is not None, **v)


def date_rules(conn, company_id: str) -> DateRules:
    """The company's date rules (the legacy rules when it has no policy)."""
    return effective(conn, company_id).date_rules


@contextmanager
def company_date_rules(firm_id: str, company_id: str) -> Iterator[DateRules]:
    """
    Reads the company's policy and puts its date rules in force for everything done inside the `with`. The file
    importers (ledger files, bank statements, registers, Google Sheets, Tally) run inside this, so every date they
    read follows the company's calendar and date order. Uses its own short connection: the importers open theirs later.
    """
    from ..db.connection import tenant_connection
    with tenant_connection(firm_id, company_id) as conn:
        rules = date_rules(conn, company_id)
    with use_rules(rules):
        yield rules


def applicable_rule_sets(policy: Optional[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """
    The rule sets (Phase 21) that apply to a company with this policy -- the first real consumer of the rules
    registry. Accounting sets follow the framework and country; auditing and compliance sets follow the country;
    tax sets follow the country, and are left out for a company with no indirect tax. A company with no policy
    has told us nothing, so nothing is listed.
    """
    if not policy:
        return []
    jur = policy["jurisdiction"]
    found = list(rules_registry.applicable(family="accounting", framework=policy["accounting_framework"], jurisdiction=jur))
    found += rules_registry.applicable(family="auditing", jurisdiction=jur)
    if policy["tax_regime"] != "NONE":
        found += rules_registry.applicable(family="tax", jurisdiction=jur)
    found += rules_registry.applicable(family="compliance", jurisdiction=jur)
    return [{"id": r.id, "title": r.title, "family": r.family, "framework": r.framework, "jurisdiction": r.jurisdiction,
             "status": r.status} for r in found]


def describe(conn, company_id: str, role: str) -> Dict[str, Any]:
    """Everything the policy screen shows."""
    policy = get_policy(conn, company_id)
    exists = policy is not None
    return {
        "policy": policy,
        "configured": exists,
        "defaults": model.DEFAULTS,
        "can_edit": model.can_write(role, exists),
        "who_may": {"set_up": sorted(model.SETUP_ROLES), "change": sorted(model.CHANGE_ROLES)},
        "depreciation_posted": _depreciation_posted(conn, company_id),
        "locked_fields": list(model.DEPRECIATION_LOCKED_FIELDS),
        "options": model.options(),
        "labels": model.FIELD_LABELS,
        "used_by": model.FIELD_USE,
        "rule_sets": applicable_rule_sets(policy),
        "country": _country(policy),
    }


def _country(policy: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    """The profile of the company's country (statement titles, what is built for it), or None before the policy is set up."""
    if not policy:
        return None
    profile = countries.profile_for(policy["jurisdiction"])
    return profile.to_json() if profile else None


def _depreciation_posted(conn, company_id: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT EXISTS (SELECT 1 FROM fixed_asset_depreciation_entries WHERE company_id = %s)", (company_id,))
        return bool(cur.fetchone()[0])


def put_policy(conn, *, company_id: str, user_id: str, role: str, data: Mapping[str, Any]) -> Dict[str, Any]:
    """
    Sets the policy up, or replaces it with the full policy in `data` (plus an optional "reason"). The whole
    change happens in one transaction with the audit event. Nothing is written when nothing changed.
    """
    data = dict(data)
    reason_in = data.pop("reason", None)
    with conn.cursor() as cur:
        # One writer at a time per company, so two people saving at once cannot both think they changed the old value.
        cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"policy:{company_id}",))
        cur.execute("SELECT 1 FROM companies WHERE id = %s", (company_id,))
        if cur.fetchone() is None:
            raise ValueError("company not found")
    old = get_policy(conn, company_id, lock=True)
    exists = old is not None
    model.check_may_write(role, exists)
    new = model.validate(data)
    changed = model.changed_settings(old, new)
    if exists and not changed:
        return {**describe(conn, company_id, role), "changed": []}
    reason = model.clean_reason(reason_in, required=exists)

    locked = model.depreciation_locked(changed) if exists else []
    if locked and _depreciation_posted(conn, company_id):
        names = " and the ".join(model.LOCKED_NAMES[f] for f in locked)
        raise ValueError(f"depreciation has already been posted for this company, so the {names} cannot be changed "
                         "(the posted figures would no longer follow the policy). Post an adjustment instead.")

    with conn.cursor() as cur:
        if not exists:
            cur.execute(
                f"INSERT INTO accounting_policies (company_id, {', '.join(_COLUMNS)}, change_reason, updated_by) "
                f"VALUES (%s, {', '.join(['%s'] * len(_COLUMNS))}, %s, %s)",
                (company_id, *[new[f] for f in _COLUMNS], reason, user_id))
        else:
            cur.execute(
                f"UPDATE accounting_policies SET {', '.join(f'{f} = %s' for f in _COLUMNS)}, change_reason = %s, "
                "updated_by = %s, updated_at = now() WHERE company_id = %s",
                (*[new[f] for f in _COLUMNS], reason, user_id, company_id))
    return {**describe(conn, company_id, role), "changed": changed}