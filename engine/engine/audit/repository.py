"""
Database-facing half of Phase 15: reads the audit trail, checks it, exports it.

The events themselves are written by the database (migration 0011 -- triggers on the tables
where the work happens), in the same transaction as the work. This module therefore only:

  list_events     the trail, newest first, filtered and paged
  get_event       one event, with the events either side of it in the chain
  object_history  everything that ever happened to one object, oldest first
  summary         counts for a dashboard card
  verify          walk the hash chain and say whether the history is intact
  export_csv      the trail as CSV -- itself recorded as an 'audit.export' event
  record          write an event by hand, for the few things no table change captures

Reading is by RLS: the session is scoped to one company, so nothing here can return another
company's events even if it tried.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from psycopg.types.json import Jsonb

from . import policy as pol

_COLUMNS = ("id, seq, occurred_at, actor_id, action, object_type, object_id, period_id, "
            "old_value, new_value, reason, prev_hash, event_hash")
_FIELDS = [c.strip() for c in _COLUMNS.split(",")]


def _now(now: Optional[datetime]) -> datetime:
    return now or datetime.now(timezone.utc)


def _people(conn, ids: Sequence[Optional[str]]) -> Dict[str, Dict[str, str]]:
    wanted = sorted({str(i) for i in ids if i})
    if not wanted:
        return {}
    with conn.cursor() as cur:
        cur.execute("SELECT id, email, role::text FROM users WHERE id = ANY(%s::uuid[])", (wanted,))
        return {str(i): {"email": e, "role": r} for i, e, r in cur.fetchall()}


def _event(row, people: Optional[Dict[str, Dict[str, str]]] = None) -> Dict[str, Any]:
    d = dict(zip(_FIELDS, row))
    for k in ("id", "actor_id", "object_id", "period_id"):
        d[k] = str(d[k]) if d[k] is not None else None
    d["seq"] = int(d["seq"])
    d["action_label"] = pol.action_label(d["action"])
    d["object_label"] = pol.object_label(d["object_type"])
    d["changes"] = pol.changed_fields(d["old_value"], d["new_value"])
    if people is not None:
        d["actor"] = people.get(d["actor_id"]) if d["actor_id"] else None
        d["headline"] = pol.headline(d, d["actor"]["email"] if d["actor"] else None)
    return d


def _where(company_id: str, f: Dict[str, Any]) -> Tuple[str, List[Any]]:
    clauses, params = ["company_id = %s"], [company_id]
    if f.get("periodId"):
        clauses.append("period_id = %s")
        params.append(f["periodId"])
    if f.get("actorId"):
        clauses.append("actor_id = %s")
        params.append(f["actorId"])
    if f.get("objectId"):
        clauses.append("object_id = %s")
        params.append(f["objectId"])
    if f.get("objectType"):
        clauses.append("object_type = %s")
        params.append(f["objectType"])
    if f.get("action"):
        if "." in f["action"]:
            clauses.append("action = %s")
            params.append(f["action"])
        else:
            clauses.append("starts_with(action, %s)")
            params.append(f["action"] + ".")
    if f.get("search"):
        clauses.append("position(lower(%s) in lower(COALESCE(reason, ''))) > 0")
        params.append(f["search"])
    start, end = pol.day_bounds(f)
    if start:
        clauses.append("occurred_at >= %s")
        params.append(start)
    if end:
        clauses.append("occurred_at < %s")
        params.append(end)
    return " AND ".join(clauses), params


# ── reading ──────────────────────────────────────────────────────────────
def list_events(conn, company_id: str, raw_filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The trail, newest first. Filters: see policy.normalise_filters. has_more says whether a next page exists."""
    f = pol.normalise_filters(raw_filters)
    where, params = _where(company_id, f)
    limit, offset = f["limit"], f["offset"]
    with conn.cursor() as cur:
        cur.execute(f"SELECT {_COLUMNS} FROM audit_events WHERE {where} ORDER BY seq DESC LIMIT %s OFFSET %s",
                    params + [limit + 1, offset])
        rows = cur.fetchall()
        cur.execute(f"SELECT COUNT(*) FROM audit_events WHERE {where}", params)
        total = cur.fetchone()[0]
    page = rows[:limit]
    people = _people(conn, [r[3] for r in page])
    return {"events": [_event(r, people) for r in page], "total": total, "has_more": len(rows) > limit,
            "limit": limit, "offset": offset, "filters": {k: v for k, v in f.items() if k not in ("limit", "offset")}}


