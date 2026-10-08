"""
Database-facing half of impact analysis. Read-only: nothing is written.

A scenario's impact is shown one of two ways, and the report says which:
  live      -- scenarios not yet posted (DRAFT .. APPROVED, DISCARDED):
               recomputed now against the CURRENT ledger. If a simulation was
               saved, `simulation_current` says whether the ledger has moved
               since (False = simulate again before relying on it).
  snapshot  -- POSTED and later: the report frozen when it was simulated.
               Once its adjustments are in the ledger a live recompute would no
               longer show "current vs scenario" correctly, so the frozen
               report is what the reviewers actually approved.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict

from ..dependency_graph import build_ledger_model
from ..scenarios.repository import _hash_overrides, _load, _normalise_overrides, _plain
from .report import build_impact_report

SNAPSHOT_STATUSES = ("POSTED", "FINALIZED", "LOCKED", "REOPEN_REQUESTED")


def scenario_impact(conn, company_id: str, scenario_id: str) -> Dict[str, Any]:
    scenario = _load(conn, company_id, scenario_id)
    saved = scenario["simulation"]
    head = {
        "scenario_id": scenario["id"], "title": scenario["title"], "version": scenario["version"],
        "status": scenario["status"], "period_id": scenario["accounting_period_id"],
        "simulated_at": scenario["simulated_at"],
    }

    if scenario["status"] in SNAPSHOT_STATUSES:
        report = (saved or {}).get("impact")
        if not report:
            raise ValueError("no saved impact report exists for this scenario (it was simulated before impact reports were added)")
        return {**head, "basis": "snapshot",
                "note": "Frozen as simulated and reviewed; the live ledger now includes the posted adjustments.",
                "simulation_current": None, "report": report}

    model = build_ledger_model(conn, company_id, scenario["accounting_period_id"])
    overrides = _normalise_overrides(model, scenario["overrides"])
    decimals = {k: Decimal(v) for k, v in overrides.items()}
    report = _plain(build_impact_report(model, decimals))

    current = None
    if saved:
        fresh_changes = _plain(model.recompute(decimals)["changes"])
        current = saved.get("overrides_hash") == _hash_overrides(overrides) and saved.get("changes") == fresh_changes
    note = ("Not simulated yet: this is a live preview." if not saved else
            "Live against the current ledger." if current else
            "The ledger or the changes have moved since this was simulated; simulate again before relying on it.")
    return {**head, "basis": "live", "note": note, "simulation_current": current, "report": report}


def preview_impact(conn, company_id: str, period_id: str, raw_overrides: Any) -> Dict[str, Any]:
    """Impact of ad-hoc changes without saving a scenario."""
    model = build_ledger_model(conn, company_id, period_id)
    overrides = _normalise_overrides(model, raw_overrides)
    report = _plain(build_impact_report(model, {k: Decimal(v) for k, v in overrides.items()}))
    return {"period_id": period_id, "basis": "preview", "note": "Preview only: nothing is saved.", "report": report}