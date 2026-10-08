"""
Database-facing half of the scenario engine. state_machine.py decides which
actions are legal; this module loads the scenario, checks the guards that
need data (period open? simulation still true? adjustments posted?), makes
the change, and writes the append-only transition log -- all inside the one
transaction `tenant_connection` gives us, so a failed guard changes nothing.

A scenario never writes to the ledger itself. It reaches POSTED only
through Phase 7 adjustments that have already passed their own
maker-checker approval (linked with link_adjustment).
"""
from __future__ import annotations

import hashlib
import json
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Dict, List, Mapping, Optional

from psycopg.types.json import Jsonb

from ..dependency_graph import build_ledger_model
from ..impact.report import build_impact_report
from ..reconciliation.repository import compact, run_reconciliation
from . import state_machine as sm

CENTS = Decimal("0.01")
ACTIVE_STATUSES = ("DRAFT", "SIMULATED", "REVIEW_REQUIRED", "APPROVED", "POSTED")

_COLUMNS = (
    "id, company_id, accounting_period_id, title, description, version, supersedes_id, superseded_by, "
    "status, overrides, simulation, simulated_at, created_by, reviewed_by, reviewed_at, review_note, "
    "finalized_by, finalized_at, reopen_requested_by, reopen_reason, reopen_requested_at, "
    "reopen_decided_by, reopen_decided_at, created_at, updated_at"
)
_FIELDS = [c.strip() for c in _COLUMNS.split(",")]


# ── helpers ──────────────────────────────────────────────────────────────
def _plain(obj: Any) -> Any:
    """JSON-safe copy (Decimals/dates become strings) for storing in jsonb."""
    return json.loads(json.dumps(obj, default=str))


def _hash_overrides(overrides: Mapping[str, str]) -> str:
    return hashlib.sha256(json.dumps(dict(overrides), sort_keys=True).encode()).hexdigest()


def _row_to_dict(row) -> Dict[str, Any]:
    d = dict(zip(_FIELDS, row))
    for k, v in d.items():
        if k.endswith("_id") or k in ("id", "superseded_by", "created_by", "reviewed_by", "finalized_by",
                                       "reopen_requested_by", "reopen_decided_by"):
            d[k] = str(v) if v is not None else None
    return d


def _load(conn, company_id: str, scenario_id: str, lock: bool = False) -> Dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {_COLUMNS} FROM scenarios WHERE company_id = %s AND id = %s" + (" FOR UPDATE" if lock else ""),
            (company_id, scenario_id),
        )
        row = cur.fetchone()
    if row is None:
        raise ValueError(f"scenario {scenario_id} not found for company {company_id}")
    return _row_to_dict(row)


def _period_lock_status(conn, company_id: str, period_id: str) -> str:
    with conn.cursor() as cur:
        cur.execute("SELECT lock_status FROM accounting_periods WHERE company_id = %s AND id = %s", (company_id, period_id))
        row = cur.fetchone()
    if row is None:
        raise ValueError(f"accounting period {period_id} not found for company {company_id}")
    return row[0]


def _require_period_open(conn, company_id: str, period_id: str) -> None:
    if _period_lock_status(conn, company_id, period_id) != "OPEN":
        raise ValueError("this accounting period is LOCKED; it must be reopened before this can be done")


def _log(conn, company_id: str, scenario_id: str, action: str, from_status: str, to_status: str, actor_id: str, note: Optional[str]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO scenario_transitions (company_id, scenario_id, action, from_status, to_status, actor_id, note)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (company_id, scenario_id, action, from_status, to_status, actor_id, note),
        )


def _begin(conn, company_id: str, scenario_id: str, action: str, actor_id: str, note: Optional[str]):
    """Load + lock the scenario and run the checks every action shares. Returns (scenario, to_status)."""
    scenario = _load(conn, company_id, scenario_id, lock=True)
    to_status = sm.next_status(action, scenario["status"])
    sm.check_note(action, note)
    if action in sm.MAKER_CHECKER:
        sm.check_maker_checker(action, actor_id, scenario[sm.MAKER_CHECKER[action]])
    if action not in sm.ALLOWED_WHEN_LOCKED:
        _require_period_open(conn, company_id, scenario["accounting_period_id"])
    return scenario, to_status