def get_event(conn, company_id: str, event_id: str) -> Dict[str, Any]:
    """One event with the events just before and after it in the chain (so a person can follow the links)."""
    pol.check_uuid(event_id, "event_id")
    with conn.cursor() as cur:
        cur.execute(f"SELECT {_COLUMNS} FROM audit_events WHERE company_id = %s AND id = %s", (company_id, event_id))
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"audit event {event_id} not found for company {company_id}")
        seq = int(row[1])
        cur.execute(f"SELECT {_COLUMNS} FROM audit_events WHERE company_id = %s AND seq IN (%s, %s)",
                    (company_id, seq - 1, seq + 1))
        neighbours = {int(r[1]): r for r in cur.fetchall()}
    rows = [row] + list(neighbours.values())
    people = _people(conn, [r[3] for r in rows])
    event = _event(row, people)
    brief = lambda r: None if r is None else {k: v for k, v in _event(r, people).items()
                                              if k in ("id", "seq", "occurred_at", "action", "action_label", "event_hash", "headline")}
    event["previous"] = brief(neighbours.get(seq - 1))
    event["next"] = brief(neighbours.get(seq + 1))
    return event


def object_history(conn, company_id: str, object_type: str, object_id: str, *, limit: int = pol.MAX_LIMIT,
                   offset: int = 0) -> Dict[str, Any]:
    """Everything that ever happened to one object, oldest first."""
    f = pol.normalise_filters({"objectType": object_type, "objectId": object_id, "limit": limit, "offset": offset})
    where, params = _where(company_id, f)
    with conn.cursor() as cur:
        cur.execute(f"SELECT {_COLUMNS} FROM audit_events WHERE {where} ORDER BY seq ASC LIMIT %s OFFSET %s",
                    params + [f["limit"] + 1, f["offset"]])
        rows = cur.fetchall()
    page = rows[:f["limit"]]
    people = _people(conn, [r[3] for r in page])
    return {"object_type": object_type, "object_id": object_id, "events": [_event(r, people) for r in page],
            "has_more": len(rows) > f["limit"], "limit": f["limit"], "offset": f["offset"]}


