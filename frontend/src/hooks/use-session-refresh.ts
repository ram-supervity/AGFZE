"use client";

import { signIn, useSession } from "next-auth/react";
import { useEffect, useRef } from "react";

/**
 * A refresh grant that Keycloak rejects cannot be recovered from in the background — the user has
 * to go through the identity provider again.
 */
export function useSessionRefresh(): void {
  const { data: session } = useSession();
  const redirecting = useRef(false);

  useEffect(() => {
    // The ref, not state: the redirect must be attempted once per page load, and signIn() leaving
    // the page in flight would otherwise let a re-render fire it again.
    if (session?.error !== "RefreshAccessTokenError" || redirecting.current) return;
    redirecting.current = true;
    void signIn("keycloak");
  }, [session?.error]);
}
