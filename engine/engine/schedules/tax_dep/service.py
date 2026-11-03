"""
Tax depreciation, the database-facing half (Phase 24).

The country's scheme (nepal.py, india.py, us.py) is pure logic. This module:
  * picks the scheme from the company's policy (country, calendar, fiscal year start),
  * reads the saved opening balances, additions, disposals and the company's own dated rates,
  * rolls the schedule forward year by year from the first year there is data to the year asked for, and
  * writes the inputs (add, bulk add, change, remove, set a rate) -- each one lands in the audit trail through the
    migration 0014 triggers, in the same transaction.

The schedule is a memo: it posts nothing to the ledger. Dates here are AD (ISO); a BS company's screen converts.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from psycopg.types.json import Jsonb

from ...calendars import bs
from ...calendars.fiscal import FiscalYear, fiscal_year_containing
from ...policy import repository as policy_repo
from . import india, nepal, us
from .common import ADDITION, DISPOSAL, HUNDRED, KINDS, OPENING, Movement, RateRow, fmt, money, positive_money

WRITE_ROLES = frozenset({"senior_accountant", "ca", "admin"})
SCHEMES = {"NP": nepal, "IN": india, "US": us}
SCHEME_NAMES = {
    "NP": "Nepal: Income Tax Act 2058, Schedule 2 (pools A to E)",
    "IN": "India: block of assets at written-down value (Income-tax Act)",
    "US": "United States: federal MACRS (IRS Publication 946)",
}
MAX_BULK_ROWS = 500
MAX_YEARS = 80

SCHEME_NOTES: Dict[str, List[str]] = {
    "NP": [
        "Memo schedule: it posts nothing to the ledger. Book depreciation is the fixed-asset schedule.",
        "Pools A to D are worked on the declining balance. Only part of an addition counts in the year it is bought (three thirds "
        "if bought in the first six months of the fiscal year, two thirds in the next three, one third in the last three); "
        "the rest is added in the following year.",
        "If the depreciation worked out for a pool is under Rs 2,000, the whole remaining base is claimed.",
        "Pool E (intangibles) is straight line over the useful life, rounded to a half year. Check how the Act treats the first year "
        "for your asset; this is the least certain part of the schedule.",
        "A powerhouse or public-infrastructure project adds one third to the rates. Use the rate preset, or set your own rates. "
        "Whether pool A also gets the uplift is not settled here: confirm with your CA.",
        "Rates were taken from public sources. Confirm them against the Act before filing.",
    ],
    "IN": [
        "Memo schedule: it posts nothing to the ledger. Book depreciation (Companies Act Schedule II) is the fixed-asset schedule.",
        "Depreciation is on each block's written-down value. An addition used for under 180 days in the year gets half the rate.",
        "For tax years from 2026-27 the Income-tax Act, 2025 applies; the sources read say the categories and rates carry over, "
        "but confirm the rate for each block.",
        "Not built: additional depreciation, and assets of different rates inside one block.",
    ],
    "US": [
        "Memo schedule: it posts nothing to the ledger. This is federal MACRS (GDS); state rules that differ are not modelled.",
        "Each addition is one asset. Enter its asset reference, Section 179 amount and bonus percent: Milaan does not decide whether "
        "an asset qualifies, and does not enforce the Section 179 limits.",
        "Half-year convention applies unless more than 40% of the year's personal-property basis (cost less Section 179) is placed in "
        "service in the last quarter, when mid-quarter applies. Real property uses mid-month.",
        "Assets bought in earlier years must be entered with their original date, Section 179 and bonus, so past years are worked out "
        "the same way (there is no opening balance for MACRS).",
        "Gain, loss and depreciation recapture on a sale are not computed. The Alternative Depreciation System is not built.",
    ],
}


class Scheme:
    """What one company's schedule is worked from: its country's module, calendar and fiscal year start."""

    def __init__(self, code: str, calendar: str, start_month: int) -> None:
        self.code, self.calendar, self.start_month = code, calendar, start_month
        self.module = SCHEMES[code]

    def fy_of(self, d: date) -> FiscalYear:
        return fiscal_year_containing(d, self.calendar, self.start_month)

    # ---- pools ---------------------------------------------------------------------------------------------
    _NP_POOL = re.compile(r"^(?:[A-D]|E(?:[-_ ][A-Za-z0-9][A-Za-z0-9 ._-]{0,30})?)$")

    def pool_code(self, raw: Any) -> str:
        text = str(raw or "").strip()
        if self.code == "NP":
            up = text.upper() if len(text) == 1 else text[:1].upper() + text[1:]
            if not self._NP_POOL.match(up):
                raise ValueError("the pool must be A, B, C, D or E (for several intangibles E-licence, E-software and so on)")
            return up
        if self.code == "IN":
            up = text.upper().replace(" ", "_")
            if up not in india.BLOCKS:
                raise ValueError("the block must be one of: " + ", ".join(india.BLOCKS))
            return up
        return f"{us.recovery_class(text)}-year"

    def pool_choices(self) -> List[Dict[str, str]]:
        if self.code == "NP":
            return [{"code": c, "name": n} for c, n in nepal.POOL_NAMES.items()]
        if self.code == "IN":
            return [{"code": c, "name": n} for c, n in india.BLOCKS.items()]
        return [{"code": f"{c}-year", "name": us.POOL_NAMES[c]} for c in us.CLASSES]

    # ---- inputs --------------------------------------------------------------------------------------------
    def clean_details(self, kind: str, pool: str, details: Any) -> Dict[str, Any]:
        if details is None:
            details = {}
        if not isinstance(details, Mapping):
            raise ValueError("details must be an object")
        d = dict(details)
        out: Dict[str, Any] = {}

        def take_bool(key: str) -> None:
            if key in d:
                v = d.pop(key)
                if not isinstance(v, bool):
                    raise ValueError(f"{key} must be true or false")
                if v:
                    out[key] = True

        def take_amount(key: str, *, required: bool = False, maximum: Optional[Decimal] = None, positive: bool = False) -> None:
            if key in d and d[key] not in (None, ""):
                v = positive_money(d.pop(key), key)
                if positive and v <= 0:
                    raise ValueError(f"{key} must be more than zero")
                if maximum is not None and v > maximum:
                    raise ValueError(f"{key} must be at most {fmt(maximum)}")
                out[key] = fmt(v)
            else:
                d.pop(key, None)
                if required:
                    raise ValueError(f"{key} is required for this {kind.lower()}")

        def take_text(key: str, *, required: bool = False) -> None:
            v = str(d.pop(key, "") or "").strip()
            if len(v) > 60:
                raise ValueError(f"{key} is too long (60 characters at most)")
            if v:
                out[key] = v
            elif required:
                raise ValueError(f"{key} is required for this {kind.lower()}")

        if self.code == "NP":
            e = nepal.is_intangible(pool)
            if kind == OPENING:
                take_amount("deferred")
                if e:
                    take_amount("life_years", required=True, positive=True)
                    take_amount("accumulated")
            elif kind == ADDITION and e:
                take_amount("life_years", required=True, positive=True)
            elif kind == DISPOSAL:
                take_bool("dissolves_pool")
        elif self.code == "IN":
            if kind == DISPOSAL:
                take_bool("block_ceases")
        else:
            if kind == OPENING:
                raise ValueError("MACRS has no opening balance: enter each earlier asset as an addition with its original date, "
                                 "Section 179 and bonus, so its past years are worked out the same way")
            if kind == ADDITION:
                take_text("asset_ref", required=True)
                take_amount("section_179")
                take_amount("bonus_percent", maximum=HUNDRED)
            else:
                take_text("asset_ref", required=True)
        if d:
            raise ValueError(f"{', '.join(sorted(d))} is not used by a {kind.lower()} in this scheme")
        return out

    def clean_movement(self, data: Mapping[str, Any]) -> Dict[str, Any]:
        kind = str(data.get("kind") or "").upper()
        if kind not in KINDS:
            raise ValueError("kind must be OPENING, ADDITION or DISPOSAL")
        pool = self.pool_code(data.get("pool"))
        try:
            when = date.fromisoformat(str(data.get("event_date") or ""))
        except ValueError:
            raise ValueError("the date must be a real date written YYYY-MM-DD (an AD date)") from None
        if not date(1944, 1, 1) <= when <= date(2043, 1, 1):
            raise ValueError("the date is outside the supported range")
        amount = positive_money(data.get("amount"), "amount")
        if kind == ADDITION and amount <= 0:
            raise ValueError("the cost of an addition must be more than zero")
        desc = str(data.get("description") or "").strip()
        if len(desc) > 200:
            raise ValueError("the description is too long (200 characters at most)")
        details = self.clean_details(kind, pool, data.get("details"))
        if kind == OPENING and self.fy_of(when).start != when:
            raise ValueError(f"an opening balance is dated the first day of a fiscal year ({self.fy_of(when).start.isoformat()} "
                             f"for the year containing {when.isoformat()})")
        if self.code == "US" and kind == ADDITION and Decimal(details.get("section_179", "0")) > amount:
            raise ValueError("the Section 179 amount cannot be more than the cost")
        return {"pool": pool, "kind": kind, "event_date": when, "amount": amount, "description": desc, "details": details}

    def clean_rate(self, data: Mapping[str, Any]) -> Dict[str, Any]:
        if self.code == "US":
            raise ValueError("MACRS percentages are the IRS tables and are not edited here")
        pool = self.pool_code(data.get("pool"))
        try:
            rate = Decimal(str(data.get("rate")).strip())
        except Exception:  # noqa: BLE001
            raise ValueError("the rate must be a percent between 0 and 100") from None
        if not rate.is_finite() or not Decimal(0) <= rate <= HUNDRED:
            raise ValueError("the rate must be a percent between 0 and 100")
        if rate.as_tuple().exponent < -6:  # type: ignore[operator]
            raise ValueError("the rate may have at most six decimal places")
        try:
            effective = date.fromisoformat(str(data.get("effective_from") or ""))
        except ValueError:
            raise ValueError("effective_from must be a real date written YYYY-MM-DD (an AD date)") from None
        if not date(1944, 1, 1) <= effective <= date(2043, 1, 1):
            raise ValueError("effective_from is outside the supported range")
        note = str(data.get("note") or "").strip()
        if len(note) > 300:
            raise ValueError("the note is too long (300 characters at most)")
        return {"pool": pool, "rate": rate, "effective_from": effective, "note": note}


# ── reading ─────────────────────────────────────────────────────────────────────────────────────────────────

def _scheme(conn, company_id: str) -> Scheme:
    policy = policy_repo.get_policy(conn, company_id)
    if policy is None:
        raise ValueError("set up the accounting policy first: the tax depreciation scheme follows the company's country")
    code = policy["jurisdiction"]
    if code not in SCHEMES:
        raise ValueError(f"tax depreciation is built for Nepal, India and the United States; this company's country is {code}. "
                         "Change the country in the accounting policy if that is wrong")
    return Scheme(code, policy["calendar"], int(policy["fiscal_year_start_month"]))


def _movement_json(m: Movement, scheme: Scheme) -> Dict[str, Any]:
    return {"id": m.id, "pool": m.pool, "kind": m.kind, "event_date": m.event_date.isoformat(), "amount": fmt(m.amount),
            "description": m.description, "details": dict(m.details), "fiscal_year": scheme.fy_of(m.event_date).label}


def load_movements(conn, company_id: str) -> List[Movement]:
    with conn.cursor() as cur:
        cur.execute("SELECT id, pool_code, kind, event_date, amount, description, details FROM tax_pool_movements "
                    "WHERE company_id = %s ORDER BY event_date, created_at, id", (company_id,))
        return [Movement(pool=r[1], kind=r[2], event_date=r[3], amount=Decimal(r[4]), description=r[5], details=r[6] or {}, id=str(r[0]))
                for r in cur.fetchall()]


def _plain(d: Decimal) -> Decimal:
    """30.000000 -> 30 and 33.330000 -> 33.33 (the column keeps six decimals; the screen should not show them)."""
    n = d.normalize()
    return n.quantize(Decimal(1)) if n.as_tuple().exponent > 0 else n  # type: ignore[operator]


def load_rates(conn, company_id: str) -> List[Tuple[str, RateRow]]:
    with conn.cursor() as cur:
        cur.execute("SELECT id, pool_code, rate, effective_from, note FROM tax_depreciation_rates WHERE company_id = %s "
                    "ORDER BY pool_code, effective_from", (company_id,))
        return [(str(r[0]), RateRow(r[1], _plain(Decimal(r[2])), r[3], r[4], "company")) for r in cur.fetchall()]


def _next_year(fy: FiscalYear, scheme: Scheme) -> FiscalYear:
    return scheme.fy_of(fy.end + timedelta(days=1))


def roll_forward(scheme: Scheme, movements: Sequence[Movement], rates: Sequence[RateRow], target: FiscalYear
                 ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """The target year's rows (and, for the US, its per-asset lines), worked from the first year with any data."""
    if scheme.code == "US":
        upto = [m for m in movements if m.event_date <= target.end]
        return us.compute_year(upto, target, scheme.fy_of)

    mod = scheme.module
    in_scope = [m for m in movements if m.event_date <= target.end]
    if not in_scope:
        return [], []
    fy = scheme.fy_of(min(m.event_date for m in in_scope))
    state: Dict[str, Any] = {}
    rows: List[Dict[str, Any]] = []
    for _ in range(MAX_YEARS):
        if fy.start > target.start:
            break
        this_year = [m for m in in_scope if fy.start <= m.event_date <= fy.end]
        for m in this_year:
            if m.kind == OPENING:
                state[m.pool] = _opening_state(scheme, m)
        flow = [m for m in this_year if m.kind != OPENING]
        if scheme.code == "NP":
            rows, state = mod.compute_year(state, flow, fy, rates)
        else:
            rows, state = mod.compute_year(state, flow, fy, rates)
        fy = _next_year(fy, scheme)
    else:
        raise ValueError("the schedule spans too many years; check the dates entered")
    return rows, []


