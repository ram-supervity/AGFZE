"use client";

import { ChartLine, Download } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { BarChart } from "@/components/charts/bar-chart";
import { ChartFrame } from "@/components/charts/chart-frame";
import { LineChart } from "@/components/charts/line-chart";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  drillThroughHref,
  formatDay,
  formatFigure,
  formatHours,
  freshnessNote,
  toCsv,
} from "@/lib/analytics";
import type { KpiTrends } from "@/lib/api-client";
import { STREAM_LABELS } from "@/lib/intake";

export interface AnalyticsWorkspaceProps {
  trends: KpiTrends;
  filters: { dateFrom: string; dateTo: string; stream: string; interval: string };
}

const EXPORT_COLUMNS = [
  { key: "day", label: "Bucket start (UTC)" },
  { key: "approved_count", label: "Approvals decided" },
  { key: "mean_hours", label: "Mean turnaround (hours)" },
  { key: "median_hours", label: "Median turnaround (hours)" },
  { key: "exception_free_count", label: "Approved with no exception" },
  { key: "intervened_count", label: "Approved after an exception" },
  { key: "automation_rate", label: "Exception-free share (%)" },
];

/**
 * The trend view, over the same endpoint the dashboard reads.
 *
 * Nothing here recomputes anything. The date range and the bucket size are sent to the API and the
 * API answers with figures it computed under this account's scope, so the analytics page and the
 * dashboard cannot disagree about what a number means - there is one definition of each, on the
 * server, and both screens draw it.
 */
