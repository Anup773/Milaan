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
def tenant_connection(firm_id: str, company_id: Optional[str] = None) -> Iterator[psycopg.Connection]:
    """
    Opens a connection scoped to one firm (and optionally one company) for
    the RLS policies in migration 0001. Commits on success, rolls back on
    any exception raised inside the `with` block.
    """
    conn = psycopg.connect(_require_env("APP_DATABASE_URL"))
    try:
        with conn.transaction():
            conn.execute("SELECT set_config('app.current_firm_id', %s, true)", (firm_id,))
            if company_id:
                conn.execute("SELECT set_config('app.current_company_id', %s, true)", (company_id,))
            yield conn
    finally:
        conn.close()
