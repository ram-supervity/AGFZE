"use client";

import { BellOff } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useSession } from "next-auth/react";
import { useEffect, useState } from "react";
import toast from "react-hot-toast";

import { EmptyState } from "@/components/shared/empty-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  ApiError,
  markAllNotificationsRead,
  type NotificationList,
} from "@/lib/api-client";
import { notificationChip, notificationLabel, relativeAge } from "@/lib/notifications";
import { cn, formatDateTime } from "@/lib/utils";

export interface NotificationCentreProps {
  data: NotificationList;
  unreadOnly: boolean;
}

/**
 * The signed-in account's own notifications, in full.
 *
 * Every row carries a deep link to the thing it is about - the exception case, the approval, the
 * integration job's transaction, the report - so a notification is a way into the work rather
 * than a restatement of it.
 *
 * There is no "mark this one read" control, deliberately: unread here means "you have not opened
 * the centre and cleared them", not "you have not read this sentence", and a per-row toggle would
 * invite somebody to clear a notification they had not acted on.
 */
export function NotificationCentre({ data, unreadOnly }: NotificationCentreProps) {
  const router = useRouter();
  const params = useSearchParams();
  const { data: session } = useSession();
  const [busy, setBusy] = useState(false);
  const [now, setNow] = useState<Date | null>(null);

  // Set on the client only, so the server render and the first hydration produce the same markup.
  useEffect(() => setNow(new Date()), []);

  const { page, total_pages: totalPages, total } = data.page;

  function navigate(changes: Record<string, string | null>) {
    const next = new URLSearchParams(params.toString());
    for (const [key, value] of Object.entries(changes)) {
      if (!value) next.delete(key);
      else next.set(key, value);
    }
    router.push(`/notifications${next.toString() ? `?${next.toString()}` : ""}`);
  }

  async function markAll() {
    const token = session?.accessToken;
    if (!token) {
      toast.error("Your session has expired. Sign in again.");
      return;
    }
    setBusy(true);
    try {
      const result = await markAllNotificationsRead(token);
      toast.success(
        result.marked > 0
          ? `${result.marked} notification${result.marked === 1 ? "" : "s"} marked as read.`
          : "Nothing was unread.",
      );
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
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border pb-3">
        <div className="flex gap-1.5">
          <Button
            variant={unreadOnly ? "ghost" : "outline"}
            size="sm"
            onClick={() => navigate({ unread_only: null, page: null })}
          >
            Everything
          </Button>
          <Button
            variant={unreadOnly ? "outline" : "ghost"}
            size="sm"
            onClick={() => navigate({ unread_only: "true", page: null })}
          >
            Unread
            {data.unread_count > 0 ? (
              <Badge variant="secondary" className="ml-1.5 tabular-nums">
                {data.unread_count}
              </Badge>
            ) : null}
          </Button>
        </div>
        <Button variant="outline" size="sm" disabled={busy || data.unread_count === 0} onClick={markAll}>
          Mark all as read
        </Button>
      </div>

      {data.items.length === 0 ? (
        <EmptyState
          icon={BellOff}
          title={unreadOnly ? "Nothing unread" : "Nothing yet"}
          description={
            unreadOnly
              ? "You are up to date. Switch to Everything to look back over what you have already read."
              : "The platform tells you here when an exception lands on your desk, a decision is waiting on you, or something you submitted comes back."
          }
        />
      ) : (
        <ul className="space-y-2">
          {data.items.map((row) => {
            const body = (
              <>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge
                    variant="outline"
                    className={cn("px-1.5 py-0 text-body-xs", notificationChip(row.notification_type))}
                  >
                    {notificationLabel(row.notification_type)}
                  </Badge>
                  {row.is_read ? null : (
                    <Badge variant="secondary" className="px-1.5 py-0 text-body-xs">
                      Unread
                    </Badge>
                  )}
                  <span className="ml-auto text-xs text-muted-foreground">
                    {now ? relativeAge(row.created_at, now) : formatDateTime(row.created_at)}
                  </span>
                </div>
                <p
                  className={cn(
                    "mt-1.5 text-sm leading-relaxed",
                    row.is_read ? "text-muted-foreground" : "font-medium text-foreground",
                  )}
                >
                  {row.message}
                </p>
              </>
            );

            return (
              <li key={row.id}>
                {row.link ? (
                  <Link
                    href={row.link}
                    className="block rounded-lg border border-border bg-surface p-3.5 transition-colors hover:border-secondary/45 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    {body}
                  </Link>
                ) : (
                  <div className="rounded-lg border border-border bg-surface p-3.5">{body}</div>
                )}
              </li>
            );
          })}
        </ul>
      )}

      <div className="flex items-center justify-between text-sm text-muted-foreground">
        <p>
          {total} notification{total === 1 ? "" : "s"} · page {page} of {totalPages}
        </p>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={page <= 1}
            onClick={() => navigate({ page: String(page - 1) })}
          >
            Previous
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={page >= totalPages}
            onClick={() => navigate({ page: String(page + 1) })}
          >
            Next
          </Button>
        </div>
      </div>
    </div>
  );
}
