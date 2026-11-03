"""
Fiscal years and their accounting periods, in the company's own calendar (Phase 24).

Until now the periods were typed in by hand, which is how a Nepali company ends up with "2082-04-01 to 2082-04-30" entered as AD dates.
Here the company's policy (calendar and the month its fiscal year starts) decides exact start and end dates:
  * a BS company's year runs Shrawan 1 to the last day of Ashadh (about 16 July to 16 July) and its months are the BS months,
  * an AD company's year starts on the 1st of its start month and its months are calendar months.
`preview` shows what would be created; `create` creates it, refusing if any of it overlaps a period the company already has.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from ..calendars import bs
from ..calendars.fiscal import FiscalYear, fiscal_months, fiscal_year_containing
from . import repository

CREATE_ROLES = frozenset({"senior_accountant", "ca", "admin"})
SPLITS = ("MONTHLY", "YEARLY")


def _plan(policy: Dict[str, Any], on_date: date, split: str) -> Dict[str, Any]:
    if split not in SPLITS:
        raise ValueError("split must be MONTHLY or YEARLY")
    calendar, start_month = policy["calendar"], int(policy["fiscal_year_start_month"])
    fy: FiscalYear = fiscal_year_containing(on_date, calendar, start_month)
    if split == "MONTHLY":
        periods = [{"label": m["label"], "start": m["start"], "end": m["end"]} for m in fiscal_months(fy)]
    else:
        periods = [{"label": f"FY {fy.label}", "start": fy.start, "end": fy.end}]
    warnings: List[str] = []
    if calendar == "BS":
        year = bs.ad_to_bs(fy.start).year
        for y in (year, year + 1):
            if bs.year_status(y) == "provisional":
                warnings.append(bs.provisional_note(y))
                break
    return {"fiscal_year": fy, "periods": periods, "warnings": warnings}


def _existing(conn, company_id: str) -> List[Dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute("SELECT id, label, period_start, period_end FROM accounting_periods WHERE company_id = %s ORDER BY period_start",
                    (company_id,))
        return [{"id": str(r[0]), "label": r[1], "start": r[2], "end": r[3]} for r in cur.fetchall()]


def _clashes(periods: List[Dict[str, Any]], existing: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    found = []
    for p in periods:
        for e in existing:
            if e["start"] <= p["end"] and e["end"] >= p["start"]:
                found.append({"new": p["label"], "existing": e["label"], "existing_start": e["start"].isoformat(),
                              "existing_end": e["end"].isoformat()})
    return found


def _json(periods: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    out = []
    for p in periods:
        item = {"label": p["label"], "start": p["start"].isoformat(), "end": p["end"].isoformat()}
        if p.get("bs_start"):
            item["bs_start"], item["bs_end"] = p["bs_start"], p["bs_end"]
        out.append(item)
    return out


def _with_bs(plan: Dict[str, Any], calendar: str) -> None:
    if calendar != "BS":
        return
    for p in plan["periods"]:
        p["bs_start"], p["bs_end"] = bs.ad_to_bs(p["start"]).iso(), bs.ad_to_bs(p["end"]).iso()


def preview(conn, company_id: str, on_date: Optional[str] = None, split: str = "MONTHLY") -> Dict[str, Any]:
    policy = repository.get_policy(conn, company_id)
    if policy is None:
        raise ValueError("set up the accounting policy first: the fiscal year follows its calendar and start month")
    when = date.fromisoformat(on_date) if on_date else date.today()
    plan = _plan(policy, when, split)
    _with_bs(plan, policy["calendar"])
    clashes = _clashes(plan["periods"], _existing(conn, company_id))
    return {"fiscal_year": plan["fiscal_year"].to_json(), "split": split, "calendar": policy["calendar"], "periods": _json(plan["periods"]),
            "clashes": clashes, "can_create": not clashes, "warnings": plan["warnings"]}


def create(conn, *, company_id: str, user_id: str, role: str, on_date: str, split: str = "MONTHLY") -> Dict[str, Any]:
    if role not in CREATE_ROLES:
        raise PermissionError(f"your role ({role}) cannot create accounting periods; allowed roles: {', '.join(sorted(CREATE_ROLES))}")
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"periods:{company_id}",))
    policy = repository.get_policy(conn, company_id)
    if policy is None:
        raise ValueError("set up the accounting policy first: the fiscal year follows its calendar and start month")
    plan = _plan(policy, date.fromisoformat(on_date), split)
    clashes = _clashes(plan["periods"], _existing(conn, company_id))
    if clashes:
        c = clashes[0]
        raise ValueError(f"{c['new']} overlaps the existing period {c['existing']} ({c['existing_start']} to {c['existing_end']}); "
                         "nothing was created")
    made = []
    with conn.cursor() as cur:
        for p in plan["periods"]:
            cur.execute("INSERT INTO accounting_periods (company_id, label, period_start, period_end) VALUES (%s, %s, %s, %s) RETURNING id",
                        (company_id, p["label"], p["start"], p["end"]))
            made.append(str(cur.fetchone()[0]))
    _with_bs(plan, policy["calendar"])
    return {"fiscal_year": plan["fiscal_year"].to_json(), "created": len(made), "ids": made, "periods": _json(plan["periods"])}