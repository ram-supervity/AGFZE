import { ScrollText } from "lucide-react";
import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { AuditExplorer } from "@/components/admin/audit-explorer";
import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { ApiError, fetchAuditEvents, type AuditEventList } from "@/lib/api-client";
import { getServerAuthSession } from "@/lib/auth";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Audit explorer" };

interface SearchParams {
  page?: string;
  date_from?: string;
  date_to?: string;
  event_type?: string;
  actor_id?: string;
  entity_type?: string;
  search?: string;
}

/**
 * Every governance event recorded since the platform's first day, finally readable.
 *
 * The trail has been written to at dozens of points across every module since Step 1 and has
 * never had a screen. It is read-only here and read-only everywhere: the table is append-only,
 * and a correction to it is a new event referencing the same entity, never an edit.
 */
export default async function AuditPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const session = await getServerAuthSession();
  if (!session?.accessToken) redirect("/signin");

  const params = await searchParams;
  const page = Math.max(1, Number.parseInt(params.page ?? "1", 10) || 1);

  let data: AuditEventList | null = null;
  let failure: string | null = null;
  let forbidden = false;

  try {
    data = await fetchAuditEvents(session.accessToken, {
      page,
      page_size: 50,
      date_from: params.date_from,
      date_to: params.date_to,
      event_type: params.event_type,
      actor_id: params.actor_id,
      entity_type: params.entity_type,
      search: params.search,
    });
  } catch (error) {
    forbidden = error instanceof ApiError && error.status === 403;
    failure = error instanceof ApiError ? error.message : "The audit trail could not be loaded.";
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Audit explorer"
        description="Who did what, when, and to which record — every governance-relevant action across intake, matching, validation, exceptions, approvals, sales drafting, FA, shipments, integration and reporting."
      />

      {failure || !data ? (
        <EmptyState
          icon={ScrollText}
          title={forbidden ? "This screen is for administrators and auditors" : "The trail could not be loaded"}
          description={
            forbidden
              ? "The full trail is open to the Admin and Auditor roles. A single transaction's own history is on its workspace, open to the desks that own it."
              : (failure ?? "No events came back from the API.")
          }
        />
      ) : (
        <AuditExplorer
          data={data}
          filters={{
            date_from: params.date_from,
            date_to: params.date_to,
            event_type: params.event_type,
            actor_id: params.actor_id,
            entity_type: params.entity_type,
            search: params.search,
          }}
        />
      )}
    </div>
  );
}
