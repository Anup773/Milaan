"""
Database-facing half of Phase 14: ONE place to see, review and decide everything
that is waiting for an approval, across scenarios and adjustments.

  inbox    what is waiting, oldest first, and for THIS person: can they decide it, and if not, why not
  summary  the dashboard's counts (waiting / waiting on you / waiting on others / decided)
  detail   the review packet for one item: exactly what the approver is being asked to approve
  history  every decision taken, by whom, on whose work, with what note
  decide   take a decision -- checked here, then carried out by the same Phase 7 / Phase 9 code that
           the older endpoints use, in the same transaction (this module changes no table itself)

Nothing here is a new source of truth: items and history are read from the tables the earlier phases
already keep (scenarios, scenario_transitions, adjustments), so there is no migration and nothing
that can disagree with them. The second-person rules are enforced by the earlier phases' own code and
database guards; this layer reports them up front and refuses early with a clear reason.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..adjustments import repository as adj_repo
from ..dependency_graph import build_ledger_model
from ..reconciliation.repository import compact, run_reconciliation
from ..scenarios import repository as scn_repo
from . import policy as pol

SCOPES = ("all", "mine", "waiting")
_PENDING_SCENARIO_STATUSES = {"REVIEW_REQUIRED": pol.KIND_SCENARIO_REVIEW, "POSTED": pol.KIND_FINALIZATION,
                              "REOPEN_REQUESTED": pol.KIND_REOPEN}
_OPEN_EXCEPTION_STATUSES = ["FLAGGED", "UNDER_REVIEW", "EVIDENCE_REQUESTED", "CORRECTION_PENDING"]
MAX_HISTORY_LIMIT = 500


def _now(now: Optional[datetime]) -> datetime:
    return now or datetime.now(timezone.utc)


def _check_actor(actor_role: str) -> None:
    if actor_role not in pol.ROLES:
        raise ValueError(f"role must be one of {', '.join(pol.ROLES)}")


def _people(conn, ids: Sequence[Optional[str]]) -> Dict[str, Dict[str, str]]:
    wanted = sorted({str(i) for i in ids if i})
    if not wanted:
        return {}
    with conn.cursor() as cur:
        cur.execute("SELECT id, email, role::text FROM users WHERE id = ANY(%s::uuid[])", (wanted,))
        return {str(i): {"email": e, "role": r} for i, e, r in cur.fetchall()}


# ── what is waiting ──────────────────────────────────────────────────────
def _pending_raw(conn, company_id: str, period_id: Optional[str]) -> List[Dict[str, Any]]:
    """Every scenario and adjustment currently waiting for a decision, as plain dicts."""
    out: List[Dict[str, Any]] = []
    with conn.cursor() as cur:
        sql = """
            SELECT s.id, s.accounting_period_id, p.label, p.lock_status, s.title, s.description, s.version, s.status,
                   s.created_by, s.reopen_requested_by, s.reopen_requested_at, s.reopen_reason,
                   (SELECT MAX(t.created_at) FROM scenario_transitions t WHERE t.scenario_id = s.id AND t.action = 'submit'),
                   (SELECT MAX(t.created_at) FROM scenario_transitions t WHERE t.scenario_id = s.id AND t.action = 'post')
            FROM scenarios s JOIN accounting_periods p ON p.id = s.accounting_period_id
            WHERE s.company_id = %s AND s.status = ANY(%s)
        """
        params: List[Any] = [company_id, sorted(_PENDING_SCENARIO_STATUSES)]
        if period_id:
            sql += " AND s.accounting_period_id = %s"
            params.append(period_id)
        cur.execute(sql, params)
        for (sid, pid, plabel, lock, title, description, version, status, created_by, reopen_by, reopen_at,
             reopen_reason, submitted_at, posted_at) in cur.fetchall():
            kind = _PENDING_SCENARIO_STATUSES[status]
            made_by, since, note = {
                pol.KIND_SCENARIO_REVIEW: (created_by, submitted_at, description),
                pol.KIND_FINALIZATION: (None, posted_at, description),
                pol.KIND_REOPEN: (reopen_by, reopen_at, reopen_reason),
            }[kind]
            out.append({"kind": kind, "id": str(sid), "title": f"{title} (v{version})", "period_id": str(pid),
                        "period_label": plabel, "period_locked": lock == "LOCKED",
                        "made_by": str(made_by) if made_by else None, "since": since, "note": note or None, "amount": None})

        sql = """
            SELECT a.id, a.accounting_period_id, p.label, p.lock_status, a.description, a.reason, a.proposed_by, a.created_at,
                   COALESCE((SELECT SUM(l.debit) FROM adjustment_lines l WHERE l.adjustment_id = a.id), 0)
            FROM adjustments a JOIN accounting_periods p ON p.id = a.accounting_period_id
            WHERE a.company_id = %s AND a.status = 'REVIEW_REQUIRED'
        """
        params = [company_id]
        if period_id:
            sql += " AND a.accounting_period_id = %s"
            params.append(period_id)
        cur.execute(sql, params)
        for aid, pid, plabel, lock, description, reason, proposed_by, created_at, amount in cur.fetchall():
            out.append({"kind": pol.KIND_ADJUSTMENT, "id": str(aid), "title": description, "period_id": str(pid),
                        "period_label": plabel, "period_locked": lock == "LOCKED", "made_by": str(proposed_by),
                        "since": created_at, "note": reason or None, "amount": amount})
    return out


def _open_scenarios_by_period(conn, company_id: str) -> Dict[str, List[Tuple[str, str, str]]]:
    """period_id -> [(scenario_id, title, status)] for every scenario that is still in progress."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT accounting_period_id, id, title, status FROM scenarios WHERE company_id = %s AND status = ANY(%s)",
            (company_id, list(scn_repo.ACTIVE_STATUSES)),
        )
        out: Dict[str, List[Tuple[str, str, str]]] = {}
        for pid, sid, title, status in cur.fetchall():
            out.setdefault(str(pid), []).append((str(sid), title, status))
        return out


