import { Router } from "express";
import { authenticate } from "../auth/middleware.js";
import { requireRole } from "../auth/authorize.js";
import type { Role } from "../auth/types.js";
import { assertCompanyInFirm } from "../companies/access.js";
import { respondError } from "../../lib/http.js";
import { runEngineCli } from "../../lib/pythonEngine.js";

export const taxDepreciationRouter = Router();

const CLI = "engine.schedules.tax_dep.cli";
// Keep in step with WRITE_ROLES in engine/engine/schedules/tax_dep/service.py (the engine checks the role again).
const WRITE_ROLES: Role[] = ["senior_accountant", "ca", "admin"];
const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/;
const UUID = /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;

function isObject(v: unknown): v is Record<string, unknown> {
  return v !== null && typeof v === "object" && !Array.isArray(v);
}

// Tax depreciation (Phase 24) is a memo schedule: it posts nothing to the ledger. The scheme follows the company's country
// (Nepal pools A-E, India blocks, US MACRS) and fiscal year from its accounting policy. Dates are AD (YYYY-MM-DD).
taxDepreciationRouter.get("/:companyId/tax-depreciation", authenticate, async (req, res) => {
  const { companyId } = req.params;
  const auth = req.auth!;
  const date = req.query.date;
  if (date !== undefined && (typeof date !== "string" || !ISO_DAY.test(date))) {
    res.status(400).json({ error: "date must be YYYY-MM-DD" });
    return;
  }
  try {
    await assertCompanyInFirm(auth.firmId, companyId);
    res.json(await runEngineCli(CLI, ["get", auth.firmId, companyId, auth.role, ...(date ? [date] : [])]));
  } catch (err) {
    respondError(res, err, "failed to load the tax depreciation schedule");
  }
});

taxDepreciationRouter.post("/:companyId/tax-depreciation/movements", authenticate, requireRole(...WRITE_ROLES), async (req, res) => {
  const { companyId } = req.params;
  const auth = req.auth!;
  if (!isObject(req.body)) {
    res.status(400).json({ error: "the entry must be a JSON object" });
    return;
  }
  try {
    await assertCompanyInFirm(auth.firmId, companyId);
    res.status(201).json(await runEngineCli(CLI, ["add", auth.firmId, companyId, auth.userId, auth.role, JSON.stringify(req.body)]));
  } catch (err) {
    respondError(res, err, "failed to add the entry");
  }
});

// Several entries at once (pasted from a spreadsheet): all are saved or none. Body: { rows: [...] }.
taxDepreciationRouter.post("/:companyId/tax-depreciation/movements/bulk", authenticate, requireRole(...WRITE_ROLES), async (req, res) => {
  const { companyId } = req.params;
  const auth = req.auth!;
  const rows: unknown = isObject(req.body) ? req.body.rows : undefined;
  if (!Array.isArray(rows) || rows.length === 0 || !rows.every(isObject)) {
    res.status(400).json({ error: "rows must be a non-empty list of entries" });
    return;
  }
  try {
    await assertCompanyInFirm(auth.firmId, companyId);
    res.status(201).json(await runEngineCli(CLI, ["add-many", auth.firmId, companyId, auth.userId, auth.role, JSON.stringify(rows)]));
  } catch (err) {
    respondError(res, err, "failed to add the entries");
  }
});

taxDepreciationRouter.put("/:companyId/tax-depreciation/movements/:id", authenticate, requireRole(...WRITE_ROLES), async (req, res) => {
  const { companyId, id } = req.params;
  const auth = req.auth!;
  if (!UUID.test(id) || !isObject(req.body)) {
    res.status(400).json({ error: "a valid entry id and a JSON object are required" });
    return;
  }
  try {
    await assertCompanyInFirm(auth.firmId, companyId);
    res.json(await runEngineCli(CLI, ["update", auth.firmId, companyId, auth.userId, auth.role, id, JSON.stringify(req.body)]));
  } catch (err) {
    respondError(res, err, "failed to change the entry");
  }
});

taxDepreciationRouter.delete("/:companyId/tax-depreciation/movements/:id", authenticate, requireRole(...WRITE_ROLES), async (req, res) => {
  const { companyId, id } = req.params;
  const auth = req.auth!;
  if (!UUID.test(id)) {
    res.status(400).json({ error: "a valid entry id is required" });
    return;
  }
  try {
    await assertCompanyInFirm(auth.firmId, companyId);
    res.json(await runEngineCli(CLI, ["delete", auth.firmId, companyId, auth.userId, auth.role, id]));
  } catch (err) {
    respondError(res, err, "failed to remove the entry");
  }
});

// The company's own rate for a pool from a date. Same pool and date again replaces the rate.
taxDepreciationRouter.put("/:companyId/tax-depreciation/rates", authenticate, requireRole(...WRITE_ROLES), async (req, res) => {
  const { companyId } = req.params;
  const auth = req.auth!;
  if (!isObject(req.body)) {
    res.status(400).json({ error: "the rate must be a JSON object" });
    return;
  }
  try {
    await assertCompanyInFirm(auth.firmId, companyId);
    res.json(await runEngineCli(CLI, ["rate-set", auth.firmId, companyId, auth.userId, auth.role, JSON.stringify(req.body)]));
  } catch (err) {
    respondError(res, err, "failed to save the rate");
  }
});

taxDepreciationRouter.delete("/:companyId/tax-depreciation/rates/:id", authenticate, requireRole(...WRITE_ROLES), async (req, res) => {
  const { companyId, id } = req.params;
  const auth = req.auth!;
  if (!UUID.test(id)) {
    res.status(400).json({ error: "a valid rate id is required" });
    return;
  }
  try {
    await assertCompanyInFirm(auth.firmId, companyId);
    res.json(await runEngineCli(CLI, ["rate-delete", auth.firmId, companyId, auth.userId, auth.role, id]));
  } catch (err) {
    respondError(res, err, "failed to remove the rate");
  }
});