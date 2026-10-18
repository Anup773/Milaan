// Session cookie helpers shared by the middleware (edge runtime) and the route handlers (node runtime).
// The API's JWT lives in an httpOnly cookie, so page scripts can never read it (an XSS bug cannot steal it).
// Only its expiry is read here, to send people to the login page before a request would fail with 401.
// The signature is NOT checked here -- the API does that on every request.

export const SESSION_COOKIE = "milaan_session";

/** Seconds since epoch at which the token expires, or null if it cannot be read. */
export function tokenExpiry(token: string): number | null {
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  try {
    const base64 = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    const padded = base64 + "=".repeat((4 - (base64.length % 4)) % 4);
    const payload = JSON.parse(atob(padded)) as { exp?: unknown };
    return typeof payload.exp === "number" ? payload.exp : null;
  } catch {
    return null;
  }
}

export function tokenIsFresh(token: string | undefined): boolean {
  if (!token) return false;
  const exp = tokenExpiry(token);
  if (exp === null) return false;
  return exp * 1000 > Date.now() + 5_000;
}

export function cookieSecure(): boolean {
  if (process.env.COOKIE_SECURE === "true") return true;
  if (process.env.COOKIE_SECURE === "false") return false;
  return process.env.NODE_ENV === "production";
}

export function apiBaseUrl(): string {
  return (process.env.API_URL ?? "http://localhost:4000").replace(/\/+$/, "");
}