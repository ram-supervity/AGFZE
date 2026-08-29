"use client";

import { ArrowUpRight } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { ExceptionQueue } from "@/lib/api-client";
import {
  AGE_CHIP,
  PRIORITY_CHIP,
  PRIORITY_LABELS,
  ageBand,
  formatAgeHours,
  ownerLabel,
  type ExceptionPriority,
} from "@/lib/governance";
import { formatMoney } from "@/lib/transactions";
import { cn } from "@/lib/utils";

export function ExceptionTable({ queue }: { queue: ExceptionQueue }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { page, total_pages: totalPages, total } = queue.page;

  function goToPage(next: number) {
    const params = new URLSearchParams(searchParams.toString());
    params.set("page", String(next));
    router.push(`/exceptions?${params.toString()}`);
  }

  return (
    <div className="space-y-3">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Problem</TableHead>
            <TableHead>Batch</TableHead>
            <TableHead>Owner</TableHead>
            <TableHead>Priority</TableHead>
            <TableHead className="text-right">Value</TableHead>
            <TableHead>Open for</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {queue.items.map((row) => {
            const band = ageBand(row.age_hours, row.ageing_threshold_hours);
            return (
              <TableRow
                key={row.id}
                className="cursor-pointer"
                onClick={() => router.push(`/exceptions/${row.id}`)}
              >
                <TableCell className="max-w-md">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="font-medium text-foreground">
                      {row.exception_label ?? row.exception_type}
                    </span>
                    {row.rule_id ? (
                      <Badge variant="muted" className="font-mono text-[10px]">
                        {row.rule_id}
                      </Badge>
                    ) : null}
                    {row.escalated ? (
                      <Badge
                        variant="outline"
                        className="border-signal-blocked/35 bg-signal-blocked/10 text-signal-blocked"
                      >
                        Escalated to HOD
                      </Badge>
                    ) : null}
                    {row.resolved_at ? <Badge variant="muted">Resolved</Badge> : null}
                  </div>
                  <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">
                    {row.summary}
                  </p>
                </TableCell>
                <TableCell className="whitespace-nowrap">
                  <span className="font-mono text-sm text-secondary">
                    {row.batch_number ?? "Not yet on a batch"}
                  </span>
                  <p className="mt-0.5 line-clamp-1 text-xs text-muted-foreground">
                    {row.counterparty ?? "No counterparty recorded"}
                  </p>
                </TableCell>
                <TableCell className="whitespace-nowrap text-sm text-muted-foreground">
                  {ownerLabel(row.owner_role)}
                  {row.assigned_to_name ? (
                    <p className="text-xs text-muted-foreground">{row.assigned_to_name}</p>
                  ) : null}
                </TableCell>
                <TableCell>
                  <Badge
                    variant="outline"
                    className={cn(PRIORITY_CHIP[row.priority as ExceptionPriority])}
                  >
                    {PRIORITY_LABELS[row.priority as ExceptionPriority] ?? row.priority}
                  </Badge>
                </TableCell>
                <TableCell className="whitespace-nowrap text-right tabular-nums">
                  {row.value ? formatMoney(row.value, row.currency ?? "USD") : "-"}
                </TableCell>
                <TableCell className="whitespace-nowrap">
                  {/* The colour ramp is computed from the configured threshold the API sends
                      back, so it moves with the configuration rather than with a literal here. */}
                  <Badge variant="outline" className={cn(AGE_CHIP[band])}>
                    {formatAgeHours(row.age_hours)}
                  </Badge>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>

      <div className="flex items-center justify-between text-sm text-muted-foreground">
        <p>
          {total} exception{total === 1 ? "" : "s"} · page {page} of {totalPages}
        </p>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={page <= 1}
            onClick={() => goToPage(page - 1)}
          >
            Previous
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={page >= totalPages}
            onClick={() => goToPage(page + 1)}
          >
            Next
            <ArrowUpRight className="ml-1 h-3.5 w-3.5" aria-hidden="true" />
          </Button>
        </div>
      </div>
    </div>
  );
}
