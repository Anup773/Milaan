import { Router } from "express";
import { authenticate } from "../auth/middleware.js";
import { requireRole } from "../auth/authorize.js";
import { assertCompanyInFirm } from "../companies/access.js";
import { respondError } from "../../lib/http.js";
import { withTenant } from "../../db/client.js";
import { runEngineCli } from "../../lib/pythonEngine.js";

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
      const result = await withTenant({ firmId: auth.firmId, companyId, userId: auth.userId }, (client) =>
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

// Phase 24: a fiscal year and its periods, worked out from the company's calendar and fiscal-year start (accounting policy).
// Keep these roles in step with CREATE_ROLES in engine/engine/policy/fiscal.py.
const SPLITS = ["MONTHLY", "YEARLY"];
const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/;

periodsRouter.get("/:companyId/fiscal-year", authenticate, async (req, res) => {
  const { companyId } = req.params;
  const auth = req.auth!;
  const date = typeof req.query.date === "string" ? req.query.date : new Date().toISOString().slice(0, 10);
  const split = typeof req.query.split === "string" ? req.query.split.toUpperCase() : "MONTHLY";
  if (!ISO_DAY.test(date) || !SPLITS.includes(split)) {
    res.status(400).json({ error: "date must be YYYY-MM-DD and split MONTHLY or YEARLY" });
    return;
  }
  try {
    await assertCompanyInFirm(auth.firmId, companyId);
    res.json(await runEngineCli("engine.policy.fiscal_cli", ["preview", auth.firmId, companyId, date, split]));
  } catch (err) {
    respondError(res, err, "failed to work out the fiscal year");
  }
});

periodsRouter.post(
  "/:companyId/fiscal-year",
  authenticate,
  requireRole("senior_accountant", "ca", "admin"),
  async (req, res) => {
    const { companyId } = req.params;
    const auth = req.auth!;
    const { date, split } = req.body ?? {};
    const mode = typeof split === "string" ? split.toUpperCase() : "MONTHLY";
    if (typeof date !== "string" || !ISO_DAY.test(date) || !SPLITS.includes(mode)) {
      res.status(400).json({ error: "date (YYYY-MM-DD) is required and split must be MONTHLY or YEARLY" });
      return;
    }
    try {
      await assertCompanyInFirm(auth.firmId, companyId);
      res
        .status(201)
        .json(await runEngineCli("engine.policy.fiscal_cli", ["create", auth.firmId, companyId, auth.userId, auth.role, date, mode]));
    } catch (err) {
      respondError(res, err, "failed to create the fiscal year's periods");
    }
  }
);