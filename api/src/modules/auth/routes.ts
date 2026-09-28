import { Router } from "express";
import { verifyPassword } from "./password.js";
import { signSession } from "./jwt.js";
import { pool } from "../../db/client.js";
import type { AuthContext, Role } from "./types.js";

export const authRouter = Router();

/**
 * Calls login_lookup() from migration 0001 -- a narrow SECURITY DEFINER
 * function that's the one legitimate exception to RLS: at login we don't
 * know the user's firm_id yet, which is exactly what we're looking up, so
 * an ordinary (RLS-protected) query on `users` would return nothing even
 * for a real user. See the migration file for why that function is safe.
 */
async function findUserByEmail(
  email: string
): Promise<{ id: string; firmId: string; passwordHash: string; role: Role; active: boolean } | null> {
  const result = await pool.query(
    "SELECT id, firm_id, password_hash, role, active FROM login_lookup($1)",
    [email]
  );
  if (result.rows.length === 0) return null;
  const row = result.rows[0];
  return { id: row.id, firmId: row.firm_id, passwordHash: row.password_hash, role: row.role, active: row.active };
}

authRouter.post("/login", async (req, res) => {
  const { email, password } = req.body ?? {};
  if (typeof email !== "string" || typeof password !== "string") {
    res.status(400).json({ error: "email and password are required" });
    return;
  }

  let user;
  try {
    user = await findUserByEmail(email);
  } catch (err) {
    console.error("login lookup failed:", err);
    res.status(500).json({ error: "could not reach the database" });
    return;
  }

  // Same message for "no such user", "wrong password", and "deactivated" --
  // don't reveal which one it was.
  if (!user || !user.active || !(await verifyPassword(password, user.passwordHash))) {
    res.status(401).json({ error: "invalid email or password" });
    return;
  }

  const auth: AuthContext = {
    userId: user.id,
    firmId: user.firmId,
    companyId: null,
    role: user.role,
  };

  res.json({ token: signSession(auth) });
});
