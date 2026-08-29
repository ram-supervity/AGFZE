import { getToken } from "next-auth/jwt";
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { buildContentSecurityPolicy, createNonce, securityHeaders } from "@/lib/csp";

/**
 * Two jobs, in one place, because Next.js runs one middleware.
 *
 * 1. **Every response carries the Content-Security-Policy and the hardening headers beside it.**
 *    The sign-in page, the legal pages and the offline route included - a policy that only covered
 *    the pages behind authentication would leave the ones an unauthenticated browser actually
 *    loads uncovered, and the sign-in page is the first thing anybody sees.
 * 2. **The protected routes still require a session**, exactly as before: no token, and the
 *    request is redirected to `/signin` with the path it was going to as `callbackUrl`.
 *
 * The session check is `getToken` directly rather than `withAuth`. That is deliberate and it was
 * found by testing rather than by reading: `withAuth` returns early - without calling the
 * middleware it wraps - for the sign-in page and for any request it redirects, so wrapping this
 * function in it left exactly those responses with no policy on them. `getToken` is what
 * `withAuth` uses internally, so the behaviour is the same and the headers are unconditional.
 */
const PROTECTED_PREFIXES = [
  "/dashboard",
  "/inbox",
  "/transactions",
  "/documents",
  "/exceptions",
  "/approvals",
  "/shipments",
  "/analytics",
  "/reports",
  "/admin",
  "/notifications",
  "/settings",
];

export function isProtected(pathname: string): boolean {
  return PROTECTED_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
}

function isSecure(request: NextRequest): boolean {
  return (
    request.nextUrl.protocol === "https:" ||
    (request.headers.get("x-forwarded-proto") || "").split(",")[0].trim() === "https"
  );
}

export default async function middleware(request: NextRequest) {
  const nonce = createNonce();
  const secure = isSecure(request);
  const policy = buildContentSecurityPolicy(nonce, {
    apiBaseUrl: process.env.NEXT_PUBLIC_API_BASE_URL,
    keycloakIssuer: process.env.KEYCLOAK_ISSUER,
    secure,
  });

  // Next.js reads the policy off the *request* headers to find the nonce and stamp it onto its own
  // bootstrap scripts, so it has to be set on the way in as well as on the way out. This is also
  // why the root layout forces dynamic rendering: a prerendered page's HTML was written at build
  // time and cannot carry a per-request nonce.
  const forwarded = new Headers(request.headers);
  forwarded.set("x-nonce", nonce);
  forwarded.set("content-security-policy", policy);

  let response: NextResponse;
  if (isProtected(request.nextUrl.pathname)) {
    const token = await getToken({ req: request, secureCookie: secure });
    if (token) {
      response = NextResponse.next({ request: { headers: forwarded } });
    } else {
      const signIn = new URL("/signin", request.url);
      signIn.searchParams.set(
        "callbackUrl",
        `${request.nextUrl.pathname}${request.nextUrl.search}`,
      );
      response = NextResponse.redirect(signIn);
    }
  } else {
    response = NextResponse.next({ request: { headers: forwarded } });
  }

  response.headers.set("content-security-policy", policy);
  for (const [name, value] of securityHeaders(secure)) response.headers.set(name, value);
  return response;
}

export const config = {
  // Everything except the assets that are served straight off disk and carry no markup: the build
  // output, the icon set, the manifest and the service worker itself. A CSP on a PNG is noise, and
  // running middleware on the worker script would put a per-request nonce into a file the browser
  // is meant to cache. `/api/auth` is NextAuth's own route handler, which serves no page.
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|icons/|sw.js|manifest.webmanifest|api/auth).*)",
  ],
};
