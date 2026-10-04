import { Router } from "express";
import { authenticate } from "../auth/middleware.js";
import { requireRole } from "../auth/authorize.js";
import { assertCompanyInFirm } from "../companies/access.js";
import { respondError } from "../../lib/http.js";
import { withTenant } from "../../db/client.js";

export const periodsRouter = Router();

periodsRouter.get("/:companyId/accounting-periods", authenticate, async (req, res) => {
  const { companyId } = req.params;
  const auth = req.auth!;

  try {
    await assertCompanyInFirm(auth.firmId, companyId);
    const result = await withTenant({ firmId: auth.firmId, companyId }, (client) =>
      client.query(
        `SELECT id, label, period_start, period_end, lock_status
         FROM accounting_periods WHERE company_id = $1 ORDER BY period_start`,
        [companyId]
      )
    );
    res.json({ periods: result.rows });
  } catch (err) {
    respondError(res, err, "failed to list accounting periods");
  }
});

periodsRouter.post(
  "/:companyId/accounting-periods",
  authenticate,
  requireRole("senior_accountant", "ca", "admin"),
  async (req, res) => {
    const { companyId } = req.params;
    const auth = req.auth!;
    const { label, periodStart, periodEnd } = req.body ?? {};

    if (typeof label !== "string" || !label.trim() || typeof periodStart !== "string" || typeof periodEnd !== "string") {
      res.status(400).json({ error: "label, periodStart and periodEnd ('YYYY-MM-DD') are required" });
      return;
    }

    try {
      await assertCompanyInFirm(auth.firmId, companyId);
      const result = await withTenant({ firmId: auth.firmId, companyId }, (client) =>
        client.query(
          `INSERT INTO accounting_periods (company_id, label, period_start, period_end)
           VALUES ($1, $2, $3, $4)
           RETURNING id, label, period_start, period_end, lock_status`,
          [companyId, label.trim(), periodStart, periodEnd]
        )
      );
      res.status(201).json({ period: result.rows[0] });
    } catch (err) {
      respondError(res, err, "failed to create accounting period");
    }
  }
);
