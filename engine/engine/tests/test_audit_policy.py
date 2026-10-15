"""Pure-logic tests for engine.audit.policy -- no database."""
import csv
import io
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from engine.approvals import policy as approval_pol
from engine.audit import policy as pol
from engine.exceptions import state_machine as exc_sm
from engine.scenarios import state_machine as scn_sm

COMPANY = "c977a92f-0000-0000-0000-000000000000"
EVENT = {"seq": 7, "occurred_at": datetime(2026, 10, 13, 5, 30, tzinfo=timezone.utc), "actor": {"email": "ca@firm.test", "role": "ca"},
         "action": "scenario.approve", "object_type": "scenario", "object_id": "o-1", "period_id": "p-1",
         "old_value": {"status": "REVIEW_REQUIRED"}, "new_value": {"status": "APPROVED"}, "reason": "Looks right", "event_hash": "ab12"}


# ── who may do what ──
def test_roles_are_known_and_nested_sensibly():
    assert pol.READ_ROLES <= set(pol.ROLES)
    assert pol.EXPORT_ROLES <= pol.READ_ROLES and pol.VERIFY_ROLES <= pol.READ_ROLES


def test_a_plain_accountant_cannot_read_the_trail_at_all():
    with pytest.raises(PermissionError, match="accountant"):
        pol.check_role("accountant", pol.READ_ROLES, "read the audit trail")


def test_a_senior_accountant_may_read_but_not_export_or_verify():
    pol.check_role("senior_accountant", pol.READ_ROLES, "read")
    for allowed in (pol.EXPORT_ROLES, pol.VERIFY_ROLES):
        with pytest.raises(PermissionError, match="allowed roles: admin, ca, reviewer"):
            pol.check_role("senior_accountant", allowed, "do it")


def test_an_unknown_role_is_a_bad_request_not_a_denial():
    with pytest.raises(ValueError, match="role must be one of"):
        pol.check_role("janitor", pol.READ_ROLES, "read")


# ── the vocabulary ──
def test_every_scenario_and_exception_state_machine_action_has_a_label():
    for action in scn_sm.TRANSITIONS:
        assert f"scenario.{action}" in pol.ACTIONS, action
    for extra in ("create", "edit", "link_adjustment", "auto_lock"):   # logged by the repository, not state-machine actions
        assert f"scenario.{extra}" in pol.ACTIONS, extra
    for action in set(exc_sm.TRANSITIONS) | set(exc_sm.SYSTEM_TRANSITIONS) | {"link_adjustment", "propose_reversal"}:
        assert f"exception.{action}" in pol.ACTIONS, action


def test_every_decision_the_approvals_inbox_reports_is_in_the_trail_vocabulary():
    for action in approval_pol.SCENARIO_ACTION_OUTCOMES:
        assert f"scenario.{action}" in pol.ACTIONS, action
    assert {"adjustment.approve", "adjustment.reject"} <= set(pol.ACTIONS)


def test_every_action_has_a_known_object_type_and_fits_the_database_check():
    for action in pol.ACTIONS:
        assert re.fullmatch(r"[a-z_]+\.[a-z_]+", action), action          # the CHECK in migration 0011
    assert all(re.fullmatch(r"[a-z_]+", t) for t in pol.OBJECT_TYPES)
    assert set(pol.ACTION_GROUPS) == {a.split(".")[0] for a in pol.ACTIONS}


def test_labels_are_plain_and_unknown_actions_are_still_shown():
    assert pol.action_label("scenario.approve") == "Scenario approved"
    assert pol.action_label("widget.get_polished") == "Widget get polished"
    assert pol.object_label("accounting_period") == "Accounting period"
    assert pol.object_label("brand_new_thing") == "Brand new thing"


def test_catalog_lists_everything_for_the_ui():
    cat = pol.catalog()
    assert len(cat["actions"]) == len(pol.ACTIONS) and cat["actions"] == sorted(cat["actions"], key=lambda a: a["action"])
    assert cat["roles"]["export"] == ["admin", "ca", "reviewer"] and cat["limits"]["max_limit"] == pol.MAX_LIMIT


# ── what changed ──
def test_changed_fields_lists_only_differences_in_a_stable_order():
    assert pol.changed_fields({"a": 1, "b": 2, "c": 3}, {"a": 1, "b": 5, "d": 4}) == [
        {"field": "b", "old": 2, "new": 5}, {"field": "c", "old": 3, "new": None}, {"field": "d", "old": None, "new": 4}]


def test_changed_fields_for_a_first_record_and_for_nothing():
    assert pol.changed_fields(None, {"x": 1}) == [{"field": "x", "old": None, "new": 1}]
    assert pol.changed_fields({"x": 1}, {"x": 1}) == []
    assert pol.changed_fields(None, None) == []


