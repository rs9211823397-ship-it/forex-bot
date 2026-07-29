import { NextRequest, NextResponse } from "next/server";
import { verifySessionToken } from "@/lib/security/token";

// Edge auth gate (Features 4 & 6):
//  - Pages without a valid session → redirect to /login
//  - API routes without a valid **signed** session cookie OR Bearer token → 401
//  - Full DB revocation checks additionally run inside mutation routes (requireUser)
const PUBLIC_PAGE_PATHS = new Set(["/login"]);
const PUBLIC_API_PREFIXES = ["/api/auth/login", "/api/auth/bootstrap", "/api/health"];

export async function proxy(req: NextRequest) {
  const { pathname } = req.nextUrl;
  const isApi = pathname.startsWith("/api/");
  if (PUBLIC_PAGE_PATHS.has(pathname)) return NextResponse.next();
  if (PUBLIC_API_PREFIXES.some((p) => pathname.startsWith(p))) return NextResponse.next();

  const cookieToken = req.cookies.get("aaqts_session")?.value;
  const authz = req.headers.get("authorization");
  const bearer = authz?.toLowerCase().startsWith("bearer ") ? authz.slice(7).trim() : null;

  const payload = (cookieToken && (await verifySessionToken(cookieToken))) || (bearer && (await verifySessionToken(bearer)));
  if (payload && payload.exp && payload.exp > Date.now()) return NextResponse.next();

  if (isApi) {
    return NextResponse.json({ error: "UNAUTHORIZED", message: "Valid session required" }, { status: 401 });
  }
  const login = new URL("/login", req.url);
  login.searchParams.set("next", pathname);
  return NextResponse.redirect(login);
}

export const config = {
  matcher: [
    // all app pages + api, excluding next internals and static assets
    "/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)",
  ],
};
