# Milaan — Phase 3 (API side): Auth foundation (Segment 2)

## Why this, not the upload endpoint I said was next
Looking at the actual folder structure before writing code: `api/src/modules/auth/`
and `api/src/modules/companies/` are both still tagged `[Phase 3]` — not built.
The only thing in `api/` right now is a health check. That means there's
nowhere for an upload endpoint (or anything else) to plug in yet — the API
has no way to know *who* is making a request or *which company's* books
they're allowed to touch. Building imports on top of that would mean
skipping exactly the thing ARCHITECTURE.md §9 calls out as starting "now,
not Phase 20." So this is the honest next step: a minimal, real login +
role system that every other module (imports, mappings, approvals, audit —
all of it) will sit behind.

Drop-in for `api/src/modules/auth/`. One assumption I couldn't verify:
**Express**. It's the most common pairing with this stack and the likely
framework behind your existing `/health` route, but I haven't seen
`index.ts`. If you're on Fastify or something else — `password.ts`,
`jwt.ts`, and the `hasRole()` half of `authorize.ts` don't touch Express at
all and drop in unchanged; only `middleware.ts`, `requireRole()`, and
`routes.ts` would need adapting to your framework's handler signature.

## What's real vs. drafted
- `types.ts`, `password.ts`, `jwt.ts`, `authorize.ts` — fully real, no
  unverified assumptions about your schema. Type-checked clean in strict
  mode and unit-tested (4/4 passing, see below).
- `middleware.ts` — real, but a deliberate simplification: it trusts the
  JWT as-is rather than re-checking the user/firm/company are still active
  in the DB on every request. Commented where that lookup goes.
- `routes.ts` — the login flow (verify password → issue token) is real;
  `findUserByEmail` is a stub that throws a clear "not implemented" error.
  Wire it to your actual `users` table once I have (or you paste) the real
  column names from `0001_init_canonical_schema.sql`.

## Install
```
npm install bcryptjs jsonwebtoken
npm install -D @types/bcryptjs @types/jsonwebtoken
```
Add `JWT_SECRET=<any long random string>` to `.env` / wherever `config/env.ts`
reads from.

## Wire it in
In your existing `index.ts` (or wherever the Express app is created):
```ts
import { authRouter } from "./modules/auth/routes";
app.use("/auth", authRouter);
```
Then protect any other route with:
```ts
import { authenticate } from "./modules/auth/middleware";
import { requireRole } from "./modules/auth/authorize";

router.post("/scenarios/:id/approve", authenticate, requireRole("ca", "senior_accountant"), handler);
```

## Test
`auth.test.ts` uses Node's built-in test runner (`node --test`), so it
works whether or not you've set up Jest/Vitest for `api/` yet — zero extra
dependencies either way. From `api/`:
```
npx tsx --test src/modules/auth/auth.test.ts
```
4/4 passing, plus a clean `tsc --strict` type-check, verified in a sandbox
before sending this over.

## Next, unless you'd rather redirect me
Companies CRUD (quick — list/create companies for the logged-in firm) is
the natural next piece, since it's what `companyId` above will actually
point at. After that, the upload endpoint now has somewhere real to
plug in.
