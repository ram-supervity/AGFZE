import { Send } from "lucide-react";
import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { DistributionTable } from "@/components/admin/distribution-table";
import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import {
  ApiError,
  fetchReportDistributionRules,
  type ReportDistributionRuleList,
} from "@/lib/api-client";
import { getServerAuthSession } from "@/lib/auth";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Report distribution" };

/**
 * Who receives the two scheduled reports, and on which channel.
 *
 * The one configuration on this platform whose effect is that somebody's phone buzzes, and it is
 * opt-in from empty: before a rule exists here, a scheduled report is generated, stored and
 * readable and reaches nobody at all.
 */
export default async function ReportDistributionPage() {
  const session = await getServerAuthSession();
  if (!session?.accessToken) redirect("/signin");

  let data: ReportDistributionRuleList | null = null;
  let failure: string | null = null;
  let forbidden = false;

  try {
    data = await fetchReportDistributionRules(session.accessToken);
  } catch (error) {
    forbidden = error instanceof ApiError && error.status === 403;
    failure =
      error instanceof ApiError ? error.message : "The distribution rules could not be loaded.";
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Report distribution"
        description="Which roles receive the daily and monthly reports, and on which channel. Recipients are notified with a link to the report in the platform — the file itself is never attached to an email."
      />

      {failure || !data ? (
        <EmptyState
          icon={Send}
          title={
            forbidden ? "This screen is for administrators" : "The rules could not be loaded"
          }
          description={
            forbidden
              ? "Who receives a report is decided by an administrator. Reports you have access to are readable from the Reports screen."
              : (failure ?? "No configuration came back from the API.")
          }
        />
      ) : (
        <DistributionTable data={data} />
      )}
    </div>
  );
}
