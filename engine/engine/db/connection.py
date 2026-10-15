"""
Postgres connection + tenant-scoped transaction helper.

Connects using the unprivileged `app_user` role from migration 0001 --
never an admin/migration connection. RLS is silently bypassed for a
table's owner, so the wrong connection string here makes every RLS policy
in the schema a no-op with no error to tell you so.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator, Optional

import psycopg


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"missing required env var: {name}")
    return value


@contextmanager
def tenant_connection(firm_id: str, company_id: Optional[str] = None,
                      user_id: Optional[str] = None) -> Iterator[psycopg.Connection]:
    """
    Opens a connection scoped to one firm (and optionally one company) for
    the RLS policies in migration 0001. Commits on success, rolls back on
    any exception raised inside the `with` block.

    user_id (optional, Phase 15): who is acting. Set as app.current_user_id so the audit
    triggers (migration 0011) can name the person for changes to tables that do not record
    one themselves. Leaving it out is fine -- those events are then recorded without an actor.
    """
    # prepare_threshold=None: never create server-side prepared statements. psycopg would
    # otherwise start doing so after a statement runs 5 times, which breaks behind
    # connection poolers in transaction mode (e.g. Supabase's pooler).
    conn = psycopg.connect(_require_env("APP_DATABASE_URL"), prepare_threshold=None)
    try:
        with conn.transaction():
            conn.execute("SELECT set_config('app.current_firm_id', %s, true)", (firm_id,))
            if company_id:
                conn.execute("SELECT set_config('app.current_company_id', %s, true)", (company_id,))
            if user_id:
                conn.execute("SELECT set_config('app.current_user_id', %s, true)", (user_id,))
            yield conn
    finally:
        conn.close()