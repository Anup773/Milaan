
"""
Phase 12's hook into the Phase 11 reconciliation framework: the reconciliation
page also says whether flags from exception review are still waiting on a
person. Importing this module registers the rule (reconciliation/repository.py
imports it next to the built-in rules).

WARNING only, never ERROR: open flags are things to look at, not a sign that
the books disagree with themselves, so they do not block a scenario's
"submit for review" (which stops on ERROR only).
"""
from __future__ import annotations

from ..exceptions.state_machine import OPEN_STATUSES
from .registry import NOT_CHECKED, PASS, WARNING, ReconContext, RuleResult, register_rule, result

EXAMPLES = 10


@register_rule("exceptions_open_for_review", "Exceptions: none waiting for review",
               "Flags raised by exception detection (or by a person) should each be retained, corrected or "
               "cleared before the period is finalised.")
def exceptions_open_for_review(ctx: ReconContext) -> RuleResult:
    rid = "exceptions_open_for_review"
    with ctx.conn.cursor() as cur:
        cur.execute("SELECT COUNT(*), MAX(run_at) FROM exception_runs WHERE company_id = %s AND accounting_period_id = %s",
                    (ctx.company_id, ctx.period_id))
        runs, last_run = cur.fetchone()
        cur.execute("SELECT COUNT(*) FROM review_exceptions WHERE company_id = %s AND accounting_period_id = %s",
                    (ctx.company_id, ctx.period_id))
        total = cur.fetchone()[0]
        if runs == 0 and total == 0:
            return result(rid, NOT_CHECKED, "Exception detection has not been run for this period yet.")
        cur.execute(
            """
            SELECT id, category, title, priority, status FROM review_exceptions
            WHERE company_id = %s AND accounting_period_id = %s AND status = ANY(%s)
            ORDER BY CASE priority WHEN 'HIGH' THEN 0 WHEN 'MEDIUM' THEN 1 ELSE 2 END, amount DESC NULLS LAST, created_at
            """,
            (ctx.company_id, ctx.period_id, sorted(OPEN_STATUSES)),
        )
        open_rows = cur.fetchall()
    when = f" (latest detection run: {last_run:%Y-%m-%d %H:%M})" if last_run else ""
    if open_rows:
        examples = [{"exception_id": str(i), "category": c, "title": t, "priority": p, "status": s}
                    for i, c, t, p, s in open_rows[:EXAMPLES]]
        return result(rid, WARNING, f"{len(open_rows)} flagged item(s) still need review or correction{when}.",
                      open=len(open_rows), examples=examples)
    return result(rid, PASS, f"All {total} flagged item(s) have been reviewed, cleared or resolved{when}.", total=total)