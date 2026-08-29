import { ShieldAlert } from "lucide-react";
import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { ReportBuilder } from "@/components/reports/report-builder";
import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { canGenerateReports } from "@/lib/analytics";
import { ApiError, fetchCurrentUser } from "@/lib/api-client";
import { getServerAuthSession } from "@/lib/auth";
import { normaliseRoles } from "@/lib/roles";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Generate a report" };

/**
 * The ad-hoc builder.
 *
 * The role check below decides what this page renders; the API decides what it will actually do,
 * and refuses a request from any other role regardless of what was rendered here.
 */
export default async function ReportBuilderPage() {
  const session = await getServerAuthSession();
  if (!session?.accessToken) redirect("/signin");

  let roles = normaliseRoles(session.user.roles);
  try {
    const profile = await fetchCurrentUser(session.accessToken);
    roles = normaliseRoles(profile.roles);
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Generate a report"
        description="Pick a period, a stream and a status. The figures are queried from the transaction records when you press Generate, and the document is stored here for you to open."
      />

      {canGenerateReports(roles) ? (
        <ReportBuilder />
      ) : (
        <EmptyState
          icon={ShieldAlert}
          title="Report generation is for administrators and the HOD"
          description="Every report the platform has already produced is on the Reports screen and open to your account. Ask an administrator or the department head for a new one."
        />
      )}
    </div>
  );
}
