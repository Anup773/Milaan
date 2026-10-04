import { withTenant } from "../../db/client.js";
import type { StatusError } from "../../lib/http.js";

export async function assertCompanyInFirm(firmId: string, companyId: string): Promise<void> {
  const belongs = await withTenant({ firmId }, async (client) => {
    const result = await client.query(`SELECT 1 FROM companies WHERE id = $1`, [companyId]);
    return result.rows.length > 0;
  });
  if (!belongs) {
    const err = new Error("company not found for this firm") as StatusError;
    err.status = 403;
    throw err;
  }
}
