import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

// The routes keep out roles that can never write; the engine checks the role again. These must say the same thing,
// so a role added in one place and forgotten in the other fails here instead of in front of a user.
const here = dirname(fileURLToPath(import.meta.url));
const engineRoot = resolve(here, "../../../../engine/engine");

function pythonRoles(file: string, name: string): string[] {
  const text = readFileSync(resolve(engineRoot, file), "utf8");
  const match = text.match(new RegExp(`${name}(?::[^=]*)?\\s*=\\s*frozenset\\(\\{([^}]*)\\}\\)`));
  assert.ok(match, `${name} not found in ${file}`);
  return [...match![1].matchAll(/"([a-z_]+)"/g)].map((m) => m[1]).sort();
}

function routeRoles(file: string, pattern: RegExp): string[] {
  const text = readFileSync(resolve(here, file), "utf8");
  const match = text.match(pattern);
  assert.ok(match, `roles not found in ${file}`);
  return [...match![1].matchAll(/"([a-z_]+)"/g)].map((m) => m[1]).sort();
}

test("tax depreciation write roles match the engine", () => {
  assert.deepEqual(
    routeRoles("routes.ts", /const WRITE_ROLES: Role\[\] = \[([^\]]*)\]/),
    pythonRoles("schedules/tax_dep/service.py", "WRITE_ROLES"),
  );
});

test("fiscal year creation roles match the engine", () => {
  assert.deepEqual(
    routeRoles("../periods/routes.ts", /"\/:companyId\/fiscal-year",\s*authenticate,\s*requireRole\(([^)]*)\)/),
    pythonRoles("policy/fiscal.py", "CREATE_ROLES"),
  );
});

test("the policy setup roles match the engine", () => {
  assert.deepEqual(
    routeRoles("../policy/routes.ts", /const SETUP_ROLES: Role\[\] = \[([^\]]*)\]/),
    pythonRoles("policy/model.py", "SETUP_ROLES"),
  );
});