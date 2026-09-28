import type { NextFunction, Request, Response } from "express";
import { verifySession } from "./jwt.js";

/**
 * DRAFT simplification: this trusts the JWT payload as-is. The real version
 * should also confirm, per ARCHITECTURE.md §9 ("resolves to User -> Firm ->
 * Company on every request"), that the user/firm/company in the token are
 * still active in the DB -- e.g. a deactivated user's existing token should
 * stop working before it expires. Add that DB lookup here once the real
 * users/firms/companies tables are wired in.
 */
export function authenticate(req: Request, res: Response, next: NextFunction) {
  const header = req.headers.authorization;
  if (!header?.startsWith("Bearer ")) {
    res.status(401).json({ error: "missing bearer token" });
    return;
  }

  try {
    req.auth = verifySession(header.slice("Bearer ".length));
    next();
  } catch {
    res.status(401).json({ error: "invalid or expired token" });
  }
}