def _finalization_blockers(open_by_period: Dict[str, List[Tuple[str, str, str]]], period_id: str, scenario_id: str) -> List[str]:
    others = [(t, s) for sid, t, s in open_by_period.get(period_id, []) if sid != scenario_id]
    if not others:
        return []
    return ["other scenarios for this period are still open: " + ", ".join(f"'{t}' ({s})" for t, s in others)
            + ". Finish or discard them first"]


def _decisions(kind: str, actor_id: str, actor_role: str, maker_id: Optional[str], period_locked: bool,
               extra_approve_reasons: Sequence[str] = ()) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for decision in pol.spec_for(kind).decisions:
        reasons = pol.blocking_reasons(kind, decision, actor_id=actor_id, actor_role=actor_role, maker_id=maker_id,
                                       period_locked=period_locked)
        if decision == pol.APPROVE:
            reasons = reasons + list(extra_approve_reasons)
        out[decision] = {"allowed": not reasons, "reasons": reasons}
    return out


def _item(raw: Dict[str, Any], company_id: str, actor_id: str, actor_role: str, now: datetime,
          open_by_period: Dict[str, List[Tuple[str, str, str]]]) -> Dict[str, Any]:
    extra = (_finalization_blockers(open_by_period, raw["period_id"], raw["id"])
             if raw["kind"] == pol.KIND_FINALIZATION else [])
    decisions = _decisions(raw["kind"], actor_id, actor_role, raw["made_by"], raw["period_locked"], extra)
    return {
        **{k: raw[k] for k in ("kind", "id", "title", "period_id", "period_label", "period_locked", "made_by", "note", "amount")},
        "label": pol.spec_for(raw["kind"]).label, "waiting_since": raw["since"], "waiting_days": pol.waiting_days(raw["since"], now),
        "is_mine": raw["made_by"] is not None and raw["made_by"] == str(actor_id),
        "can_decide": any(d["allowed"] for d in decisions.values()), "decisions": decisions,
        "decide_via": {"method": "POST", "path": f"/companies/{company_id}/approvals/{raw['kind']}/{raw['id']}/decide"},
    }


