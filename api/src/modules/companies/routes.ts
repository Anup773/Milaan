import { Router } from "express";
import { authenticate } from "../auth/middleware.js";
import { requireRole } from "../auth/authorize.js";
import { respondError } from "../../lib/http.js";
import { withTenant } from "../../db/client.js";

export const companiesRouter = Router();

// The companies (client books) of the caller's firm. Row-level security already limits `companies` to
// the session's firm; the frontend uses this list for its company switcher.
companiesRouter.get("/", authenticate, async (req, res) => {
  const auth = req.auth!;
  try {
    const result = await withTenant({ firmId: auth.firmId }, (client) =>
      client.query(`SELECT id, name, created_at FROM companies ORDER BY name`)
    );
    res.json({ companies: result.rows });
  } catch (err) {
    respondError(res, err, "failed to list companies");
  }
});

companiesRouter.post("/", authenticate, requireRole("senior_accountant", "ca", "admin"), async (req, res) => {
  const auth = req.auth!;
  const { name } = req.body ?? {};
  if (typeof name !== "string" || !name.trim()) {
    res.status(400).json({ error: "name is required" });
    return;
  }
  try {
    const result = await withTenant({ firmId: auth.firmId, userId: auth.userId }, (client) =>
      client.query(
        `INSERT INTO companies (firm_id, name) VALUES ($1, $2) RETURNING id, name, created_at`,
        [auth.firmId, name.trim()]
      )
    );
    res.status(201).json({ company: result.rows[0] });
  } catch (err) {
    respondError(res, err, "failed to create company");
  }
});