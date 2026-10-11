"""Pure-logic tests for engine.versions.impact -- no database."""
from datetime import date
from decimal import Decimal

from engine.mapping.planner import Period
from engine.versions import impact
from engine.versions.matcher import diff_rows
from engine.versions.models import RowVersion

D = Decimal

MARCH = Period("p-mar", "Mar 2026", date(2026, 3, 1), date(2026, 3, 31), locked=True)
APRIL = Period("p-apr", "Apr 2026", date(2026, 4, 1), date(2026, 4, 30), locked=False)
PERIODS = [APRIL, MARCH]


def row(rid, n, account="Bank", d=(2026, 3, 5), desc="", debit="0", credit="0", ref="", status="OK"):
    return RowVersion(rid, n, account, date(*d) if d else None, desc, D(debit), D(credit), ref, status)


def run(old, new, mapped=None):
    changes = diff_rows(old, new)
    return changes, impact.by_account(old, new, changes, mapped or {}), impact.by_period(old, new, changes, PERIODS)


def test_find_period():
    assert impact.find_period(date(2026, 3, 31), PERIODS) is MARCH
    assert impact.find_period(date(2026, 5, 1), PERIODS) is None
    assert impact.find_period(None, PERIODS) is None


def test_totals_move_by_the_difference_and_ignore_error_rows():
    old = [row("a", 1, debit="100"), row("b", 2, "Sales", credit="100"), row("e", 3, debit="9999", status="ERROR")]
    new = [row("a2", 1, debit="150", ref="X"), row("b2", 2, "Sales", credit="150")]
    t = impact.totals(old, new)
    assert t["base"]["total_debit"] == D("100") and t["base"]["rows_with_errors"] == 1 and t["base"]["in_balance"]
    assert t["compare"]["total_credit"] == D("150") and t["delta_debit"] == D("50") and t["delta_credit"] == D("50")


def test_an_unbalanced_file_is_reported_as_not_in_balance():
    t = impact.totals([row("a", 1, debit="100")], [row("b", 1, debit="100"), row("c", 2, "Sales", credit="90")])
    assert t["base"]["in_balance"] is False and t["compare"]["in_balance"] is False


def test_by_account_orders_by_net_movement_and_attaches_the_mapped_account():
    old = [row("a", 1, "Bank", debit="100", ref="V1"), row("b", 2, "Sales", credit="100", ref="V1")]
    new = [row("a2", 1, "Bank", debit="400", ref="V1"), row("b2", 2, "Sales", credit="400", ref="V1"), row("c", 3, "Rent", debit="5", ref="V2")]
    mapped = {"bank": {"id": "acc-1", "code": "1000", "name": "Bank", "account_type": "Asset"}}
    _, accounts, _ = run(old, new, mapped)
    assert [a["label"] for a in accounts] == ["Bank", "Sales", "Rent"]
    bank = accounts[0]
    assert bank["net_change"] == D("300") and bank["account"]["code"] == "1000" and bank["changed_rows"] == 1
    assert accounts[1]["net_change"] == D("-300") and accounts[2]["account"] is None


def test_accounts_with_no_difference_are_left_out():
    rows_old = [row("a", 1, "Bank", debit="100", ref="V1"), row("z", 2, "Rent", debit="7", ref="V9")]
    rows_new = [row("a2", 1, "Bank", debit="100", ref="V1"), row("z2", 2, "Rent", debit="8", ref="V9")]
    _, accounts, _ = run(rows_old, rows_new)
    assert [a["label"] for a in accounts] == ["Rent"]


def test_a_description_only_change_has_no_net_effect_but_still_counts_as_a_changed_row():
    _, accounts, periods = run([row("a", 1, debit="100", desc="taxi")], [row("b", 1, debit="100", desc="cab")])
    assert accounts[0]["net_change"] == 0 and accounts[0]["changed_rows"] == 1
    assert periods[0]["affected"] is True and periods[0]["net_change"] == 0


def test_by_period_totals_and_ordering():
    old = [row("a", 1, d=(2026, 4, 2), debit="10", ref="A1"), row("b", 2, d=(2026, 3, 2), debit="20", ref="B1")]
    new = [row("a2", 1, d=(2026, 4, 2), debit="10", ref="A1"), row("b2", 2, d=(2026, 3, 2), debit="25", ref="B1")]
    _, _, periods = run(old, new)
    assert [p["label"] for p in periods] == ["Mar 2026", "Apr 2026"]
    mar, apr = periods
    assert mar["net_change"] == D("5") and mar["affected"] and not apr["affected"]


def test_a_change_that_moves_a_row_between_periods_touches_both():
    _, _, periods = run([row("a", 1, d=(2026, 3, 30), debit="100", ref="V1")], [row("b", 1, d=(2026, 4, 2), debit="100", ref="V1")])
    by_label = {p["label"]: p for p in periods}
    assert by_label["Mar 2026"]["net_change"] == D("-100") and by_label["Apr 2026"]["net_change"] == D("100")
    assert by_label["Mar 2026"]["affected"] and by_label["Apr 2026"]["affected"]


def test_locked_periods_are_reported_only_when_affected():
    old = [row("a", 1, d=(2026, 3, 2), debit="20", ref="B1"), row("c", 2, d=(2026, 4, 2), debit="9", ref="C1")]
    untouched = [row("a2", 1, d=(2026, 3, 2), debit="20", ref="B1"), row("c2", 2, d=(2026, 4, 2), debit="12", ref="C1")]
    _, _, p1 = run(old, untouched)
    assert impact.locked_periods_affected(p1) == []
    touched = [row("a2", 1, d=(2026, 3, 2), debit="21", ref="B1"), row("c2", 2, d=(2026, 4, 2), debit="9", ref="C1")]
    _, _, p2 = run(old, touched)
    assert impact.locked_periods_affected(p2) == [{"period_id": "p-mar", "label": "Mar 2026"}]


def test_undated_rows_are_grouped_under_no_period_and_sorted_last():
    _, _, periods = run([row("a", 1, d=None, debit="5")], [row("b", 1, d=(2026, 3, 2), debit="5")])
    assert periods[-1]["label"] == impact.NO_PERIOD and periods[-1]["period_id"] is None