def _dec(m: Movement, key: str) -> Decimal:
    return Decimal(str(m.details.get(key, "0") or "0"))


def _opening_state(scheme: Scheme, m: Movement) -> Any:
    if scheme.code == "IN":
        return m.amount
    if nepal.is_intangible(m.pool):
        life = nepal.half_year_life(Decimal(str(m.details["life_years"])))
        accumulated = _dec(m, "accumulated")
        return nepal.PoolState(wdv=m.amount, deferred=_dec(m, "deferred"), life_years=life,
                               counted_cost=m.amount + accumulated, accumulated=accumulated)
    return nepal.PoolState(wdv=m.amount, deferred=_dec(m, "deferred"))


def schedule(conn, company_id: str, role: str, on_date: Optional[str] = None) -> Dict[str, Any]:
    """Everything the Tax depreciation screen shows for the fiscal year containing `on_date` (default: today's year)."""
    scheme = _scheme(conn, company_id)
    when = date.fromisoformat(on_date) if on_date else date.today()
    try:
        target = scheme.fy_of(when)
    except ValueError as exc:
        raise ValueError(str(exc)) from None
    movements = load_movements(conn, company_id)
    stored = load_rates(conn, company_id)
    rates = [r for _, r in stored]
    rows, lines = roll_forward(scheme, movements, rates, target)
    mod = scheme.module
    warnings: List[str] = []
    if scheme.calendar == "BS":
        start_year = bs.ad_to_bs(target.start).year
        for y in (start_year, start_year + 1):
            if bs.year_status(y) == "provisional":
                warnings.append(bs.provisional_note(y))
                break
    if not movements:
        warnings.append("Nothing has been entered yet. Add the opening balances and additions for the first year to start the schedule.")
    if any(r.get("rate_source") == "company" for r in rows):
        warnings.append("Some pools use rates this company has set. The rate used is shown on each row.")
    years = sorted({scheme.fy_of(m.event_date).label for m in movements})
    out: Dict[str, Any] = {
        "scheme": scheme.code, "scheme_name": SCHEME_NAMES[scheme.code], "fiscal_year": target.to_json(),
        "pools": rows, "columns": mod.COLUMNS, "totals": mod.totals(rows) if rows else {},
        "lines": lines, "line_columns": us.LINE_COLUMNS if scheme.code == "US" else [],
        "notes": SCHEME_NOTES[scheme.code], "warnings": warnings, "pool_choices": scheme.pool_choices(),
        "rate_presets": list(mod.RATE_PRESETS),
        "standard_rates": [{"pool": r.pool, "rate": fmt(r.rate), "effective_from": r.effective_from.isoformat(), "note": r.note}
                           for r in mod.STANDARD_RATES],
        "company_rates": [{"id": rid, "pool": r.pool, "rate": fmt(r.rate), "effective_from": r.effective_from.isoformat(), "note": r.note}
                          for rid, r in stored],
        "movements": [_movement_json(m, scheme) for m in movements],
        "years_with_data": years, "can_edit": role in WRITE_ROLES, "calendar": scheme.calendar,
    }
    return out


