"""
Turns a database error into the {"error", "status"} the engine CLIs print.

Phase 9's period-lock trigger refuses any change to a LOCKED period's
journal with a check-violation (SQLSTATE 23514) whose message contains
"LOCKED". That is a business-rule rejection -- the caller's fault -- so it
is reported as 400 with a plain message, not as a 500 server failure.
Anything else stays a 500.
"""
from __future__ import annotations

from typing import Any, Dict


def is_locked_period_error(exc: BaseException) -> bool:
    return getattr(exc, "sqlstate", None) == "23514" and "LOCKED" in str(exc)


def error_payload(exc: BaseException) -> Dict[str, Any]:
    if is_locked_period_error(exc):
        return {"error": "this accounting period is LOCKED; it must be reopened before the ledger can be changed", "status": 400}
    return {"error": str(exc), "status": 500}
