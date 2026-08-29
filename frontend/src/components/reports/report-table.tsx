"use client";

import { FileDown, Plus } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
  REPORT_FORMATS,
  REPORT_FORMAT_LABELS,
  REPORT_STREAM_LABELS,
  REPORT_TYPES,
  REPORT_TYPE_CHIP,
  REPORT_TYPE_LABELS,
  formatDay,
  formatMoment,
  type ReportFormat,
  type ReportType,
} from "@/lib/analytics";
import type { ReportList } from "@/lib/api-client";
import { formatBytes } from "@/lib/intake";
import { cn } from "@/lib/utils";

export interface ReportTableProps {
  list: ReportList;
  filters: { reportType: string; outputFormat: string };
}

export function ReportTable({ list, filters }: ReportTableProps) {
  const router = useRouter();
  const params = useSearchParams();
  const { page, total_pages: totalPages, total } = list.page;

  function apply(changes: Record<string, string | null>) {
    const next = new URLSearchParams(params.toString());
    for (const [key, value] of Object.entries(changes)) {
      if (value === null || value === "") next.delete(key);
      else next.set(key, value);
    }
    next.delete("page");
    router.push(`/reports?${next.toString()}`);
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3 rounded-lg border border-border bg-surface p-4">
        <div className="flex flex-wrap gap-3">
          <label className="space-y-1.5 text-xs text-muted-foreground">
            <span className="block">Type</span>
            <Select
              value={filters.reportType}
              onChange={(event) => apply({ report_type: event.target.value || null })}
              className="h-9 w-40"
            >
              <option value="">Every type</option>
              {REPORT_TYPES.map((value) => (
                <option key={value} value={value}>
                  {REPORT_TYPE_LABELS[value]}
                </option>
              ))}
            </Select>
          </label>
          <label className="space-y-1.5 text-xs text-muted-foreground">
            <span className="block">Format</span>
            <Select
              value={filters.outputFormat}
              onChange={(event) => apply({ output_format: event.target.value || null })}
              className="h-9 w-40"
            >
              <option value="">Either format</option>
              {REPORT_FORMATS.map((value) => (
                <option key={value} value={value}>
                  {REPORT_FORMAT_LABELS[value]}
                </option>
              ))}
            </Select>
          </label>
        </div>

        {list.can_generate ? (
          <Button asChild size="sm">
            <Link href="/reports/builder">
              <Plus className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
              Generate a report
            </Link>
          </Button>
        ) : null}
      </div>

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Report</TableHead>
            <TableHead>Period</TableHead>
            <TableHead>Stream</TableHead>
            <TableHead>Reference</TableHead>
            <TableHead>Generated</TableHead>
            <TableHead className="text-right">Open</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {list.items.map((report) => (
            <TableRow
              key={report.id}
              className="cursor-pointer"
              onClick={() => router.push(`/reports/${report.id}`)}
            >
              <TableCell>
                <div className="flex flex-wrap items-center gap-1.5">
                  <Badge
                    variant="outline"
                    className={cn(REPORT_TYPE_CHIP[report.report_type as ReportType])}
                  >
                    {REPORT_TYPE_LABELS[report.report_type as ReportType] ?? report.report_type}
                  </Badge>
                  <span className="text-sm text-foreground">{report.title}</span>
                </div>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  {REPORT_FORMAT_LABELS[report.output_format as ReportFormat] ??
                    report.output_format}
                  {report.byte_size ? ` · ${formatBytes(report.byte_size)}` : ""}
                  {report.ai_summary_error ? " · summary unavailable" : ""}
                </p>
              </TableCell>
              <TableCell className="whitespace-nowrap text-sm text-muted-foreground">
                {formatDay(report.period_start)} → {formatDay(report.period_end)}
              </TableCell>
              <TableCell className="text-sm text-muted-foreground">
                {REPORT_STREAM_LABELS[report.stream] ?? report.stream}
              </TableCell>
              <TableCell>
                <span className="font-mono text-xs text-secondary">
                  {report.generation_reference}
                </span>
              </TableCell>
              <TableCell className="text-sm text-muted-foreground">
                {formatMoment(report.generated_at)}
                <p className="mt-0.5 text-xs">
                  {/* Never attributed to a person where nobody asked for it. */}
                  {report.scheduled
                    ? "On schedule, by the platform"
                    : (report.generated_by_name ?? "Account no longer on the platform")}
                </p>
              </TableCell>
              <TableCell className="text-right" onClick={(event) => event.stopPropagation()}>
                <Button asChild size="sm" variant="outline">
                  <Link href={`/reports/${report.id}`}>
                    <FileDown className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
                    Open
                  </Link>
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      <div className="flex items-center justify-between text-sm text-muted-foreground">
        <p>
          {total} report{total === 1 ? "" : "s"} · page {page} of {totalPages}
        </p>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={page <= 1}
            onClick={() => apply({ page: String(page - 1) })}
          >
            Previous
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={page >= totalPages}
            onClick={() => apply({ page: String(page + 1) })}
          >
            Next
          </Button>
        </div>
      </div>
    </div>
  );
}
