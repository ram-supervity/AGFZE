import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { buildContentSecurityPolicy, originOf, securityHeaders } from "@/lib/csp";
import { isProtected } from "@/middleware";

const ORIGINS = {
  apiBaseUrl: "https://api.command-centre.agfze.ae/api/v1",
  keycloakIssuer: "https://id.agfze.ae/realms/agfze",
};

function directive(policy: string, name: string): string {
  const found = policy.split("; ").find((part) => part.startsWith(`${name} `));
  expect(found, `${name} is missing from the policy`).toBeTruthy();
  return found as string;
}

describe("content security policy", () => {
  it("restricts scripts to this origin and a per-request nonce, never unsafe-inline", () => {
    const policy = buildContentSecurityPolicy("abc123", ORIGINS);
    const scripts = directive(policy, "script-src");

    expect(scripts).toContain("'self'");
    expect(scripts).toContain("'nonce-abc123'");
    expect(scripts).not.toContain("'unsafe-inline'");
    expect(scripts).not.toContain("'unsafe-eval'");
  });

  it("allows connections only to this origin, the API and the Keycloak issuer", () => {
    const connect = directive(buildContentSecurityPolicy("n", ORIGINS), "connect-src");

    expect(connect).toBe(
      "connect-src 'self' https://api.command-centre.agfze.ae https://id.agfze.ae",
    );
  });

  it("names no external provider, because the browser never reaches one", () => {
    const policy = buildContentSecurityPolicy("n", ORIGINS);

    for (const host of [
      "graph.microsoft.com",
      "login.microsoftonline.com",
      "generativelanguage.googleapis.com",
      "googleapis.com",
      "sap",
      "dms",
    ]) {
      expect(policy).not.toContain(host);
    }
  });

  it("forbids framing, plugins and a rewritten base URI outright", () => {
    const policy = buildContentSecurityPolicy("n", ORIGINS);

    expect(policy).toContain("frame-ancestors 'none'");
    expect(policy).toContain("frame-src 'none'");
    expect(policy).toContain("object-src 'none'");
    expect(policy).toContain("base-uri 'self'");
  });

  it("upgrades insecure requests only where the response is itself secure", () => {
    expect(buildContentSecurityPolicy("n", { ...ORIGINS, secure: true })).toContain(
      "upgrade-insecure-requests",
    );
    expect(buildContentSecurityPolicy("n", { ...ORIGINS, secure: false })).not.toContain(
      "upgrade-insecure-requests",
    );
  });

  it("tolerates an unset or malformed origin rather than emitting a broken source", () => {
    const policy = buildContentSecurityPolicy("n", { apiBaseUrl: "not a url" });

    expect(directive(policy, "connect-src")).toBe("connect-src 'self'");
    expect(originOf("not a url")).toBeNull();
    expect(originOf(undefined)).toBeNull();
  });

  it("sends HSTS only over HTTPS", () => {
    const names = (secure: boolean) => securityHeaders(secure).map(([name]) => name);

    expect(names(true)).toContain("Strict-Transport-Security");
    expect(names(false)).not.toContain("Strict-Transport-Security");
    expect(names(false)).toEqual(
      expect.arrayContaining(["X-Content-Type-Options", "X-Frame-Options", "Referrer-Policy"]),
    );
  });
});

describe("the nonce can actually be applied", () => {
  it("renders every page per request, because a prerendered one cannot carry a nonce", () => {
    /**
     * The quiet failure this guards against, found by serving the built app and reading the HTML
     * rather than by reasoning about it: a statically prerendered page's markup is written at
     * build time, so Next.js cannot stamp a per-request nonce onto its scripts - and under a
     * nonce-based policy with `strict-dynamic` those scripts are simply blocked. The sign-in page
     * was exactly that, static, and arrived with every script refused.
     *
     * Declared once in the root layout so a page added later cannot silently become static and
     * lose its scripts, and asserted here so removing that line fails the build rather than the
     * browser.
     */
    const layout = readFileSync(join(process.cwd(), "src", "app", "layout.tsx"), "utf8");

    expect(layout).toMatch(/export const dynamic = "force-dynamic"/);
  });

  it("sets the policy on the request as well as the response", () => {
    // Next.js finds the nonce by reading the CSP off the *request* headers. Setting it only on the
    // way out would produce a valid-looking policy and unnonced scripts.
    const middleware = readFileSync(join(process.cwd(), "src", "middleware.ts"), "utf8");

    expect(middleware).toMatch(/forwarded\.set\("content-security-policy", policy\)/);
    expect(middleware).toMatch(/response\.headers\.set\("content-security-policy", policy\)/);
  });
});

describe("middleware route protection", () => {
  it("still requires a session on every governed route", () => {
    for (const path of [
      "/dashboard",
      "/inbox/abc",
      "/transactions/purchase/abc",
      "/exceptions",
      "/approvals/abc",
      "/admin/rules",
      "/settings",
      "/notifications",
    ]) {
      expect(isProtected(path), path).toBe(true);
    }
  });

  it("leaves the public and authentication routes open, so the CSP can cover them too", () => {
    for (const path of ["/", "/signin", "/signout", "/offline", "/privacy", "/terms"]) {
      expect(isProtected(path), path).toBe(false);
    }
  });

  it("does not protect a path that merely starts with a protected word", () => {
    expect(isProtected("/administration")).toBe(false);
    expect(isProtected("/reportsomething")).toBe(false);
  });
});
