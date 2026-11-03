import { Router } from "express";
import { authenticate } from "../auth/middleware.js";
import { assertCompanyInFirm } from "../companies/access.js";
import { respondError } from "../../lib/http.js";
import { runEngineCli } from "../../lib/pythonEngine.js";

export const statementsRouter = Router();

// ?whole=true adds a whole-unit "presented" form of the statement (each line rounded, the footing difference shown).
function wholeArgs(query: Record<string, unknown>): string[] {
  return query.whole === "true" || query.whole === "1" ? ["whole"] : [];
}

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
    const result = await runEngineCli("engine.ledger.cli", ["profit-loss", auth.firmId, companyId, periodId, ...wholeArgs(req.query)]);
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
    const result = await runEngineCli("engine.ledger.cli", ["balance-sheet", auth.firmId, companyId, asOfDate, ...wholeArgs(req.query)]);
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

// Phase 24: the statement of changes in equity, the checks between statements, and a comparison with printed figures.
statementsRouter.get("/:companyId/statements/equity", authenticate, async (req, res) => {
  const { companyId } = req.params;
  const { periodId } = req.query;
  const auth = req.auth!;

  if (typeof periodId !== "string") {
    res.status(400).json({ error: "periodId query parameter is required" });
    return;
  }
  try {
    await assertCompanyInFirm(auth.firmId, companyId);
    const result = await runEngineCli("engine.ledger.cli", ["equity", auth.firmId, companyId, periodId, ...wholeArgs(req.query)]);
    res.json(result);
  } catch (err) {
    respondError(res, err, "failed to load the statement of changes in equity");
  }
});

statementsRouter.get("/:companyId/statements/checks", authenticate, async (req, res) => {
  const { companyId } = req.params;
  const { periodId } = req.query;
  const auth = req.auth!;

  if (typeof periodId !== "string") {
    res.status(400).json({ error: "periodId query parameter is required" });
    return;
  }
  try {
    await assertCompanyInFirm(auth.firmId, companyId);
    const result = await runEngineCli("engine.ledger.cli", ["checks", auth.firmId, companyId, periodId]);
    res.json(result);
  } catch (err) {
    respondError(res, err, "failed to check the statements against each other");
  }
});

// Body: { periodId, figures: { total_assets: "6,25,737,702", net_profit: "1234567", ... } }. Read-only (nothing is saved),
// so it is a POST only because the figures travel in the body.
statementsRouter.post("/:companyId/statements/compare", authenticate, async (req, res) => {
  const { companyId } = req.params;
  const auth = req.auth!;
  const { periodId, figures } = req.body ?? {};

  if (typeof periodId !== "string") {
    res.status(400).json({ error: "periodId is required" });
    return;
  }
  if (figures === null || typeof figures !== "object" || Array.isArray(figures)) {
    res.status(400).json({ error: "figures must be an object such as { \"total_assets\": \"1250000\" }" });
    return;
  }
  try {
    await assertCompanyInFirm(auth.firmId, companyId);
    const result = await runEngineCli("engine.ledger.cli", ["compare", auth.firmId, companyId, periodId, JSON.stringify(figures)]);
    res.json(result);
  } catch (err) {
    respondError(res, err, "failed to compare the printed figures with the ledger");
  }
});