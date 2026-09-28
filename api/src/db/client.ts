import "dotenv/config";
import pg from "pg";

const { Pool } = pg;

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

export interface TenantContext {
  firmId: string;
  companyId?: string;
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
