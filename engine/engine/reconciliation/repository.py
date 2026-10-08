"""
Runs the registered rules, keeps the history, and reads it back.

Every run is stored (migration 0008, append-only): which rules ran, what
each said, who ran it, when, and -- for a scenario -- that it was checked
against the scenario's what-if figures.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Mapping, Optional

from psycopg.types.json import Jsonb

from . import rules as _rules  # noqa: F401 -- importing registers the built-in rules
from .registry import ReconContext, catalog, run_rules, summarize
from ..scenarios_json import plain


def run_reconciliation(conn, *, company_id: str, period_id: str, run_by: str,
                       scenario_id: Optional[str] = None, overrides: Optional[Mapping[str, Decimal]] = None,
                       model=None, persist: bool = True) -> Dict[str, Any]:
    ctx = ReconContext(conn, company_id, period_id, overrides, model)
    ctx.period  # fail early, clearly, if the period isn't this company's
    results = run_rules(ctx)
    summary = summarize(results)
    rows = [plain({"rule_id": r.rule_id, "title": r.title, "status": r.status,
                   "message": r.message, "details": dict(r.details)}) for r in results]
    out: Dict[str, Any] = {"period_id": period_id, "scenario_id": scenario_id,
                           "with_overrides": bool(overrides), **summary, "results": rows}

    if persist:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO reconciliation_runs
                    (company_id, accounting_period_id, scenario_id, with_overrides, run_by, overall_status, counts)
                VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id, run_at
                """,
                (company_id, period_id, scenario_id, bool(overrides), run_by, summary["overall_status"], Jsonb(summary["counts"])),
            )
            run_id, run_at = cur.fetchone()
            for i, r in enumerate(rows):
                cur.execute(
                    """
                    INSERT INTO reconciliation_results (company_id, run_id, sort_order, rule_id, title, status, message, details)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (company_id, run_id, i, r["rule_id"], r["title"], r["status"], r["message"], Jsonb(r["details"])),
                )
        out["run_id"], out["run_at"] = str(run_id), run_at
    return out


def compact(run: Mapping[str, Any]) -> Dict[str, Any]:
    """Small form of a run, for embedding in a scenario's saved simulation."""
    return {"run_id": run.get("run_id"), "overall_status": run["overall_status"], "counts": run["counts"],
            "results": [{"rule_id": r["rule_id"], "title": r["title"], "status": r["status"], "message": r["message"]}
                        for r in run["results"]]}


def failing_titles(run: Mapping[str, Any], status: str = "ERROR") -> List[str]:
    return [r["title"] for r in run["results"] if r["status"] == status]


def get_run(conn, company_id: str, run_id: str) -> Dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, accounting_period_id, scenario_id, with_overrides, run_by, run_at, overall_status, counts
            FROM reconciliation_runs WHERE company_id = %s AND id = %s
            """,
            (company_id, run_id),
        )
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"reconciliation run {run_id} not found for company {company_id}")
        cur.execute(
            "SELECT rule_id, title, status, message, details FROM reconciliation_results WHERE run_id = %s ORDER BY sort_order",
            (run_id,),
        )
        results = [{"rule_id": a, "title": b, "status": c, "message": d, "details": e} for a, b, c, d, e in cur.fetchall()]
    rid, pid, sid, wo, by, at, overall, counts = row
    return {"run_id": str(rid), "period_id": str(pid), "scenario_id": str(sid) if sid else None,
            "with_overrides": wo, "run_by": str(by), "run_at": at, "overall_status": overall,
            "counts": counts, "results": results}


def list_runs(conn, company_id: str, period_id: str, limit: int = 25) -> List[Dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, scenario_id, with_overrides, run_by, run_at, overall_status, counts
            FROM reconciliation_runs WHERE company_id = %s AND accounting_period_id = %s
            ORDER BY run_at DESC, id LIMIT %s
            """,
            (company_id, period_id, limit),
        )
        return [{"run_id": str(i), "scenario_id": str(s) if s else None, "with_overrides": w,
                 "run_by": str(b), "run_at": a, "overall_status": o, "counts": c}
                for i, s, w, b, a, o, c in cur.fetchall()]


def latest_run(conn, company_id: str, period_id: str) -> Optional[Dict[str, Any]]:
    """The most recent run of the books as posted (not scenario what-ifs)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id FROM reconciliation_runs
            WHERE company_id = %s AND accounting_period_id = %s AND scenario_id IS NULL
            ORDER BY run_at DESC, id LIMIT 1
            """,
            (company_id, period_id),
        )
        row = cur.fetchone()
    return get_run(conn, company_id, str(row[0])) if row else None


def rule_catalog() -> List[Dict[str, str]]:
    return catalog()