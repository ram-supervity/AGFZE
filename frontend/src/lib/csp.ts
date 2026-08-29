/**
 * The Content-Security-Policy this application serves, built in one pure function.
 *
 * No prior step shipped a CSP at all, so this is the whole of it and it is deliberately narrow.
 * The rule it follows is that a source only appears here if the browser genuinely has to reach it:
 *
 * - **this origin**, for the application's own pages, chunks, styles and icons;
 * - **the API origin**, because the browser talks to the backend directly for uploads, polling and
 *   every client-component read, and because a signed document link is served from it;
 * - **the Keycloak issuer**, which is where the browser is sent to sign in and back from.
 *
 * Nothing else. Every other external system this platform integrates with - Graph, Gemini, SAP,
 * DMS, a carrier, an SMTP relay - is reached by the backend and by the backend only, so not one of
 * them has any business in a browser-facing policy, and none of them is named below.
 *
 * `script-src` carries a per-request nonce rather than `'unsafe-inline'`. Next.js reads the nonce
 * out of the CSP header the middleware sets and stamps it onto its own bootstrap scripts, so the
 * strictest useful setting is also the one that works. `style-src` keeps `'unsafe-inline'`: the
 * framework emits inline style attributes and a hydration style block, an injected `style`
 * attribute cannot execute anything, and refusing it would break the application to buy nothing.
 */

export interface CspOrigins {
  /** Where the backend API lives, absolute. Empty is tolerated and simply contributes nothing. */
  apiBaseUrl?: string;
  /** The Keycloak realm URL the browser is redirected to and back from. */
  keycloakIssuer?: string;
  /** Whether this response is being served over HTTPS. Controls upgrade-insecure-requests. */
  secure?: boolean;
}

/** The origin of an absolute URL, or null for anything that is not one. */
export function originOf(value: string | undefined | null): string | null {
  if (!value) return null;
  try {
    return new URL(value).origin;
  } catch {
    return null;
  }
}

function unique(values: (string | null)[]): string[] {
  return [...new Set(values.filter((value): value is string => Boolean(value)))];
}

/**
 * Build the policy. `nonce` is generated per request and must never be reused across two.
 */
export function buildContentSecurityPolicy(nonce: string, origins: CspOrigins = {}): string {
  const api = originOf(origins.apiBaseUrl);
  const keycloak = originOf(origins.keycloakIssuer);

  const directives: [string, string[]][] = [
    ["default-src", ["'self'"]],
    // 'strict-dynamic' lets the nonced Next.js bootstrap load the chunks it knows about without
    // every one of them needing a nonce of its own. Browsers that do not understand it fall back
    // to the host list beside it rather than to nothing.
    ["script-src", unique(["'self'", `'nonce-${nonce}'`, "'strict-dynamic'"])],
    ["style-src", ["'self'", "'unsafe-inline'"]],
    // Signed document thumbnails and page images are served by the API, as blob and data URLs in
    // a couple of client-side previews.
    ["img-src", unique(["'self'", "blob:", "data:", api])],
    ["font-src", ["'self'", "data:"]],
    ["connect-src", unique(["'self'", api, keycloak])],
    ["form-action", unique(["'self'", keycloak])],
    ["frame-src", ["'none'"]],
    ["frame-ancestors", ["'none'"]],
    ["object-src", ["'none'"]],
    ["base-uri", ["'self'"]],
    ["manifest-src", ["'self'"]],
    // The service worker, and nothing else, and only from this origin.
    ["worker-src", ["'self'", "blob:"]],
  ];

  const policy = directives.map(([name, values]) => `${name} ${values.join(" ")}`);
  if (origins.secure) policy.push("upgrade-insecure-requests");
  return policy.join("; ");
}

/** The headers that accompany the policy on every page response. */
export function securityHeaders(secure: boolean, hstsMaxAgeSeconds = 63072000): [string, string][] {
  const headers: [string, string][] = [
    ["X-Content-Type-Options", "nosniff"],
    ["X-Frame-Options", "DENY"],
    ["Referrer-Policy", "strict-origin-when-cross-origin"],
    ["Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=()"],
  ];
  // Only over HTTPS. Pinning a browser to a scheme the local stack does not serve would make the
  // local stack unreachable in that browser afterwards.
  if (secure) {
    headers.push([
      "Strict-Transport-Security",
      `max-age=${hstsMaxAgeSeconds}; includeSubDomains; preload`,
    ]);
  }
  return headers;
}

/** A 128-bit nonce, base64. Uses Web Crypto, which the edge runtime and Node 22 both provide. */
export function createNonce(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return btoa(String.fromCharCode(...bytes));
}
