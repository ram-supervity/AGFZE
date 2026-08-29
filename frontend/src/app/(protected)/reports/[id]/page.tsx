import { ClipboardList } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { ReportViewer } from "@/components/reports/report-viewer";
import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { Button } from "@/components/ui/button";
import { ApiError, fetchReportDetail, type ReportDetail } from "@/lib/api-client";
import { getServerAuthSession } from "@/lib/auth";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Report" };

export default async function ReportPage({ params }: { params: Promise<{ id: string }> }) {
  const session = await getServerAuthSession();
  if (!session?.accessToken) redirect("/signin");

  const { id } = await params;

  let report: ReportDetail | null = null;
  let failure: string | null = null;

  try {
    report = await fetchReportDetail(session.accessToken, id);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    failure = error instanceof ApiError ? error.message : "The report could not be loaded.";
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title={report?.title ?? "Report"}
        description={
          report
            ? `Reference ${report.generation_reference}. Every figure below links through to the records it was computed from.`
            : undefined
        }
        actions={
          <Button asChild size="sm" variant="outline">
            <Link href="/reports">Back to reports</Link>
          </Button>
        }
      />

      {failure || !report ? (
        <EmptyState
          icon={ClipboardList}
          title="The report could not be loaded"
          description={failure ?? "No report came back from the API."}
        />
      ) : (
        <ReportViewer report={report} />
      )}
    </div>
  );
}
