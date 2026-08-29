import { getServerSession, type NextAuthOptions } from "next-auth";
import type { JWT } from "next-auth/jwt";
import KeycloakProvider from "next-auth/providers/keycloak";

import { getServerEnv } from "@/lib/env";
import { normaliseRoles, type PlatformRole } from "@/lib/roles";

const REFRESH_MARGIN_MS = 60_000;

// The payload is decoded without verifying the signature purely to drive UI gating; the backend
// verifies every token against the Keycloak JWKS on every request and is the only authority on
// what a role permits.
function decodeJwtPayload(token: string | undefined): Record<string, unknown> | null {
  const segment = token?.split(".")[1];
  if (!segment) return null;
  try {
    const json = Buffer.from(segment.replace(/-/g, "+").replace(/_/g, "/"), "base64").toString(
      "utf8",
    );
    const payload: unknown = JSON.parse(json);
    return typeof payload === "object" && payload !== null
      ? (payload as Record<string, unknown>)
      : null;
  } catch {
    return null;
  }
}

function expiryFromClaims(claims: Record<string, unknown> | null): number | undefined {
  return typeof claims?.exp === "number" ? claims.exp : undefined;
}

function rolesFromClaims(claims: Record<string, unknown> | null, clientId: string): PlatformRole[] {
  if (!claims) return [];
  const realm = (claims.realm_access as { roles?: unknown } | undefined)?.roles;
  const resource = (claims.resource_access as Record<string, { roles?: unknown }> | undefined)?.[
    clientId
  ]?.roles;
  return normaliseRoles([
    ...(Array.isArray(realm) ? realm : []),
    ...(Array.isArray(resource) ? resource : []),
  ]);
}

interface RefreshResponse {
  access_token?: unknown;
  refresh_token?: unknown;
  id_token?: unknown;
  expires_in?: unknown;
}

async function refreshAccessToken(token: JWT): Promise<JWT> {
  const env = getServerEnv();
  if (!token.refreshToken) return { ...token, error: "RefreshAccessTokenError" };

  try {
    const response = await fetch(`${env.KEYCLOAK_INTERNAL_ISSUER}/protocol/openid-connect/token`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        grant_type: "refresh_token",
        client_id: env.KEYCLOAK_CLIENT_ID,
        client_secret: env.KEYCLOAK_CLIENT_SECRET,
        refresh_token: token.refreshToken,
      }),
      cache: "no-store",
    });

    const payload = (await response.json()) as RefreshResponse;
    if (!response.ok || typeof payload.access_token !== "string") {
      throw new Error(`Keycloak refused the refresh grant (HTTP ${response.status})`);
    }

    const claims = decodeJwtPayload(payload.access_token);
    return {
      ...token,
      accessToken: payload.access_token,
      refreshToken:
        typeof payload.refresh_token === "string" ? payload.refresh_token : token.refreshToken,
      idToken: typeof payload.id_token === "string" ? payload.id_token : token.idToken,
      expiresAt:
        typeof payload.expires_in === "number"
          ? Math.floor(Date.now() / 1000) + payload.expires_in
          : expiryFromClaims(claims),
      roles: rolesFromClaims(claims, env.KEYCLOAK_CLIENT_ID),
      error: undefined,
    };
  } catch (cause) {
    console.error(
      "Keycloak access token refresh failed:",
      cause instanceof Error ? cause.message : "unknown error",
    );
    // Keep the stale token so the session survives long enough for the UI to send the user back
    // through Keycloak rather than dropping them mid-action.
    return { ...token, error: "RefreshAccessTokenError" };
  }
}

let providers: NextAuthOptions["providers"] | null = null;

function keycloakProviders(): NextAuthOptions["providers"] {
  const env = getServerEnv();
  const browserIssuer = env.KEYCLOAK_ISSUER;
  const internalIssuer = env.KEYCLOAK_INTERNAL_ISSUER;

  return [
    KeycloakProvider({
      clientId: env.KEYCLOAK_CLIENT_ID,
      clientSecret: env.KEYCLOAK_CLIENT_SECRET,
      issuer: browserIssuer,
      // Discovery is switched off and each endpoint pinned by hand: the browser reaches Keycloak on
      // a different host than this server does, and only the authorization redirect belongs to the
      // browser-facing one.
      wellKnown: undefined,
      authorization: {
        url: `${browserIssuer}/protocol/openid-connect/auth`,
        params: { scope: "openid profile email" },
      },
      token: `${internalIssuer}/protocol/openid-connect/token`,
      userinfo: `${internalIssuer}/protocol/openid-connect/userinfo`,
      jwks_endpoint: `${internalIssuer}/protocol/openid-connect/certs`,
      checks: ["pkce", "state"],
    }),
  ];
}

export const authOptions: NextAuthOptions = {
  // Resolved on first use rather than at import time, so `next build` succeeds on a machine that
  // has no Keycloak credentials in its environment.
  get providers() {
    providers ??= keycloakProviders();
    return providers;
  },
  // Default NextAuth cookies: the tokens below never leave the encrypted, HTTP-only, SameSite=Lax
  // session cookie - nothing in this app writes them to localStorage or sessionStorage.
  session: { strategy: "jwt" },
  pages: {
    signIn: "/signin",
    signOut: "/signout",
    error: "/auth-error",
  },
  callbacks: {
    async jwt({ token, account }) {
      if (account?.access_token) {
        const claims = decodeJwtPayload(account.access_token);
        token.accessToken = account.access_token;
        token.refreshToken = account.refresh_token;
        token.idToken = account.id_token;
        token.expiresAt = account.expires_at ?? expiryFromClaims(claims);
        token.roles = rolesFromClaims(claims, getServerEnv().KEYCLOAK_CLIENT_ID);
        if (typeof claims?.sub === "string") token.sub = claims.sub;
        delete token.error;
        return token;
      }

      if (token.expiresAt && Date.now() < token.expiresAt * 1000 - REFRESH_MARGIN_MS) {
        return token;
      }

      return refreshAccessToken(token);
    },
    async session({ session, token }) {
      session.user = {
        ...session.user,
        id: token.sub ?? "",
        name: session.user?.name ?? null,
        email: session.user?.email ?? null,
        roles: token.roles ?? [],
      };
      session.accessToken = token.accessToken;
      // Needed server-side to build the RP-initiated logout URL; it travels to Keycloak as the
      // id_token_hint query parameter either way.
      session.idToken = token.idToken;
      session.expiresAt = token.expiresAt;
      session.error = token.error;
      return session;
    },
  },
  debug: false,
};

export function getServerAuthSession() {
  return getServerSession(authOptions);
}

export function keycloakLogoutUrl(idToken: string, postLogoutRedirectUri: string): string {
  const url = new URL(`${getServerEnv().KEYCLOAK_ISSUER}/protocol/openid-connect/logout`);
  url.searchParams.set("id_token_hint", idToken);
  url.searchParams.set("post_logout_redirect_uri", postLogoutRedirectUri);
  return url.toString();
}