def test_headline_names_the_person_or_says_system():
    assert pol.headline({"action": "scenario.approve", "actor_id": "u"}, "ca@firm.test") == "ca@firm.test -- Scenario approved"
    assert pol.headline({"action": "period.lock", "actor_id": None}) == "System -- Accounting period locked"
    assert pol.headline({"action": "period.lock", "actor_id": "gone"}) == "Unknown user -- Accounting period locked"


# ── filters ──
ID = "11111111-2222-3333-4444-555555555555"


def test_filters_are_validated_and_tidied():
    f = pol.normalise_filters({"periodId": ID.upper(), "action": "scenario", "objectType": "scenario", "from": "2026-04-01",
                               "to": "2026-04-30", "search": "  late invoice ", "limit": "20", "offset": "5", "ignored": 1})
    assert f == {"periodId": ID, "action": "scenario", "objectType": "scenario", "from": "2026-04-01", "to": "2026-04-30",
                 "search": "late invoice", "limit": 20, "offset": 5}


def test_no_filters_gives_only_the_paging_defaults():
    assert pol.normalise_filters(None) == {"limit": pol.DEFAULT_LIMIT, "offset": 0}
    assert pol.normalise_filters({}, paged=False) == {}


@pytest.mark.parametrize("bad, message", [
    ({"periodId": "nope"}, "periodId is not a valid id"),
    ({"actorId": "1"}, "actorId is not a valid id"),
    ({"action": "Scenario.Approve"}, "action must look like"),
    ({"action": "scenario.approve.now"}, "action must look like"),
    ({"action": "nonsense"}, "action group must be one of"),
    ({"objectType": "spaceship"}, "objectType must be one of"),
    ({"from": "30/04/2026"}, "from must be a date"),
    ({"to": "2026-02-30"}, "to is not a real date"),
    ({"from": "2026-05-01", "to": "2026-04-01"}, "cannot be earlier"),
    ({"search": "x" * 201}, "too long"),
    ({"search": 5}, "must be text"),
    ({"limit": "many"}, "limit must be a whole number"),
    ({"offset": "-"}, "offset must be a whole number"),
])
def test_bad_filters_are_refused_with_a_clear_message(bad, message):
    with pytest.raises(ValueError, match=message):
        pol.normalise_filters(bad)


def test_an_exact_action_is_accepted_even_if_only_the_group_is_known():
    assert pol.normalise_filters({"action": "scenario.approve"}, paged=False) == {"action": "scenario.approve"}


def test_limit_and_offset_are_clamped():
    assert pol.clamp_limit(0) == 1 and pol.clamp_limit(10_000) == pol.MAX_LIMIT and pol.clamp_limit(10_000, 50_000) == 10_000
    assert pol.clamp_offset(-4) == 0 and pol.clamp_offset("7") == 7


def test_day_bounds_include_the_whole_last_day_in_utc():
    start, end = pol.day_bounds({"from": "2026-04-01", "to": "2026-04-30"})
    assert start == datetime(2026, 4, 1, tzinfo=timezone.utc) and end == datetime(2026, 5, 1, tzinfo=timezone.utc)
    assert pol.day_bounds({}) == (None, None)


# ── CSV ──
@pytest.mark.parametrize("value, expected", [
    (None, ""), ("plain", "plain"), (42, "42"), ("a=b", "a=b"),
    ("=SUM(A1:A9)", "'=SUM(A1:A9)"), ("+1", "'+1"), ("-2", "'-2"), ("@cmd", "'@cmd"), ("\tx", "'\tx"), ("\rx", "'\rx"),
    ({"b": 1, "a": [2]}, '{"a":[2],"b":1}'),
    (datetime(2026, 10, 13, 5, 30, tzinfo=timezone.utc), "2026-10-13T05:30:00+00:00"),
])
def test_csv_cells_are_formula_safe(value, expected):
    assert pol.csv_safe(value) == expected


def test_a_json_value_that_starts_with_a_dash_is_still_neutralised():
    assert pol.csv_safe("-5 reversed").startswith("'")


def test_csv_round_trips_with_every_column_and_hostile_text():
    hostile = {**EVENT, "reason": '=HYPERLINK("http://evil.test","click")'}
    text = pol.to_csv([EVENT, hostile])
    rows = list(csv.reader(io.StringIO(text)))
    assert tuple(rows[0]) == pol.CSV_COLUMNS and len(rows) == 3 and all(len(r) == len(pol.CSV_COLUMNS) for r in rows)
    first = dict(zip(pol.CSV_COLUMNS, rows[1]))
    assert first["actor_email"] == "ca@firm.test" and first["action_label"] == "Scenario approved"
    assert first["old_value"] == '{"status":"REVIEW_REQUIRED"}' and first["occurred_at"] == "2026-10-13T05:30:00+00:00"
    assert dict(zip(pol.CSV_COLUMNS, rows[2]))["reason"].startswith("'=HYPERLINK")
    assert text.endswith("\r\n") and text.splitlines()[0].startswith('"seq"')