# ── writing ─────────────────────────────────────────────────────────────────────────────────────────────────

def _may_write(role: str) -> None:
    if role not in WRITE_ROLES:
        raise PermissionError(f"your role ({role}) cannot change tax depreciation inputs; allowed roles: {', '.join(sorted(WRITE_ROLES))}")


def _company_lock(conn, company_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"tax_dep:{company_id}",))
        cur.execute("SELECT 1 FROM companies WHERE id = %s", (company_id,))
        if cur.fetchone() is None:
            raise ValueError("company not found")


def _opening_clash(conn, company_id: str, scheme: Scheme, row: Mapping[str, Any], skip_id: Optional[str] = None) -> None:
    if row["kind"] != OPENING:
        return
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM tax_pool_movements WHERE company_id = %s AND pool_code = %s AND kind = 'OPENING' "
                    "AND event_date = %s AND (%s::uuid IS NULL OR id <> %s::uuid)",
                    (company_id, row["pool"], row["event_date"], skip_id, skip_id))
        if cur.fetchone() is not None:
            raise ValueError(f"pool {row['pool']} already has an opening balance for the fiscal year starting {row['event_date'].isoformat()}; "
                             "change that one instead")


def _insert(conn, company_id: str, user_id: str, row: Mapping[str, Any]) -> str:
    with conn.cursor() as cur:
        cur.execute("INSERT INTO tax_pool_movements (company_id, pool_code, kind, event_date, amount, description, details, created_by) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                    (company_id, row["pool"], row["kind"], row["event_date"], row["amount"], row["description"],
                     Jsonb(row["details"]), user_id))
        return str(cur.fetchone()[0])


