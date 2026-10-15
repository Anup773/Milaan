import { Router } from "express";
import { authenticate } from "../auth/middleware.js";
import { requireRole } from "../auth/authorize.js";
import { assertCompanyInFirm } from "../companies/access.js";
import { respondError } from "../../lib/http.js";
import { runEngineCli } from "../../lib/pythonEngine.js";
import type { Role } from "../auth/types.js";

export const auditRouter = Router();

const CLI = "engine.audit.cli";

// Who may do what with the audit trail. These lists are the same ones engine/audit/policy.py holds
// (READ_ROLES / EXPORT_ROLES / VERIFY_ROLES) -- tests/test_audit_policy.py reads this file and fails
// if the two ever drift apart. The engine checks the role again itself, so a route that forgot
// requireRole would still be refused with 403.
const READERS: Role[] = ["senior_accountant", "ca", "reviewer", "admin"];
const EXPORTERS: Role[] = ["ca", "reviewer", "admin"];
const VERIFIERS: Role[] = ["ca", "reviewer", "admin"];

const queryText = (v: unknown): string | undefined => (typeof v === "string" && v.length > 0 ? v : undefined);

const FILTER_KEYS = ["periodId", "actorId", "action", "objectType", "objectId", "from", "to", "search"] as const;

/** Builds the filters the engine accepts from the query string. The engine validates every value itself. */
function filtersFrom(query: Record<string, unknown>, paged: boolean): Record<string, unknown> | { error: string } {
  const filters: Record<string, unknown> = {};
  for (const key of FILTER_KEYS) {
    const v = queryText(query[key]);
    if (v !== undefined) filters[key] = v;
  }
  if (paged) {
    for (const key of ["limit", "offset"] as const) {
      const v = queryText(query[key]);
      if (v !== undefined) {
        const n = Number(v);
        if (!Number.isInteger(n) || n < 0) return { error: `${key} must be a non-negative whole number` };
        filters[key] = n;
      }
    }
  }
  return filters;
}

// Everything a UI needs to build filters and labels, plus who may do what.
auditRouter.get("/:companyId/audit-events/catalog", authenticate, requireRole(...READERS), async (req, res) => {
  const { companyId } = req.params;
  const auth = req.auth!;
  try {
    await assertCompanyInFirm(auth.firmId, companyId);
    res.json(await runEngineCli(CLI, ["catalog", auth.firmId, companyId]));
  } catch (err) {
    respondError(res, err, "failed to load the audit catalog");
  }
});

// Counts for a dashboard card. Optional: periodId, actorId, action, objectType, from, to, search.
auditRouter.get("/:companyId/audit-events/summary", authenticate, requireRole(...READERS), async (req, res) => {
  const { companyId } = req.params;
  const auth = req.auth!;
  const filters = filtersFrom(req.query, false);
  if ("error" in filters) {
    res.status(400).json(filters);
    return;
  }
  try {
    await assertCompanyInFirm(auth.firmId, companyId);
    res.json(await runEngineCli(CLI, ["summary", auth.firmId, companyId, auth.role, JSON.stringify(filters)]));
  } catch (err) {
    respondError(res, err, "failed to load the audit summary");
  }
});

// Walks the hash chain: is the recorded history intact? Returns ok, how many events were checked,
// the first broken event if any, and the head hash (write it down to prove later that nothing at the end was removed).
auditRouter.get("/:companyId/audit-events/verify", authenticate, requireRole(...VERIFIERS), async (req, res) => {
  const { companyId } = req.params;
  const auth = req.auth!;
  try {
    await assertCompanyInFirm(auth.firmId, companyId);
    res.json(await runEngineCli(CLI, ["verify", auth.firmId, companyId, auth.role]));
  } catch (err) {
    respondError(res, err, "failed to verify the audit trail");
  }
});

// The trail as a CSV download (oldest first, formula-safe). Taking a copy is itself recorded as an
// 'audit.export' event. Optional filters as for the list.
auditRouter.get("/:companyId/audit-events/export", authenticate, requireRole(...EXPORTERS), async (req, res) => {
  const { companyId } = req.params;
  const auth = req.auth!;
  const filters = filtersFrom(req.query, false);
  if ("error" in filters) {
    res.status(400).json(filters);
    return;
  }
  try {
    await assertCompanyInFirm(auth.firmId, companyId);
    const out = await runEngineCli<{ filename: string; csv: string; rows: number; truncated: boolean }>(CLI, [
      "export", auth.firmId, companyId, auth.userId, auth.role, JSON.stringify(filters),
    ]);
    res.setHeader("Content-Type", "text/csv; charset=utf-8");
    res.setHeader("Content-Disposition", `attachment; filename="${out.filename}"`);
    res.setHeader("X-Audit-Rows", String(out.rows));
    res.setHeader("X-Audit-Truncated", String(out.truncated));
    res.send(out.csv);
  } catch (err) {
    respondError(res, err, "failed to export the audit trail");
  }
});

// Everything that ever happened to one object, oldest first. Optional: limit (max 500), offset.
auditRouter.get(
  "/:companyId/audit-events/object/:objectType/:objectId",
  authenticate,
  requireRole(...READERS),
  async (req, res) => {
    const { companyId, objectType, objectId } = req.params;
    const auth = req.auth!;
    const paging = filtersFrom(req.query, true);
    if ("error" in paging) {
      res.status(400).json(paging);
      return;
    }
    const { limit, offset } = paging as { limit?: number; offset?: number };
    try {
      await assertCompanyInFirm(auth.firmId, companyId);
      res.json(
        await runEngineCli(CLI, [
          "history", auth.firmId, companyId, auth.role, objectType, objectId, JSON.stringify({ limit, offset }),
        ]),
      );
    } catch (err) {
      respondError(res, err, "failed to load the object's history");
    }
  },
);

// The trail, newest first. Optional: periodId, actorId, action ('scenario.approve' or a group like 'scenario'),
// objectType, objectId, from, to (YYYY-MM-DD, inclusive), search (inside the reason), limit (max 500), offset.
auditRouter.get("/:companyId/audit-events", authenticate, requireRole(...READERS), async (req, res) => {
  const { companyId } = req.params;
  const auth = req.auth!;
  const filters = filtersFrom(req.query, true);
  if ("error" in filters) {
    res.status(400).json(filters);
    return;
  }
  try {
    await assertCompanyInFirm(auth.firmId, companyId);
    res.json(await runEngineCli(CLI, ["list", auth.firmId, companyId, auth.role, JSON.stringify(filters)]));
  } catch (err) {
    respondError(res, err, "failed to load the audit trail");
  }
});

// One event with the events just before and after it in the chain. Declared last so "summary",
// "verify", "export" and "catalog" are not taken for ids.
auditRouter.get("/:companyId/audit-events/:eventId", authenticate, requireRole(...READERS), async (req, res) => {
  const { companyId, eventId } = req.params;
  const auth = req.auth!;
  try {
    await assertCompanyInFirm(auth.firmId, companyId);
    res.json(await runEngineCli(CLI, ["get", auth.firmId, companyId, auth.role, eventId]));
  } catch (err) {
    respondError(res, err, "failed to load the audit event");
  }
});
