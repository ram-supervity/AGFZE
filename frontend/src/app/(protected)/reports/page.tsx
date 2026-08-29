import { ClipboardList } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";

import { ReportTable } from "@/components/reports/report-table";
import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { Button } from "@/components/ui/button";
import { ApiError, fetchReports, type ReportList } from "@/lib/api-client";
import { getServerAuthSession } from "@/lib/auth";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Reports" };

interface SearchParams {
  page?: string;
  report_type?: string;
  output_format?: string;
}

export default async function ReportsPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const session = await getServerAuthSession();
  if (!session?.accessToken) redirect("/signin");

  const params = await searchParams;
  const page = Math.max(1, Number.parseInt(params.page ?? "1", 10) || 1);

  let list: ReportList | null = null;
  let failure: string | null = null;

  try {
    list = await fetchReports(session.accessToken, {
      page,
      page_size: 25,
      report_type: params.report_type,
      output_format: params.output_format,
    });
  } catch (error) {
    failure = error instanceof ApiError ? error.message : "The report list could not be loaded.";
  }

  const filtered = Boolean(params.report_type || params.output_format);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Reports"
        description="Every report this platform has produced, on schedule and on request. Each one is stored here and downloaded from here; none of them is sent to anybody."
      />

      {failure || !list ? (
        <EmptyState
          icon={ClipboardList}
          title="The report list could not be loaded"
          description={failure ?? "No reports came back from the API."}
        />
      ) : list.items.length === 0 ? (
        <EmptyState
          icon={ClipboardList}
          title={filtered ? "Nothing matches those filters" : "No report has been produced yet"}
          description={
            filtered
              ? "Clear the filters to see every report the platform has produced."
              : "The daily summary is produced each morning and the management report on the first of the month. Anything else is asked for in the builder."
          }
          action={
            list.can_generate ? (
              <Button asChild size="sm">
                <Link href="/reports/builder">Generate one now</Link>
              </Button>
            ) : null
          }
        />
      ) : (
        <ReportTable
          list={list}
          filters={{
            reportType: params.report_type ?? "",
            outputFormat: params.output_format ?? "",
          }}
        />
      )}
    </div>
  );
}
