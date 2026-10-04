import { Router } from "express";
import { authenticate } from "../auth/middleware.js";
import { assertCompanyInFirm } from "../companies/access.js";
import { respondError } from "../../lib/http.js";
import { runEngineCli } from "../../lib/pythonEngine.js";

export const statementsRouter = Router();

statementsRouter.get("/:companyId/statements/trial-balance", authenticate, async (req, res) => {
  const { companyId } = req.params;
  const { periodId } = req.query;
  const auth = req.auth!;

  if (typeof periodId !== "string") {
    res.status(400).json({ error: "periodId query parameter is required" });
    return;
  }
  try {
    await assertCompanyInFirm(auth.firmId, companyId);
    const result = await runEngineCli("engine.ledger.cli", ["trial-balance", auth.firmId, companyId, periodId]);
    res.json(result);
  } catch (err) {
    respondError(res, err, "failed to load trial balance");
  }
});

statementsRouter.get("/:companyId/statements/profit-loss", authenticate, async (req, res) => {
  const { companyId } = req.params;
  const { periodId } = req.query;
  const auth = req.auth!;

  if (typeof periodId !== "string") {
    res.status(400).json({ error: "periodId query parameter is required" });
    return;
  }
  try {
    await assertCompanyInFirm(auth.firmId, companyId);
    const result = await runEngineCli("engine.ledger.cli", ["profit-loss", auth.firmId, companyId, periodId]);
    res.json(result);
  } catch (err) {
    respondError(res, err, "failed to load profit & loss");
  }
});

statementsRouter.get("/:companyId/statements/balance-sheet", authenticate, async (req, res) => {
  const { companyId } = req.params;
  const { asOfDate } = req.query;
  const auth = req.auth!;

  if (typeof asOfDate !== "string") {
    res.status(400).json({ error: "asOfDate query parameter is required (YYYY-MM-DD)" });
    return;
  }
  try {
    await assertCompanyInFirm(auth.firmId, companyId);
    const result = await runEngineCli("engine.ledger.cli", ["balance-sheet", auth.firmId, companyId, asOfDate]);
    res.json(result);
  } catch (err) {
    respondError(res, err, "failed to load balance sheet");
  }
});

statementsRouter.get("/:companyId/statements/general-ledger", authenticate, async (req, res) => {
  const { companyId } = req.params;
  const { accountId, periodId } = req.query;
  const auth = req.auth!;

  if (typeof accountId !== "string" || typeof periodId !== "string") {
    res.status(400).json({ error: "accountId and periodId query parameters are required" });
    return;
  }
  try {
    await assertCompanyInFirm(auth.firmId, companyId);
    const result = await runEngineCli("engine.ledger.cli", ["general-ledger", auth.firmId, companyId, accountId, periodId]);
    res.json(result);
  } catch (err) {
    respondError(res, err, "failed to load general ledger");
  }
});

statementsRouter.get("/:companyId/statements/cash-flow", authenticate, async (req, res) => {
  const { companyId } = req.params;
  const { periodId } = req.query;
  const auth = req.auth!;

  if (typeof periodId !== "string") {
    res.status(400).json({ error: "periodId query parameter is required" });
    return;
  }
  try {
    await assertCompanyInFirm(auth.firmId, companyId);
    const result = await runEngineCli("engine.ledger.cli", ["cash-flow", auth.firmId, companyId, periodId]);
    res.json(result);
  } catch (err) {
    respondError(res, err, "failed to load cash flow");
  }
});