def inbox(conn, company_id: str, *, actor_id: str, actor_role: str, period_id: Optional[str] = None,
          kind: Optional[str] = None, scope: str = "all", now: Optional[datetime] = None) -> Dict[str, Any]:
    """
    Everything waiting for a decision, oldest first. scope: "all"; "mine" = what this person can decide
    right now; "waiting" = what this person made and is waiting on somebody else for.
    """
    _check_actor(actor_role)
    if kind is not None:
        pol.spec_for(kind)
    if scope not in SCOPES:
        raise ValueError(f"scope must be one of {', '.join(SCOPES)}")
    now = _now(now)
    open_by_period = _open_scenarios_by_period(conn, company_id)
    items = [_item(r, company_id, actor_id, actor_role, now, open_by_period)
             for r in _pending_raw(conn, company_id, period_id) if kind is None or r["kind"] == kind]
    if scope == "mine":
        items = [i for i in items if i["can_decide"]]
    elif scope == "waiting":
        items = [i for i in items if i["is_mine"]]
    items.sort(key=lambda i: (i["waiting_since"] is None, i["waiting_since"] or now, i["kind"], i["id"]))
    return {"items": items, "count": len(items), "people": _people(conn, [i["made_by"] for i in items]),
            "actor": {"id": str(actor_id), "role": actor_role}}


# ── decided so far ───────────────────────────────────────────────────────
def _decided_counts(conn, company_id: str, period_id: Optional[str]) -> Dict[str, Dict[str, int]]:
    by_kind: Dict[str, Dict[str, int]] = {k: {o: 0 for o in pol.OUTCOMES} for k in pol.KINDS}
    with conn.cursor() as cur:
        sql = ("SELECT t.action, COUNT(*) FROM scenario_transitions t JOIN scenarios s ON s.id = t.scenario_id "
               "WHERE t.company_id = %s AND t.action = ANY(%s)")
        params: List[Any] = [company_id, sorted(pol.SCENARIO_ACTION_OUTCOMES)]
        if period_id:
            sql += " AND s.accounting_period_id = %s"
            params.append(period_id)
        cur.execute(sql + " GROUP BY t.action", params)
        for action, n in cur.fetchall():
            kind, outcome = pol.SCENARIO_ACTION_OUTCOMES[action]
            by_kind[kind][outcome] += n

        sql = "SELECT status, COUNT(*) FROM adjustments WHERE company_id = %s AND reviewed_at IS NOT NULL AND status = ANY(%s)"
        params = [company_id, sorted(pol.ADJUSTMENT_STATUS_OUTCOMES)]
        if period_id:
            sql += " AND accounting_period_id = %s"
            params.append(period_id)
        cur.execute(sql + " GROUP BY status", params)
        for status, n in cur.fetchall():
            by_kind[pol.KIND_ADJUSTMENT][pol.ADJUSTMENT_STATUS_OUTCOMES[status]] += n
    return by_kind


def summary(conn, company_id: str, *, actor_id: str, actor_role: str, period_id: Optional[str] = None,
            now: Optional[datetime] = None) -> Dict[str, Any]:
    """The dashboard card: how much is waiting, how much of it is for you, how much is you waiting on others."""
    waiting = inbox(conn, company_id, actor_id=actor_id, actor_role=actor_role, period_id=period_id, now=now)["items"]
    by_kind = {k: sum(1 for i in waiting if i["kind"] == k) for k in pol.KINDS}
    ages = [i["waiting_days"] for i in waiting if i["waiting_days"] is not None]
    decided = _decided_counts(conn, company_id, period_id)
    totals = {o: sum(decided[k][o] for k in pol.KINDS) for o in pol.OUTCOMES}
    return {"period_id": period_id, "waiting_total": len(waiting), "waiting_by_kind": by_kind,
            "waiting_for_you": sum(1 for i in waiting if i["can_decide"]),
            "waiting_on_others": sum(1 for i in waiting if i["is_mine"]),
            "oldest_waiting_days": max(ages) if ages else None,
            "decided": {"total_by_outcome": totals, "by_kind": decided}}


