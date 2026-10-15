"""
Phase 15 audit-trail policy -- pure logic, no database.

What the audit trail is made of is decided in the database (migration 0011: triggers write
the events, a hash chain protects them). This module is the vocabulary around it, in one place:

  * the catalogue of every action an event can carry, with a plain-language label -- so the UI
    can show "Scenario approved" instead of "scenario.approve", and filters can be validated
  * who may read, export and verify the trail
  * turning an event's old/new values into a list of "what changed"
  * validating and tidying the filters a caller sends
  * the CSV export, with formula-injection-safe cells (ARCHITECTURE.md §9)

tests/test_audit_policy.py reads migration 0011 and the Node routes and fails if this file and
either of them ever drift apart.
"""
from __future__ import annotations

import csv
import io
import json
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, FrozenSet, List, Mapping, Optional, Sequence, Tuple

ROLES: Tuple[str, ...] = ("accountant", "senior_accountant", "ca", "reviewer", "admin")

# Who may do what with the trail. Seeing who did what is a supervisory job; a plain accountant
# works inside the books, they do not audit them. Exporting and verifying are narrower still.
READ_ROLES: FrozenSet[str] = frozenset({"senior_accountant", "ca", "reviewer", "admin"})
EXPORT_ROLES: FrozenSet[str] = frozenset({"ca", "reviewer", "admin"})
VERIFY_ROLES: FrozenSet[str] = frozenset({"ca", "reviewer", "admin"})

MAX_LIMIT = 500
DEFAULT_LIMIT = 100
MAX_EXPORT_ROWS = 50_000

# object_type -> label
OBJECT_TYPES: Dict[str, str] = {
    "scenario": "Scenario",
    "exception": "Exception",
    "exception_run": "Exception detection run",
    "reconciliation_run": "Reconciliation run",
    "adjustment": "Adjustment",
    "accounting_period": "Accounting period",
    "account": "Account",
    "account_mapping": "Account mapping",
    "source_file": "Imported file",
    "fixed_asset": "Fixed asset",
    "audit": "Audit trail",
}

# Actions the database triggers write, from the transition tables (their vocabulary comes from
# scenarios/state_machine.py and exceptions/state_machine.py) plus the other captured tables.
SCENARIO_ACTIONS: Dict[str, str] = {
    "create": "Scenario created",
    "edit": "Scenario changes edited",
    "simulate": "Scenario simulated",
    "revise": "Scenario sent back to draft for revision",
    "submit": "Scenario submitted for review",
    "approve": "Scenario approved",
    "reject": "Scenario rejected",
    "link_adjustment": "Adjustment linked to scenario",
    "post": "Scenario posted",
    "finalize": "Scenario finalised",
    "auto_lock": "Period locked on finalisation",
    "discard": "Scenario discarded",
    "request_reopen": "Reopen requested",
    "approve_reopen": "Reopen approved",
    "deny_reopen": "Reopen denied",
}
EXCEPTION_ACTIONS: Dict[str, str] = {
    "flag": "Exception flagged",
    "claim": "Exception taken up for review",
    "request_evidence": "Evidence requested",
    "evidence_received": "Evidence received",
    "retain": "Exception retained",
    "correct": "Correction decided",
    "reverse": "Reversal decided",
    "resolve": "Exception resolved",
    "reopen": "Exception reopened",
    "link_adjustment": "Adjustment linked to exception",
    "propose_reversal": "Reversal proposed",
    "clear": "Exception cleared (no longer detected)",
    "redetect": "Exception detected again",
    "detection_run": "Exception detection run",
}
OTHER_ACTIONS: Dict[str, str] = {
    "reconciliation.run": "Reconciliation run",
    "adjustment.propose": "Adjustment proposed",
    "adjustment.approve": "Adjustment approved and posted",
    "adjustment.reject": "Adjustment rejected",
    "period.create": "Accounting period created",
    "period.lock": "Accounting period locked",
    "period.reopen": "Accounting period reopened",
    "account.create": "Account created",
    "account.update": "Account changed",
    "mapping.confirm": "Account mapping confirmed",
    "mapping.change": "Account mapping changed",
    "import.upload": "File uploaded",
    "import.processed": "File processed",
    "import.error": "File failed to process",
    "fixed_asset.create": "Fixed asset added",
    "fixed_asset.depreciation_posted": "Depreciation posted",
    # written by this module itself, not by a trigger
    "audit.export": "Audit trail exported",
}

