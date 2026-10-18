import { NextResponse, type NextRequest } from "next/server";
import { SESSION_COOKIE, tokenIsFresh } from "@/lib/session";

// Keeps signed-out visitors on the login page and signed-in ones off it. This is a convenience, not the
// security boundary: the API verifies the token on every request and answers 401 when it is not valid.
export function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;
  const signedIn = tokenIsFresh(req.cookies.get(SESSION_COOKIE)?.value);

  if (pathname === "/login") {
    if (signedIn) return NextResponse.redirect(new URL("/dashboard", req.url));
    return NextResponse.next();
  }

  if (!signedIn) {
    const url = new URL("/login", req.url);
    if (pathname !== "/") url.searchParams.set("next", pathname + req.nextUrl.search);
    const res = NextResponse.redirect(url);
    if (req.cookies.get(SESSION_COOKIE)) res.cookies.delete(SESSION_COOKIE);
    return res;
  }
  return NextResponse.next();
}

export const config = {
  // everything except the API routes, Next's own assets and the favicon
  matcher: ["/((?!api/|_next/|favicon.ico).*)"],
};