def history(conn, company_id: str, *, period_id: Optional[str] = None, kind: Optional[str] = None,
            outcome: Optional[str] = None, limit: int = 50, offset: int = 0) -> Dict[str, Any]:
    """Every decision taken, newest first: who decided, on whose work, when, and what they wrote."""
    if kind is not None:
        pol.spec_for(kind)
    if outcome is not None and outcome not in pol.OUTCOMES:
        raise ValueError(f"outcome must be one of {', '.join(pol.OUTCOMES)}")
    limit, offset = max(1, min(int(limit), MAX_HISTORY_LIMIT)), max(0, int(offset))
    want = offset + limit + 1  # one extra, to know whether there is more
    records: List[Dict[str, Any]] = []

    actions = pol.actions_for(kind, outcome)
    statuses = pol.adjustment_statuses_for(kind, outcome)
    with conn.cursor() as cur:
        if actions:
            sql = """
                SELECT t.id, t.created_at, t.action, t.actor_id, t.note, s.id, s.title, s.version, s.accounting_period_id,
                       p.label, s.created_by, s.reopen_requested_by
                FROM scenario_transitions t
                JOIN scenarios s ON s.id = t.scenario_id
                JOIN accounting_periods p ON p.id = s.accounting_period_id
                WHERE t.company_id = %s AND t.action = ANY(%s)
            """
            params: List[Any] = [company_id, actions]
            if period_id:
                sql += " AND s.accounting_period_id = %s"
                params.append(period_id)
            cur.execute(sql + " ORDER BY t.created_at DESC, t.id LIMIT %s", params + [want])
            for tid, at, action, actor, note, sid, title, version, pid, plabel, created_by, reopen_by in cur.fetchall():
                k, o = pol.SCENARIO_ACTION_OUTCOMES[action]
                made_by = {pol.KIND_SCENARIO_REVIEW: created_by, pol.KIND_FINALIZATION: None, pol.KIND_REOPEN: reopen_by}[k]
                records.append({"at": at, "kind": k, "outcome": o, "object_id": str(sid), "title": f"{title} (v{version})",
                                "period_id": str(pid), "period_label": plabel, "decided_by": str(actor),
                                "made_by": str(made_by) if made_by else None, "note": note, "amount": None, "_key": str(tid)})
        if statuses:
            sql = """
                SELECT a.id, a.reviewed_at, a.status, a.reviewed_by, a.rejection_note, a.description, a.accounting_period_id,
                       p.label, a.proposed_by, COALESCE((SELECT SUM(l.debit) FROM adjustment_lines l WHERE l.adjustment_id = a.id), 0)
                FROM adjustments a JOIN accounting_periods p ON p.id = a.accounting_period_id
                WHERE a.company_id = %s AND a.reviewed_at IS NOT NULL AND a.status = ANY(%s)
            """
            params = [company_id, statuses]
            if period_id:
                sql += " AND a.accounting_period_id = %s"
                params.append(period_id)
            cur.execute(sql + " ORDER BY a.reviewed_at DESC, a.id LIMIT %s", params + [want])
            for aid, at, status, reviewer, note, description, pid, plabel, proposer, amount in cur.fetchall():
                records.append({"at": at, "kind": pol.KIND_ADJUSTMENT, "outcome": pol.ADJUSTMENT_STATUS_OUTCOMES[status],
                                "object_id": str(aid), "title": description, "period_id": str(pid), "period_label": plabel,
                                "decided_by": str(reviewer), "made_by": str(proposer), "note": note, "amount": amount,
                                "_key": str(aid)})

    records.sort(key=lambda r: (r["at"], r["_key"]), reverse=True)
    page = records[offset:offset + limit]
    people = _people(conn, [r["decided_by"] for r in page] + [r["made_by"] for r in page])
    for r in page:
        r.pop("_key")
    return {"decisions": page, "has_more": len(records) > offset + limit, "limit": limit, "offset": offset, "people": people}


# ── the review packet ────────────────────────────────────────────────────
def _simulation_is_current(conn, company_id: str, scenario: Dict[str, Any]) -> Tuple[Optional[bool], Optional[str]]:
    """
    Does the saved simulation still match today's ledger? (The same re-run Phase 9's submit does.)
    True / False when it could be checked; (None, why) when it could not -- never a guess.
    """
    saved = scenario.get("simulation")
    if not saved:
        return None, "this scenario has no saved simulation"
    try:
        with conn.transaction():  # a failure here must not spoil the caller's transaction
            model = build_ledger_model(conn, company_id, scenario["accounting_period_id"])
            fresh = scn_repo._run_simulation(model, scn_repo._normalise_overrides(model, scenario["overrides"]))
        return fresh["changes"] == saved.get("changes"), None
    except Exception as exc:  # noqa: BLE001
        return None, f"could not re-check against the ledger: {exc}"


