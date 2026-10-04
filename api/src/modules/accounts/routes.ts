import { Router } from "express";
import { authenticate } from "../auth/middleware.js";
import { requireRole } from "../auth/authorize.js";
import { assertCompanyInFirm } from "../companies/access.js";
import { respondError } from "../../lib/http.js";
import { withTenant } from "../../db/client.js";

export const accountsRouter = Router();

const VALID_ACCOUNT_TYPES = ["Asset", "Liability", "Equity", "Income", "Expense"];

accountsRouter.get("/:companyId/accounts", authenticate, async (req, res) => {
  const { companyId } = req.params;
  const auth = req.auth!;

  try {
    await assertCompanyInFirm(auth.firmId, companyId);
    const result = await withTenant({ firmId: auth.firmId, companyId }, (client) =>
      client.query(
        `SELECT id, code, name, account_type, parent_account_id
         FROM accounts WHERE company_id = $1 ORDER BY code`,
        [companyId]
      )
    );
    res.json({ accounts: result.rows });
  } catch (err) {
    respondError(res, err, "failed to list accounts");
  }
});

accountsRouter.post(
  "/:companyId/accounts",
  authenticate,
  requireRole("senior_accountant", "ca", "admin"),
  async (req, res) => {
    const { companyId } = req.params;
    const auth = req.auth!;
    const { code, name, accountType, parentAccountId } = req.body ?? {};

    if (typeof code !== "string" || !code.trim() || typeof name !== "string" || !name.trim()) {
      res.status(400).json({ error: "code and name are required" });
      return;
    }
    if (!VALID_ACCOUNT_TYPES.includes(accountType)) {
      res.status(400).json({ error: `accountType must be one of ${VALID_ACCOUNT_TYPES.join(", ")}` });
      return;
    }

    try {
      await assertCompanyInFirm(auth.firmId, companyId);
      const result = await withTenant({ firmId: auth.firmId, companyId }, (client) =>
        client.query(
          `INSERT INTO accounts (company_id, code, name, account_type, parent_account_id)
           VALUES ($1, $2, $3, $4, $5)
           RETURNING id, code, name, account_type, parent_account_id`,
          [companyId, code.trim(), name.trim(), accountType, parentAccountId ?? null]
        )
      );
      res.status(201).json({ account: result.rows[0] });
    } catch (err) {
      respondError(res, err, "failed to create account");
    }
  }
);