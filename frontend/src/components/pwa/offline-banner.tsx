"use client";

import { CloudOff, RefreshCw } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { useOfflineState } from "@/hooks/use-offline-state";
import { relativeAge } from "@/lib/notifications";
import { cn } from "@/lib/utils";

/**
 * The honest banner: what is on screen, and how old it is.
 *
 * Two states, and they say different things because they are different situations. Offline is
 * "the connection is gone and nothing here will update". Stale is "this came out of the cache at
 * 09:14" - which is a fact the service worker stamped on the response, not an estimate.
 *
 * Neither state is an error, and neither is dismissible: an error banner would suggest something
 * went wrong, and a dismissible one would let somebody read four-hour-old figures with nothing on
 * screen saying so.
 */
export function OfflineBanner() {
  const { online, cachedAt } = useOfflineState();
  const router = useRouter();
  const [now, setNow] = useState<Date | null>(null);
  const [retrying, setRetrying] = useState(false);

  useEffect(() => {
    // Client-only, so the server render and the first hydration agree.
    setNow(new Date());
    const timer = window.setInterval(() => setNow(new Date()), 30_000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!online || !retrying) return;
    setRetrying(false);
    router.refresh();
  }, [online, retrying, router]);

  if (online && !cachedAt) return null;

  const age = cachedAt && now ? relativeAge(cachedAt, now) : null;

  return (
    <div
      role="status"
      aria-live="polite"
      className={cn(
        "mb-4 flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-md border px-3.5 py-2.5 text-sm",
        online
          ? "border-signal-review/35 bg-signal-review/10 text-foreground"
          : "border-border bg-muted text-foreground",
      )}
    >
      <CloudOff aria-hidden="true" className="h-4 w-4 shrink-0 text-muted-foreground" />
      {online ? (
        <span>
          You&rsquo;re viewing cached data{age ? ` from ${age}` : ""} - reconnect to update.
        </span>
      ) : (
        <span>
          You&rsquo;re offline. What you have already opened stays readable
          {age ? ` (cached ${age})` : ""}, and nothing can be submitted, approved or changed until
          you reconnect.
        </span>
      )}
      <button
        type="button"
        onClick={() => {
          setRetrying(true);
          router.refresh();
        }}
        className="ml-auto inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium text-secondary hover:bg-background/60"
      >
        <RefreshCw aria-hidden="true" className={cn("h-3.5 w-3.5", retrying && "animate-spin")} />
        Try again
      </button>
    </div>
  );
}
