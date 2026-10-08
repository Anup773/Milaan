import { Router } from "express";
import type { RequestHandler } from "express";
import { authenticate } from "../auth/middleware.js";
import { requireRole } from "../auth/authorize.js";
import { assertCompanyInFirm } from "../companies/access.js";
import { respondError } from "../../lib/http.js";
import { runEngineCli } from "../../lib/pythonEngine.js";
import type { Role } from "../auth/types.js";

export const scenariosRouter = Router();

const CLI = "engine.scenarios.cli";

// Who may do what (the second-person rules -- approver != creator, reopen
// decider != requester -- are enforced separately, in the engine AND by the
// database; these role lists only say which jobs may take part at all).
const MAKERS: Role[] = ["accountant", "senior_accountant", "ca", "admin"];
const REVIEWERS: Role[] = ["reviewer", "ca", "admin"];
const SENIORS: Role[] = ["senior_accountant", "ca", "reviewer", "admin"];
const FINALIZERS: Role[] = ["ca", "admin"];
const REOPEN_REQUESTERS: Role[] = ["senior_accountant", "ca", "admin"];

const text = (v: unknown): string | undefined => (typeof v === "string" && v.trim() ? v.trim() : undefined);

/** Builds a POST handler for an action on one scenario: runs `engine.scenarios.cli <command> ...`. */
function action(
  command: string,
  failMessage: string,
  buildExtraArgs: (body: Record<string, unknown>) => string[] | { error: string },
): RequestHandler {
  return async (req, res) => {
    const { companyId, scenarioId } = req.params;
    const auth = req.auth!;
    const extra = buildExtraArgs((req.body ?? {}) as Record<string, unknown>);
    if (!Array.isArray(extra)) {
      res.status(400).json(extra);
      return;
    }
    try {
      await assertCompanyInFirm(auth.firmId, companyId);
      res.json(await runEngineCli(CLI, [command, auth.firmId, companyId, scenarioId, auth.userId, ...extra]));
    } catch (err) {
      respondError(res, err, failMessage);
    }
  };
}

const noArgs = () => [] as string[];
const optionalNote = (b: Record<string, unknown>) => {
  const n = text(b.note);
  return n ? [n] : [];
};
const requiredText = (field: string, label: string) => (b: Record<string, unknown>) => {
  const v = text(b[field]);
  return v ? [v] : { error: `${label} is required` };
};

// ── reads ────────────────────────────────────────────────────────────────
scenariosRouter.get("/:companyId/scenarios", authenticate, async (req, res) => {
  const { companyId } = req.params;
  const { status } = req.query;
  const auth = req.auth!;
  try {
    await assertCompanyInFirm(auth.firmId, companyId);
    const args = ["list", auth.firmId, companyId];
    if (typeof status === "string") args.push(status);
    res.json(await runEngineCli(CLI, args));
  } catch (err) {
    respondError(res, err, "failed to list scenarios");
  }
});

scenariosRouter.get("/:companyId/scenarios/:scenarioId", authenticate, async (req, res) => {
  const { companyId, scenarioId } = req.params;
  const auth = req.auth!;
  try {
    await assertCompanyInFirm(auth.firmId, companyId);
    res.json(await runEngineCli(CLI, ["get", auth.firmId, companyId, scenarioId]));
  } catch (err) {
    respondError(res, err, "failed to load scenario");
  }
});

// ── create / edit ────────────────────────────────────────────────────────
scenariosRouter.post("/:companyId/scenarios", authenticate, requireRole(...MAKERS), async (req, res) => {
  const { companyId } = req.params;
  const auth = req.auth!;
  const { periodId, title, description, overrides } = req.body ?? ({} as Record<string, unknown>);

  if (typeof periodId !== "string" || !text(title) || typeof overrides !== "object" || overrides === null || Array.isArray(overrides)) {
    res.status(400).json({ error: "periodId, title and an overrides object ({ nodeId: amount }) are required" });
    return;
  }
  try {
    await assertCompanyInFirm(auth.firmId, companyId);
    const payload = JSON.stringify({ periodId, title, description: typeof description === "string" ? description : "", overrides, createdBy: auth.userId });
    res.status(201).json(await runEngineCli(CLI, ["create", auth.firmId, companyId, payload]));
  } catch (err) {
    respondError(res, err, "failed to create scenario");
  }
});

scenariosRouter.put(
  "/:companyId/scenarios/:scenarioId/overrides",
  authenticate,
  requireRole(...MAKERS),
  action("edit", "failed to edit scenario", (b) =>
    typeof b.overrides === "object" && b.overrides !== null && !Array.isArray(b.overrides)
      ? [JSON.stringify(b.overrides)]
      : { error: "an overrides object ({ nodeId: amount }) is required" },
  ),
);

// ── the state machine ────────────────────────────────────────────────────
const p = "/:companyId/scenarios/:scenarioId";
scenariosRouter.post(`${p}/simulate`, authenticate, requireRole(...MAKERS), action("simulate", "failed to simulate", noArgs));
scenariosRouter.post(`${p}/revise`, authenticate, requireRole(...MAKERS), action("revise", "failed to revise", noArgs));
scenariosRouter.post(`${p}/submit`, authenticate, requireRole(...MAKERS), action("submit", "failed to submit for review", noArgs));
scenariosRouter.post(`${p}/discard`, authenticate, requireRole(...MAKERS), action("discard", "failed to discard", optionalNote));

scenariosRouter.post(`${p}/approve`, authenticate, requireRole(...REVIEWERS), action("approve", "failed to approve", optionalNote));
scenariosRouter.post(`${p}/reject`, authenticate, requireRole(...REVIEWERS), action("reject", "failed to reject", requiredText("note", "a note explaining the rejection")));

scenariosRouter.post(`${p}/adjustments`, authenticate, requireRole(...SENIORS), action("link", "failed to link adjustment", requiredText("adjustmentId", "adjustmentId")));
scenariosRouter.post(`${p}/post`, authenticate, requireRole(...SENIORS), action("post", "failed to post", noArgs));
scenariosRouter.post(`${p}/finalize`, authenticate, requireRole(...FINALIZERS), action("finalize", "failed to finalize", noArgs));

scenariosRouter.post(`${p}/reopen-request`, authenticate, requireRole(...REOPEN_REQUESTERS), action("request-reopen", "failed to request reopen", requiredText("reason", "a reason")));
scenariosRouter.post(
  `${p}/reopen-decision`,
  authenticate,
  requireRole(...FINALIZERS),
  action("decide-reopen", "failed to decide reopen", (b) => {
    if (b.decision !== "approve" && b.decision !== "deny") return { error: "decision must be 'approve' or 'deny'" };
    const note = text(b.note);
    return note ? [b.decision, note] : [b.decision];
  }),
);