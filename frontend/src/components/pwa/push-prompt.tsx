"use client";

import { BellRing, X } from "lucide-react";
import { useSession } from "next-auth/react";
import { useCallback, useEffect, useState } from "react";
import toast from "react-hot-toast";

import { Button } from "@/components/ui/button";
import { fetchNotifications } from "@/lib/api-client";
import { enablePush, pushPermission, pushSupported } from "@/lib/push";

/** Remembered per browser, so somebody who said "not now" is not asked again on every page. */
const DISMISSED_KEY = "agfze.push-prompt.dismissed";

/**
 * The notifications that mean work has actually landed on this person. Nothing else prompts.
 */
const QUALIFYING_TYPES = new Set(["approval.requested", "exception.opened"]);

/**
 * How long after mount the first check may run. The prompt must never appear on initial page
 * load - somebody signing in to look something up should not be met with a permission request -
 * so this is a floor on when it can appear at all, not a nicety.
 */
export const PROMPT_DELAY_MS = 8_000;

/**
 * The contextual push opt-in.
 *
 * Asked at the moment it makes sense rather than at the moment the application loads: it appears
 * once the person actually has an approval waiting on them or an exception on their desk, which
 * is the only point at which "we can tell you the moment this happens" means anything. A browser
 * permission asked for out of context is a permission that gets denied permanently, and a denied
 * permission cannot be asked for a second time.
 *
 * Dismissing it is remembered. The same flow stays permanently available in Settings, so saying
 * "not now" here never becomes "never" without the user's say-so.
 */
export function PushPrompt() {
  const { data: session } = useSession();
  const token = session?.accessToken;
  const [visible, setVisible] = useState(false);
  const [busy, setBusy] = useState(false);

  const dismiss = useCallback(() => {
    setVisible(false);
    try {
      window.localStorage.setItem(DISMISSED_KEY, new Date().toISOString());
    } catch {
      /* private mode, or storage disabled - the prompt simply reappears next session */
    }
  }, []);

  useEffect(() => {
    if (!token || !pushSupported() || pushPermission() !== "default") return;
    try {
      if (window.localStorage.getItem(DISMISSED_KEY)) return;
    } catch {
      /* unreadable storage is treated as "not dismissed" */
    }

    let cancelled = false;
    const timer = window.setTimeout(async () => {
      try {
        const payload = await fetchNotifications(token, { page: 1, page_size: 10 });
        const hasWork = payload.items.some((row) => QUALIFYING_TYPES.has(row.notification_type));
        if (!cancelled && hasWork) setVisible(true);
      } catch {
        // A failed read is not a reason to ask for a permission.
      }
    }, PROMPT_DELAY_MS);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [token]);

  if (!visible) return null;

  async function turnOn() {
    if (!token) return;
    setBusy(true);
    const result = await enablePush(token);
    setBusy(false);
    if (result.ok) {
      toast.success("This browser will now tell you the moment something needs you.");
      setVisible(false);
      return;
    }
    if (result.reason === "denied") {
      toast.error(
        "Your browser has blocked notifications for this site. You can re-enable them in its site settings.",
      );
      dismiss();
      return;
    }
    if (result.reason === "not-configured") {
      toast.error("Push is not configured on this deployment yet.");
      dismiss();
      return;
    }
    toast.error("This browser could not be subscribed. Nothing has changed.");
  }

  return (
    <aside
      aria-label="Push notification offer"
      className="mb-4 flex flex-wrap items-start gap-3 rounded-lg border border-pill-purple-border bg-pill-purple-bg px-space-200 py-space-150"
    >
      <BellRing aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-accent" />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-foreground">
          Be told the moment a decision is waiting on you
        </p>
        <p className="mt-0.5 text-sm text-muted-foreground">
          Your browser can notify you when an approval reaches your queue or an exception lands on
          your desk - even when this tab is closed. Only those two things, never marketing, and
          never the commercial detail itself.
        </p>
        <div className="mt-2.5 flex flex-wrap gap-2">
          <Button size="sm" disabled={busy} onClick={() => void turnOn()}>
            {busy ? "Asking your browser…" : "Turn on notifications"}
          </Button>
          <Button size="sm" variant="ghost" onClick={dismiss}>
            Not now
          </Button>
        </div>
      </div>
      <button
        type="button"
        onClick={dismiss}
        aria-label="Dismiss"
        className="rounded-md p-1 text-muted-foreground hover:bg-muted"
      >
        <X aria-hidden="true" className="h-4 w-4" />
      </button>
    </aside>
  );
}