ACTIONS: Dict[str, str] = {
    **{f"scenario.{a}": label for a, label in SCENARIO_ACTIONS.items()},
    **{f"exception.{a}": label for a, label in EXCEPTION_ACTIONS.items()},
    **OTHER_ACTIONS,
}
ACTION_GROUPS: Tuple[str, ...] = tuple(sorted({a.split(".")[0] for a in ACTIONS}))

_ACTION_RE = re.compile(r"^[a-z_]+(\.[a-z_]+)?$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def action_label(action: str) -> str:
    """A plain-language label; an action this file does not know yet is shown tidied, never hidden."""
    return ACTIONS.get(action) or action.replace(".", " ").replace("_", " ").capitalize()


def object_label(object_type: str) -> str:
    return OBJECT_TYPES.get(object_type) or object_type.replace("_", " ").capitalize()


def catalog() -> Dict[str, Any]:
    """Everything a UI needs to build filters and labels, plus who may do what."""
    return {
        "actions": [{"action": a, "label": label} for a, label in sorted(ACTIONS.items())],
        "action_groups": list(ACTION_GROUPS),
        "object_types": [{"object_type": t, "label": label} for t, label in sorted(OBJECT_TYPES.items())],
        "roles": {"read": sorted(READ_ROLES), "export": sorted(EXPORT_ROLES), "verify": sorted(VERIFY_ROLES)},
        "limits": {"default_limit": DEFAULT_LIMIT, "max_limit": MAX_LIMIT, "max_export_rows": MAX_EXPORT_ROWS},
    }


def check_role(actor_role: str, allowed: FrozenSet[str], what: str) -> None:
    """PermissionError (HTTP 403) when this role may not do `what`."""
    if actor_role not in ROLES:
        raise ValueError(f"role must be one of {', '.join(ROLES)}")
    if actor_role not in allowed:
        raise PermissionError(f"your role ({actor_role}) cannot {what}; allowed roles: {', '.join(sorted(allowed))}")


# ── what changed ─────────────────────────────────────────────────────────
def changed_fields(old: Optional[Mapping[str, Any]], new: Optional[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """
    One entry per field that differs between the old and the new value, in a stable order:
    {"field", "old", "new"}. A field only on one side shows None on the other. A first-time
    record (no old value) lists every new field; an event with neither side gives [].
    """
    old, new = old or {}, new or {}
    out: List[Dict[str, Any]] = []
    for key in sorted(set(old) | set(new)):
        before, after = old.get(key), new.get(key)
        if before != after:
            out.append({"field": key, "old": before, "new": after})
    return out


def headline(event: Mapping[str, Any], actor_email: Optional[str] = None) -> str:
    """One readable line: 'ca@firm.com -- Scenario approved'. Nobody named -> 'System'."""
    who = actor_email or ("System" if not event.get("actor_id") else "Unknown user")
    return f"{who} -- {action_label(str(event['action']))}"


# ── filters ──────────────────────────────────────────────────────────────
def _parse_day(value: Any, label: str) -> date:
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise ValueError(f"{label} must be a date like 2026-04-30")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{label} is not a real date")


def check_uuid(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _UUID_RE.match(value):
        raise ValueError(f"{label} is not a valid id")
    return value.lower()


def normalise_filters(raw: Optional[Mapping[str, Any]], *, paged: bool = True) -> Dict[str, Any]:
    """
    Validate what a caller sent and return a clean filter dict (only keys that were given).
    periodId / actorId / objectId: ids. action: an exact action ('scenario.approve') or a group
    ('scenario'). objectType: one of OBJECT_TYPES. from / to: whole days, both inclusive, UTC.
    search: text matched inside the reason. limit/offset (when paged).
    """
    raw = dict(raw or {})
    out: Dict[str, Any] = {}
    for key, label in (("periodId", "periodId"), ("actorId", "actorId"), ("objectId", "objectId")):
        if raw.get(key):
            out[key] = check_uuid(raw[key], label)
    if raw.get("action"):
        action = raw["action"]
        if not isinstance(action, str) or not _ACTION_RE.match(action):
            raise ValueError("action must look like 'scenario.approve' or just 'scenario'")
        if "." not in action and action not in ACTION_GROUPS:
            raise ValueError(f"action group must be one of {', '.join(ACTION_GROUPS)}")
        out["action"] = action
    if raw.get("objectType"):
        if raw["objectType"] not in OBJECT_TYPES:
            raise ValueError(f"objectType must be one of {', '.join(sorted(OBJECT_TYPES))}")
        out["objectType"] = raw["objectType"]
    start = _parse_day(raw["from"], "from") if raw.get("from") else None
    end = _parse_day(raw["to"], "to") if raw.get("to") else None
    if start and end and end < start:
        raise ValueError("'to' cannot be earlier than 'from'")
    if start:
        out["from"] = start.isoformat()
    if end:
        out["to"] = end.isoformat()
    if raw.get("search"):
        if not isinstance(raw["search"], str):
            raise ValueError("search must be text")
        text = raw["search"].strip()
        if len(text) > 200:
            raise ValueError("search is too long (200 characters at most)")
        if text:
            out["search"] = text
    if paged:
        out["limit"] = clamp_limit(raw.get("limit", DEFAULT_LIMIT))
        out["offset"] = clamp_offset(raw.get("offset", 0))
    return out


def clamp_limit(value: Any, maximum: int = MAX_LIMIT) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise ValueError("limit must be a whole number")
    return max(1, min(n, maximum))


def clamp_offset(value: Any) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise ValueError("offset must be a whole number")
    return max(0, n)


def day_bounds(filters: Mapping[str, Any]) -> Tuple[Optional[datetime], Optional[datetime]]:
    """[start, end) as UTC timestamps: 'from' is the start of that day, 'to' includes the whole day."""
    start = end = None
    if filters.get("from"):
        start = datetime.combine(date.fromisoformat(filters["from"]), datetime.min.time(), tzinfo=timezone.utc)
    if filters.get("to"):
        end = datetime.combine(date.fromisoformat(filters["to"]) + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
    return start, end


# ── CSV export ───────────────────────────────────────────────────────────
CSV_COLUMNS: Tuple[str, ...] = (
    "seq", "occurred_at", "actor_email", "actor_role", "action", "action_label", "object_type", "object_id",
    "period_id", "old_value", "new_value", "reason", "event_hash",
)

_FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r", "\n")


def csv_safe(value: Any) -> str:
    """
    One CSV cell as text. A cell that starts with = + - @ (or a tab/newline) would be run as a
    formula by Excel or Sheets, so it gets a leading apostrophe -- the standard defence. JSON values
    become compact JSON text; None becomes empty.
    """
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        text = json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
    elif isinstance(value, datetime):
        text = value.astimezone(timezone.utc).isoformat()
    else:
        text = str(value)
    return "'" + text if text.startswith(_FORMULA_STARTS) else text


def to_csv(events: Sequence[Mapping[str, Any]]) -> str:
    """The events as CSV text (every cell quoted, CRLF line ends, formula-safe)."""
    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    writer.writerow(CSV_COLUMNS)
    for e in events:
        who = e.get("actor") or {}
        writer.writerow([
            csv_safe(e.get("seq")), csv_safe(e.get("occurred_at")), csv_safe(who.get("email")), csv_safe(who.get("role")),
            csv_safe(e.get("action")), csv_safe(action_label(str(e.get("action", "")))), csv_safe(e.get("object_type")),
            csv_safe(e.get("object_id")), csv_safe(e.get("period_id")), csv_safe(e.get("old_value")),
            csv_safe(e.get("new_value")), csv_safe(e.get("reason")), csv_safe(e.get("event_hash")),
        ])
    return buf.getvalue()


def export_filename(company_id: str, now: datetime) -> str:
    return f"audit-trail-{company_id[:8]}-{now.astimezone(timezone.utc).strftime('%Y%m%d-%H%M%S')}.csv"