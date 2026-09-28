import jwt from "jsonwebtoken";
import type { AuthContext } from "./types.js";

const EXPIRES_IN = "12h";

// Read lazily (inside the functions below), not at module load -- so
// importing this file never fails just because env vars haven't loaded
// yet, and it stays easy to test. Add JWT_SECRET to your .env / config/env.ts.
function getSecret(): string {
  const value = process.env.JWT_SECRET;
  if (!value) {
    throw new Error("missing required env var: JWT_SECRET");
  }
  return value;
}

export function signSession(auth: AuthContext): string {
  return jwt.sign(auth, getSecret(), { expiresIn: EXPIRES_IN });
}

export function verifySession(token: string): AuthContext {
  return jwt.verify(token, getSecret()) as AuthContext;
}