def _normalise_overrides(model, raw: Any) -> Dict[str, str]:
    """Validate {node_id: amount} against the real graph; return {node_id: '123.45'}."""
    if not isinstance(raw, dict) or not raw:
        raise ValueError("overrides must be a non-empty object of {nodeId: amount}")
    out: Dict[str, str] = {}
    for node_id, value in raw.items():
        spec = model.specs.get(node_id)
        if spec is None:
            raise ValueError(f"unknown node: {node_id!r}")
        if not spec.is_leaf:
            raise ValueError(f"{node_id!r} is a computed node; only source (leaf) nodes can be changed")
        if isinstance(value, bool) or value is None:
            raise ValueError(f"override for {node_id!r} must be a number")
        try:
            amount = Decimal(str(value))
        except InvalidOperation:
            raise ValueError(f"override for {node_id!r} is not a valid number")
        if not amount.is_finite():
            raise ValueError(f"override for {node_id!r} is not a valid number")
        out[node_id] = str(amount.quantize(CENTS, rounding=ROUND_HALF_UP))
    return out


def _run_simulation(model, overrides: Mapping[str, str]) -> Dict[str, Any]:
    decimals = {k: Decimal(v) for k, v in overrides.items()}
    result = model.recompute(decimals)
    before, after = model.evaluate(), model.evaluate(decimals)
    return _plain({
        "overrides_hash": _hash_overrides(overrides),
        "changes": result["changes"],
        "downstream_unchanged": result["downstream_unchanged"],
        "net_profit_before": before["pl:net_profit"], "net_profit_after": after["pl:net_profit"],
        "balance_check_before": before["bs:check"], "balance_check_after": after["bs:check"],
        # The full current/scenario/delta report, frozen with the simulation so it
        # can still be shown after posting, when the live ledger has moved on.
        "impact": build_impact_report(model, decimals),
    })


