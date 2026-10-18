import { NextResponse, type NextRequest } from "next/server";
import { SESSION_COOKIE, apiBaseUrl, cookieSecure, tokenExpiry } from "@/lib/session";

export const dynamic = "force-dynamic";

// Signs in against the Milaan API and keeps the token in an httpOnly cookie. The token is never sent on to the browser's scripts.
export async function POST(req: NextRequest) {
  let body: { email?: unknown; password?: unknown };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "email and password are required" }, { status: 400 });
  }
  if (typeof body.email !== "string" || typeof body.password !== "string" || !body.email || !body.password) {
    return NextResponse.json({ error: "email and password are required" }, { status: 400 });
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${apiBaseUrl()}/auth/login`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ email: body.email, password: body.password }),
      cache: "no-store",
    });
  } catch {
    return NextResponse.json({ error: "cannot reach the Milaan API - is it running?" }, { status: 502 });
  }

  const data = (await upstream.json().catch(() => ({}))) as { token?: unknown; error?: unknown };
  if (!upstream.ok || typeof data.token !== "string") {
    const message = typeof data.error === "string" ? data.error : "sign-in failed";
    return NextResponse.json({ error: message }, { status: upstream.status === 401 ? 401 : upstream.ok ? 502 : upstream.status });
  }

  const exp = tokenExpiry(data.token);
  const maxAge = exp ? Math.max(60, exp - Math.floor(Date.now() / 1000)) : 60 * 60 * 12;
  const res = NextResponse.json({ ok: true });
  res.cookies.set(SESSION_COOKIE, data.token, {
    httpOnly: true,
    sameSite: "lax",
    secure: cookieSecure(),
    path: "/",
    maxAge,
  });
  return res;
}