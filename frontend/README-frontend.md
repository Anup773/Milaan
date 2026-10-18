# Milaan frontend

Next.js 14 (App Router) + Tailwind. It talks only to its own `/api/proxy/*` routes, which forward to the Milaan API and add the signed-in user's token. The browser never sees the token (it lives in an httpOnly cookie).

## Run it

1. Start the API (`api/`, default port 4000) and make sure the database is migrated.
2. In `frontend/`:

```
   cp .env.example .env.local      # PowerShell: copy .env.example .env.local
   npm install
   npm run dev
```

3. Open http://localhost:3000 and sign in with a user that exists in the API.

## Settings (`.env.local`)

- `API_URL`: where the API is. Default `http://localhost:4000`.
- `COOKIE_SECURE`: set to `true` when served over HTTPS (production).

## Production

```
npm run build
npm start
```

## Not built yet

- Evidence screens (no API endpoint yet).
- Approval policy screen (planned for Phase 22).