# ── actions ──────────────────────────────────────────────────────────────
def create_scenario(conn, *, company_id: str, period_id: str, title: str, description: str,
                    overrides: Any, created_by: str) -> Dict[str, Any]:
    if not title or not title.strip():
        raise ValueError("title is required")
    _require_period_open(conn, company_id, period_id)
    model = build_ledger_model(conn, company_id, period_id)
    clean = _normalise_overrides(model, overrides)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO scenarios (company_id, accounting_period_id, title, description, overrides, created_by)
            VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
            """,
            (company_id, period_id, title.strip(), (description or "").strip(), Jsonb(clean), created_by),
        )
        scenario_id = str(cur.fetchone()[0])
    _log(conn, company_id, scenario_id, "create", "DRAFT", "DRAFT", created_by, None)
    return {"scenario_id": scenario_id, "status": "DRAFT"}


def update_overrides(conn, *, company_id: str, scenario_id: str, overrides: Any, actor_id: str) -> Dict[str, Any]:
    scenario = _load(conn, company_id, scenario_id, lock=True)
    if scenario["status"] != "DRAFT":
        raise ValueError(f"only a DRAFT can be edited (this one is {scenario['status']}); revise it first")
    _require_period_open(conn, company_id, scenario["accounting_period_id"])
    model = build_ledger_model(conn, company_id, scenario["accounting_period_id"])
    clean = _normalise_overrides(model, overrides)
    with conn.cursor() as cur:
        cur.execute("UPDATE scenarios SET overrides = %s, simulation = NULL, simulated_at = NULL WHERE id = %s",
                    (Jsonb(clean), scenario_id))
    _log(conn, company_id, scenario_id, "edit", "DRAFT", "DRAFT", actor_id, None)
    return {"scenario_id": scenario_id, "status": "DRAFT"}


def simulate(conn, *, company_id: str, scenario_id: str, actor_id: str) -> Dict[str, Any]:
    scenario, to_status = _begin(conn, company_id, scenario_id, "simulate", actor_id, None)
    model = build_ledger_model(conn, company_id, scenario["accounting_period_id"])
    overrides = _normalise_overrides(model, scenario["overrides"])
    simulation = _run_simulation(model, overrides)
    # The reconciliation checks run automatically after every simulation (ARCHITECTURE.md §7),
    # against the scenario's what-if figures, and the verdict is kept with the simulation.
    recon = run_reconciliation(
        conn, company_id=company_id, period_id=scenario["accounting_period_id"], run_by=actor_id,
        scenario_id=scenario_id, overrides={k: Decimal(v) for k, v in overrides.items()}, model=model)
    simulation["reconciliation"] = _plain(compact(recon))
    with conn.cursor() as cur:
        cur.execute("UPDATE scenarios SET status = %s, simulation = %s, simulated_at = now() WHERE id = %s",
                    (to_status, Jsonb(simulation), scenario_id))
    _log(conn, company_id, scenario_id, "simulate", scenario["status"], to_status, actor_id, None)
    return {"scenario_id": scenario_id, "status": to_status, "simulation": simulation}


def revise(conn, *, company_id: str, scenario_id: str, actor_id: str) -> Dict[str, Any]:
    scenario, to_status = _begin(conn, company_id, scenario_id, "revise", actor_id, None)
    with conn.cursor() as cur:
        cur.execute("UPDATE scenarios SET status = %s WHERE id = %s", (to_status, scenario_id))
    _log(conn, company_id, scenario_id, "revise", scenario["status"], to_status, actor_id, None)
    return {"scenario_id": scenario_id, "status": to_status}


def submit(conn, *, company_id: str, scenario_id: str, actor_id: str) -> Dict[str, Any]:
    """
    SIMULATED -> REVIEW_REQUIRED. The checks that run here before a human
    reviewer ever sees it: the simulation must exist, match the saved
    changes, still be true against the CURRENT ledger (re-run and compared),
    and leave the balance sheet balanced. Phase 11's general reconciliation
    framework will add more checks at this same step.
    """
    scenario, to_status = _begin(conn, company_id, scenario_id, "submit", actor_id, None)
    saved = scenario["simulation"]
    if not saved:
        raise ValueError("simulate this scenario before submitting it")
    if saved.get("overrides_hash") != _hash_overrides(scenario["overrides"]):
        raise ValueError("the saved simulation is out of date with the scenario's changes; simulate again")
    if Decimal(str(saved.get("balance_check_after"))) != 0:
        raise ValueError("the simulated balance sheet does not balance; it cannot be submitted for review")

    model = build_ledger_model(conn, company_id, scenario["accounting_period_id"])
    fresh = _run_simulation(model, _normalise_overrides(model, scenario["overrides"]))
    if fresh["changes"] != saved["changes"]:
        raise ValueError("the ledger has changed since this was simulated; simulate again before submitting")
    recon = run_reconciliation(
        conn, company_id=company_id, period_id=scenario["accounting_period_id"], run_by=actor_id,
        scenario_id=scenario_id, overrides={k: Decimal(v) for k, v in scenario["overrides"].items()}, model=model)
    errors = [f"{r['title']} ({r['message']})" for r in recon["results"] if r["status"] == "ERROR"]
    if errors:
        raise ValueError(f"reconciliation found {len(errors)} error(s) that must be fixed before review: " + "; ".join(errors))

    with conn.cursor() as cur:
        cur.execute("UPDATE scenarios SET status = %s WHERE id = %s", (to_status, scenario_id))
    _log(conn, company_id, scenario_id, "submit", scenario["status"], to_status, actor_id, None)
    return {"scenario_id": scenario_id, "status": to_status}


def approve(conn, *, company_id: str, scenario_id: str, actor_id: str, note: Optional[str]) -> Dict[str, Any]:
    scenario, to_status = _begin(conn, company_id, scenario_id, "approve", actor_id, note)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE scenarios SET status = %s, reviewed_by = %s, reviewed_at = now(), review_note = %s WHERE id = %s",
            (to_status, actor_id, (note or "").strip() or None, scenario_id),
        )
    _log(conn, company_id, scenario_id, "approve", scenario["status"], to_status, actor_id, note)
    return {"scenario_id": scenario_id, "status": to_status}


def reject(conn, *, company_id: str, scenario_id: str, actor_id: str, note: str) -> Dict[str, Any]:
    scenario, to_status = _begin(conn, company_id, scenario_id, "reject", actor_id, note)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE scenarios SET status = %s, reviewed_by = NULL, reviewed_at = NULL, review_note = %s WHERE id = %s",
            (to_status, note.strip(), scenario_id),
        )
    _log(conn, company_id, scenario_id, "reject", scenario["status"], to_status, actor_id, note)
    return {"scenario_id": scenario_id, "status": to_status}


def link_adjustment(conn, *, company_id: str, scenario_id: str, adjustment_id: str, actor_id: str) -> Dict[str, Any]:
    scenario = _load(conn, company_id, scenario_id, lock=True)
    if scenario["status"] != "APPROVED":
        raise ValueError(f"adjustments can only be linked to an APPROVED scenario (this one is {scenario['status']})")
    _require_period_open(conn, company_id, scenario["accounting_period_id"])
    with conn.cursor() as cur:
        cur.execute("SELECT accounting_period_id, status FROM adjustments WHERE company_id = %s AND id = %s",
                    (company_id, adjustment_id))
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"adjustment {adjustment_id} not found for company {company_id}")
        if str(row[0]) != scenario["accounting_period_id"]:
            raise ValueError("that adjustment belongs to a different accounting period")
        if row[1] == "REJECTED":
            raise ValueError("a REJECTED adjustment cannot be linked")
        cur.execute(
            """
            INSERT INTO scenario_adjustments (scenario_id, adjustment_id, company_id, linked_by)
            VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING
            """,
            (scenario_id, adjustment_id, company_id, actor_id),
        )
    _log(conn, company_id, scenario_id, "link_adjustment", "APPROVED", "APPROVED", actor_id, f"adjustment {adjustment_id}")
    return {"scenario_id": scenario_id, "adjustment_id": adjustment_id, "status": "APPROVED"}


def post(conn, *, company_id: str, scenario_id: str, actor_id: str) -> Dict[str, Any]:
    """APPROVED -> POSTED, only once the linked adjustments are really posted to the ledger."""
    scenario, to_status = _begin(conn, company_id, scenario_id, "post", actor_id, None)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT a.id, a.status FROM scenario_adjustments sa
            JOIN adjustments a ON a.id = sa.adjustment_id
            WHERE sa.scenario_id = %s ORDER BY a.created_at
            """,
            (scenario_id,),
        )
        linked = cur.fetchall()
    if not linked:
        raise ValueError("link at least one approved adjustment before posting; a scenario reaches the ledger only through adjustments")
    waiting = [str(a) for a, s in linked if s != "POSTED"]
    if waiting:
        raise ValueError(f"{len(waiting)} linked adjustment(s) are not POSTED yet (each needs its own second-person approval)")
    with conn.cursor() as cur:
        cur.execute("UPDATE scenarios SET status = %s WHERE id = %s", (to_status, scenario_id))
    _log(conn, company_id, scenario_id, "post", scenario["status"], to_status, actor_id, f"{len(linked)} adjustment(s) posted")
    return {"scenario_id": scenario_id, "status": to_status, "adjustments": len(linked)}


