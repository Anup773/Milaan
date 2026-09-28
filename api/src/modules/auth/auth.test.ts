import { test } from "node:test";
import assert from "node:assert/strict";

process.env.JWT_SECRET = "test-secret-do-not-use-in-prod";

import { hashPassword, verifyPassword } from "./password.js";
import { signSession, verifySession } from "./jwt.js";
import { hasRole } from "./authorize.js";
import type { AuthContext } from "./types.js";

test("password hash round-trips and rejects wrong password", async () => {
  const hash = await hashPassword("correct horse battery staple");
  assert.equal(await verifyPassword("correct horse battery staple", hash), true);
  assert.equal(await verifyPassword("wrong password", hash), false);
});

test("jwt session round-trips", () => {
  const auth: AuthContext = { userId: "u1", firmId: "f1", companyId: "c1", role: "ca" };
  const token = signSession(auth);
  const decoded = verifySession(token);
  // verifySession also returns jwt's own `iat`/`exp` claims, so check our
  // fields specifically rather than a strict deep-equal against `auth`.
  assert.equal(decoded.userId, auth.userId);
  assert.equal(decoded.firmId, auth.firmId);
  assert.equal(decoded.companyId, auth.companyId);
  assert.equal(decoded.role, auth.role);
});

test("jwt rejects a tampered token", () => {
  const token = signSession({ userId: "u1", firmId: "f1", companyId: null, role: "admin" });
  assert.throws(() => verifySession(token.slice(0, -2) + "xx"));
});

test("hasRole allows listed roles and rejects others", () => {
  assert.equal(hasRole("ca", ["ca", "senior_accountant"]), true);
  assert.equal(hasRole("accountant", ["ca", "senior_accountant"]), false);
});
