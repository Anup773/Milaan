"""
Database-facing half of Phase 12. state_machine.py decides which actions are
legal, planner.py decides what a detection run does with its findings, rules.py
decides what is worth flagging; this module loads and writes, all inside the
one transaction `tenant_connection` gives us, so a failed guard changes nothing.

What this module can and cannot do to the books:
  * It NEVER writes to journal_entries / journal_lines.
  * A "Correct" or "Reverse" decision only parks the flag in CORRECTION_PENDING.
    The ledger changes only when a Phase 7 adjustment is posted -- and that
    adjustment needs a second person's approval (propose_adjustment /
    approve_adjustment are reused here, not re-implemented).
  * Detection never overrides a person's decision, never deletes a flag, and
    never says what a flag means.
"""
from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional

from psycopg.types.json import Jsonb

from ..adjustments.repository import propose_adjustment
from ..ledger.reports import _period_dates
from ..scenarios_json import plain
from . import rules as _rules  # noqa: F401 -- importing registers the built-in detectors
from . import state_machine as sm
from .dataset import entry_summary  # noqa: F401 -- re-exported for callers building their own details
from .planner import ExistingException, plan_detection
from .registry import CATEGORIES, PRIORITIES, PRIORITY_RANK, DetectionContext, Thresholds, catalog, run_detectors

_COLUMNS = (
    "id, company_id, accounting_period_id, rule_id, category, source, fingerprint, title, message, priority, "
    "journal_entry_id, related_entry_ids, amount, details, status, detected_run_id, raised_by, assigned_to, "
    "decision, decision_note, decided_by, decided_at, created_at, updated_at"
)
_FIELDS = [c.strip() for c in _COLUMNS.split(",")]
_ID_FIELDS = ("id", "company_id", "accounting_period_id", "journal_entry_id", "detected_run_id",
              "raised_by", "assigned_to", "decided_by")


# ── helpers ──────────────────────────────────────────────────────────────
def _uuids(values) -> List[uuid.UUID]:
    return [uuid.UUID(str(v)) for v in values]


def _row_to_dict(row) -> Dict[str, Any]:
    d = dict(zip(_FIELDS, row))
    for k in _ID_FIELDS:
        d[k] = str(d[k]) if d[k] is not None else None
    d["related_entry_ids"] = [str(x) for x in (d["related_entry_ids"] or [])]
    return d


def _load(conn, company_id: str, exception_id: str, lock: bool = False) -> Dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {_COLUMNS} FROM review_exceptions WHERE company_id = %s AND id = %s" + (" FOR UPDATE" if lock else ""),
            (company_id, exception_id),
        )
        row = cur.fetchone()
    if row is None:
        raise ValueError(f"exception {exception_id} not found for company {company_id}")
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
        raise ValueError("this accounting period is LOCKED; it must be reopened before a correction can be made")


