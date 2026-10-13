import { Router } from "express";
import { authenticate } from "../auth/middleware.js";
import { assertCompanyInFirm } from "../companies/access.js";
import { respondError } from "../../lib/http.js";
import { runEngineCli } from "../../lib/pythonEngine.js";

export const approvalsRouter = Router();

const CLI = "engine.approvals.cli";
const KINDS = ["scenario_review", "finalization", "reopen_request", "adjustment"];
const SCOPES = ["all", "mine", "waiting"];
const OUTCOMES = ["APPROVED", "REJECTED", "FINALIZED"];

const queryText = (v: unknown): string | undefined => (typeof v === "string" && v.length > 0 ? v : undefined);

// One place for everything that is waiting for a decision (scenario reviews, finalisations, reopen
// requests, adjustments). Any signed-in user of the firm may look; WHO MAY DECIDE WHAT is decided by
// the engine's approval policy, which is told the caller's role and id from the signed token. It answers
// 403 when the person may not take the decision (wrong role, or they made the thing themselves) and 400
// when the decision cannot be taken right now (period locked, no longer waiting, no note on a rejection...).
// The older per-object endpoints (scenarios/..., adjustments/...) keep working unchanged.

// Who may decide what, for building the UI.
approvalsRouter.get("/:companyId/approvals/policy", authenticate, async (req, res) => {
  const { companyId } = req.params;
  const auth = req.auth!;
  try {
    await assertCompanyInFirm(auth.firmId, companyId);
    res.json(await runEngineCli(CLI, ["policy", auth.firmId, companyId]));
  } catch (err) {
    respondError(res, err, "failed to load approval policy");
  }
});

// What is waiting, oldest first, and for the caller: can they decide it, and if not, why not.
// Optional: periodId, kind, scope=all|mine|waiting  (mine = you can decide it now; waiting = you made it)
approvalsRouter.get("/:companyId/approvals/inbox", authenticate, async (req, res) => {
  const { companyId } = req.params;
  const q = req.query;
  const auth = req.auth!;
  const filters: Record<string, string> = {};
  const periodId = queryText(q.periodId);
  const kind = queryText(q.kind);
  const scope = queryText(q.scope);
  if (periodId) filters.periodId = periodId;
  if (kind) {
    if (!KINDS.includes(kind)) {
      res.status(400).json({ error: `kind must be one of ${KINDS.join(", ")}` });
      return;
    }
    filters.kind = kind;
  }
  if (scope) {
    if (!SCOPES.includes(scope)) {
      res.status(400).json({ error: `scope must be one of ${SCOPES.join(", ")}` });
      return;
    }
    filters.scope = scope;
  }
  try {
    await assertCompanyInFirm(auth.firmId, companyId);
    res.json(await runEngineCli(CLI, ["inbox", auth.firmId, companyId, auth.userId, auth.role, JSON.stringify(filters)]));
  } catch (err) {
    respondError(res, err, "failed to load approvals inbox");
  }
});

// The dashboard card: waiting / waiting for you / waiting on others / decided so far. Optional: periodId.
approvalsRouter.get("/:companyId/approvals/summary", authenticate, async (req, res) => {
  const { companyId } = req.params;
  const periodId = queryText(req.query.periodId);
  const auth = req.auth!;
  try {
    await assertCompanyInFirm(auth.firmId, companyId);
    const args = ["summary", auth.firmId, companyId, auth.userId, auth.role];
    if (periodId) args.push(periodId);
    res.json(await runEngineCli(CLI, args));
  } catch (err) {
    respondError(res, err, "failed to load approvals summary");
  }
});

// Every decision taken so far, newest first. Optional: periodId, kind, outcome, limit (max 500), offset.
approvalsRouter.get("/:companyId/approvals/history", authenticate, async (req, res) => {
  const { companyId } = req.params;
  const q = req.query;
  const auth = req.auth!;
  const filters: Record<string, unknown> = {};
  const periodId = queryText(q.periodId);
  const kind = queryText(q.kind);
  const outcome = queryText(q.outcome)?.toUpperCase();
  if (periodId) filters.periodId = periodId;
  if (kind) {
    if (!KINDS.includes(kind)) {
      res.status(400).json({ error: `kind must be one of ${KINDS.join(", ")}` });
      return;
    }
    filters.kind = kind;
  }
  if (outcome) {
    if (!OUTCOMES.includes(outcome)) {
      res.status(400).json({ error: `outcome must be one of ${OUTCOMES.join(", ")}` });
      return;
    }
    filters.outcome = outcome;
  }
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
    res.json(await runEngineCli(CLI, ["history", auth.firmId, companyId, JSON.stringify(filters)]));
  } catch (err) {
    respondError(res, err, "failed to load approval history");
  }
});

// The review packet for one item: what exactly is being approved and what backs it.
approvalsRouter.get("/:companyId/approvals/:kind/:itemId", authenticate, async (req, res) => {
  const { companyId, kind, itemId } = req.params;
  const auth = req.auth!;
  if (!KINDS.includes(kind)) {
    res.status(400).json({ error: `kind must be one of ${KINDS.join(", ")}` });
    return;
  }
  try {
    await assertCompanyInFirm(auth.firmId, companyId);
    res.json(await runEngineCli(CLI, ["detail", auth.firmId, companyId, kind, itemId, auth.userId, auth.role]));
  } catch (err) {
    respondError(res, err, "failed to load approval item");
  }
});

// Take a decision: { "decision": "approve" | "reject", "note": "..." }. A rejection needs a note.
approvalsRouter.post("/:companyId/approvals/:kind/:itemId/decide", authenticate, async (req, res) => {
  const { companyId, kind, itemId } = req.params;
  const { decision, note } = req.body ?? ({} as Record<string, unknown>);
  const auth = req.auth!;
  if (!KINDS.includes(kind)) {
    res.status(400).json({ error: `kind must be one of ${KINDS.join(", ")}` });
    return;
  }
  if (decision !== "approve" && decision !== "reject") {
    res.status(400).json({ error: "decision must be 'approve' or 'reject'" });
    return;
  }
  try {
    await assertCompanyInFirm(auth.firmId, companyId);
    const args = ["decide", auth.firmId, companyId, kind, itemId, decision, auth.userId, auth.role];
    if (typeof note === "string" && note.trim()) args.push(note.trim());
    res.json(await runEngineCli(CLI, args));
  } catch (err) {
    respondError(res, err, "failed to record decision");
  }
});