def test_csv_with_no_events_is_just_the_header():
    assert list(csv.reader(io.StringIO(pol.to_csv([])))) == [list(pol.CSV_COLUMNS)]


def test_a_system_event_has_blank_actor_cells():
    rows = list(csv.reader(io.StringIO(pol.to_csv([{**EVENT, "actor": None}]))))
    row = dict(zip(pol.CSV_COLUMNS, rows[1]))
    assert row["actor_email"] == "" and row["actor_role"] == ""


def test_export_filename_is_safe_and_dated():
    name = pol.export_filename(COMPANY, datetime(2026, 10, 13, 5, 30, 9, tzinfo=timezone.utc))
    assert name == "audit-trail-c977a92f-20261013-053009.csv" and re.fullmatch(r"[A-Za-z0-9._-]+", name)


# ── the policy agrees with the code that actually enforces it ──
ROOT = Path(__file__).resolve().parents[3]
API = ROOT / "api" / "src" / "modules"
MIGRATION = ROOT / "engine" / "migrations" / "0011_audit_events.sql"


def _roles(text):
    return set(re.findall(r'"(\w+)"', text))


@pytest.mark.skipif(not (API / "audit" / "routes.ts").exists(), reason="api/ not next to engine/")
def test_policy_roles_match_the_roles_the_api_routes_enforce():
    routes = (API / "audit" / "routes.ts").read_text()
    for name, expected in (("READERS", pol.READ_ROLES), ("EXPORTERS", pol.EXPORT_ROLES), ("VERIFIERS", pol.VERIFY_ROLES)):
        found = _roles(re.search(rf"const {name}: Role\[\] = \[(.*?)\];", routes).group(1))
        assert found == expected, name


@pytest.mark.skipif(not (API / "audit" / "routes.ts").exists(), reason="api/ not next to engine/")
def test_every_audit_route_is_behind_authentication_and_a_role():
    routes = (API / "audit" / "routes.ts").read_text()
    handlers = re.findall(r"auditRouter\.get\(\s*\"[^\"]+\",\s*authenticate,\s*requireRole\(\.\.\.(\w+)\)", routes)
    assert len(handlers) == routes.count("auditRouter.get(") == 7
    assert set(handlers) <= {"READERS", "EXPORTERS", "VERIFIERS"}


@pytest.mark.skipif(not MIGRATION.exists(), reason="migrations/ not found")
def test_the_migration_captures_every_table_the_vocabulary_depends_on():
    sql = MIGRATION.read_text()
    for table in ("scenario_transitions", "exception_transitions", "exception_runs", "reconciliation_runs", "adjustments",
                  "accounting_periods", "accounts", "account_mappings", "source_files", "fixed_assets",
                  "fixed_asset_depreciation_entries"):
        assert re.search(rf"ON {table}\s+FOR EACH ROW EXECUTE FUNCTION audit_capture\(\)", sql), table


@pytest.mark.skipif(not MIGRATION.exists(), reason="migrations/ not found")
def test_the_migration_only_writes_actions_and_object_types_the_vocabulary_knows():
    sql = MIGRATION.read_text()
    literal_actions = set(re.findall(r"'((?:[a-z_]+)\.(?:[a-z_]+))'", sql)) - {"app.current_user_id", "app.current_company_id"}
    assert literal_actions and literal_actions <= set(pol.ACTIONS), literal_actions - set(pol.ACTIONS)
    prefixes = set(re.findall(r"'((?:scenario|exception|import))\.' \|\|", sql))
    assert prefixes == {"scenario", "exception", "import"}
    object_types = set(re.findall(r"audit_emit\([^,]+,[^,]+,[^,]+,\s*'([a-z_]+)'", sql))
    assert object_types and object_types <= set(pol.OBJECT_TYPES), object_types - set(pol.OBJECT_TYPES)


@pytest.mark.skipif(not MIGRATION.exists(), reason="migrations/ not found")
def test_the_migration_keeps_the_table_append_only_for_the_app_role():
    sql = MIGRATION.read_text()
    assert "REVOKE UPDATE, DELETE, TRUNCATE ON audit_events FROM app_user" in sql
    assert "BEFORE UPDATE OR DELETE ON audit_events" in sql and "BEFORE TRUNCATE ON audit_events" in sql