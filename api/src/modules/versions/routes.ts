import { Router } from "express";
import { authenticate } from "../auth/middleware.js";
import { assertCompanyInFirm } from "../companies/access.js";
import { respondError } from "../../lib/http.js";
import { runEngineCli } from "../../lib/pythonEngine.js";

export const versionsRouter = Router();

const CLI = "engine.versions.cli";
const KINDS = ["CHANGED", "ADDED", "REMOVED", "UNCHANGED"];

const queryText = (v: unknown): string | undefined => (typeof v === "string" && v.length > 0 ? v : undefined);

// Both routes only READ. A comparison never changes an import, the ledger or anything else:
// turning a difference into a ledger change is what adjustments (with approval) are for.

// Every import for the company, newest first -- what can be chosen for a comparison.
versionsRouter.get("/:companyId/versions/files", authenticate, async (req, res) => {
  const { companyId } = req.params;
  const auth = req.auth!;
  try {
    await assertCompanyInFirm(auth.firmId, companyId);
    res.json(await runEngineCli(CLI, ["files", auth.firmId, companyId]));
  } catch (err) {
    respondError(res, err, "failed to list imports");
  }
});

// Compare an older import (baseFileId) with a newer one (compareFileId).
// Optional: kind=CHANGED|ADDED|REMOVED|UNCHANGED (repeat or comma-separate for several),
// includeUnchanged=true, limit (max 2000), offset.
versionsRouter.get("/:companyId/versions/compare", authenticate, async (req, res) => {
  const { companyId } = req.params;
  const q = req.query;
  const auth = req.auth!;
  const baseFileId = queryText(q.baseFileId);
  const compareFileId = queryText(q.compareFileId);
  if (!baseFileId || !compareFileId) {
    res.status(400).json({ error: "baseFileId and compareFileId query parameters are required" });
    return;
  }

  const options: Record<string, unknown> = {};
  const rawKinds = ([] as unknown[]).concat(q.kind ?? []).flatMap((k) => (typeof k === "string" ? k.split(",") : []));
  const kinds = rawKinds.map((k) => k.trim().toUpperCase()).filter((k) => k.length > 0);
  if (kinds.some((k) => !KINDS.includes(k))) {
    res.status(400).json({ error: `kind must be one of ${KINDS.join(", ")}` });
    return;
  }
  if (kinds.length > 0) options.kinds = kinds;
  if (q.includeUnchanged === "true") options.includeUnchanged = true;
  for (const key of ["limit", "offset"] as const) {
    const v = queryText(q[key]);
    if (v !== undefined) {
      const n = Number(v);
      if (!Number.isInteger(n) || n < 0) {
        res.status(400).json({ error: `${key} must be a non-negative whole number` });
        return;
      }
      options[key] = n;
    }
  }

  try {
    await assertCompanyInFirm(auth.firmId, companyId);
    res.json(await runEngineCli(CLI, ["compare", auth.firmId, companyId, baseFileId, compareFileId, JSON.stringify(options)]));
  } catch (err) {
    respondError(res, err, "failed to compare imports");
  }
});