def finalize(conn, *, company_id: str, scenario_id: str, actor_id: str) -> Dict[str, Any]:
    """POSTED -> FINALIZED -> LOCKED in one step; the accounting period locks with it."""
    scenario, to_status = _begin(conn, company_id, scenario_id, "finalize", actor_id, None)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT title, status FROM scenarios
            WHERE company_id = %s AND accounting_period_id = %s AND id <> %s AND status = ANY(%s)
            """,
            (company_id, scenario["accounting_period_id"], scenario_id, list(ACTIVE_STATUSES)),
        )
        others = cur.fetchall()
    if others:
        names = ", ".join(f"'{t}' ({s})" for t, s in others)
        raise ValueError(f"other scenarios for this period are still open: {names}. Finish or discard them first")

    final_status = sm.AUTO_NEXT[to_status]  # LOCKED
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE scenarios SET status = %s, finalized_by = %s, finalized_at = now() WHERE id = %s",
            (final_status, actor_id, scenario_id),
        )
        cur.execute("UPDATE accounting_periods SET lock_status = 'LOCKED' WHERE company_id = %s AND id = %s",
                    (company_id, scenario["accounting_period_id"]))
    _log(conn, company_id, scenario_id, "finalize", scenario["status"], to_status, actor_id, None)
    _log(conn, company_id, scenario_id, "auto_lock", to_status, final_status, actor_id, "period locked on finalisation")
    return {"scenario_id": scenario_id, "status": final_status, "period_lock_status": "LOCKED"}


def discard(conn, *, company_id: str, scenario_id: str, actor_id: str, note: Optional[str]) -> Dict[str, Any]:
    scenario, to_status = _begin(conn, company_id, scenario_id, "discard", actor_id, note)
    with conn.cursor() as cur:
        cur.execute("UPDATE scenarios SET status = %s WHERE id = %s", (to_status, scenario_id))
    _log(conn, company_id, scenario_id, "discard", scenario["status"], to_status, actor_id, note)
    return {"scenario_id": scenario_id, "status": to_status}


def request_reopen(conn, *, company_id: str, scenario_id: str, actor_id: str, reason: str) -> Dict[str, Any]:
    scenario, to_status = _begin(conn, company_id, scenario_id, "request_reopen", actor_id, reason)
    if scenario["superseded_by"]:
        raise ValueError("this version has already been superseded by a newer one")
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE scenarios SET status = %s, reopen_requested_by = %s, reopen_reason = %s,
                   reopen_requested_at = now(), reopen_decided_by = NULL, reopen_decided_at = NULL
            WHERE id = %s
            """,
            (to_status, actor_id, reason.strip(), scenario_id),
        )
    _log(conn, company_id, scenario_id, "request_reopen", scenario["status"], to_status, actor_id, reason)
    return {"scenario_id": scenario_id, "status": to_status}


