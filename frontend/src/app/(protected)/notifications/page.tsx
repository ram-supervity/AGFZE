import { BellOff } from "lucide-react";
import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { NotificationCentre } from "@/components/notifications/notification-centre";
import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { ApiError, fetchNotifications, type NotificationList } from "@/lib/api-client";
import { getServerAuthSession } from "@/lib/auth";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Notifications" };

interface SearchParams {
  page?: string;
  unread_only?: string;
}

/**
 * The notification centre.
 *
 * In-app is the only channel this platform has, so this page is the delivery, not a copy of one
 * sent elsewhere. Nothing here was emailed and nothing was pushed, and no wording on this screen
 * suggests otherwise.
 */
export default async function NotificationsPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const session = await getServerAuthSession();
  if (!session?.accessToken) redirect("/signin");

  const params = await searchParams;
  const page = Math.max(1, Number.parseInt(params.page ?? "1", 10) || 1);
  const unreadOnly = params.unread_only === "true";

  let data: NotificationList | null = null;
  let failure: string | null = null;

  try {
    data = await fetchNotifications(session.accessToken, {
      page,
      page_size: 25,
      unread_only: unreadOnly,
    });
  } catch (error) {
    failure =
      error instanceof ApiError ? error.message : "Your notifications could not be loaded.";
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Notifications"
        description="What the platform needs to tell you, and only you. Delivered in-app — nothing here was emailed or pushed, because neither channel exists yet."
      />

      {failure || !data ? (
        <EmptyState
          icon={BellOff}
          title="Your notifications could not be loaded"
          description={failure ?? "Nothing came back from the API."}
        />
      ) : (
        <NotificationCentre data={data} unreadOnly={unreadOnly} />
      )}
    </div>
  );
}
