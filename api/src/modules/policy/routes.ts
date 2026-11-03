import { Router } from "express";
import { authenticate } from "../auth/middleware.js";
import { requireRole } from "../auth/authorize.js";
import type { Role } from "../auth/types.js";
import { assertCompanyInFirm } from "../companies/access.js";
import { respondError } from "../../lib/http.js";
import { runEngineCli } from "../../lib/pythonEngine.js";

export const policyRouter = Router();

const CLI = "engine.policy.cli";

// The company accounting policy (ARCHITECTURE.md §13): one per company. Anyone in the firm may read it. Setting it up
// is for the people who may create a company; changing it afterwards is for a CA or admin. The engine enforces the
// finer rule (set up vs change, and that a change needs a reason); this route only keeps out roles that can do neither.
// Keep these in step with SETUP_ROLES in engine/engine/policy/model.py (a test compares them).
const SETUP_ROLES: Role[] = ["senior_accountant", "ca", "admin"];

policyRouter.get("/:companyId/policy", authenticate, async (req, res) => {
  const { companyId } = req.params;
  const auth = req.auth!;
  try {
    await assertCompanyInFirm(auth.firmId, companyId);
    res.json(await runEngineCli(CLI, ["get", auth.firmId, companyId, auth.role]));
  } catch (err) {
    respondError(res, err, "failed to load the accounting policy");
  }
});

policyRouter.put("/:companyId/policy", authenticate, requireRole(...SETUP_ROLES), async (req, res) => {
  const { companyId } = req.params;
  const auth = req.auth!;
  const body: unknown = req.body;
  if (body === null || typeof body !== "object" || Array.isArray(body)) {
    res.status(400).json({ error: "the policy must be a JSON object holding every setting" });
    return;
  }
  try {
    await assertCompanyInFirm(auth.firmId, companyId);
    res.json(await runEngineCli(CLI, ["put", auth.firmId, companyId, auth.userId, auth.role, JSON.stringify(body)]));
  } catch (err) {
    respondError(res, err, "failed to save the accounting policy");
  }
});
