import { PlugZap } from "lucide-react";
import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { IntegrationMonitor } from "@/components/integrations/integration-monitor";
import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { ApiError, fetchIntegrationJobs, type IntegrationJobQueue } from "@/lib/api-client";
import { getServerAuthSession } from "@/lib/auth";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Integration monitor" };

interface SearchParams {
  page?: string;
  target_system?: string;
  status?: string;
  /** How a transaction workspace links through to exactly its own three jobs. */
  transaction_id?: string;
}

/**
 * The integration-support function's screen, under the existing Admin section.
 *
 * Admin-only, and the API enforces that on every call it makes - the 403 that comes back for any
 * other role is rendered as an honest message rather than an empty table, so nobody mistakes "you
 * may not see this" for "there is nothing here".
 */
export default async function IntegrationsPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const session = await getServerAuthSession();
  if (!session?.accessToken) redirect("/signin");

  const params = await searchParams;
  const page = Math.max(1, Number.parseInt(params.page ?? "1", 10) || 1);

  let queue: IntegrationJobQueue | null = null;
  let failure: string | null = null;
  let forbidden = false;

  try {
    queue = await fetchIntegrationJobs(session.accessToken, {
      page,
      page_size: 25,
      target_system: params.target_system,
      status: params.status,
      transaction_id: params.transaction_id,
    });
  } catch (error) {
    forbidden = error instanceof ApiError && error.status === 403;
    failure =
      error instanceof ApiError ? error.message : "The integration monitor could not be loaded.";
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Integration monitor"
        description="Every posting an approved transaction owes the tracker, SAP and the document store - what succeeded, what failed, and what is waiting on a person."
      />

      {failure || !queue ? (
        <EmptyState
          icon={PlugZap}
          title={forbidden ? "This screen is for administrators" : "The monitor could not be loaded"}
          description={
            forbidden
              ? "Integration jobs are worked by the integration-support function. Your own transactions show their posting status on their workspace."
              : (failure ?? "No integration data came back from the API.")
          }
        />
      ) : (
        <IntegrationMonitor
          queue={queue}
          filters={{
            target: params.target_system ?? "",
            status: params.status ?? "",
            transactionId: params.transaction_id ?? "",
          }}
        />
      )}
    </div>
  );
}
