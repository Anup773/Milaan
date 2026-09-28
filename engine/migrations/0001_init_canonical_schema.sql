-- 0001_init_canonical_schema.sql
-- Milaan canonical schema: tenancy, ingestion, and the core double-entry ledger.
--
-- Multi-tenancy is enforced at the database layer via Row-Level Security
-- (ARCHITECTURE.md §9), not just in application code. RLS is driven by two
-- session variables the application sets at the start of each request,
-- AFTER authenticating the user and -- for company-scoped actions --
-- confirming the requested company belongs to that user's firm:
--   SET LOCAL app.current_firm_id = '<uuid>';
--   SET LOCAL app.current_company_id = '<uuid>';   -- only when scoped to one company
-- Policies read these back via current_setting(..., true) -- the `true`
-- means "return NULL instead of erroring if unset" -- so a connection that
-- never sets these sees zero rows, not an error, in any tenant-scoped
-- table. That fail-closed behaviour is deliberate.
--
-- IMPORTANT: RLS is silently bypassed for the role that owns these tables
-- (whoever runs this migration) and for superusers. The application must
-- connect as `app_user` below, not as your admin/migration connection, or
-- these policies do nothing. This was verified for real, not assumed --
-- see the README for how.

CREATE TABLE firms (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name        text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE companies (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id     uuid NOT NULL REFERENCES firms(id),
    name        text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON companies (firm_id);

CREATE TYPE user_role AS ENUM ('accountant', 'senior_accountant', 'ca', 'reviewer', 'admin');

CREATE TABLE users (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id        uuid NOT NULL REFERENCES firms(id),
    email          text NOT NULL,
    password_hash  text NOT NULL,
    role           user_role NOT NULL,
    active         boolean NOT NULL DEFAULT true,
    created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX users_email_unique ON users (lower(email));
CREATE INDEX ON users (firm_id);

CREATE TABLE accounting_periods (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id   uuid NOT NULL REFERENCES companies(id),
    label        text NOT NULL,
    period_start date NOT NULL,
    period_end   date NOT NULL,
    lock_status  text NOT NULL DEFAULT 'OPEN' CHECK (lock_status IN ('OPEN', 'LOCKED')),
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON accounting_periods (company_id);

CREATE TYPE account_type AS ENUM ('Asset', 'Liability', 'Equity', 'Income', 'Expense');

CREATE TABLE accounts (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id         uuid NOT NULL REFERENCES companies(id),
    code               text NOT NULL,
    name               text NOT NULL,
    account_type       account_type NOT NULL,
    parent_account_id  uuid REFERENCES accounts(id),
    created_at         timestamptz NOT NULL DEFAULT now(),
    UNIQUE (company_id, code)
);
CREATE INDEX ON accounts (company_id);

CREATE TABLE data_sources (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id  uuid NOT NULL REFERENCES companies(id),
    name        text NOT NULL,
    source_type text NOT NULL,  -- 'excel' | 'csv' | 'tally' | ... -- text, not enum: Phase 17+ connectors add more
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON data_sources (company_id);

CREATE TABLE source_files (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id     uuid NOT NULL REFERENCES companies(id),
    data_source_id uuid NOT NULL REFERENCES data_sources(id),
    filename       text NOT NULL,
    uploaded_by    uuid REFERENCES users(id),
    uploaded_at    timestamptz NOT NULL DEFAULT now(),
    status         text NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'PROCESSED', 'ERROR'))
);
CREATE INDEX ON source_files (company_id);

-- Matches engine/engine/ingestion/models.py::ParsedSourceRow field for field.
CREATE TABLE source_rows (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id        uuid NOT NULL REFERENCES companies(id),
    source_file_id    uuid NOT NULL REFERENCES source_files(id),
    row_number        integer NOT NULL,
    account_ref       text NOT NULL,
    transaction_date  date,
    description       text NOT NULL DEFAULT '',
    debit             numeric(18,2) NOT NULL DEFAULT 0,
    credit            numeric(18,2) NOT NULL DEFAULT 0,
    reference         text NOT NULL DEFAULT '',
    raw_json          jsonb NOT NULL DEFAULT '{}',
    status            text NOT NULL DEFAULT 'OK' CHECK (status IN ('OK', 'WARNING', 'ERROR')),
    created_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON source_rows (company_id);
CREATE INDEX ON source_rows (source_file_id);

CREATE TABLE journal_entries (
    id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id            uuid NOT NULL REFERENCES companies(id),
    accounting_period_id  uuid NOT NULL REFERENCES accounting_periods(id),
    entry_date            date NOT NULL,
    description           text NOT NULL DEFAULT '',
    source_row_id         uuid REFERENCES source_rows(id),  -- null for manual/adjustment entries (later phases)
    created_by            uuid REFERENCES users(id),
    created_at            timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON journal_entries (company_id);
CREATE INDEX ON journal_entries (accounting_period_id);

CREATE TABLE journal_lines (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id        uuid NOT NULL REFERENCES companies(id),  -- denormalized from journal_entries, for simple/fast RLS
    journal_entry_id  uuid NOT NULL REFERENCES journal_entries(id),
    account_id        uuid NOT NULL REFERENCES accounts(id),
    debit             numeric(18,2) NOT NULL DEFAULT 0,
    credit            numeric(18,2) NOT NULL DEFAULT 0,
    created_at        timestamptz NOT NULL DEFAULT now(),
    CHECK (debit = 0 OR credit = 0)  -- one side per line; a line that's both is two lines
);
CREATE INDEX ON journal_lines (company_id);
CREATE INDEX ON journal_lines (journal_entry_id);
CREATE INDEX ON journal_lines (account_id);

-- ── Row-Level Security ──────────────────────────────────────────────────
ALTER TABLE firms               ENABLE ROW LEVEL SECURITY;
ALTER TABLE companies           ENABLE ROW LEVEL SECURITY;
ALTER TABLE users                ENABLE ROW LEVEL SECURITY;
ALTER TABLE accounting_periods   ENABLE ROW LEVEL SECURITY;
ALTER TABLE accounts             ENABLE ROW LEVEL SECURITY;
ALTER TABLE data_sources         ENABLE ROW LEVEL SECURITY;
ALTER TABLE source_files         ENABLE ROW LEVEL SECURITY;
ALTER TABLE source_rows          ENABLE ROW LEVEL SECURITY;
ALTER TABLE journal_entries      ENABLE ROW LEVEL SECURITY;
ALTER TABLE journal_lines        ENABLE ROW LEVEL SECURITY;

CREATE POLICY firm_isolation ON firms
    USING (id = current_setting('app.current_firm_id', true)::uuid);
CREATE POLICY firm_isolation ON companies
    USING (firm_id = current_setting('app.current_firm_id', true)::uuid);
CREATE POLICY firm_isolation ON users
    USING (firm_id = current_setting('app.current_firm_id', true)::uuid);

CREATE POLICY company_isolation ON accounting_periods
    USING (company_id = current_setting('app.current_company_id', true)::uuid);
CREATE POLICY company_isolation ON accounts
    USING (company_id = current_setting('app.current_company_id', true)::uuid);
CREATE POLICY company_isolation ON data_sources
    USING (company_id = current_setting('app.current_company_id', true)::uuid);
CREATE POLICY company_isolation ON source_files
    USING (company_id = current_setting('app.current_company_id', true)::uuid);
CREATE POLICY company_isolation ON source_rows
    USING (company_id = current_setting('app.current_company_id', true)::uuid);
CREATE POLICY company_isolation ON journal_entries
    USING (company_id = current_setting('app.current_company_id', true)::uuid);
CREATE POLICY company_isolation ON journal_lines
    USING (company_id = current_setting('app.current_company_id', true)::uuid);

-- ── Login lookup ─────────────────────────────────────────────────────────
-- The one legitimate case where a query has to cross firm boundaries: at
-- login, we don't know the user's firm_id yet -- that's what we're looking
-- up. Ordinary RLS on `users` would return zero rows here even for a real
-- user, since no app.current_firm_id can be set before we know it. This
-- function runs as SECURITY DEFINER (the migration owner's privileges, not
-- the caller's), so it deliberately bypasses RLS -- but ONLY to return
-- exactly these 5 columns for exactly one matching email. It is not a
-- general-purpose RLS bypass.
CREATE OR REPLACE FUNCTION login_lookup(p_email text)
RETURNS TABLE (id uuid, firm_id uuid, password_hash text, role user_role, active boolean)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT id, firm_id, password_hash, role, active
  FROM users
  WHERE lower(email) = lower(p_email);
$$;

REVOKE ALL ON FUNCTION login_lookup(text) FROM PUBLIC;

-- ── Application role ─────────────────────────────────────────────────────
-- Run this whole file as your admin/migration connection (e.g. Supabase's
-- default connection string). The application itself must then connect
-- using APP_DATABASE_URL (this role) -- never the admin connection -- or
-- RLS above does nothing.
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_user') THEN
    CREATE ROLE app_user LOGIN PASSWORD 'CHANGE_ME';
  END IF;
END $$;

GRANT USAGE ON SCHEMA public TO app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_user;
GRANT EXECUTE ON FUNCTION login_lookup(text) TO app_user;