def _log(conn, company_id: str, exception_id: str, action: str, from_status: Optional[str], to_status: str,
         actor_id: str, note: Optional[str], run_id: Optional[str] = None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO exception_transitions (company_id, exception_id, action, from_status, to_status, actor_id, note, run_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (company_id, exception_id, action, from_status, to_status, actor_id, note, run_id),
        )


def _linked_adjustments(conn, company_id: str, exception_id: str) -> List[Dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT a.id, a.status, a.description, ea.reverses_journal_entry_id, ea.linked_by, ea.linked_at
            FROM exception_adjustments ea JOIN adjustments a ON a.id = ea.adjustment_id
            WHERE ea.company_id = %s AND ea.exception_id = %s ORDER BY ea.linked_at, a.id
            """,
            (company_id, exception_id),
        )
        return [{"adjustment_id": str(i), "status": s, "description": d,
                 "reverses_journal_entry_id": str(r) if r else None, "linked_by": str(lb), "linked_at": la}
                for i, s, d, r, lb, la in cur.fetchall()]


# ── detection ────────────────────────────────────────────────────────────
def detect(conn, *, company_id: str, period_id: str, run_by: str, today: Optional[date] = None,
           thresholds: Optional[Thresholds] = None) -> Dict[str, Any]:
    """
    Runs every detector on one period and brings the flags up to date. The run
    itself is saved (append-only), with one outcome per rule -- CHECKED,
    NOT_CHECKED or ERROR -- so a check that could not run is visible, never
    silently a clean bill of health.
    """
    with conn.cursor() as cur:
        # One detection at a time per company+period, so two overlapping runs cannot both decide "new".
        cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"exceptions:{company_id}:{period_id}",))

    ctx = DetectionContext(conn, company_id, period_id, today, thresholds)
    ctx.dataset  # fail early, clearly, if the period isn't this company's
    outcomes = run_detectors(ctx)

    # Lock this period's flags while we update them, so a reviewer acting at the same moment
    # waits for us instead of racing us (and every status we log below is the true one).
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, fingerprint, rule_id, source, status FROM review_exceptions
            WHERE company_id = %s AND accounting_period_id = %s FOR UPDATE
            """,
            (company_id, period_id),
        )
        existing = {fp: ExistingException(str(i), fp, rid, src, st) for i, fp, rid, src, st in cur.fetchall()}

    plan = plan_detection(outcomes, existing)
    open_before = sum(1 for e in existing.values() if e.status in sm.OPEN_STATUSES)
    counts = {
        "findings": plan.findings_total, "new": len(plan.new), "redetected": len(plan.redetected),
        "already_known": len(plan.known), "cleared": len(plan.to_clear),
        "open_after": open_before + len(plan.new) + len(plan.redetected) - len(plan.to_clear),
    }
    rules_out = [{"rule_id": o.rule_id, "category": o.category, "title": o.title, "status": o.status,
                  "message": o.message, "findings": len(o.findings)} for o in outcomes]

    new_exceptions: List[Dict[str, Any]] = []
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO exception_runs (company_id, accounting_period_id, run_by, counts, rule_outcomes)
            VALUES (%s, %s, %s, %s, %s) RETURNING id, run_at
            """,
            (company_id, period_id, run_by, Jsonb(counts), Jsonb(rules_out)),
        )
        run_id, run_at = cur.fetchone()
        run_id = str(run_id)

        for f in plan.new:
            cur.execute(
                """
                INSERT INTO review_exceptions
                    (company_id, accounting_period_id, rule_id, category, source, fingerprint, title, message, priority,
                     journal_entry_id, related_entry_ids, amount, details, detected_run_id)
                VALUES (%s, %s, %s, %s, 'DETECTED', %s, %s, %s, %s, %s, %s::uuid[], %s, %s, %s)
                ON CONFLICT (company_id, accounting_period_id, fingerprint) DO NOTHING
                RETURNING id
                """,
                (company_id, period_id, f.rule_id, f.category, f.fingerprint, f.title, f.message, f.priority,
                 f.journal_entry_id, _uuids(f.related_entry_ids), f.amount, Jsonb(plain(dict(f.details))), run_id),
            )
            row = cur.fetchone()
            if row is None:
                raise ValueError("another change touched these exceptions while detection was running; run detection again")
            exception_id = str(row[0])
            _log(conn, company_id, exception_id, "flag", None, sm.FLAGGED, run_by, f"found by {f.rule_id}", run_id)
            new_exceptions.append({"id": exception_id, "category": f.category, "title": f.title,
                                   "priority": f.priority, "journal_entry_id": f.journal_entry_id})

        for current, f in plan.redetected:
            cur.execute(
                """
                UPDATE review_exceptions
                SET status = 'FLAGGED', assigned_to = NULL, decision = NULL, decision_note = NULL,
                    decided_by = NULL, decided_at = NULL,
                    title = %s, message = %s, priority = %s, amount = %s, details = %s, updated_at = now()
                WHERE company_id = %s AND id = %s AND status = 'CLEARED' RETURNING id
                """,
                (f.title, f.message, f.priority, f.amount, Jsonb(plain(dict(f.details))), company_id, current.id),
            )
            if cur.fetchone() is None:
                raise ValueError("another change touched these exceptions while detection was running; run detection again")
            _log(conn, company_id, current.id, "redetect", sm.CLEARED, sm.FLAGGED, run_by,
                 f"detected again by {f.rule_id}", run_id)
            new_exceptions.append({"id": current.id, "category": f.category, "title": f.title,
                                   "priority": f.priority, "journal_entry_id": f.journal_entry_id})

        for current, f in plan.known:
            if current.status == sm.FLAGGED:  # nobody has looked yet: keep the wording and figures current
                cur.execute(
                    """
                    UPDATE review_exceptions
                    SET title = %s, message = %s, priority = %s, amount = %s, details = %s, updated_at = now()
                    WHERE company_id = %s AND id = %s AND status = 'FLAGGED'
                    """,
                    (f.title, f.message, f.priority, f.amount, Jsonb(plain(dict(f.details))), company_id, current.id),
                )

        for current in plan.to_clear:
            cur.execute(
                """
                UPDATE review_exceptions
                SET status = 'CLEARED', decision = NULL, decision_note = NULL, decided_by = NULL, decided_at = NULL,
                    updated_at = now()
                WHERE company_id = %s AND id = %s AND status = %s RETURNING id
                """,
                (company_id, current.id, current.status),
            )
            if cur.fetchone() is None:
                raise ValueError("another change touched these exceptions while detection was running; run detection again")
            _log(conn, company_id, current.id, "clear", current.status, sm.CLEARED, run_by,
                 f"no longer detected by {current.rule_id}", run_id)

    return {"run_id": run_id, "run_at": run_at, "period_id": period_id, "counts": counts,
            "rules": rules_out, "new_exceptions": new_exceptions}


def raise_manual(conn, *, company_id: str, journal_entry_id: str, note: str, raised_by: str,
                 title: Optional[str] = None, priority: str = "MEDIUM") -> Dict[str, Any]:
    """A person flags an entry the detectors did not (category OTHER). The period is the entry's own."""
    if not note or not note.strip():
        raise ValueError("a note saying why this entry needs review is required")
    if priority not in PRIORITIES:
        raise ValueError(f"priority must be one of {', '.join(PRIORITIES)}")

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT je.accounting_period_id, je.entry_date, je.description, COALESCE(SUM(jl.debit), 0)
            FROM journal_entries je LEFT JOIN journal_lines jl ON jl.journal_entry_id = je.id
            WHERE je.company_id = %s AND je.id = %s
            GROUP BY je.id
            """,
            (company_id, journal_entry_id),
        )
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"journal entry {journal_entry_id} not found for company {company_id}")
        period_id, entry_date, description, total = row
        period_id = str(period_id)
        clean_title = (title or "").strip() or "Flagged for review by a person"
        details = {"raised_note": note.strip(),
                   "entry": {"journal_entry_id": journal_entry_id, "entry_date": entry_date.isoformat(),
                             "description": description, "amount": total}}
        cur.execute(
            """
            INSERT INTO review_exceptions
                (company_id, accounting_period_id, rule_id, category, source, fingerprint, title, message, priority,
                 journal_entry_id, related_entry_ids, amount, details, raised_by)
            VALUES (%s, %s, 'manual', 'OTHER', 'MANUAL', %s, %s, %s, %s, %s, %s::uuid[], %s, %s, %s) RETURNING id
            """,
            (company_id, period_id, f"manual:{uuid.uuid4()}", clean_title, note.strip(), priority,
             journal_entry_id, _uuids([journal_entry_id]), total, Jsonb(plain(details)), raised_by),
        )
        exception_id = str(cur.fetchone()[0])
    _log(conn, company_id, exception_id, "flag", None, sm.FLAGGED, raised_by, note.strip())
    return {"exception_id": exception_id, "status": sm.FLAGGED, "period_id": period_id}


# ── the review actions ───────────────────────────────────────────────────
def act(conn, *, company_id: str, exception_id: str, action: str, actor_id: str, note: Optional[str] = None) -> Dict[str, Any]:
    """claim / request_evidence / evidence_received / retain / correct / reverse / resolve / reopen."""
    ex = _load(conn, company_id, exception_id, lock=True)
    to_status = sm.next_status(action, ex["status"])
    sm.check_note(action, note)
    sm.check_maker_checker(action, actor_id, ex["raised_by"])
    if action in sm.REQUIRES_OPEN_PERIOD:
        _require_period_open(conn, company_id, ex["accounting_period_id"])
    text = (note or "").strip() or None

    linked = _linked_adjustments(conn, company_id, exception_id) if action in ("resolve", "reopen") else []
    if action == "resolve":
        if not linked:
            raise ValueError("link or propose at least one adjustment before resolving; a correction reaches the ledger only through adjustments")
        waiting = [a for a in linked if a["status"] == "REVIEW_REQUIRED"]
        if waiting:
            raise ValueError(f"{len(waiting)} linked adjustment(s) are still waiting for a second person's approval")
        if not any(a["status"] == "POSTED" for a in linked):
            raise ValueError("none of the linked adjustments was posted (they were all rejected); propose another, or reopen the exception")
    if action == "reopen" and ex["status"] == sm.CORRECTION_PENDING:
        live = [a for a in linked if a["status"] in ("POSTED", "REVIEW_REQUIRED")]
        if live:
            raise ValueError("a correction is already pending or posted for this exception; reject the pending adjustment first "
                             "(a posted adjustment cannot be withdrawn)")

    with conn.cursor() as cur:
        if action == "claim":
            cur.execute("UPDATE review_exceptions SET status = %s, assigned_to = %s, updated_at = now() WHERE id = %s",
                        (to_status, actor_id, exception_id))
        elif action in sm.DECISION_FOR:
            cur.execute(
                """
                UPDATE review_exceptions
                SET status = %s, decision = %s, decision_note = %s, decided_by = %s, decided_at = now(), updated_at = now()
                WHERE id = %s
                """,
                (to_status, sm.DECISION_FOR[action], text, actor_id, exception_id),
            )
        elif action in ("evidence_received", "reopen"):
            cur.execute(
                """
                UPDATE review_exceptions
                SET status = %s, decision = NULL, decision_note = NULL, decided_by = NULL, decided_at = NULL, updated_at = now()
                WHERE id = %s
                """,
                (to_status, exception_id),
            )
        else:  # resolve: the decision (Correct / Reverse) stays on record
            cur.execute("UPDATE review_exceptions SET status = %s, updated_at = now() WHERE id = %s", (to_status, exception_id))

    _log(conn, company_id, exception_id, action, ex["status"], to_status, actor_id, text)
    return {"exception_id": exception_id, "status": to_status, "available_actions": sm.available_actions(to_status)}


def link_adjustment(conn, *, company_id: str, exception_id: str, adjustment_id: str, actor_id: str) -> Dict[str, Any]:
    """Ties an existing Phase 7 adjustment to a flag being corrected (the 'if changed -> adjustment' step of §7)."""
    ex = _load(conn, company_id, exception_id, lock=True)
    if ex["status"] != sm.CORRECTION_PENDING:
        raise ValueError(f"adjustments can only be linked to an exception awaiting correction (this one is {ex['status']})")
    _require_period_open(conn, company_id, ex["accounting_period_id"])
    with conn.cursor() as cur:
        cur.execute("SELECT accounting_period_id, status FROM adjustments WHERE company_id = %s AND id = %s",
                    (company_id, adjustment_id))
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"adjustment {adjustment_id} not found for company {company_id}")
        if str(row[0]) != ex["accounting_period_id"]:
            raise ValueError("that adjustment belongs to a different accounting period")
        if row[1] == "REJECTED":
            raise ValueError("a REJECTED adjustment cannot be linked")
        cur.execute(
            """
            INSERT INTO exception_adjustments (exception_id, adjustment_id, company_id, linked_by)
            VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING
            """,
            (exception_id, adjustment_id, company_id, actor_id),
        )
    _log(conn, company_id, exception_id, "link_adjustment", sm.CORRECTION_PENDING, sm.CORRECTION_PENDING, actor_id,
         f"adjustment {adjustment_id}")
    return {"exception_id": exception_id, "adjustment_id": adjustment_id, "status": sm.CORRECTION_PENDING}


def propose_reversal(conn, *, company_id: str, exception_id: str, actor_id: str, entry_date: Any = None,
                     reason: Optional[str] = None, journal_entry_id: Optional[str] = None) -> Dict[str, Any]:
    """
    For a flag decided REVERSE: builds the mirror-image entry (every debit becomes a
    credit and vice versa) and proposes it as a normal Phase 7 adjustment, linked
    to this exception. It lands in REVIEW_REQUIRED: someone other than the proposer
    must approve it before anything reaches the ledger.
    """
    ex = _load(conn, company_id, exception_id, lock=True)
    if ex["status"] != sm.CORRECTION_PENDING or ex["decision"] != "REVERSE":
        raise ValueError("a reversal can only be proposed for an exception decided REVERSE and awaiting correction "
                         f"(this one is {ex['status']}" + (f", decision {ex['decision']}" if ex["decision"] else "") + ")")
    period_id = ex["accounting_period_id"]
    _require_period_open(conn, company_id, period_id)

    target = str(journal_entry_id) if journal_entry_id else ex["journal_entry_id"]
    if target not in {ex["journal_entry_id"], *ex["related_entry_ids"]}:
        raise ValueError("that entry is not one of the entries this flag is about")

    start, end, _ = _period_dates(conn, company_id, period_id)
    with conn.cursor() as cur:
        cur.execute("SELECT entry_date, description FROM journal_entries WHERE company_id = %s AND id = %s", (company_id, target))
        head = cur.fetchone()
        if head is None:
            raise ValueError(f"journal entry {target} not found for company {company_id}")
        original_date, original_description = head
        cur.execute("SELECT account_id, debit, credit FROM journal_lines WHERE company_id = %s AND journal_entry_id = %s ORDER BY id",
                    (company_id, target))
        original_lines = cur.fetchall()
        if not original_lines:
            raise ValueError("that entry has no lines to reverse")
        cur.execute(
            """
            SELECT 1 FROM exception_adjustments ea JOIN adjustments a ON a.id = ea.adjustment_id
            WHERE ea.company_id = %s AND ea.reverses_journal_entry_id = %s AND a.status <> 'REJECTED'
            """,
            (company_id, target),
        )
        if cur.fetchone() is not None:
            raise ValueError("this entry already has a reversal that is pending approval or posted")

    if entry_date is None:
        when = original_date if start <= original_date <= end else end
    else:
        try:
            when = entry_date if isinstance(entry_date, date) else date.fromisoformat(str(entry_date))
        except ValueError:
            raise ValueError("entryDate must be a date in YYYY-MM-DD form")
    if not (start <= when <= end):
        raise ValueError(f"the reversal date must fall inside the exception's accounting period ({start.isoformat()} to {end.isoformat()})")

    why = (reason or "").strip() or f"Reversal after review of exception {exception_id}: {ex['decision_note'] or 'decided REVERSE'}"
    result = propose_adjustment(
        conn, company_id=company_id, period_id=period_id, entry_date=when,
        description=f"Reversal of: {original_description or target}", reason=why,
        lines=[{"account_id": str(acc), "debit": credit, "credit": debit} for acc, debit, credit in original_lines],
        proposed_by=actor_id,
    )
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO exception_adjustments (exception_id, adjustment_id, company_id, linked_by, reverses_journal_entry_id)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (exception_id, result["adjustment_id"], company_id, actor_id, target),
        )
    _log(conn, company_id, exception_id, "propose_reversal", sm.CORRECTION_PENDING, sm.CORRECTION_PENDING, actor_id,
         f"adjustment {result['adjustment_id']} reverses entry {target}")
    return {"exception_id": exception_id, "adjustment_id": result["adjustment_id"], "adjustment_status": result["status"],
            "reverses_journal_entry_id": target, "entry_date": when, "status": sm.CORRECTION_PENDING}


# ── reads ────────────────────────────────────────────────────────────────
_SUMMARY_FIELDS = ("id", "accounting_period_id", "rule_id", "category", "source", "title", "message", "priority",
                   "journal_entry_id", "amount", "status", "assigned_to", "decision", "created_at")


def list_exceptions(conn, company_id: str, *, period_id: Optional[str] = None, status: Optional[str] = None,
                    category: Optional[str] = None, priority: Optional[str] = None, open_only: bool = False,
                    limit: int = 200, offset: int = 0) -> Dict[str, Any]:
    if status is not None and status not in sm.ALL_STATUSES:
        raise ValueError(f"status must be one of {', '.join(sorted(sm.ALL_STATUSES))}")
    if category is not None and category not in CATEGORIES:
        raise ValueError(f"category must be one of {', '.join(CATEGORIES)}")
    if priority is not None and priority not in PRIORITIES:
        raise ValueError(f"priority must be one of {', '.join(PRIORITIES)}")
    limit, offset = max(1, min(int(limit), 500)), max(0, int(offset))

    where, params = ["company_id = %s"], [company_id]
    if period_id:
        where.append("accounting_period_id = %s"); params.append(period_id)
    if status:
        where.append("status = %s"); params.append(status)
    if category:
        where.append("category = %s"); params.append(category)
    if priority:
        where.append("priority = %s"); params.append(priority)
    if open_only:
        where.append("status = ANY(%s)"); params.append(sorted(sm.OPEN_STATUSES))
    clause = " AND ".join(where)

    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM review_exceptions WHERE {clause}", params)
        total = cur.fetchone()[0]
        cur.execute(
            f"""
            SELECT {", ".join(_SUMMARY_FIELDS)} FROM review_exceptions WHERE {clause}
            ORDER BY CASE priority WHEN 'HIGH' THEN 0 WHEN 'MEDIUM' THEN 1 ELSE 2 END, amount DESC NULLS LAST, created_at, id
            LIMIT %s OFFSET %s
            """,
            params + [limit, offset],
        )
        rows = cur.fetchall()

    items = []
    for row in rows:
        d = dict(zip(_SUMMARY_FIELDS, row))
        for k in ("id", "accounting_period_id", "journal_entry_id", "assigned_to"):
            d[k] = str(d[k]) if d[k] is not None else None
        items.append(d)
    return {"exceptions": items, "count": total, "limit": limit, "offset": offset}


def summary(conn, company_id: str, period_id: str) -> Dict[str, Any]:
    """The dashboard's exception card: how many flags, in what state, how pressing."""
    _period_dates(conn, company_id, period_id)  # not this company's period -> a clear 400
    open_list = sorted(sm.OPEN_STATUSES)
    with conn.cursor() as cur:
        cur.execute("SELECT status, COUNT(*) FROM review_exceptions WHERE company_id = %s AND accounting_period_id = %s GROUP BY status",
                    (company_id, period_id))
        by_status = {s: 0 for s in sorted(sm.ALL_STATUSES)}
        by_status.update({s: n for s, n in cur.fetchall()})
        cur.execute("SELECT category, COUNT(*) FROM review_exceptions WHERE company_id = %s AND accounting_period_id = %s AND status = ANY(%s) GROUP BY category",
                    (company_id, period_id, open_list))
        open_by_category = {c: 0 for c in CATEGORIES}
        open_by_category.update({c: n for c, n in cur.fetchall()})
        cur.execute("SELECT priority, COUNT(*) FROM review_exceptions WHERE company_id = %s AND accounting_period_id = %s AND status = ANY(%s) GROUP BY priority",
                    (company_id, period_id, open_list))
        open_by_priority = {p: 0 for p in PRIORITIES}
        open_by_priority.update({p: n for p, n in cur.fetchall()})
        cur.execute("SELECT id, run_at, run_by, counts FROM exception_runs WHERE company_id = %s AND accounting_period_id = %s ORDER BY run_at DESC, id LIMIT 1",
                    (company_id, period_id))
        last = cur.fetchone()
    return {
        "period_id": period_id, "open_total": sum(by_status[s] for s in open_list), "by_status": by_status,
        "open_by_category": open_by_category, "open_by_priority": open_by_priority,
        "last_run": None if last is None else {"run_id": str(last[0]), "run_at": last[1], "run_by": str(last[2]), "counts": last[3]},
    }


def get_exception(conn, company_id: str, exception_id: str) -> Dict[str, Any]:
    ex = _load(conn, company_id, exception_id)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT action, from_status, to_status, actor_id, note, run_id, created_at FROM exception_transitions "
            "WHERE exception_id = %s ORDER BY created_at, id",
            (exception_id,),
        )
        transitions = [{"action": a, "from_status": f, "to_status": t, "actor_id": str(u), "note": n,
                        "run_id": str(r) if r else None, "at": c} for a, f, t, u, n, r, c in cur.fetchall()]

        entry_ids = _uuids(dict.fromkeys([ex["journal_entry_id"], *ex["related_entry_ids"]]))
        cur.execute(
            "SELECT id, entry_date, description, accounting_period_id FROM journal_entries WHERE company_id = %s AND id = ANY(%s) ORDER BY entry_date, id",
            (company_id, entry_ids),
        )
        entries = {str(i): {"journal_entry_id": str(i), "entry_date": d, "description": desc,
                            "period_id": str(p), "lines": []} for i, d, desc, p in cur.fetchall()}
        cur.execute(
            """
            SELECT jl.journal_entry_id, a.code, a.name, a.account_type, jl.debit, jl.credit
            FROM journal_lines jl JOIN accounts a ON a.id = jl.account_id
            WHERE jl.company_id = %s AND jl.journal_entry_id = ANY(%s) ORDER BY jl.journal_entry_id, a.code, jl.id
            """,
            (company_id, entry_ids),
        )
        for eid, code, name, atype, debit, credit in cur.fetchall():
            entries[str(eid)]["lines"].append({"code": code, "name": name, "account_type": atype, "debit": debit, "credit": credit})

    ex["transitions"] = transitions
    ex["linked_adjustments"] = _linked_adjustments(conn, company_id, exception_id)
    ex["entries"] = list(entries.values())
    ex["period_lock_status"] = _period_lock_status(conn, company_id, ex["accounting_period_id"])
    ex["available_actions"] = sm.available_actions(ex["status"])
    return ex


