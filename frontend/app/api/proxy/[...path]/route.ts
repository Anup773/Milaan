import { NextResponse, type NextRequest } from "next/server";
import { cookies } from "next/headers";
import { SESSION_COOKIE, apiBaseUrl } from "@/lib/session";

export const dynamic = "force-dynamic";

// Forwards the browser's API calls to the Milaan API and adds the signed-in user's token (from the httpOnly
// cookie) as the Authorization header. Nothing about who may do what is decided here -- the API decides.

const PASS_THROUGH_RESPONSE_HEADERS = [
  "content-type",
  "content-disposition",
  "x-audit-rows",
  "x-audit-truncated",
];

type Ctx = { params: { path: string[] } };

async function forward(req: NextRequest, { params }: Ctx): Promise<Response> {
  const segments = params.path ?? [];
  if (segments.length === 0 || segments.some((s) => s === "" || s === "." || s === ".." || s.includes("\\"))) {
    return NextResponse.json({ error: "bad path" }, { status: 400 });
  }
  const path = segments.join("/");

  // Sign-in has its own route (it sets the cookie). Letting it through here would hand the raw token to page scripts.
  if (path === "auth/login") {
    return NextResponse.json({ error: "not found" }, { status: 404 });
  }

  // Same-origin only for anything that changes data (belt and braces on top of the SameSite cookie).
  if (req.method !== "GET" && req.method !== "HEAD") {
    const origin = req.headers.get("origin");
    if (origin) {
      let originHost: string | null = null;
      try {
        originHost = new URL(origin).host;
      } catch {
        originHost = null;
      }
      if (originHost !== req.headers.get("host")) {
        return NextResponse.json({ error: "cross-site request refused" }, { status: 403 });
      }
    }
  }

  const token = cookies().get(SESSION_COOKIE)?.value;
  if (!token) return NextResponse.json({ error: "not signed in" }, { status: 401 });

  const target = new URL(`${apiBaseUrl()}/${path}`);
  target.search = req.nextUrl.search;

  const headers = new Headers();
  headers.set("authorization", `Bearer ${token}`);
  const contentType = req.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);
  const contentLength = req.headers.get("content-length");
  if (contentLength) headers.set("content-length", contentLength);

  const hasBody = req.method !== "GET" && req.method !== "HEAD";
  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: req.method,
      headers,
      body: hasBody ? req.body : undefined,
      // Node's fetch needs this to stream a request body (file uploads).
      ...(hasBody ? { duplex: "half" } : {}),
      redirect: "manual",
      cache: "no-store",
    } as RequestInit);
  } catch {
    return NextResponse.json({ error: "cannot reach the Milaan API - is it running?" }, { status: 502 });
  }

  const out = new Headers();
  for (const name of PASS_THROUGH_RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value) out.set(name, value);
  }
  out.set("cache-control", "no-store");
  return new NextResponse(upstream.body, { status: upstream.status, headers: out });
}

export const GET = forward;
export const POST = forward;
export const PUT = forward;
export const PATCH = forward;
export const DELETE = forward;