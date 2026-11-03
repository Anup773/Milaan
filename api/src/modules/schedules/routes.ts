import { Router } from "express";
import { authenticate } from "../auth/middleware.js";
import { requireRole } from "../auth/authorize.js";
import { assertCompanyInFirm } from "../companies/access.js";
import { respondError } from "../../lib/http.js";
import { runEngineCli } from "../../lib/pythonEngine.js";
import { withTenant } from "../../db/client.js";
import { AssetPolicyError, applyAssetPolicy, type AssetPolicy } from "./assetPolicy.js";

export const schedulesRouter = Router();

// ---- Fixed asset CRUD: plain Node+pg, same pattern as accounts/periods ----

schedulesRouter.get("/:companyId/fixed-assets", authenticate, async (req, res) => {
  const { companyId } = req.params;
  const auth = req.auth!;

  try {
    await assertCompanyInFirm(auth.firmId, companyId);
    const result = await withTenant({ firmId: auth.firmId, companyId }, (client) =>
      client.query(
        `SELECT id, name, acquisition_date, cost, salvage_value, useful_life_months,
                depreciation_method, asset_account_id, accumulated_depreciation_account_id,
                depreciation_expense_account_id, disposed_date
         FROM fixed_assets WHERE company_id = $1 ORDER BY acquisition_date, name`,
        [companyId]
      )
    );
    res.json({ fixedAssets: result.rows });
  } catch (err) {
    respondError(res, err, "failed to list fixed assets");
  }
});

schedulesRouter.post(
  "/:companyId/fixed-assets",
  authenticate,
  requireRole("senior_accountant", "ca", "admin"),
  async (req, res) => {
    const { companyId } = req.params;
    const auth = req.auth!;
    const {
      name, acquisitionDate, cost, salvageValue, usefulLifeMonths,
      assetAccountId, accumulatedDepreciationAccountId, depreciationExpenseAccountId,
    } = req.body ?? {};

    if (
      typeof name !== "string" || !name.trim() ||
      typeof acquisitionDate !== "string" ||
      typeof cost !== "number" || cost <= 0 ||
      // usefulLifeMonths may be left out: the company's accounting policy can supply a default (checked below)
      (usefulLifeMonths !== undefined && usefulLifeMonths !== null && (typeof usefulLifeMonths !== "number" || usefulLifeMonths <= 0)) ||
      typeof assetAccountId !== "string" ||
      typeof accumulatedDepreciationAccountId !== "string" ||
      typeof depreciationExpenseAccountId !== "string"
    ) {
      res.status(400).json({
        error:
          "name, acquisitionDate, cost, assetAccountId, accumulatedDepreciationAccountId and depreciationExpenseAccountId are required " +
          "(usefulLifeMonths too, unless the company's accounting policy sets a default); cost and usefulLifeMonths must be positive numbers",
      });
      return;
    }

    try {
      await assertCompanyInFirm(auth.firmId, companyId);

      const result = await withTenant({ firmId: auth.firmId, companyId, userId: auth.userId }, async (client) => {
        // Catches the easy mistake of pointing a field at the wrong kind of
        // account (e.g. an Expense account as the asset_account_id) before
        // it can silently distort the accounting equation.
        const typeCheck = await client.query(
          `SELECT id, account_type FROM accounts WHERE company_id = $1 AND id = ANY($2::uuid[])`,
          [companyId, [assetAccountId, accumulatedDepreciationAccountId, depreciationExpenseAccountId]]
        );
        const typeById = new Map(typeCheck.rows.map((r) => [r.id as string, r.account_type as string]));
        const problems: string[] = [];
        if (typeById.get(assetAccountId) !== "Asset") problems.push("assetAccountId must be an Asset account");
        if (typeById.get(accumulatedDepreciationAccountId) !== "Asset")
          problems.push("accumulatedDepreciationAccountId must be an Asset account");
        if (typeById.get(depreciationExpenseAccountId) !== "Expense")
          problems.push("depreciationExpenseAccountId must be an Expense account");
        if (problems.length > 0) {
          const err = new Error(problems.join("; ")) as Error & { status?: number };
          err.status = 400;
          throw err;
        }

        // The company's accounting policy (Phase 22): the capitalisation threshold, and a default useful life.
        const policyRow = await client.query(
          `SELECT capitalization_threshold, default_useful_life_months FROM accounting_policies WHERE company_id = $1`,
          [companyId]
        );
        let life: number;
        try {
          life = applyAssetPolicy({ cost, usefulLifeMonths }, (policyRow.rows[0] as AssetPolicy | undefined) ?? null).usefulLifeMonths;
        } catch (err) {
          if (!(err instanceof AssetPolicyError)) throw err;
          const e = new Error(err.message) as Error & { status?: number };
          e.status = 400;
          throw e;
        }

        const inserted = await client.query(
          `INSERT INTO fixed_assets
             (company_id, name, acquisition_date, cost, salvage_value, useful_life_months,
              asset_account_id, accumulated_depreciation_account_id, depreciation_expense_account_id)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
           RETURNING id, name, acquisition_date, cost, salvage_value, useful_life_months`,
          [
            companyId, name.trim(), acquisitionDate, cost, salvageValue ?? 0, life,
            assetAccountId, accumulatedDepreciationAccountId, depreciationExpenseAccountId,
          ]
        );
        return inserted.rows[0];
      });

      res.status(201).json({ fixedAsset: result });
    } catch (err) {
      respondError(res, err, "failed to create fixed asset");
    }
  }
);

// ---- Depreciation schedule: Python engine ----

schedulesRouter.get("/:companyId/schedules/fixed-assets", authenticate, async (req, res) => {
  const { companyId } = req.params;
  const { periodId } = req.query;
  const auth = req.auth!;

  if (typeof periodId !== "string") {
    res.status(400).json({ error: "periodId query parameter is required" });
    return;
  }
  try {
    await assertCompanyInFirm(auth.firmId, companyId);
    const result = await runEngineCli("engine.schedules.cli", ["rollforward", auth.firmId, companyId, periodId]);
    res.json(result);
  } catch (err) {
    respondError(res, err, "failed to load fixed-asset rollforward");
  }
});

schedulesRouter.post(
  "/:companyId/schedules/fixed-assets/post-depreciation",
  authenticate,
  requireRole("senior_accountant", "ca", "admin"),
  async (req, res) => {
    const { companyId } = req.params;
    const { periodId } = req.body ?? {};
    const auth = req.auth!;

    if (typeof periodId !== "string") {
      res.status(400).json({ error: "periodId is required" });
      return;
    }
    try {
      await assertCompanyInFirm(auth.firmId, companyId);
      const result = await runEngineCli("engine.schedules.cli", ["post", auth.firmId, companyId, periodId, auth.userId]);
      res.json(result);
    } catch (err) {
      respondError(res, err, "failed to post depreciation");
    }
  }
);

schedulesRouter.get("/:companyId/schedules/fixed-assets/reconcile", authenticate, async (req, res) => {
  const { companyId } = req.params;
  const { periodId } = req.query;
  const auth = req.auth!;

  if (typeof periodId !== "string") {
    res.status(400).json({ error: "periodId query parameter is required" });
    return;
  }
  try {
    await assertCompanyInFirm(auth.firmId, companyId);
    const result = await runEngineCli("engine.schedules.cli", ["reconcile", auth.firmId, companyId, periodId]);
    res.json(result);
  } catch (err) {
    respondError(res, err, "failed to reconcile fixed-asset schedule");
  }
});