def decide_reopen(conn, *, company_id: str, scenario_id: str, actor_id: str, approve_it: bool, note: Optional[str]) -> Dict[str, Any]:
    """
    Deny: back to LOCKED. Approve: the period reopens and a NEW DRAFT version
    is created (carrying the same changes); the locked version is kept
    exactly as it was and marked superseded -- never edited in place.
    """
    action = "approve_reopen" if approve_it else "deny_reopen"
    scenario, to_status = _begin(conn, company_id, scenario_id, action, actor_id, note)

    if not approve_it:
        with conn.cursor() as cur:
            cur.execute("UPDATE scenarios SET status = %s, reopen_decided_by = %s, reopen_decided_at = now() WHERE id = %s",
                        (to_status, actor_id, scenario_id))
        _log(conn, company_id, scenario_id, action, scenario["status"], to_status, actor_id, note)
        return {"scenario_id": scenario_id, "status": to_status, "reopened": False}

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO scenarios (company_id, accounting_period_id, title, description, version,
                                   supersedes_id, overrides, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
            """,
            (company_id, scenario["accounting_period_id"], scenario["title"], scenario["description"],
             scenario["version"] + 1, scenario_id, Jsonb(scenario["overrides"]), scenario["reopen_requested_by"]),
        )
        new_id = str(cur.fetchone()[0])
        cur.execute(
            "UPDATE scenarios SET status = %s, superseded_by = %s, reopen_decided_by = %s, reopen_decided_at = now() WHERE id = %s",
            (to_status, new_id, actor_id, scenario_id),
        )
        cur.execute("UPDATE accounting_periods SET lock_status = 'OPEN' WHERE company_id = %s AND id = %s",
                    (company_id, scenario["accounting_period_id"]))
    _log(conn, company_id, scenario_id, action, scenario["status"], to_status, actor_id, (note or "").strip() or f"reopened; superseded by {new_id}")
    _log(conn, company_id, new_id, "create", "DRAFT", "DRAFT", scenario["reopen_requested_by"],
         f"version {scenario['version'] + 1}, reopened from {scenario_id}")
    return {"scenario_id": scenario_id, "status": to_status, "reopened": True, "new_version_id": new_id,
            "new_version": scenario["version"] + 1}


# ── reads ────────────────────────────────────────────────────────────────
def get_scenario(conn, company_id: str, scenario_id: str) -> Dict[str, Any]:
    scenario = _load(conn, company_id, scenario_id)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT action, from_status, to_status, actor_id, note, created_at FROM scenario_transitions "
            "WHERE scenario_id = %s ORDER BY created_at, id",
            (scenario_id,),
        )
        transitions = [{"action": a, "from_status": f, "to_status": t, "actor_id": str(u), "note": n, "at": c}
                       for a, f, t, u, n, c in cur.fetchall()]
        cur.execute(
            "SELECT a.id, a.status, a.description FROM scenario_adjustments sa JOIN adjustments a ON a.id = sa.adjustment_id "
            "WHERE sa.scenario_id = %s ORDER BY a.created_at",
            (scenario_id,),
        )
        adjustments = [{"adjustment_id": str(i), "status": s, "description": d} for i, s, d in cur.fetchall()]
    scenario["transitions"] = transitions
    scenario["linked_adjustments"] = adjustments
    scenario["period_lock_status"] = _period_lock_status(conn, company_id, scenario["accounting_period_id"])
    scenario["available_actions"] = sm.available_actions(scenario["status"])
    return scenario


def list_scenarios(conn, company_id: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
    if status is not None and status not in sm.ALL_STATUSES:
        raise ValueError(f"status must be one of {', '.join(sorted(sm.ALL_STATUSES))}")
    sql = ("SELECT id, accounting_period_id, title, version, status, superseded_by, created_by, created_at "
           "FROM scenarios WHERE company_id = %s")
    params: list = [company_id]
    if status:
        sql += " AND status = %s"
        params.append(status)
    sql += " ORDER BY created_at DESC"
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return [{"scenario_id": str(i), "period_id": str(p), "title": t, "version": v, "status": s,
             "superseded_by": str(sb) if sb else None, "created_by": str(cb), "created_at": ca}
            for i, p, t, v, s, sb, cb, ca in rows]