def list_runs(conn, company_id: str, period_id: str, limit: int = 25) -> List[Dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, run_by, run_at, counts FROM exception_runs WHERE company_id = %s AND accounting_period_id = %s "
            "ORDER BY run_at DESC, id LIMIT %s",
            (company_id, period_id, max(1, min(int(limit), 200))),
        )
        return [{"run_id": str(i), "run_by": str(b), "run_at": a, "counts": c} for i, b, a, c in cur.fetchall()]


def get_run(conn, company_id: str, run_id: str) -> Dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, accounting_period_id, run_by, run_at, counts, rule_outcomes FROM exception_runs WHERE company_id = %s AND id = %s",
            (company_id, run_id),
        )
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"exception run {run_id} not found for company {company_id}")
        cur.execute(
            "SELECT id, category, title, priority, status FROM review_exceptions WHERE company_id = %s AND detected_run_id = %s "
            "ORDER BY CASE priority WHEN 'HIGH' THEN 0 WHEN 'MEDIUM' THEN 1 ELSE 2 END, created_at, id",
            (company_id, run_id),
        )
        first_found = [{"id": str(i), "category": c, "title": t, "priority": p, "status": s} for i, c, t, p, s in cur.fetchall()]
    rid, pid, by, at, counts, rule_outcomes = row
    return {"run_id": str(rid), "period_id": str(pid), "run_by": str(by), "run_at": at, "counts": counts,
            "rules": rule_outcomes, "first_found_in_this_run": first_found}


def rule_catalog() -> Dict[str, Any]:
    return {"rules": catalog(), "thresholds": plain(asdict(Thresholds())), "categories": list(CATEGORIES)}