def _open_exceptions(conn, company_id: str, period_id: str) -> Dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*), COUNT(*) FILTER (WHERE priority = 'HIGH') FROM review_exceptions
            WHERE company_id = %s AND accounting_period_id = %s AND status = ANY(%s)
            """,
            (company_id, period_id, _OPEN_EXCEPTION_STATUSES),
        )
        total, high = cur.fetchone()
    return {"open": total, "open_high_priority": high}


def _scenario_packet(conn, company_id: str, kind: str, scenario_id: str, actor_id: str, actor_role: str) -> Dict[str, Any]:
    scn = scn_repo.get_scenario(conn, company_id, scenario_id)
    spec = pol.spec_for(kind)
    sim = scn.get("simulation") or {}
    before, after = sim.get("net_profit_before"), sim.get("net_profit_after")
    packet: Dict[str, Any] = {
        "scenario": {k: scn[k] for k in ("id", "title", "description", "version", "status", "supersedes_id", "superseded_by",
                                         "accounting_period_id", "overrides", "created_by", "created_at", "reviewed_by",
                                         "reviewed_at", "review_note", "finalized_by", "finalized_at", "reopen_requested_by",
                                         "reopen_reason", "reopen_requested_at", "reopen_decided_by", "reopen_decided_at")},
        "period_lock_status": scn["period_lock_status"],
        "linked_adjustments": scn["linked_adjustments"], "transitions": scn["transitions"],
        "headline": {"net_profit_before": before, "net_profit_after": after,
                     "net_profit_change": str(Decimal(str(after)) - Decimal(str(before))) if before is not None and after is not None else None,
                     "balance_check_after": sim.get("balance_check_after"),
                     "nodes_changed": len(sim.get("changes") or []), "overrides_count": len(scn["overrides"] or {})},
    }
    maker_id = {pol.KIND_SCENARIO_REVIEW: scn["created_by"], pol.KIND_FINALIZATION: None,
                pol.KIND_REOPEN: scn["reopen_requested_by"]}[kind]
    extra: List[str] = []
    pending = scn["status"] == spec.pending_status
    period_id = scn["accounting_period_id"]

    if kind == pol.KIND_SCENARIO_REVIEW:
        packet["reconciliation"] = sim.get("reconciliation")
        current, why = _simulation_is_current(conn, company_id, scn)
        packet["simulation_current"] = current
        if why:
            packet["simulation_check_note"] = why
        if current is False:
            extra.append("the ledger has changed since this scenario was simulated; reject it so it can be simulated and submitted again")
        packet["period_exceptions"] = _open_exceptions(conn, company_id, period_id)
    elif kind == pol.KIND_FINALIZATION:
        open_by_period = _open_scenarios_by_period(conn, company_id)
        extra = _finalization_blockers(open_by_period, period_id, scenario_id)
        packet["other_open_scenarios"] = [{"scenario_id": sid, "title": t, "status": s}
                                          for sid, t, s in open_by_period.get(period_id, []) if sid != scenario_id]
        packet["period_exceptions"] = _open_exceptions(conn, company_id, period_id)
        try:
            with conn.transaction():
                packet["reconciliation"] = plain_recon(run_reconciliation(
                    conn, company_id=company_id, period_id=period_id, run_by=actor_id, persist=False))
        except Exception as exc:  # noqa: BLE001
            packet["reconciliation"] = None
            packet["reconciliation_note"] = f"could not run the reconciliation checks: {exc}"
    else:  # reopen
        packet["reopen"] = {"requested_by": scn["reopen_requested_by"], "reason": scn["reopen_reason"],
                            "requested_at": scn["reopen_requested_at"],
                            "if_approved": f"the period reopens and a new DRAFT version {scn['version'] + 1} is created; "
                                           f"version {scn['version']} is kept exactly as it is, marked superseded"}

    decisions = _decisions(kind, actor_id, actor_role, maker_id, scn["period_lock_status"] == "LOCKED", extra)
    if not pending:
        for d in decisions.values():
            d["allowed"] = False
            d["reasons"] = [f"this is no longer awaiting a decision (it is {scn['status']})"]
    packet.update({"kind": kind, "label": spec.label, "pending": pending, "made_by": str(maker_id) if maker_id else None,
                   "decisions": decisions, "can_decide": any(d["allowed"] for d in decisions.values())})
    return packet


def plain_recon(run: Dict[str, Any]) -> Dict[str, Any]:
    """The reconciliation run in its small form, plus the results that need attention (everything but PASS)."""
    small = compact(run)
    small["attention"] = [r for r in small["results"] if r["status"] != "PASS"]
    return small


def _adjustment_packet(conn, company_id: str, adjustment_id: str, actor_id: str, actor_role: str) -> Dict[str, Any]:
    adj = adj_repo.get_adjustment(conn, company_id, adjustment_id)
    with conn.cursor() as cur:
        cur.execute("SELECT id, code, name, account_type FROM accounts WHERE company_id = %s AND id = ANY(%s::uuid[])",
                    (company_id, [l["account_id"] for l in adj["lines"]]))
        accounts = {str(i): {"code": c, "name": n, "account_type": t} for i, c, n, t in cur.fetchall()}
        cur.execute("SELECT label, period_start, period_end, lock_status FROM accounting_periods WHERE company_id = %s AND id = %s",
                    (company_id, adj["accounting_period_id"]))
        label, start, end, lock = cur.fetchone()
        cur.execute(
            "SELECT s.id, s.title, s.version, s.status FROM scenario_adjustments sa JOIN scenarios s ON s.id = sa.scenario_id "
            "WHERE sa.company_id = %s AND sa.adjustment_id = %s ORDER BY s.created_at",
            (company_id, adjustment_id),
        )
        scenarios = [{"scenario_id": str(i), "title": f"{t} (v{v})", "status": s} for i, t, v, s in cur.fetchall()]
        cur.execute(
            """
            SELECT e.id, e.title, e.category, e.status, ea.reverses_journal_entry_id
            FROM exception_adjustments ea JOIN review_exceptions e ON e.id = ea.exception_id
            WHERE ea.company_id = %s AND ea.adjustment_id = %s ORDER BY ea.linked_at
            """,
            (company_id, adjustment_id),
        )
        exceptions = [{"exception_id": str(i), "title": t, "category": c, "status": s,
                       "reverses_journal_entry_id": str(r) if r else None} for i, t, c, s, r in cur.fetchall()]

    lines = [{**l, **accounts.get(l["account_id"], {"code": None, "name": None, "account_type": None})} for l in adj["lines"]]
    total_debit = sum((l["debit"] for l in lines), Decimal("0"))
    total_credit = sum((l["credit"] for l in lines), Decimal("0"))
    pending = adj["status"] == "REVIEW_REQUIRED"
    decisions = _decisions(pol.KIND_ADJUSTMENT, actor_id, actor_role, adj["proposed_by"], lock == "LOCKED")
    if not pending:
        for d in decisions.values():
            d["allowed"] = False
            d["reasons"] = [f"this is no longer awaiting a decision (it is {adj['status']})"]
    return {
        "kind": pol.KIND_ADJUSTMENT, "label": pol.spec_for(pol.KIND_ADJUSTMENT).label, "pending": pending,
        "adjustment": adj, "lines": lines,
        "totals": {"debit": total_debit, "credit": total_credit, "balanced": total_debit == total_credit},
        "period": {"id": adj["accounting_period_id"], "label": label, "start": start, "end": end, "lock_status": lock,
                   "entry_date_in_period": start <= adj["entry_date"] <= end},
        "linked_scenarios": scenarios, "linked_exceptions": exceptions,
        "made_by": adj["proposed_by"], "decisions": decisions, "can_decide": any(d["allowed"] for d in decisions.values()),
    }


def detail(conn, company_id: str, *, kind: str, item_id: str, actor_id: str, actor_role: str) -> Dict[str, Any]:
    """The review packet: what exactly is being approved, what backs it, and whether THIS person can decide it."""
    _check_actor(actor_role)
    pol.spec_for(kind)
    packet = (_adjustment_packet(conn, company_id, item_id, actor_id, actor_role) if kind == pol.KIND_ADJUSTMENT
              else _scenario_packet(conn, company_id, kind, item_id, actor_id, actor_role))
    ids = [packet.get("made_by")]
    if kind == pol.KIND_ADJUSTMENT:
        ids += [packet["adjustment"]["reviewed_by"]]
    else:
        s = packet["scenario"]
        ids += [s["created_by"], s["reviewed_by"], s["finalized_by"], s["reopen_requested_by"], s["reopen_decided_by"]]
        ids += [t["actor_id"] for t in packet["transitions"]]
    packet["people"] = _people(conn, ids)
    return packet


# ── deciding ─────────────────────────────────────────────────────────────
def _decision_context(conn, company_id: str, kind: str, item_id: str) -> Dict[str, Any]:
    with conn.cursor() as cur:
        if kind == pol.KIND_ADJUSTMENT:
            cur.execute(
                "SELECT a.status, a.proposed_by, a.accounting_period_id, p.lock_status FROM adjustments a "
                "JOIN accounting_periods p ON p.id = a.accounting_period_id WHERE a.company_id = %s AND a.id = %s",
                (company_id, item_id))
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"adjustment {item_id} not found for company {company_id}")
            status, maker, pid, lock = row
        else:
            cur.execute(
                "SELECT s.status, s.created_by, s.reopen_requested_by, s.accounting_period_id, p.lock_status FROM scenarios s "
                "JOIN accounting_periods p ON p.id = s.accounting_period_id WHERE s.company_id = %s AND s.id = %s",
                (company_id, item_id))
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"scenario {item_id} not found for company {company_id}")
            status, created_by, reopen_by, pid, lock = row
            maker = {pol.KIND_SCENARIO_REVIEW: created_by, pol.KIND_FINALIZATION: None, pol.KIND_REOPEN: reopen_by}[kind]
    return {"status": status, "maker": str(maker) if maker else None, "period_id": str(pid), "locked": lock == "LOCKED"}


def decide(conn, *, company_id: str, kind: str, item_id: str, decision: str, actor_id: str, actor_role: str,
           note: Optional[str] = None) -> Dict[str, Any]:
    """
    Takes one decision. Checked in this order, each with its own clear message: the decision exists for this kind;
    the thing is still waiting; the person's role and the second-person rule (PermissionError); the period and other
    state (ValueError); a reason for a rejection. Then it is carried out by the earlier phases' own code.
    """
    _check_actor(actor_role)
    spec = pol.spec_for(kind)
    pol.check_decision(kind, decision)
    ctx = _decision_context(conn, company_id, kind, item_id)
    if ctx["status"] != spec.pending_status:
        raise ValueError(f"this {spec.label.lower()} is no longer awaiting a decision (it is {ctx['status']})")

    denied = pol.permission_reasons(kind, decision, actor_id=actor_id, actor_role=actor_role, maker_id=ctx["maker"])
    if denied:
        raise PermissionError("; ".join(denied))
    blocked = pol.state_reasons(kind, decision, period_locked=ctx["locked"])
    if kind == pol.KIND_FINALIZATION:
        blocked += _finalization_blockers(_open_scenarios_by_period(conn, company_id), ctx["period_id"], item_id)
    if blocked:
        raise ValueError("; ".join(blocked))
    pol.check_note(decision, note)

    args = dict(company_id=company_id)
    if kind == pol.KIND_SCENARIO_REVIEW:
        if decision == pol.APPROVE:
            current, _why = _simulation_is_current(conn, company_id, scn_repo.get_scenario(conn, company_id, item_id))
            if current is False:
                raise ValueError("the ledger has changed since this scenario was simulated; reject it so it can be simulated and submitted again")
            result = scn_repo.approve(conn, **args, scenario_id=item_id, actor_id=actor_id, note=note)
        else:
            result = scn_repo.reject(conn, **args, scenario_id=item_id, actor_id=actor_id, note=note)
    elif kind == pol.KIND_FINALIZATION:
        result = scn_repo.finalize(conn, **args, scenario_id=item_id, actor_id=actor_id)
    elif kind == pol.KIND_REOPEN:
        result = scn_repo.decide_reopen(conn, **args, scenario_id=item_id, actor_id=actor_id,
                                        approve_it=(decision == pol.APPROVE), note=note)
    else:
        if decision == pol.APPROVE:
            result = adj_repo.approve_adjustment(conn, **args, adjustment_id=item_id, reviewed_by=actor_id)
        else:
            result = adj_repo.reject_adjustment(conn, **args, adjustment_id=item_id, reviewed_by=actor_id,
                                                rejection_note=(note or "").strip())
    return {"kind": kind, "item_id": item_id, "decision": decision, "decided_by": str(actor_id), "result": result}