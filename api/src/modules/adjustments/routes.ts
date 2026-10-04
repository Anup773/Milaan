import { Router } from "express";
import { authenticate } from "../auth/middleware.js";
import { requireRole } from "../auth/authorize.js";
import { assertCompanyInFirm } from "../companies/access.js";
import { respondError } from "../../lib/http.js";
import { runEngineCli } from "../../lib/pythonEngine.js";

export const adjustmentsRouter = Router();

interface ProposedLineInput {
  accountId: string;
  debit: number;
  credit: number;
}

adjustmentsRouter.get("/:companyId/adjustments", authenticate, async (req, res) => {
  const { companyId } = req.params;
  const { status } = req.query;
  const auth = req.auth!;

  try {
    await assertCompanyInFirm(auth.firmId, companyId);
    const args = ["list", auth.firmId, companyId];
    if (typeof status === "string") args.push(status);
    const result = await runEngineCli("engine.adjustments.cli", args);
    res.json(result);
  } catch (err) {
    respondError(res, err, "failed to list adjustments");
  }
});

adjustmentsRouter.get("/:companyId/adjustments/:adjustmentId", authenticate, async (req, res) => {
  const { companyId, adjustmentId } = req.params;
  const auth = req.auth!;

  try {
    await assertCompanyInFirm(auth.firmId, companyId);
    const result = await runEngineCli("engine.adjustments.cli", ["get", auth.firmId, companyId, adjustmentId]);
    res.json(result);
  } catch (err) {
    respondError(res, err, "failed to load adjustment");
  }
});

adjustmentsRouter.post(
  "/:companyId/adjustments",
  authenticate,
  requireRole("accountant", "senior_accountant", "ca", "admin"),
  async (req, res) => {
    const { companyId } = req.params;
    const auth = req.auth!;
    const { periodId, entryDate, description, reason, lines } = req.body ?? ({} as {
      periodId?: string;
      entryDate?: string;
      description?: string;
      reason?: string;
      lines?: ProposedLineInput[];
    });

    if (
      typeof periodId !== "string" ||
      typeof entryDate !== "string" ||
      typeof description !== "string" || !description.trim() ||
      typeof reason !== "string" || !reason.trim() ||
      !Array.isArray(lines) || lines.length < 2
    ) {
      res.status(400).json({ error: "periodId, entryDate, description, reason and at least 2 lines are required" });
      return;
    }

    try {
      await assertCompanyInFirm(auth.firmId, companyId);
      const payload = JSON.stringify({ periodId, entryDate, description, reason, lines, proposedBy: auth.userId });
      const result = await runEngineCli("engine.adjustments.cli", ["propose", auth.firmId, companyId, payload]);
      res.status(201).json(result);
    } catch (err) {
      respondError(res, err, "failed to propose adjustment");
    }
  }
);

// Approve/reject deliberately excludes plain "accountant" -- the point of
// this gate is a second, more senior pair of eyes. "reviewer" is included
// on purpose: it's the role that exists specifically for this.
adjustmentsRouter.post(
  "/:companyId/adjustments/:adjustmentId/approve",
  authenticate,
  requireRole("senior_accountant", "ca", "reviewer", "admin"),
  async (req, res) => {
    const { companyId, adjustmentId } = req.params;
    const auth = req.auth!;

    try {
      await assertCompanyInFirm(auth.firmId, companyId);
      const result = await runEngineCli("engine.adjustments.cli", ["approve", auth.firmId, companyId, adjustmentId, auth.userId]);
      res.json(result);
    } catch (err) {
      respondError(res, err, "failed to approve adjustment");
    }
  }
);

adjustmentsRouter.post(
  "/:companyId/adjustments/:adjustmentId/reject",
  authenticate,
  requireRole("senior_accountant", "ca", "reviewer", "admin"),
  async (req, res) => {
    const { companyId, adjustmentId } = req.params;
    const { note } = req.body ?? {};
    const auth = req.auth!;

    try {
      await assertCompanyInFirm(auth.firmId, companyId);
      const args = ["reject", auth.firmId, companyId, adjustmentId, auth.userId];
      if (typeof note === "string" && note.trim()) args.push(note.trim());
      const result = await runEngineCli("engine.adjustments.cli", args);
      res.json(result);
    } catch (err) {
      respondError(res, err, "failed to reject adjustment");
    }
  }
);