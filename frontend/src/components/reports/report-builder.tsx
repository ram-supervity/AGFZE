"use client";

import { Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useSession } from "next-auth/react";
import { useState } from "react";
import toast from "react-hot-toast";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { Select } from "@/components/ui/select";
import {
  REPORT_FORMATS,
  REPORT_FORMAT_LABELS,
  REPORT_STREAMS,
  REPORT_STREAM_LABELS,
  REPORT_TYPES,
  REPORT_TYPE_LABELS,
  daysAgo,
  isoDate,
  type ReportFormat,
  type ReportType,
} from "@/lib/analytics";
import { ApiError, fetchJobStatus, fetchReports, requestReport } from "@/lib/api-client";
import { TRANSACTION_STATUSES, TRANSACTION_STATUS_LABELS } from "@/lib/transactions";

const POLL_INTERVAL_MS = 1500;
const POLL_LIMIT = 120;

/**
 * The ad-hoc builder: a filter form, a real background job, and the report it produced.
 *
 * Progress is polled through `GET /jobs/{job_id}/status`, the same endpoint every background job
 * on this platform is polled through. When the job completes, the newest report is looked up and
 * the viewer opened on it - nothing is rendered from what this form asked for, only from what was
 * actually produced.
 */
export function ReportBuilder() {
  const router = useRouter();
  const { data: session } = useSession();

  const [reportType, setReportType] = useState<ReportType>("adhoc");
  const [outputFormat, setOutputFormat] = useState<ReportFormat>("pdf");
  const [dateFrom, setDateFrom] = useState(daysAgo(30));
  const [dateTo, setDateTo] = useState(isoDate(new Date()));
  const [stream, setStream] = useState("both");
  const [status, setStatus] = useState("");
  const [progress, setProgress] = useState(0);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  async function submit() {
    if (!session?.accessToken) {
      toast.error("Your session has expired. Sign in again to generate a report.");
      return;
    }
    if (dateTo < dateFrom) {
      toast.error("The period has to end after it starts.");
      return;
    }

    setBusy(true);
    setProgress(5);
    setNote(null);

    try {
      const accepted = await requestReport(session.accessToken, {
        report_type: reportType,
        output_format: outputFormat,
        date_from: `${dateFrom}T00:00:00Z`,
        date_to: `${dateTo}T23:59:59Z`,
        stream,
        status: status || null,
      });
      setNote(accepted.message);
      await track(session.accessToken, accepted.job_id);
    } catch (error) {
      setBusy(false);
      setProgress(0);
      toast.error(
        error instanceof ApiError ? error.message : "The report could not be requested.",
      );
    }
  }

  async function track(accessToken: string, jobId: string) {
    for (let attempt = 0; attempt < POLL_LIMIT; attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
      let job;
      try {
        job = await fetchJobStatus(accessToken, jobId);
      } catch {
        // A transient polling failure is not the generation failing; the job is running server
        // side either way, and the report will appear in the list when it is done.
        setBusy(false);
        toast("Progress could not be polled. The report will appear in the list when it is ready.");
        router.push("/reports");
        return;
      }

      setProgress(Math.max(10, job.progress));

      if (job.status === "failed") {
        setBusy(false);
        setProgress(0);
        toast.error(job.error_message ?? "The report could not be generated. Nothing was produced.");
        return;
      }

      if (job.status === "completed") {
        setProgress(100);
        await openResult(accessToken, job.result_ref);
        return;
      }
    }
    setBusy(false);
    toast("The report is taking longer than expected. It will appear in the list when it is done.");
    router.push("/reports");
  }

  async function openResult(accessToken: string, resultRef: string | null) {
    // `report:<id>` is what the job records on completion. Falling back to the newest report keeps
    // the redirect working even if the reference format ever changes.
    const id = resultRef?.startsWith("report:") ? resultRef.slice("report:".length) : null;
    if (id) {
      router.push(`/reports/${id}`);
      return;
    }
    try {
      const list = await fetchReports(accessToken, { page: 1, page_size: 1 });
      const newest = list.items[0];
      router.push(newest ? `/reports/${newest.id}` : "/reports");
    } catch {
      router.push("/reports");
    }
  }

  return (
    <div className="space-y-5">
      <form
        className="grid gap-4 rounded-medium border-thin border-border bg-elevation-default shadow-raised p-5 sm:grid-cols-2 xl:grid-cols-3"
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <div className="space-y-1.5">
          <Label htmlFor="rb-type">Report</Label>
          <Select
            id="rb-type"
            value={reportType}
            disabled={busy}
            onChange={(event) => setReportType(event.target.value as ReportType)}
          >
            {REPORT_TYPES.map((value) => (
              <option key={value} value={value}>
                {REPORT_TYPE_LABELS[value]}
              </option>
            ))}
          </Select>
          <p className="text-xs text-muted-foreground">
            {reportType === "monthly"
              ? "Carries the AI-written executive summary. Every figure under it is computed by the platform."
              : "Every figure is computed by the platform from the transaction records."}
          </p>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="rb-from">From</Label>
          <Input
            id="rb-from"
            type="date"
            value={dateFrom}
            max={dateTo}
            disabled={busy}
            onChange={(event) => setDateFrom(event.target.value)}
          />
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="rb-to">To</Label>
          <Input
            id="rb-to"
            type="date"
            value={dateTo}
            min={dateFrom}
            disabled={busy}
            onChange={(event) => setDateTo(event.target.value)}
          />
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="rb-stream">Business stream</Label>
          <Select
            id="rb-stream"
            value={stream}
            disabled={busy}
            onChange={(event) => setStream(event.target.value)}
          >
            {REPORT_STREAMS.map((value) => (
              <option key={value} value={value}>
                {REPORT_STREAM_LABELS[value]}
              </option>
            ))}
          </Select>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="rb-status">Transaction status</Label>
          <Select
            id="rb-status"
            value={status}
            disabled={busy}
            onChange={(event) => setStatus(event.target.value)}
          >
            <option value="">Every status</option>
            {TRANSACTION_STATUSES.map((value) => (
              <option key={value} value={value}>
                {TRANSACTION_STATUS_LABELS[value]}
              </option>
            ))}
          </Select>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="rb-format">Format</Label>
          <Select
            id="rb-format"
            value={outputFormat}
            disabled={busy}
            onChange={(event) => setOutputFormat(event.target.value as ReportFormat)}
          >
            {REPORT_FORMATS.map((value) => (
              <option key={value} value={value}>
                {REPORT_FORMAT_LABELS[value]}
              </option>
            ))}
          </Select>
        </div>

        <div className="sm:col-span-2 xl:col-span-3">
          <Button type="submit" disabled={busy}>
            {busy ? (
              <>
                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                Generating
              </>
            ) : (
              "Generate"
            )}
          </Button>
        </div>
      </form>

      {busy || progress > 0 ? (
        <div className="space-y-space-100 rounded-medium border-thin border-border bg-elevation-default p-space-200">
          <Progress value={progress} />
          <p className="text-xs text-muted-foreground">
            {progress >= 100
              ? "Done. Opening the report."
              : "Querying the transaction records and rendering the document."}
          </p>
        </div>
      ) : null}

      <p className="rounded-medium border-thin border-border bg-elevation-sunken px-4 py-3 text-xs leading-relaxed text-muted-foreground">
        {note ??
          "The report is generated from the records themselves and stored in the platform. It is not sent to anybody - this platform has no outbound email or notification yet. Every generation produces a new report; an earlier one is never overwritten."}
      </p>
    </div>
  );
}
