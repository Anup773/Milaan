# Milaan — real database (Segment 4)

Everything below was tested against a real local Postgres in my sandbox
before this was sent — schema applied cleanly, and I proved tenant
isolation actually works (not just "the policy exists"): a second firm
gets zero rows even when the data physically exists in the same table,
even when the ID is guessed directly. Full login flow tested too: correct
password → real token issued; wrong password / unknown email → same
generic error either way (no clue given about which one it was).

## Exactly what's new, changed, or to delete

**Brand new files — add these:**
- `engine/migrations/0001_init_canonical_schema.sql`
- `engine/engine/db/__init__.py`
- `engine/engine/db/connection.py`
- `engine/engine/ingestion/persist.py`
- `api/src/db/client.ts`

**Delete this one** (superseded by `persist.py` above):
- `engine/engine/ingestion/persist_stub.py`

**Replace these 3 with the versions in this zip** (all changed):
- `api/src/modules/auth/routes.ts` — login is real now, no longer a stub
- `api/package.json` — added the `pg` package
- `api/.env.example` — added the database connection line

`ingestion`'s other 8 files, and everything in `auth/` besides `routes.ts`,
are untouched — leave them exactly as they are.

## Get a real database (5 minutes, no install)
1. supabase.com → sign up (free) → "New project"
2. In the project, open the **SQL Editor** and paste in the entire
   contents of `0001_init_canonical_schema.sql`, then run it.
3. Before running, change `'CHANGE_ME'` near the bottom of that file (the
   `app_user` password) to something real.
4. Project Settings → Database → copy the connection string. In your
   `.env`, set `APP_DATABASE_URL` to that string, but with `app_user` and
   your real password in place of the default user/password — the app
   must connect as `app_user`, never Supabase's own admin connection, or
   every RLS rule in the schema silently does nothing.

## Run it
From `api/`: `npm install`, then `npm run dev`. `/auth/login` will now
give real answers instead of "not wired up yet" — you'll need at least
one row in `firms` and `users` first (insert directly via Supabase's SQL
Editor for now; a signup endpoint is a later phase).
