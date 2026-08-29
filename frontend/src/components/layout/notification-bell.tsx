"use client";

import { Bell } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useSession } from "next-auth/react";
import { useCallback, useEffect, useState } from "react";
import toast from "react-hot-toast";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  ApiError,
  fetchNotifications,
  markAllNotificationsRead,
  type NotificationRow,
} from "@/lib/api-client";
import { badgeCount, notificationChip, notificationLabel, relativeAge } from "@/lib/notifications";
import { cn } from "@/lib/utils";

/** How often the bell asks the API for the current unread count, in milliseconds. */
const POLL_INTERVAL_MS = 60_000;
/** How many rows the quick preview shows before it defers to the full centre. */
const PREVIEW_LIMIT = 6;

/**
 * The header bell, deferred explicitly since Step 1 and built now that there is real data.
 *
 * It polls rather than holding a socket open, deliberately: this platform has no realtime
 * transport, the notifications it counts are minutes-relevant rather than seconds-relevant, and a
 * WebSocket introduced for a number that changes a few times a day would be infrastructure with
 * nothing to justify it.
 *
 * The count is what the API says it is. There is no client-side arithmetic on it: marking
 * everything read re-reads the count from the response rather than assuming it is now zero.
 */
export function NotificationBell() {
  const { data: session } = useSession();
  const router = useRouter();
  const token = session?.accessToken;

  const [unread, setUnread] = useState(0);
  const [items, setItems] = useState<NotificationRow[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [now, setNow] = useState<Date | null>(null);

  const load = useCallback(async () => {
    if (!token) return;
    try {
      const payload = await fetchNotifications(token, { page: 1, page_size: PREVIEW_LIMIT });
      setUnread(payload.unread_count);
      setItems(payload.items);
      setLoaded(true);
    } catch {
      // A failed poll is not worth a toast: the centre is one click away and the next tick
      // retries. The badge simply keeps whatever it last knew to be true.
    }
  }, [token]);

  useEffect(() => {
    if (!token) return;
    // Set on the client only, so the server render and the first hydration agree.
    setNow(new Date());
    void load();
    const timer = window.setInterval(() => {
      setNow(new Date());
      void load();
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [token, load]);

  async function markAll() {
    if (!token) return;
    setBusy(true);
    try {
      const result = await markAllNotificationsRead(token);
      setUnread(result.unread_count);
      setItems((rows) => rows.map((row) => ({ ...row, is_read: true })));
      router.refresh();
    } catch (error) {
      toast.error(
        error instanceof ApiError ? error.message : "Your notifications could not be updated.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <DropdownMenu onOpenChange={(open) => (open ? void load() : null)}>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          aria-label={
            unread > 0 ? `Notifications, ${unread} unread` : "Notifications, none unread"
          }
          className="relative h-9 w-9 shrink-0 text-primary-foreground hover:bg-primary-foreground/10 hover:text-primary-foreground"
        >
          <Bell aria-hidden="true" className="h-[18px] w-[18px]" />
          {unread > 0 ? (
            <span
              aria-hidden="true"
              className="absolute -right-0.5 -top-0.5 inline-flex min-w-[1.05rem] items-center justify-center rounded-full bg-signal-blocked px-1 text-[10px] font-semibold leading-4 text-white"
            >
              {badgeCount(unread)}
            </span>
          ) : null}
        </Button>
      </DropdownMenuTrigger>

      <DropdownMenuContent align="end" className="w-[22rem] p-0">
        <div className="flex items-center justify-between px-3 py-2.5">
          <DropdownMenuLabel className="p-0 text-sm font-semibold">
            Notifications
          </DropdownMenuLabel>
          {unread > 0 ? (
            <Button
              variant="ghost"
              size="sm"
              className="h-7 px-2 text-xs"
              disabled={busy}
              onClick={(event) => {
                event.preventDefault();
                void markAll();
              }}
            >
              Mark all as read
            </Button>
          ) : null}
        </div>
        <DropdownMenuSeparator className="m-0" />

        {items.length === 0 ? (
          <p className="px-3 py-6 text-center text-sm text-muted-foreground">
            {loaded ? "Nothing yet." : "Loading…"}
          </p>
        ) : (
          <ul className="max-h-[22rem] overflow-y-auto py-1">
            {items.map((row) => (
              <li key={row.id}>
                <DropdownMenuItem asChild className="cursor-pointer px-3 py-2">
                  <Link href={row.link ?? "/notifications"} className="block">
                    <span className="flex items-center gap-2">
                      <Badge
                        variant="outline"
                        className={cn("px-1.5 py-0 text-[10px]", notificationChip(row.notification_type))}
                      >
                        {notificationLabel(row.notification_type)}
                      </Badge>
                      {row.is_read ? null : (
                        <span
                          aria-label="Unread"
                          className="h-1.5 w-1.5 rounded-full bg-signal-blocked"
                        />
                      )}
                      <span className="ml-auto text-[11px] text-muted-foreground">
                        {now ? relativeAge(row.created_at, now) : ""}
                      </span>
                    </span>
                    <span
                      className={cn(
                        "mt-1 block whitespace-normal text-sm leading-snug",
                        row.is_read ? "text-muted-foreground" : "font-medium text-foreground",
                      )}
                    >
                      {row.message}
                    </span>
                  </Link>
                </DropdownMenuItem>
              </li>
            ))}
          </ul>
        )}

        <DropdownMenuSeparator className="m-0" />
        <DropdownMenuItem asChild className="cursor-pointer justify-center px-3 py-2 text-sm">
          <Link href="/notifications">Open the notification centre</Link>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
