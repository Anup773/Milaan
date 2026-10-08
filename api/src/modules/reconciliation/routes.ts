import { Router } from "express";
import { authenticate } from "../auth/middleware.js";
import { assertCompanyInFirm } from "../companies/access.js";
import { respondError } from "../../lib/http.js";
import { runEngineCli } from "../../lib/pythonEngine.js";

export const reconciliationRouter = Router();

const CLI = "engine.reconciliation.cli";

// Running the checks never changes the books -- it only records what the
// checks said (append-only history) -- so any authenticated user of the firm
// may run them. Firm membership is checked on every route.

function queryText(v: unknown): string | null {
  return typeof v === "string" && v.length > 0 ? v : null;
}

// The catalog of checks.
reconciliationRouter.get("/:companyId/reconciliation/rules", authenticate, async (req, res) => {
  const { companyId } = req.params;
  const auth = req.auth!;
  try {
    await assertCompanyInFirm(auth.firmId, companyId);
    res.json(await runEngineCli(CLI, ["rules", auth.firmId, companyId]));
  } catch (err) {
    respondError(res, err, "failed to list reconciliation rules");
  }
});

// Run every check on the books as posted, and save the run.
reconciliationRouter.post("/:companyId/reconciliation/run", authenticate, async (req, res) => {
  const { companyId } = req.params;
  const periodId = (req.body ?? {}).periodId;
  const auth = req.auth!;
  if (typeof periodId !== "string" || periodId.length === 0) {
    res.status(400).json({ error: "periodId is required" });
    return;
  }
  try {
    await assertCompanyInFirm(auth.firmId, companyId);
    res.status(201).json(await runEngineCli(CLI, ["run", auth.firmId, companyId, periodId, auth.userId]));
  } catch (err) {
    respondError(res, err, "failed to run reconciliation");
  }
});

// The most recent saved run for a period ({ "run": null } if none yet).
reconciliationRouter.get("/:companyId/reconciliation", authenticate, async (req, res) => {
  const { companyId } = req.params;
  const periodId = queryText(req.query.periodId);
  const auth = req.auth!;
  if (!periodId) {
    res.status(400).json({ error: "periodId query parameter is required" });
    return;
  }
  try {
    await assertCompanyInFirm(auth.firmId, companyId);
    res.json(await runEngineCli(CLI, ["latest", auth.firmId, companyId, periodId]));
  } catch (err) {
    respondError(res, err, "failed to load reconciliation");
  }
});

// History of saved runs for a period.
reconciliationRouter.get("/:companyId/reconciliation/runs", authenticate, async (req, res) => {
  const { companyId } = req.params;
  const periodId = queryText(req.query.periodId);
  const auth = req.auth!;
  if (!periodId) {
    res.status(400).json({ error: "periodId query parameter is required" });
    return;
  }
  try {
    await assertCompanyInFirm(auth.firmId, companyId);
    res.json(await runEngineCli(CLI, ["list", auth.firmId, companyId, periodId]));
  } catch (err) {
    respondError(res, err, "failed to list reconciliation runs");
  }
});

// One saved run with all its results.
reconciliationRouter.get("/:companyId/reconciliation/runs/:runId", authenticate, async (req, res) => {
  const { companyId, runId } = req.params;
  const auth = req.auth!;
  try {
    await assertCompanyInFirm(auth.firmId, companyId);
    res.json(await runEngineCli(CLI, ["get", auth.firmId, companyId, runId]));
  } catch (err) {
    respondError(res, err, "failed to load reconciliation run");
  }
});
