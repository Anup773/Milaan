import { Router } from "express";
import type { RequestHandler } from "express";
import { authenticate } from "../auth/middleware.js";
import { requireRole } from "../auth/authorize.js";
import { assertCompanyInFirm } from "../companies/access.js";
import { respondError } from "../../lib/http.js";
import { runEngineCli } from "../../lib/pythonEngine.js";
import type { Role } from "../auth/types.js";

export const exceptionsRouter = Router();

const CLI = "engine.exceptions.cli";

// Who may do what. Looking at flags, running detection and raising a flag by hand never change the
// books, so any authenticated user of the firm may. Deciding a flag is a review job. Proposing the
// reversal of an entry is the same job as proposing any adjustment. (The second-person rules --
// whoever raised a manual flag cannot decide it; whoever proposes an adjustment cannot approve it --
// are enforced separately, in the engine AND by the database.)
const REVIEWERS: Role[] = ["senior_accountant", "ca", "reviewer", "admin"];
const MAKERS: Role[] = ["accountant", "senior_accountant", "ca", "admin"];

const text = (v: unknown): string | undefined => (typeof v === "string" && v.trim() ? v.trim() : undefined);
const queryText = (v: unknown): string | undefined => (typeof v === "string" && v.length > 0 ? v : undefined);

/** A POST handler for an action on one flag: runs `engine.exceptions.cli <command> ...`. */
function action(
  command: string,
  failMessage: string,
  buildExtraArgs: (body: Record<string, unknown>) => string[] | { error: string },
): RequestHandler {
  return async (req, res) => {
    const { companyId, exceptionId } = req.params;
    const auth = req.auth!;
    const extra = buildExtraArgs((req.body ?? {}) as Record<string, unknown>);
    if (!Array.isArray(extra)) {
      res.status(400).json(extra);
      return;
    }
    try {
      await assertCompanyInFirm(auth.firmId, companyId);
      res.json(await runEngineCli(CLI, [command, auth.firmId, companyId, exceptionId, auth.userId, ...extra]));
    } catch (err) {
      respondError(res, err, failMessage);
    }
  };
}

const optionalNote = (b: Record<string, unknown>) => {
  const n = text(b.note);
  return n ? [n] : [];
};
const requiredNote = (b: Record<string, unknown>) => {
  const n = text(b.note);
  return n ? [n] : { error: "a note is required" };
};

// ── reads (declared before /:exceptionId so "rules", "summary" and "runs" are not taken for ids) ──
exceptionsRouter.get("/:companyId/exceptions/rules", authenticate, async (req, res) => {
  const { companyId } = req.params;
  const auth = req.auth!;
  try {
    await assertCompanyInFirm(auth.firmId, companyId);
    res.json(await runEngineCli(CLI, ["rules", auth.firmId, companyId]));
  } catch (err) {
    respondError(res, err, "failed to list exception rules");
  }
});

// The dashboard's exception card.
exceptionsRouter.get("/:companyId/exceptions/summary", authenticate, async (req, res) => {
  const { companyId } = req.params;
  const periodId = queryText(req.query.periodId);
  const auth = req.auth!;
  if (!periodId) {
    res.status(400).json({ error: "periodId query parameter is required" });
    return;
  }
  try {
    await assertCompanyInFirm(auth.firmId, companyId);
    res.json(await runEngineCli(CLI, ["summary", auth.firmId, companyId, periodId]));
  } catch (err) {
    respondError(res, err, "failed to load exception summary");
  }
});

exceptionsRouter.get("/:companyId/exceptions/runs", authenticate, async (req, res) => {
  const { companyId } = req.params;
  const periodId = queryText(req.query.periodId);
  const auth = req.auth!;
  if (!periodId) {
    res.status(400).json({ error: "periodId query parameter is required" });
    return;
  }
  try {
    await assertCompanyInFirm(auth.firmId, companyId);
    res.json(await runEngineCli(CLI, ["runs", auth.firmId, companyId, periodId]));
  } catch (err) {
    respondError(res, err, "failed to list detection runs");
  }
});

exceptionsRouter.get("/:companyId/exceptions/runs/:runId", authenticate, async (req, res) => {
  const { companyId, runId } = req.params;
  const auth = req.auth!;
  try {
    await assertCompanyInFirm(auth.firmId, companyId);
    res.json(await runEngineCli(CLI, ["run", auth.firmId, companyId, runId]));
  } catch (err) {
    respondError(res, err, "failed to load detection run");
  }
});

// List flags. Filters: periodId, status, category, priority, openOnly=true, limit, offset.
exceptionsRouter.get("/:companyId/exceptions", authenticate, async (req, res) => {
  const { companyId } = req.params;
  const q = req.query;
  const auth = req.auth!;
  const filters: Record<string, unknown> = {};
  for (const key of ["periodId", "status", "category", "priority"] as const) {
    const v = queryText(q[key]);
    if (v) filters[key] = v;
  }
  if (q.openOnly === "true") filters.openOnly = true;
  for (const key of ["limit", "offset"] as const) {
    const v = queryText(q[key]);
    if (v !== undefined) {
      const n = Number(v);
      if (!Number.isInteger(n) || n < 0) {
        res.status(400).json({ error: `${key} must be a non-negative whole number` });
        return;
      }
      filters[key] = n;
    }
  }
  try {
    await assertCompanyInFirm(auth.firmId, companyId);
    res.json(await runEngineCli(CLI, ["list", auth.firmId, companyId, JSON.stringify(filters)]));
  } catch (err) {
    respondError(res, err, "failed to list exceptions");
  }
});

