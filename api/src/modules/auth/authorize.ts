import type { NextFunction, Request, Response } from "express";
import type { Role } from "./types.js";

export function hasRole(actual: Role, allowed: readonly Role[]): boolean {
  return allowed.includes(actual);
}

/** Usage: router.post('/scenarios/:id/approve', authenticate, requireRole('ca', 'senior_accountant'), handler) */
export function requireRole(...allowed: Role[]) {
  return (req: Request, res: Response, next: NextFunction) => {
    if (!req.auth) {
      res.status(401).json({ error: "not authenticated" });
      return;
    }
    if (!hasRole(req.auth.role, allowed)) {
      res.status(403).json({ error: "not authorized for this action" });
      return;
    }
    next();
  };
}
