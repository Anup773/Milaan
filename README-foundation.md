# Milaan — real project foundation (Segment 3)

This is the piece that was actually missing: the files that make `pip
install` and `npm install` have something to install *into*. Verified for
real in a sandbox — fresh install, clean strict type-check, tests passing,
and the server actually booted and answered requests (see below).

## What's in here

**engine/** — `pyproject.toml` (declares openpyxl + pytest, makes the
`engine` package installable) and `engine/engine/__init__.py`. Your
existing `ingestion/` and `tests/` folders don't need to change — just
add these two new files alongside them.

**api/** — `package.json`, `tsconfig.json`, `.env.example`, and a real
`src/index.ts` that boots an Express server with a `/health` route and
wires in the auth routes.

**api/src/modules/auth/** — all 7 files again, **replace your existing
auth folder with these**. Testing this end to end caught a real bug: five
of the files were missing `.js` on their internal imports (required by
the module setup in tsconfig.json). Fixed here.

## Install

From `engine/`:
```
pip install -e ".[dev]"
pytest engine/tests/test_ingestion.py -v
```

From `api/`:
```
npm install
cp .env.example .env
npm test
npm run dev
```
Then, with it running, open `http://localhost:4000/health` in a browser —
you should see `{"status":"ok"}`.

## What this proves (checked in my sandbox before sending)
- Fresh `pip install` into an empty virtual environment → 6/6 tests pass.
- Fresh `npm install` → strict type-check clean, 4/4 tests pass.
- Server actually started and answered real requests:
  `/health` → `{"status":"ok"}`
  `/auth/login` → `{"error":"login not wired up yet -- see routes.ts"}`
  (that second one is *correct* — there's no real database yet, so it
  honestly says so instead of crashing or faking a result)

## What's still not here
A real database. `persist_stub.py` and `findUserByEmail` in `routes.ts`
are still intentional stubs. Postgres + the first real migration is the
next segment.
