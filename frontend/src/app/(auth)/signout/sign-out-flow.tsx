"use client";

import { Loader2 } from "lucide-react";
import { signOut, useSession } from "next-auth/react";
import { useEffect, useRef, useState } from "react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { disablePush } from "@/lib/push";
import { clearApplicationCaches, unregisterServiceWorkers } from "@/lib/pwa";

export interface SignOutFlowProps {
  /** Null when the session carried no id_token, which leaves nothing for Keycloak to revoke. */
  logoutUrl: string | null;
}

/**
 * Sign-out, extended in Step 10 to leave nothing about this account on the device.
 *
 * Before the session is closed, three things happen, in this order and for this reason:
 *
 *  1. **The push subscription is removed** - browser-side and server-side. A subscription that
 *     outlived the session would keep telling a signed-out device that an approval is waiting.
 *  2. **Every cache is deleted.** A cached screen can name a counterparty and quote a price, and
 *     on a shared or a lost device the right amount of that left behind is none of it. Every
 *     cache on the origin goes, not only the ones this build recognises.
 *  3. **The service worker is unregistered**, so nothing is left holding storage or serving a
 *     cached page to whoever signs in next.
 *
 * All three are best effort and none of them can prevent the sign-out. A tidy-up that could fail
 * a sign-out would be a device left signed in because a cache would not clear.
 */
export function SignOutFlow({ logoutUrl }: SignOutFlowProps) {
  const { data: session } = useSession();
  const started = useRef(false);
  const [stage, setStage] = useState<"clearing" | "signing-out">("clearing");

  useEffect(() => {
    if (started.current) return;
    started.current = true;

    void (async () => {
      try {
        await disablePush(session?.accessToken);
        await clearApplicationCaches();
        await unregisterServiceWorkers();
      } catch {
        // Nothing here may block the sign-out itself.
      }
      setStage("signing-out");

      if (!logoutUrl) {
        void signOut({ callbackUrl: "/signin" });
        return;
      }
      await signOut({ redirect: false });
      window.location.replace(logoutUrl);
    })();
    // The session is read once, at the moment the flow starts; a later refresh must not restart it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [logoutUrl]);

  return (
    <main className="flex min-h-screen items-center justify-center px-6 py-12">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle className="flex items-center gap-3 text-xl">
            <Loader2 className="h-5 w-5 animate-spin text-accent" aria-hidden />
            {stage === "clearing" ? "Clearing this device…" : "Signing you out…"}
          </CardTitle>
          <CardDescription>
            {stage === "clearing"
              ? "Cached screens are being removed from this browser and its push subscription cancelled, so nothing about your work is left behind on it."
              : "Your session here is being closed, and you are being sent on to the identity provider so that its session ends too."}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            You will land back on the sign-in page in a moment. You can close this tab safely once
            you do.
          </p>
        </CardContent>
      </Card>
    </main>
  );
}
