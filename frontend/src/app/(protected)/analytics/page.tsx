import { ChartLine } from "lucide-react";
import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { AnalyticsWorkspace } from "@/components/analytics/analytics-workspace";
import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { daysAgo, isoDate } from "@/lib/analytics";
import { ApiError, fetchKpiTrends, type KpiTrends } from "@/lib/api-client";
import { getServerAuthSession } from "@/lib/auth";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Analytics" };

interface SearchParams {
  date_from?: string;
  date_to?: string;
  stream?: string;
  interval?: string;
}

/**
 * The same figures the dashboard shows, over a range somebody chooses.
 *
 * It reads `GET /dashboards/kpis` - the endpoint the dashboard reads - rather than a second one of
 * its own, so a definition can never drift between the two screens. The date range and the bucket
 * size are the only things this page adds.
 */
export default async function AnalyticsPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const session = await getServerAuthSession();
  if (!session?.accessToken) redirect("/signin");

  const params = await searchParams;
  const dateFrom = params.date_from || daysAgo(90);
  const dateTo = params.date_to || isoDate(new Date());
  const stream = params.stream === "scrap" || params.stream === "fa" ? params.stream : "";
  const interval = params.interval === "week" ? "week" : "day";

  let trends: KpiTrends | null = null;
  let failure: string | null = null;

  try {
    trends = await fetchKpiTrends(session.accessToken, {
      date_from: `${dateFrom}T00:00:00Z`,
      date_to: `${dateTo}T23:59:59Z`,
      stream: stream || undefined,
      interval,
    });
  } catch (error) {
    failure = error instanceof ApiError ? error.message : "The KPI data could not be loaded.";
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Analytics"
        description="Turnaround, automation and extraction quality over a range you choose — computed from the transaction records themselves, scoped to what your roles may see."
      />

      {failure || !trends ? (
        <EmptyState
          icon={ChartLine}
          title="The KPI data could not be loaded"
          description={
            failure ??
            "No figures came back from the API. Nothing is shown rather than a number nobody can vouch for."
          }
        />
      ) : (
        <AnalyticsWorkspace
          trends={trends}
          filters={{ dateFrom, dateTo, stream, interval }}
        />
      )}
    </div>
  );
}
