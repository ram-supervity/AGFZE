"use client";

import { ChartLine, Ship, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import type { ReactNode } from "react";

import { BarChart } from "@/components/charts/bar-chart";
import { ChartFrame } from "@/components/charts/chart-frame";
import { DonutChart } from "@/components/charts/donut-chart";
import { LineChart } from "@/components/charts/line-chart";
import { KpiTile } from "@/components/dashboard/kpi-tile";
import { Badge } from "@/components/ui/badge";
import { Select } from "@/components/ui/select";
import {
  drillThroughHref,
  formatDay,
  formatHours,
  freshnessNote,
  orderedPanels,
  phaseSlices,
} from "@/lib/analytics";
import type { DashboardSummary } from "@/lib/api-client";
import { STREAM_LABELS } from "@/lib/intake";

export interface DashboardViewProps {
  summary: DashboardSummary;
  stream: string;
}

/**
 * The dashboard's real content, built for the first time in Step 8.
 *
 * Every tile, every arc and every bar is a link into the queue it counts. Nothing on this screen
 * is a number with no way through to its rows, and nothing is computed here: the browser receives
 * already-aggregated, already-scoped figures and draws them. What this account may see was
 * decided by the queries that produced the payload, not by which of these panels rendered.
 */
export function DashboardView({ summary, stream }: DashboardViewProps) {
  const router = useRouter();
  const params = useSearchParams();

  const slices = phaseSlices(summary.transactions_by_status);
  const panels = orderedPanels(summary.emphasis);

  const exceptionBars = summary.exceptions.categories.map((row) => ({
    key: row.category,
    label: row.label,
    value: row.open_count,
    href: drillThroughHref(row),
    detail:
      row.open_count === 0
        ? "Nothing open."
        : `${row.ageing.under_24h} under 24h · ${row.ageing["24_to_72h"]} 24–72h · ${row.ageing.over_72h} over 72h`,
  }));

  const trend = summary.turnaround_trend;

  function setStream(value: string) {
    const next = new URLSearchParams(params.toString());
    if (value) next.set("stream", value);
    else next.delete("stream");
    router.push(`/dashboard?${next.toString()}`);
  }

  const panelNodes: Record<string, ReactNode> = {
    transactions: (
      <ChartFrame
        key="transactions"
        title="Where the deals are"
        description="Every transaction on the platform, grouped by the phase of the lifecycle it has reached. The phases are named in full below the ring; each one lists the statuses inside it."
        isEmpty={slices.every((slice) => slice.value === 0)}
        emptyMessage="No transaction has been opened yet."
        emptyIcon={ChartLine}
      >
        <DonutChart slices={slices} totalLabel="transactions on the platform" />
      </ChartFrame>
    ),
    exceptions: (
      <ChartFrame
        key="exceptions"
        title="Open exceptions by category"
        description="Unresolved cases only, in the categories your roles work. Every age is computed from the case's own opened-at timestamp at the moment this was queried."
        isEmpty={summary.exceptions.total_open === 0}
        emptyMessage="Nothing is open in the categories your roles work."
        emptyIcon={TriangleAlert}
        actions={
          summary.exceptions.over_72h > 0 ? (
            <Badge
              variant="outline"
              className="border-pill-red-border bg-pill-red-bg text-pill-red-text"
            >
              {summary.exceptions.over_72h} over 72h
            </Badge>
          ) : null
        }
      >
        <BarChart data={exceptionBars} valueLabel="Open cases per category" />
      </ChartFrame>
    ),
    approvals: (
      <ChartFrame
        key="approvals"
        title="Turnaround, day by day"
        description="Hours from the request arriving to the approval being decided, for every transaction approved on that day. A day nobody approved anything on is a gap in the line, not a zero."
        isEmpty={trend.every((bucket) => bucket.approved_count === 0)}
        emptyMessage="No transaction has been approved in the last thirty days."
        emptyIcon={ChartLine}
        actions={
          <Link
            href="/analytics"
            className="text-xs text-secondary underline-offset-4 hover:underline"
          >
            Open in Analytics
          </Link>
        }
      >
        <LineChart
          labels={trend.map((bucket) => formatDay(bucket.bucket_start))}
          series={[
            {
              key: "mean",
              label: "Mean hours",
              points: trend.map((bucket) => bucket.mean_hours),
              unit: "h",
            },
            {
              key: "median",
              label: "Median hours",
              // Dashed, because mean and median are the same number on any day with one
              // approval, and a solid line under a solid line is invisible.
              dashed: true,
              points: trend.map((bucket) => bucket.median_hours),
              unit: "h",
            },
          ]}
          valueLabel="Hours from request received to approval decided"
        />
      </ChartFrame>
    ),
    shipments: (
      <ChartFrame
        key="shipments"
        title="Cargo"
        description={`Shipments by status, and separately those nobody has established a position for in ${Math.round(summary.shipments.stale_threshold_hours)} hours or more.`}
        isEmpty={summary.shipments.total === 0}
        emptyMessage="No shipment has been recorded against a batch yet."
        emptyIcon={Ship}
      >
        <BarChart
          valueLabel="Shipments by status"
          data={[
            ...summary.shipments.by_status.map((row) => ({
              key: row.status,
              label: row.label,
              value: row.count,
              href: drillThroughHref(row),
            })),
            {
              key: "stale",
              label: "Past their check window",
              value: summary.shipments.stale_count,
              href: drillThroughHref({
                target: summary.shipments.stale_target,
                filters: summary.shipments.stale_filters,
              }),
              detail:
                "Counted from the stored last-checked timestamp, whether a carrier reported it or somebody typed it in.",
            },
          ]}
        />
      </ChartFrame>
    ),
    integrations: (
      <ChartFrame
        key="integrations"
        title="Downstream postings"
        description="What the approved deals owe the tracker, SAP and the document store."
        disclosure={summary.integrations.separation_note}
        isEmpty={Object.values(summary.integrations.by_status).every((count) => count === 0)}
        emptyMessage="No transaction has reached the posting stage yet."
      >
        <BarChart
          valueLabel="Integration jobs by state"
          data={Object.entries(summary.integrations.by_status).map(([status, count]) => ({
            key: status,
            label: status.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase()),
            value: count,
            href: drillThroughHref({ target: "integrations", filters: { status } }),
          }))}
        />
      </ChartFrame>
    ),
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-space-150 rounded-medium border-thin border-border bg-elevation-default px-space-200 py-space-150">
        <div className="min-w-0 space-y-0.5">
          <p className="text-sm text-foreground">{summary.scope_note}</p>
          <p className="text-xs text-muted-foreground">
            {freshnessNote(summary.cache_age_seconds, summary.cache_ttl_seconds)}
          </p>
        </div>
        <label className="flex items-center gap-2 text-xs text-muted-foreground">
          <span>Stream</span>
          <Select
            value={stream}
            onChange={(event) => setStream(event.target.value)}
            className="h-8 w-40"
            aria-label="Filter the dashboard by business stream"
          >
            <option value="">Both streams</option>
            {summary.streams.map((value) => (
              <option key={value} value={value}>
                {STREAM_LABELS[value as keyof typeof STREAM_LABELS] ?? value}
              </option>
            ))}
          </Select>
        </label>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {summary.tiles.map((figure) => (
          <KpiTile key={figure.key} figure={figure} />
        ))}
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        {panels.map((panel) => panelNodes[panel]).filter(Boolean)}
      </div>

      <section className="rounded-medium border-thin border-border bg-elevation-default shadow-raised p-5">
        <h3 className="text-sm font-semibold text-foreground">How these figures are computed</h3>
        <p className="mt-1 text-xs text-muted-foreground">
          Every number on this screen is a live count or duration over the transaction records
          themselves. None of them is stored, estimated or carried over from a previous run.
        </p>
        <dl className="mt-4 grid gap-x-8 gap-y-3 sm:grid-cols-2">
          {Object.entries(summary.definitions).map(([key, definition]) => (
            <div key={key}>
              <dt className="text-xs font-medium text-foreground">
                {key.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase())}
              </dt>
              <dd className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
                {definition}
              </dd>
            </div>
          ))}
        </dl>
        <p className="mt-4 border-t border-border pt-3 text-xs text-muted-foreground">
          Turnaround over the last thirty days: mean {formatHours(summary.turnaround.mean_hours)},
          median {formatHours(summary.turnaround.median_hours)}, over{" "}
          {summary.turnaround.sample_size} approval
          {summary.turnaround.sample_size === 1 ? "" : "s"}.
        </p>
      </section>
    </div>
  );
}
