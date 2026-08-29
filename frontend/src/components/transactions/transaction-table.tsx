"use client";

import { ArrowDown, ArrowUp } from "lucide-react";
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
import type { TransactionList } from "@/lib/api-client";
import { labelFor } from "@/lib/intake";
import {
  SHIPMENT_STATUS_CHIP,
  SHIPMENT_STATUS_LABELS,
  type ShipmentStatus,
} from "@/lib/shipments";
import {
  INVOICE_STATUS_LABELS,
  TRANSACTION_STATUS_CHIP,
  TRANSACTION_STATUS_LABELS,
  deskLabel,
  formatAge,
  formatMoney,
  workspacePath,
  type TransactionStatus,
} from "@/lib/transactions";
import { cn } from "@/lib/utils";

export interface TransactionTableProps {
  list: TransactionList;
  sortBy: string;
  sortDir: "asc" | "desc";
}

export function TransactionTable({ list, sortBy, sortDir }: TransactionTableProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { page, total_pages: totalPages, total } = list.page;

  function navigate(changes: Record<string, string>) {
    const next = new URLSearchParams(searchParams.toString());
    for (const [key, value] of Object.entries(changes)) next.set(key, value);
    router.push(`/transactions?${next.toString()}`);
  }

  function sort(key: string) {
    navigate({
      sort_by: key,
      sort_dir: sortBy === key && sortDir === "desc" ? "asc" : "desc",
      page: "1",
    });
  }

  function SortHeader({ column, label }: { column: string; label: string }) {
    const active = sortBy === column;
    return (
      // aria-sort belongs on the column header itself, not on the control inside it.
      <TableHead aria-sort={active ? (sortDir === "asc" ? "ascending" : "descending") : "none"}>
        <button
          type="button"
          onClick={() => sort(column)}
          className="inline-flex items-center gap-1 rounded-sm text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {label}
          {active ? (
            sortDir === "asc" ? (
              <ArrowUp className="h-3 w-3" aria-hidden="true" />
            ) : (
              <ArrowDown className="h-3 w-3" aria-hidden="true" />
            )
          ) : null}
        </button>
      </TableHead>
    );
  }

  return (
    <div className="space-y-3">
      <Table>
        <TableHeader>
          <TableRow>
            <SortHeader column="batch_number" label="Batch / contract" />
            <TableHead>Counterparty</TableHead>
            <TableHead>Status</TableHead>
            <TableHead className="text-right">Value</TableHead>
            <TableHead>Shipment</TableHead>
            <SortHeader column="created_at" label="Age" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {list.items.map((row) => (
            <TableRow
              key={row.id}
              className="cursor-pointer"
              onClick={() => router.push(workspacePath(row))}
            >
              <TableCell className="font-medium">
                <span className="font-mono text-sm text-secondary">{row.batch_number}</span>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  {row.contract_number ?? "No contract reference"} · {deskLabel(row)}
                </p>
              </TableCell>
              <TableCell className="max-w-xs">
                <span className="line-clamp-1 text-foreground">
                  {row.counterparty ?? "No counterparty recorded"}
                  {row.counterparty_code ? (
                    <span className="ml-1.5 font-mono text-xs text-muted-foreground">
                      {row.counterparty_code}
                    </span>
                  ) : null}
                  {row.is_b2b ? (
                    <Badge variant="muted" className="ml-1.5 align-middle">
                      B2B
                    </Badge>
                  ) : null}
                </span>
                {row.is_b2b && row.b2b_partner_name ? (
                  <span className="line-clamp-1 text-xs text-muted-foreground">
                    with {row.b2b_partner_name}
                  </span>
                ) : null}
                <span className="line-clamp-1 text-xs text-muted-foreground">
                  {row.commodity_name ?? row.commodity_code ?? "Grade not resolved"}
                  {row.invoice_status
                    ? ` · ${labelFor(INVOICE_STATUS_LABELS, row.invoice_status)} invoice`
                    : ""}
                </span>
              </TableCell>
              <TableCell>
                <div className="flex flex-wrap items-center gap-1.5">
                  <Badge
                    variant="outline"
                    className={cn(
                      TRANSACTION_STATUS_CHIP[row.status as TransactionStatus] ??
                        "border-border bg-muted text-muted-foreground",
                    )}
                  >
                    {labelFor(TRANSACTION_STATUS_LABELS, row.status)}
                  </Badge>
                  {row.failing_rule_count > 0 ? (
                    <Badge
                      variant="outline"
                      className="border-signal-blocked/35 bg-signal-blocked/10 text-signal-blocked"
                    >
                      {row.failing_rule_count} check
                      {row.failing_rule_count === 1 ? "" : "s"} outstanding
                    </Badge>
                  ) : null}
                </div>
              </TableCell>
              <TableCell className="whitespace-nowrap text-right tabular-nums">
                {formatMoney(row.value, row.currency)}
              </TableCell>
              <TableCell>
                {/* Real from . An em dash still means something specific and true: no
                    shipment record exists, which is not a claim that the cargo is on schedule. */}
                {row.shipment_status ? (
                  <div className="flex flex-wrap items-center gap-1.5">
                    <Badge
                      variant="outline"
                      className={cn(
                        SHIPMENT_STATUS_CHIP[row.shipment_status as ShipmentStatus] ??
                          "border-border bg-muted text-muted-foreground",
                      )}
                    >
                      {labelFor(SHIPMENT_STATUS_LABELS, row.shipment_status)}
                    </Badge>
                    {row.shipment_count > 1 ? (
                      <span className="text-xs text-muted-foreground">
                        {row.shipment_count} shipments
                      </span>
                    ) : null}
                    {row.shipment_stale ? (
                      <Badge
                        variant="outline"
                        className="border-signal-review/35 bg-signal-review/10 text-signal-review"
                        title="Nobody has established where this cargo is for longer than the configured threshold."
                      >
                        Not checked recently
                      </Badge>
                    ) : null}
                  </div>
                ) : (
                  <span className="text-sm text-muted-foreground">No shipment recorded</span>
                )}
              </TableCell>
              <TableCell className="whitespace-nowrap text-sm text-muted-foreground">
                {formatAge(row.age_days)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      <div className="flex items-center justify-between text-sm text-muted-foreground">
        <p>
          {total} transaction{total === 1 ? "" : "s"} · page {page} of {totalPages}
        </p>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={page <= 1}
            onClick={() => navigate({ page: String(page - 1) })}
          >
            Previous
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={page >= totalPages}
            onClick={() => navigate({ page: String(page + 1) })}
          >
            Next
          </Button>
        </div>
      </div>
    </div>
  );
}