def _check_computes(conn, company_id: str, scheme: Scheme) -> None:
    """After a change, the whole history must still work (a bad combination is refused rather than saved)."""
    movements = load_movements(conn, company_id)
    if not movements:
        return
    rates = [r for _, r in load_rates(conn, company_id)]
    last = scheme.fy_of(max(m.event_date for m in movements))
    roll_forward(scheme, movements, rates, last)


def add_movement(conn, *, company_id: str, user_id: str, role: str, data: Mapping[str, Any]) -> Dict[str, Any]:
    _may_write(role)
    _company_lock(conn, company_id)
    scheme = _scheme(conn, company_id)
    row = scheme.clean_movement(data)
    _opening_clash(conn, company_id, scheme, row)
    new_id = _insert(conn, company_id, user_id, row)
    _check_computes(conn, company_id, scheme)
    return {"id": new_id, **_row_json(row)}


def add_movements(conn, *, company_id: str, user_id: str, role: str, rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Several inputs at once (pasted from a spreadsheet): all are saved or none."""
    _may_write(role)
    if not isinstance(rows, (list, tuple)) or not rows:
        raise ValueError("there are no rows to add")
    if len(rows) > MAX_BULK_ROWS:
        raise ValueError(f"at most {MAX_BULK_ROWS} rows can be added at once")
    _company_lock(conn, company_id)
    scheme = _scheme(conn, company_id)
    cleaned: List[Dict[str, Any]] = []
    for i, raw in enumerate(rows, start=1):
        try:
            if not isinstance(raw, Mapping):
                raise ValueError("each row must be an object")
            cleaned.append(scheme.clean_movement(raw))
        except ValueError as exc:
            raise ValueError(f"row {i}: {exc}") from None
    seen = set()
    for i, row in enumerate(cleaned, start=1):
        try:
            if row["kind"] == OPENING:
                key = (row["pool"], row["event_date"])
                if key in seen:
                    raise ValueError(f"pool {row['pool']} has two opening balances for {row['event_date'].isoformat()}")
                seen.add(key)
            _opening_clash(conn, company_id, scheme, row)
        except ValueError as exc:
            raise ValueError(f"row {i}: {exc}") from None
    ids = [_insert(conn, company_id, user_id, row) for row in cleaned]
    _check_computes(conn, company_id, scheme)
    return {"added": len(ids), "ids": ids}


def update_movement(conn, *, company_id: str, user_id: str, role: str, movement_id: str, data: Mapping[str, Any]) -> Dict[str, Any]:
    _may_write(role)
    _company_lock(conn, company_id)
    scheme = _scheme(conn, company_id)
    row = scheme.clean_movement(data)
    _opening_clash(conn, company_id, scheme, row, skip_id=movement_id)
    with conn.cursor() as cur:
        cur.execute("UPDATE tax_pool_movements SET pool_code = %s, kind = %s, event_date = %s, amount = %s, description = %s, details = %s "
                    "WHERE id = %s AND company_id = %s RETURNING id",
                    (row["pool"], row["kind"], row["event_date"], row["amount"], row["description"], Jsonb(row["details"]),
                     movement_id, company_id))
        if cur.fetchone() is None:
            raise ValueError("that entry was not found")
    _check_computes(conn, company_id, scheme)
    return {"id": movement_id, **_row_json(row)}


def delete_movement(conn, *, company_id: str, user_id: str, role: str, movement_id: str) -> Dict[str, Any]:
    _may_write(role)
    _company_lock(conn, company_id)
    scheme = _scheme(conn, company_id)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM tax_pool_movements WHERE id = %s AND company_id = %s RETURNING id", (movement_id, company_id))
        if cur.fetchone() is None:
            raise ValueError("that entry was not found")
    _check_computes(conn, company_id, scheme)
    return {"deleted": movement_id}


def set_rate(conn, *, company_id: str, user_id: str, role: str, data: Mapping[str, Any]) -> Dict[str, Any]:
    _may_write(role)
    _company_lock(conn, company_id)
    scheme = _scheme(conn, company_id)
    row = scheme.clean_rate(data)
    with conn.cursor() as cur:
        cur.execute("INSERT INTO tax_depreciation_rates (company_id, pool_code, rate, effective_from, note, created_by) "
                    "VALUES (%s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (company_id, pool_code, effective_from) DO UPDATE SET rate = EXCLUDED.rate, note = EXCLUDED.note "
                    "RETURNING id", (company_id, row["pool"], row["rate"], row["effective_from"], row["note"], user_id))
        rate_id = str(cur.fetchone()[0])
    _check_computes(conn, company_id, scheme)
    return {"id": rate_id, "pool": row["pool"], "rate": fmt(row["rate"]), "effective_from": row["effective_from"].isoformat(),
            "note": row["note"]}


def delete_rate(conn, *, company_id: str, user_id: str, role: str, rate_id: str) -> Dict[str, Any]:
    _may_write(role)
    _company_lock(conn, company_id)
    scheme = _scheme(conn, company_id)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM tax_depreciation_rates WHERE id = %s AND company_id = %s RETURNING id", (rate_id, company_id))
        if cur.fetchone() is None:
            raise ValueError("that rate was not found")
    _check_computes(conn, company_id, scheme)
    return {"deleted": rate_id}


def _row_json(row: Mapping[str, Any]) -> Dict[str, Any]:
    return {"pool": row["pool"], "kind": row["kind"], "event_date": row["event_date"].isoformat(), "amount": fmt(row["amount"]),
            "description": row["description"], "details": dict(row["details"])}