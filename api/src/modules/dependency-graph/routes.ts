import { Router } from "express";
import { authenticate } from "../auth/middleware.js";
import { assertCompanyInFirm } from "../companies/access.js";
import { respondError } from "../../lib/http.js";
import { runEngineCli } from "../../lib/pythonEngine.js";

export const dependencyGraphRouter = Router();

// Everything here is read-only: the graph is rebuilt from the ledger on each
// call and nothing is written, so any authenticated user of the firm may use
// it. (Role-gated, saved scenarios are Phase 9.) Firm membership is still
// checked on every route, exactly like the statements routes.

function requireQuery(value: unknown, name: string): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

// The whole graph for one period: every node with its current value, and every edge.
dependencyGraphRouter.get("/:companyId/dependency-graph", authenticate, async (req, res) => {
  const { companyId } = req.params;
  const periodId = requireQuery(req.query.periodId, "periodId");
  const auth = req.auth!;

  if (!periodId) {
    res.status(400).json({ error: "periodId query parameter is required" });
    return;
  }
  try {
    await assertCompanyInFirm(auth.firmId, companyId);
    res.json(await runEngineCli("engine.dependency_graph.cli", ["graph", auth.firmId, companyId, periodId]));
  } catch (err) {
    respondError(res, err, "failed to load dependency graph");
  }
});

// "Where did this number come from?" / "What does changing this affect?"
for (const direction of ["upstream", "downstream"] as const) {
  dependencyGraphRouter.get(`/:companyId/dependency-graph/${direction}`, authenticate, async (req, res) => {
    const { companyId } = req.params;
    const periodId = requireQuery(req.query.periodId, "periodId");
    const node = requireQuery(req.query.node, "node");
    const auth = req.auth!;

    if (!periodId || !node) {
      res.status(400).json({ error: "periodId and node query parameters are required" });
      return;
    }
    try {
      await assertCompanyInFirm(auth.firmId, companyId);
      res.json(await runEngineCli("engine.dependency_graph.cli", [direction, auth.firmId, companyId, periodId, node]));
    } catch (err) {
      respondError(res, err, `failed to load ${direction} nodes`);
    }
  });
}

// "Change one thing, see every impact": a what-if only -- nothing is saved or posted.
dependencyGraphRouter.post("/:companyId/dependency-graph/recompute", authenticate, async (req, res) => {
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
    res.json(await runEngineCli("engine.dependency_graph.cli", ["recompute", auth.firmId, companyId, periodId, payload]));
  } catch (err) {
    respondError(res, err, "failed to recompute");
  }
});

// The lower half of the drill-down: an account's ledger lines and where each came from.
dependencyGraphRouter.get("/:companyId/dependency-graph/trace", authenticate, async (req, res) => {
  const { companyId } = req.params;
  const periodId = requireQuery(req.query.periodId, "periodId");
  const accountId = requireQuery(req.query.accountId, "accountId");
  const scope = req.query.scope;
  const auth = req.auth!;

  if (!periodId || !accountId) {
    res.status(400).json({ error: "periodId and accountId query parameters are required" });
    return;
  }
  if (scope !== undefined && scope !== "period" && scope !== "cumulative") {
    res.status(400).json({ error: "scope must be 'period' or 'cumulative'" });
    return;
  }
  try {
    await assertCompanyInFirm(auth.firmId, companyId);
    const args = ["trace", auth.firmId, companyId, periodId, accountId];
    if (typeof scope === "string") args.push(scope);
    res.json(await runEngineCli("engine.dependency_graph.cli", args));
  } catch (err) {
    respondError(res, err, "failed to trace account");
  }
});