import type { Metadata } from "next";

import { getServerAuthSession, keycloakLogoutUrl } from "@/lib/auth";
import { getServerEnv } from "@/lib/env";

import { SignOutFlow } from "./sign-out-flow";

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "Signing out" };

// The logout URL is built here rather than in the client component: it needs the browser-facing
// issuer and the id_token, and neither the server env nor `@/lib/auth` may enter the client bundle.
export default async function SignOutPage() {
  const session = await getServerAuthSession();
  const returnTo = `${getServerEnv().NEXTAUTH_URL.replace(/\/+$/, "")}/signin`;
  const logoutUrl = session?.idToken ? keycloakLogoutUrl(session.idToken, returnTo) : null;

  return <SignOutFlow logoutUrl={logoutUrl} />;
}