def summary(conn, company_id: str, raw_filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The dashboard card: how much is on record, by kind of action, by kind of object, and by person."""
    f = pol.normalise_filters(raw_filters, paged=False)
    where, params = _where(company_id, f)
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*), MIN(occurred_at), MAX(occurred_at), MAX(seq) FROM audit_events WHERE {where}", params)
        total, first_at, last_at, head_seq = cur.fetchone()
        cur.execute(f"SELECT split_part(action, '.', 1), COUNT(*) FROM audit_events WHERE {where} GROUP BY 1 ORDER BY 2 DESC, 1", params)
        by_group = [{"group": g, "count": n} for g, n in cur.fetchall()]
        cur.execute(f"SELECT object_type, COUNT(*) FROM audit_events WHERE {where} GROUP BY 1 ORDER BY 2 DESC, 1", params)
        by_object = [{"object_type": t, "label": pol.object_label(t), "count": n} for t, n in cur.fetchall()]
        cur.execute(f"SELECT actor_id, COUNT(*), MAX(occurred_at) FROM audit_events WHERE {where} "
                    "GROUP BY actor_id ORDER BY 2 DESC, 1 NULLS LAST LIMIT 10", params)
        actors = cur.fetchall()
    people = _people(conn, [a for a, _, _ in actors])
    return {"total": total, "first_event_at": first_at, "last_event_at": last_at, "latest_seq": head_seq,
            "by_group": by_group, "by_object_type": by_object,
            "by_actor": [{"actor_id": str(a) if a else None, "actor": people.get(str(a)) if a else None,
                          "count": n, "last_event_at": last} for a, n, last in actors],
            "filters": f}


# ── checking ─────────────────────────────────────────────────────────────
def verify(conn, company_id: str, *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """
    Walk this company's hash chain from the first event. ok=True means every event's contents match its
    hash and every link matches the one before. head_seq / head_hash identify the newest event: write
    them down somewhere else, and a later check can prove nothing at the end was removed either.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT events_checked, first_broken_seq, problem FROM audit_verify_chain(%s)", (company_id,))
        checked, broken_seq, problem = cur.fetchone()
        cur.execute("SELECT seq, event_hash, occurred_at FROM audit_events WHERE company_id = %s ORDER BY seq DESC LIMIT 1",
                    (company_id,))
        head = cur.fetchone()
    return {"ok": broken_seq is None, "events_checked": checked, "first_broken_seq": broken_seq, "problem": problem,
            "head_seq": head[0] if head else None, "head_hash": head[1] if head else None,
            "head_at": head[2] if head else None, "checked_at": _now(now)}


# ── writing by hand ──────────────────────────────────────────────────────
def record(conn, *, company_id: str, actor_id: Optional[str], action: str, object_type: str,
           object_id: Optional[str] = None, period_id: Optional[str] = None, old_value: Any = None,
           new_value: Any = None, reason: Optional[str] = None) -> Dict[str, Any]:
    """
    Append one event. For things no table change captures (the export is the first). The database
    sets seq, time and hashes. The action must be one this module knows, so the trail stays a
    vocabulary the UI can label.
    """
    if action not in pol.ACTIONS:
        raise ValueError(f"unknown audit action: {action!r}")
    if object_type not in pol.OBJECT_TYPES:
        raise ValueError(f"unknown audit object type: {object_type!r}")
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO audit_events (company_id, seq, occurred_at, actor_id, action, object_type, object_id, period_id,
                                      old_value, new_value, reason, prev_hash, event_hash)
            VALUES (%s, 0, now(), %s, %s, %s, %s, %s, %s, %s, %s, '', '')
            RETURNING id, seq, event_hash
            """,
            (company_id, actor_id, action, object_type, object_id, period_id,
             Jsonb(old_value) if old_value is not None else None,
             Jsonb(new_value) if new_value is not None else None,
             (reason or "").strip() or None),
        )
        event_id, seq, event_hash = cur.fetchone()
    return {"id": str(event_id), "seq": seq, "event_hash": event_hash}


# ── export ───────────────────────────────────────────────────────────────
def export_csv(conn, company_id: str, *, actor_id: str, actor_role: str, raw_filters: Optional[Dict[str, Any]] = None,
               now: Optional[datetime] = None) -> Dict[str, Any]:
    """
    The trail (oldest first, up to MAX_EXPORT_ROWS) as formula-safe CSV text. Taking a copy of the
    audit trail is itself an audited act: an 'audit.export' event records who, and with which filters.
    """
    pol.check_role(actor_role, pol.EXPORT_ROLES, "export the audit trail")
    f = pol.normalise_filters(raw_filters, paged=False)
    where, params = _where(company_id, f)
    with conn.cursor() as cur:
        cur.execute(f"SELECT {_COLUMNS} FROM audit_events WHERE {where} ORDER BY seq ASC LIMIT %s",
                    params + [pol.MAX_EXPORT_ROWS + 1])
        rows = cur.fetchall()
    truncated = len(rows) > pol.MAX_EXPORT_ROWS
    rows = rows[:pol.MAX_EXPORT_ROWS]
    people = _people(conn, [r[3] for r in rows])
    events = [_event(r, people) for r in rows]
    record(conn, company_id=company_id, actor_id=actor_id, action="audit.export", object_type="audit",
           new_value={"rows": len(events), "truncated": truncated, "filters": f})
    return {"filename": pol.export_filename(company_id, _now(now)), "csv": pol.to_csv(events),
            "rows": len(events), "truncated": truncated}