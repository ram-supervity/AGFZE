import { LayoutTemplate } from "lucide-react";
import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { ReportTemplatesTable } from "@/components/admin/report-templates-table";
import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { ApiError, fetchReportTemplates, type ReportTemplateList } from "@/lib/api-client";
import { getServerAuthSession } from "@/lib/auth";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Report templates" };

/**
 * What each report is made of — and nothing about what it says.
 *
 * The reporting engine was always built against a template rather than against hard-coded
 * layouts: the PDF and XLSX renderers switch on a section's declared kind and have never known a
 * section's name. This is the last step of that promise. Confirming a report's shape with AGFZE
 * is a conversation, and a conversation should not need a release.
 *
 * No figure is reachable from here. Every number a report prints is computed from the governed
 * tables at the moment it is generated; these rows decide only which blocks are asked for.
 */
export default async function ReportTemplatesPage() {
  const session = await getServerAuthSession();
  if (!session?.accessToken) redirect("/signin");

  let data: ReportTemplateList | null = null;
  let failure: string | null = null;
  let forbidden = false;

  try {
    data = await fetchReportTemplates(session.accessToken);
  } catch (error) {
    forbidden = error instanceof ApiError && error.status === 403;
    failure = error instanceof ApiError ? error.message : "The templates could not be loaded.";
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Report templates"
        description="Which sections each report carries, in what order, and which figures go in each. An edit governs the next generation; the reports already produced keep the structure they were built to."
      />

      {failure || !data ? (
        <EmptyState
          icon={LayoutTemplate}
          title={
            forbidden ? "This screen is for administrators" : "The templates could not be loaded"
          }
          description={
            forbidden
              ? "What a report is made of is decided by an administrator. The reports themselves are readable from the Reports screen."
              : (failure ?? "No configuration came back from the API.")
          }
        />
      ) : (
        <ReportTemplatesTable data={data} />
      )}
    </div>
  );
}
