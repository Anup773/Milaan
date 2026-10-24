import "dotenv/config";
import pg from "pg";

const { Pool, types } = pg;

// Return Postgres DATE columns (oid 1082) as plain "YYYY-MM-DD" strings. By default node-postgres turns them
// into JS Dates at local midnight, so JSON.stringify shifts them by the server's timezone offset
// (2025-04-01 becomes "2025-03-31T18:15:00.000Z" on a UTC+05:45 server) and every client then shows the wrong day.
// A calendar date has no time zone; keeping it a string keeps it exact.
types.setTypeParser(1082, (value: string) => value);

function requireEnv(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(`missing required env var: ${name}`);
  }
  return value;
}

// Connect using the unprivileged `app_user` role created by migration 0001
// -- never an admin/migration connection. RLS is silently bypassed for a
// table's owner, so pointing this at the wrong connection string would
// make every RLS policy in the schema a no-op with no error to tell you so.
export const pool = new Pool({
  connectionString: requireEnv("APP_DATABASE_URL"),
});

// An idle connection can be dropped by the database (restart, failover, network). node-postgres reports that as an
// 'error' event on the pool; with no listener Node treats it as uncaught and the whole API process exits. Log it and
// carry on: the pool discards the dead connection and opens a new one for the next request.
pool.on("error", (err) => {
  console.error("database connection error (idle client):", err.message);
});

export interface TenantContext {
  firmId: string;
  companyId?: string;
  /** Who is acting (Phase 15). The audit triggers read it to name the person on changes to tables that do not record one themselves. */
  userId?: string;
}

/**
 * Runs `fn` inside a transaction with the RLS session variables set for the
 * given tenant. Use this for every query that touches tenant-scoped data --
 * it's what makes the RLS policies in migration 0001 actually apply to one
 * specific firm/company rather than blocking everything.
 */
export async function withTenant<T>(
  tenant: TenantContext,
  fn: (client: pg.PoolClient) => Promise<T>
): Promise<T> {
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    await client.query("SELECT set_config('app.current_firm_id', $1, true)", [tenant.firmId]);
    if (tenant.companyId) {
      await client.query("SELECT set_config('app.current_company_id', $1, true)", [tenant.companyId]);
    }
    if (tenant.userId) {
      await client.query("SELECT set_config('app.current_user_id', $1, true)", [tenant.userId]);
    }
    const result = await fn(client);
    await client.query("COMMIT");
    return result;
  } catch (err) {
    await client.query("ROLLBACK");
    throw err;
  } finally {
    client.release();
  }
}