export function AnalyticsWorkspace({ trends, filters }: AnalyticsWorkspaceProps) {
  const router = useRouter();
  const params = useSearchParams();
  const [exported, setExported] = useState(false);

  function apply(changes: Record<string, string | null>) {
    const next = new URLSearchParams(params.toString());
    for (const [key, value] of Object.entries(changes)) {
      if (value === null || value === "") next.delete(key);
      else next.set(key, value);
    }
    router.push(`/analytics?${next.toString()}`);
  }

  const rows = trends.series.map((bucket) => ({
    day: bucket.bucket_start.slice(0, 10),
    approved_count: bucket.approved_count,
    mean_hours: bucket.mean_hours,
    median_hours: bucket.median_hours,
    exception_free_count: bucket.exception_free_count,
    intervened_count: bucket.intervened_count,
    automation_rate: bucket.automation_rate,
  }));

  function exportChartData() {
    const blob = new Blob([toCsv(EXPORT_COLUMNS, rows)], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `agfze-kpis-${filters.dateFrom}-to-${filters.dateTo}.csv`;
    anchor.click();
    URL.revokeObjectURL(url);
    setExported(true);
  }

  const labels = trends.series.map((bucket) => formatDay(bucket.bucket_start));
  const nothingApproved = trends.series.every((bucket) => bucket.approved_count === 0);

  return (
    <div className="space-y-6">
      <form
        className="grid gap-3 rounded-lg border border-border bg-surface p-4 sm:grid-cols-2 xl:grid-cols-5"
        onSubmit={(event) => event.preventDefault()}
      >
        <div className="space-y-1.5">
          <Label htmlFor="kpi-from">From</Label>
          <Input
            id="kpi-from"
            type="date"
            value={filters.dateFrom}
            max={filters.dateTo}
            onChange={(event) => apply({ date_from: event.target.value || null })}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="kpi-to">To</Label>
          <Input
            id="kpi-to"
            type="date"
            value={filters.dateTo}
            min={filters.dateFrom}
            onChange={(event) => apply({ date_to: event.target.value || null })}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="kpi-stream">Stream</Label>
          <Select
            id="kpi-stream"
            value={filters.stream}
            onChange={(event) => apply({ stream: event.target.value || null })}
          >
            <option value="">Both streams</option>
            {trends.streams.map((value) => (
              <option key={value} value={value}>
                {STREAM_LABELS[value as keyof typeof STREAM_LABELS] ?? value}
              </option>
            ))}
          </Select>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="kpi-interval">Bucket</Label>
          <Select
            id="kpi-interval"
            value={filters.interval}
            onChange={(event) => apply({ interval: event.target.value })}
          >
            <option value="day">By day</option>
            <option value="week">By week</option>
          </Select>
        </div>
        <div className="flex items-end">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={exportChartData}
            disabled={rows.length === 0}
          >
            <Download className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
            Export chart data
          </Button>
        </div>
      </form>

      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
        <p>{trends.scope_note}</p>
        <p>{freshnessNote(trends.cache_age_seconds, trends.cache_ttl_seconds)}</p>
      </div>

      {exported ? (
        <p className="rounded-medium border-thin border-border bg-elevation-sunken px-4 py-2 text-xs text-muted-foreground">
          The chart data was downloaded as a CSV to this device. Nothing was sent anywhere - an
          export is a file on your machine, and the platform never mails one out.
        </p>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat
          label="Approvals decided"
          value={formatFigure(trends.automation.approved_count)}
          note={`${trends.automation.exception_free_count} with no exception, ${trends.automation.intervened_count} after one.`}
        />
        <Stat
          label="Ran without intervention"
          value={formatFigure(trends.automation.automation_rate, "percent")}
          note={trends.automation.definition}
        />
        <Stat
          label="Mean turnaround"
          value={formatHours(trends.turnaround.mean_hours)}
          note={`Median ${formatHours(trends.turnaround.median_hours)} over ${trends.turnaround.sample_size} approval${trends.turnaround.sample_size === 1 ? "" : "s"}.`}
        />
        <Stat
          label="Fields not overridden"
          value={formatFigure(trends.extraction.non_override_rate, "percent")}
          note={trends.extraction.disclosure}
        />
      </div>

      <ChartFrame
        title="Turnaround over time"
        description="Hours from a request arriving to the approval on it being decided, per bucket. A bucket in which nothing was approved is a gap, not a zero."
        isEmpty={nothingApproved}
        emptyIcon={ChartLine}
        emptyMessage="No transaction was approved in this range, so there is no turnaround to plot."
      >
        <LineChart
          labels={labels}
          valueLabel="Hours from request received to approval decided"
          series={[
            {
              key: "mean",
              label: "Mean hours",
              points: trends.series.map((bucket) => bucket.mean_hours),
              unit: "h",
            },
            {
              key: "median",
              label: "Median hours",
              // Dashed, because mean and median are the same number on any day with one
              // approval, and a solid line under a solid line is invisible.
              dashed: true,
              points: trends.series.map((bucket) => bucket.median_hours),
              unit: "h",
            },
          ]}
        />
      </ChartFrame>

      <div className="grid gap-4 xl:grid-cols-2">
        <ChartFrame
          title="Extraction non-override rate by document type"
          description="The share of fields read from each document type that nobody had to correct."
          disclosure={trends.extraction.disclosure}
          isEmpty={trends.extraction.by_document_type.length === 0}
          emptyMessage="No document was extracted in this range."
        >
          <BarChart
            valueLabel="Percentage of fields left unchanged"
            max={100}
            data={trends.extraction.by_document_type.map((row) => ({
              key: row.document_type,
              label: row.document_type.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase()),
              value: row.non_override_rate ?? 0,
              display: formatFigure(row.non_override_rate, "percent"),
              href: drillThroughHref(row),
              detail: `${row.field_count} field${row.field_count === 1 ? "" : "s"} read, ${row.overridden_count} corrected`,
            }))}
          />
        </ChartFrame>

        <ChartFrame
          title="Automation against manual intervention"
          description="Of the transactions approved in each bucket, how many never had an exception case opened against them and how many did."
          isEmpty={nothingApproved}
          emptyMessage="No transaction was approved in this range."
        >
          <LineChart
            labels={labels}
            valueLabel="Approvals per bucket, split by whether an exception was ever opened"
            series={[
              {
                key: "exception_free",
                label: "No exception opened",
                points: trends.series.map((bucket) =>
                  bucket.approved_count ? bucket.exception_free_count : null,
                ),
              },
              {
                key: "intervened",
                label: "Needed intervention",
                points: trends.series.map((bucket) =>
                  bucket.approved_count ? bucket.intervened_count : null,
                ),
              },
            ]}
          />
        </ChartFrame>
      </div>

      <section className="rounded-medium border-thin border-border bg-elevation-default shadow-raised p-5">
        <h3 className="text-sm font-semibold text-foreground">The numbers behind the charts</h3>
        <p className="mt-1 text-xs text-muted-foreground">
          The same series, as a table. Every chart on this page has one, so no figure depends on
          being able to read a colour.
        </p>
        <div className="mt-4 overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                {EXPORT_COLUMNS.map((column) => (
                  <TableHead key={column.key}>{column.label}</TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => (
                <TableRow key={row.day}>
                  {EXPORT_COLUMNS.map((column) => (
                    <TableCell key={column.key} className="tabular-nums">
                      {row[column.key as keyof typeof row] ?? "-"}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </section>
    </div>
  );
}

function Stat({ label, value, note }: { label: string; value: string; note: string }) {
  return (
    <div className="rounded-medium border-thin border-border bg-elevation-default shadow-raised p-4">
      <p className="text-xs font-medium uppercase tracking-widest text-muted-foreground">
        {label}
      </p>
      <p className="mt-2 text-2xl font-semibold tabular-nums tracking-tight text-foreground">
        {value}
      </p>
      <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">{note}</p>
    </div>
  );
}
