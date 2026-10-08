import { Router } from "express";
import { authenticate } from "../auth/middleware.js";
import { assertCompanyInFirm } from "../companies/access.js";
import { respondError } from "../../lib/http.js";
import { runEngineCli } from "../../lib/pythonEngine.js";

export const impactRouter = Router();

// Impact analysis is read-only -- nothing is saved or posted -- so any
// authenticated user of the firm may use it. Firm membership is still
// checked on every route, exactly like the statements routes.

// A saved scenario's report: current vs scenario vs delta.
// Live for scenarios not yet posted; the frozen snapshot once posted.
impactRouter.get("/:companyId/scenarios/:scenarioId/impact", authenticate, async (req, res) => {
  const { companyId, scenarioId } = req.params;
  const auth = req.auth!;
  try {
    await assertCompanyInFirm(auth.firmId, companyId);
    res.json(await runEngineCli("engine.impact.cli", ["scenario", auth.firmId, companyId, scenarioId]));
  } catch (err) {
    respondError(res, err, "failed to build impact report");
  }
});

// The same report for ad-hoc changes, without saving a scenario.
impactRouter.post("/:companyId/impact/preview", authenticate, async (req, res) => {
  const { companyId } = req.params;
  const { periodId, overrides } = req.body ?? ({} as { periodId?: string; overrides?: Record<string, unknown> });
  const auth = req.auth!;

  if (
    typeof periodId !== "string" ||
    typeof overrides !== "object" || overrides === null || Array.isArray(overrides) ||
    Object.keys(overrides).length === 0
  ) {
    res.status(400).json({ error: "periodId and a non-empty overrides object ({ nodeId: amount }) are required" });
    return;
  }
  try {
    await assertCompanyInFirm(auth.firmId, companyId);
    const payload = JSON.stringify({ overrides });
    res.json(await runEngineCli("engine.impact.cli", ["preview", auth.firmId, companyId, periodId, payload]));
  } catch (err) {
    respondError(res, err, "failed to build impact preview");
  }
});