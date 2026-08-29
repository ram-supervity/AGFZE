import { Inbox } from "lucide-react";
import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { InboxFilters } from "@/components/intake/inbox-filters";
import { RequestQueueTable } from "@/components/intake/request-queue-table";
import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { Button } from "@/components/ui/button";
import { ApiError, fetchRequestQueue, type RequestQueue } from "@/lib/api-client";
import { getServerAuthSession } from "@/lib/auth";
import { canCorrect } from "@/lib/intake";
import { normaliseRoles } from "@/lib/roles";
import Link from "next/link";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Inbox" };

interface SearchParams {
  page?: string;
  category?: string;
  stream?: string;
  needs_review?: string;
  search?: string;
}

export default async function InboxPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const session = await getServerAuthSession();
  if (!session?.accessToken) redirect("/signin");

  const params = await searchParams;
  const page = Math.max(1, Number.parseInt(params.page ?? "1", 10) || 1);
  const roles = normaliseRoles(session.user.roles);

  let queue: RequestQueue | null = null;
  let failure: string | null = null;

  try {
    queue = await fetchRequestQueue(session.accessToken, {
      page,
      page_size: 25,
      category: params.category,
      stream: params.stream,
      needs_review: params.needs_review === "true" ? true : undefined,
      search: params.search,
    });
  } catch (error) {
    failure =
      error instanceof ApiError
        ? error.message
        : "The request queue could not be loaded right now.";
  }

  const filtered = Boolean(
    params.category || params.stream || params.needs_review === "true" || params.search,
  );

  return (
    <div className="space-y-6">
      <PageHeader
        title="Inbox"
        description="Trade email and portal uploads waiting to be triaged, newest first."
        actions={
          canCorrect(roles) ? (
            <Button asChild size="sm">
              <Link href="/inbox/upload">Upload documents</Link>
            </Button>
          ) : undefined
        }
      />

      <InboxFilters
        category={params.category ?? ""}
        stream={params.stream ?? ""}
        needsReview={params.needs_review === "true"}
        search={params.search ?? ""}
      />

      {failure ? (
        <EmptyState
          icon={Inbox}
          title="The queue could not be loaded"
          description={failure}
        />
      ) : queue && queue.items.length > 0 ? (
        <RequestQueueTable queue={queue} />
      ) : (
        <EmptyState
          icon={Inbox}
          title={filtered ? "Nothing matches those filters" : "The queue is clear"}
          description={
            filtered
              ? "No request matches the filters you have applied. Clear them to see the whole queue."
              : "Nothing is waiting to be triaged. New mail arriving in the approved mailbox appears here automatically, and uploaded documents appear here too."
          }
          action={
            canCorrect(roles) ? (
              <Button asChild size="sm" variant="outline">
                <Link href="/inbox/upload">Upload documents</Link>
              </Button>
            ) : undefined
          }
        />
      )}
    </div>
  );
}
