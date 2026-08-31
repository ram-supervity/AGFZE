"use client";

import { BellRing, BellOff, Loader2 } from "lucide-react";
import { useSession } from "next-auth/react";
import { useEffect, useState } from "react";
import toast from "react-hot-toast";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { currentSubscription, disablePush, enablePush, pushPermission } from "@/lib/push";
import { serviceWorkerEnabled } from "@/lib/pwa";

type Status = "checking" | "unsupported" | "blocked" | "off" | "on" | "no-worker";

/**
 * The permanent home of the push opt-in, beside the email preference and deliberately unlike it.
 *
 * The email toggle writes a column. This one asks a browser for a permission, subscribes a
 * specific device, and registers that device with the API - which is why it is a status and an
 * action rather than a switch, and why it reports what the browser currently says instead of what
 * this platform would prefer. A permission the user has blocked cannot be un-blocked from here by
 * any code, and the honest thing is to say so and point at the browser's own settings.
 *
 * It governs this browser only. Somebody signed in on a laptop and a phone subscribes each once.
 */
export function PushSettings() {
  const { data: session } = useSession();
  const token = session?.accessToken;
  const [status, setStatus] = useState<Status>("checking");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const permission = pushPermission();
      if (permission === "unsupported") {
        if (!cancelled) setStatus("unsupported");
        return;
      }
      if (!serviceWorkerEnabled()) {
        // Development. The worker is never registered against `npm run dev`, and without one
        // there is no push manager to subscribe through. Said plainly rather than failing.
        if (!cancelled) setStatus("no-worker");
        return;
      }
      if (permission === "denied") {
        if (!cancelled) setStatus("blocked");
        return;
      }
      const subscription = await currentSubscription();
      if (!cancelled) setStatus(subscription ? "on" : "off");
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function turnOn() {
    if (!token) return;
    setBusy(true);
    const result = await enablePush(token);
    setBusy(false);
    if (result.ok) {
      setStatus("on");
      toast.success("This browser is subscribed.");
      return;
    }
    if (result.reason === "denied") {
      setStatus("blocked");
      toast.error("Your browser blocked the request.");
      return;
    }
    if (result.reason === "not-configured") {
      toast.error("Push is not configured on this deployment yet.");
      return;
    }
    toast.error("This browser could not be subscribed. Nothing has changed.");
  }

  async function turnOff() {
    setBusy(true);
    await disablePush(token);
    setBusy(false);
    setStatus("off");
    toast.success("This browser will no longer receive push notifications.");
  }

  return (
    <div className="rounded-md border border-border px-3 py-2.5">
      <div className="flex flex-wrap items-start gap-x-3 gap-y-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-foreground">Push notifications</span>
            <StatusBadge status={status} />
          </div>
          <p className="mt-0.5 text-xs text-muted-foreground">{DESCRIPTION[status]}</p>
        </div>

        {status === "off" ? (
          <Button size="sm" disabled={busy || !token} onClick={() => void turnOn()}>
            {busy ? (
              <Loader2 aria-hidden="true" className="mr-1.5 h-3.5 w-3.5 animate-spin" />
            ) : (
              <BellRing aria-hidden="true" className="mr-1.5 h-3.5 w-3.5" />
            )}
            Enable on this browser
          </Button>
        ) : null}
        {status === "on" ? (
          <Button size="sm" variant="outline" disabled={busy} onClick={() => void turnOff()}>
            <BellOff aria-hidden="true" className="mr-1.5 h-3.5 w-3.5" />
            Disable on this browser
          </Button>
        ) : null}
      </div>
    </div>
  );
}

const DESCRIPTION: Record<Status, string> = {
  checking: "Asking your browser what it currently allows…",
  unsupported: "This browser does not support web push. Nothing else about your account changes.",
  blocked:
    "Your browser has blocked notifications for this site. Only its own site settings can undo that - no page can ask again once it has been refused.",
  off: "Not enabled on this browser. Turning it on asks your browser for permission and registers this device; it does not change your email setting.",
  on: "This browser is subscribed and will be notified when an approval or exception reaches you, even with the tab closed.",
  "no-worker":
    "Push needs the installed service worker, which is only registered in a production build - not under `npm run dev`. Your other browsers are unaffected.",
};

function StatusBadge({ status }: { status: Status }) {
  if (status === "on") {
    return (
      <Badge variant="outline" className="border-pill-green-border bg-pill-green-bg text-pill-green-text">
        On for this browser
      </Badge>
    );
  }
  if (status === "blocked") {
    return (
      <Badge variant="outline" className="border-pill-red-border bg-pill-red-bg text-pill-red-text">
        Blocked by the browser
      </Badge>
    );
  }
  if (status === "checking") return null;
  return <Badge variant="muted">Off</Badge>;
}