// One flag with its history, linked adjustments and the entries it is about.
exceptionsRouter.get("/:companyId/exceptions/:exceptionId", authenticate, async (req, res) => {
  const { companyId, exceptionId } = req.params;
  const auth = req.auth!;
  try {
    await assertCompanyInFirm(auth.firmId, companyId);
    res.json(await runEngineCli(CLI, ["get", auth.firmId, companyId, exceptionId]));
  } catch (err) {
    respondError(res, err, "failed to load exception");
  }
});

// ── detection and manual flags ───────────────────────────────────────────
// Run every detector on a period and bring the flags up to date (the run is saved).
exceptionsRouter.post("/:companyId/exceptions/detect", authenticate, async (req, res) => {
  const { companyId } = req.params;
  const periodId = (req.body ?? {}).periodId;
  const auth = req.auth!;
  if (typeof periodId !== "string" || periodId.length === 0) {
    res.status(400).json({ error: "periodId is required" });
    return;
  }
  try {
    await assertCompanyInFirm(auth.firmId, companyId);
    res.status(201).json(await runEngineCli(CLI, ["detect", auth.firmId, companyId, periodId, auth.userId]));
  } catch (err) {
    respondError(res, err, "failed to run exception detection");
  }
});

// A person flags an entry the detectors did not ("other review flags").
exceptionsRouter.post("/:companyId/exceptions", authenticate, async (req, res) => {
  const { companyId } = req.params;
  const { journalEntryId, note, title, priority } = req.body ?? ({} as Record<string, unknown>);
  const auth = req.auth!;
  if (typeof journalEntryId !== "string" || !text(note)) {
    res.status(400).json({ error: "journalEntryId and a note saying why the entry needs review are required" });
    return;
  }
  try {
    await assertCompanyInFirm(auth.firmId, companyId);
    const payload = JSON.stringify({
      journalEntryId, note, raisedBy: auth.userId,
      title: typeof title === "string" ? title : undefined,
      priority: typeof priority === "string" ? priority : undefined,
    });
    res.status(201).json(await runEngineCli(CLI, ["raise", auth.firmId, companyId, payload]));
  } catch (err) {
    respondError(res, err, "failed to raise exception");
  }
});

// ── the review flow: FLAGGED -> CA REVIEW -> Retain / Correct / Reverse / Request evidence ──
const p = "/:companyId/exceptions/:exceptionId";
exceptionsRouter.post(`${p}/claim`, authenticate, requireRole(...REVIEWERS), action("claim", "failed to start review", optionalNote));
exceptionsRouter.post(`${p}/request-evidence`, authenticate, requireRole(...REVIEWERS), action("request-evidence", "failed to request evidence", requiredNote));
exceptionsRouter.post(`${p}/evidence-received`, authenticate, requireRole(...REVIEWERS), action("evidence-received", "failed to record evidence", requiredNote));
exceptionsRouter.post(`${p}/retain`, authenticate, requireRole(...REVIEWERS), action("retain", "failed to retain", requiredNote));
exceptionsRouter.post(`${p}/correct`, authenticate, requireRole(...REVIEWERS), action("correct", "failed to mark for correction", requiredNote));
exceptionsRouter.post(`${p}/reverse`, authenticate, requireRole(...REVIEWERS), action("reverse", "failed to mark for reversal", requiredNote));
exceptionsRouter.post(`${p}/reopen`, authenticate, requireRole(...REVIEWERS), action("reopen", "failed to reopen", requiredNote));
exceptionsRouter.post(`${p}/resolve`, authenticate, requireRole(...REVIEWERS), action("resolve", "failed to resolve", optionalNote));

// ── "if changed -> adjustment": the correction reaches the ledger only through a Phase 7 adjustment ──
// Tie an adjustment someone proposed (POST /companies/:id/adjustments) to this flag.
exceptionsRouter.post(
  `${p}/adjustments`,
  authenticate,
  requireRole(...REVIEWERS),
  action("link", "failed to link adjustment", (b) => {
    const id = text(b.adjustmentId);
    return id ? [id] : { error: "adjustmentId is required" };
  }),
);

// For a flag decided REVERSE: build the mirror-image entry and propose it as an adjustment.
// It still needs a second person's approval before anything is posted.
exceptionsRouter.post(
  `${p}/propose-reversal`,
  authenticate,
  requireRole(...MAKERS),
  action("propose-reversal", "failed to propose reversal", (b) => [
    JSON.stringify({
      entryDate: typeof b.entryDate === "string" ? b.entryDate : undefined,
      reason: typeof b.reason === "string" ? b.reason : undefined,
      journalEntryId: typeof b.journalEntryId === "string" ? b.journalEntryId : undefined,
    }),
  ]),
);