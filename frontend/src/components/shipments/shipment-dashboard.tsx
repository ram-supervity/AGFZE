"use client";

import { ExternalLink, RefreshCw, Ship, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useSession } from "next-auth/react";
import { useState } from "react";
import toast from "react-hot-toast";

import { EmptyState } from "@/components/shared/empty-state";
import {
  ShipmentFilters,
  type ShipmentView,
} from "@/components/shipments/shipment-filters";
import { StalenessIndicator } from "@/components/shipments/staleness-indicator";
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
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import {
  ApiError,
  refreshShipment,
  type ShipmentList,
  type ShipmentListItem,
} from "@/lib/api-client";
import { labelFor } from "@/lib/intake";
import {
  SHIPMENT_MILESTONE_LABELS,
  SHIPMENT_STATUS_CHIP,
  SHIPMENT_STATUS_LABELS,
  formatDate,
  sourceLabel,
  trackingModeNote,
  type ShipmentStatus,
} from "@/lib/shipments";
import { cn } from "@/lib/utils";

export interface ShipmentDashboardProps {
  list: ShipmentList;
  filters: {
    search: string;
    status: string;
    carrier: string;
    portOfDischarge: string;
    staleOnly: boolean;
  };
}

/**
 * The board that replaces one person's morning spent on carrier websites.
 *
 * Every row reads the same whether the last update came from a carrier adapter or from somebody
 * typing what they were told on the telephone. The source is a caption under the timestamp, not a
 * badge, a mode or a second layout - which is the point: the desk needs to know where the cargo is
 * and when that was last established, and how it was established is a footnote.
 */
export function ShipmentDashboard({ list, filters }: ShipmentDashboardProps) {
  const router = useRouter();
  const params = useSearchParams();
  const { data: session } = useSession();
  const [view, setView] = useState<ShipmentView>("table");
  const [refreshing, setRefreshing] = useState<string | null>(null);

  const token = session?.accessToken;
  const { page, total_pages: totalPages, total } = list.page;

  function navigate(changes: Record<string, string>) {
    const next = new URLSearchParams(params.toString());
    for (const [key, value] of Object.entries(changes)) next.set(key, value);
    router.push(`/shipments?${next.toString()}`);
  }

  async function refresh(shipment: ShipmentListItem) {
    if (!token) {
      toast.error("Your session has expired. Sign in again to refresh this shipment.");
      return;
    }
    setRefreshing(shipment.id);
    try {
      const result = await refreshShipment(token, shipment.id);
      if (result.attempted && result.updated) {
        toast.success(result.message);
      } else {
        // Not an error. No adapter handles this shipment, which is the ordinary case, and the
        // right next  is to open it and type in what the carrier said.
        toast(result.message, { icon: "✎" });
      }
      router.refresh();
    } catch (error) {
      toast.error(
        error instanceof ApiError ? error.message : "The shipment could not be refreshed.",
      );
    } finally {
      setRefreshing(null);
    }
  }

  if (list.items.length === 0) {
    const filtered = Boolean(
      filters.search ||
        filters.status ||
        filters.carrier ||
        filters.portOfDischarge ||
        filters.staleOnly,
    );
    return (
      <div className="space-y-4">
        <ShipmentFilters
          {...filters}
          carriers={list.carriers}
          ports={list.ports_of_discharge}
          view={view}
          onViewChange={setView}
        />
        <EmptyState
          icon={Ship}
          title={filtered ? "Nothing matches those filters" : "No shipments yet"}
          description={
            filtered
              ? "No shipment matches the filters you have applied. Clear them to see the whole board."
              : "A shipment appears here once a container is recorded against a batch, or when the logistics desk opens one by hand for cargo the paperwork has not caught up with."
          }
        />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <ShipmentFilters
        {...filters}
        carriers={list.carriers}
        ports={list.ports_of_discharge}
        view={view}
        onViewChange={setView}
      />

      <p className="rounded-md border border-border bg-surface px-4 py-3 text-sm text-muted-foreground">
        {trackingModeNote(list.carrier_adapters_available)}
      </p>

      {view === "table" ? (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Container / B/L</TableHead>
              <TableHead>Route</TableHead>
              <TableHead>Milestone</TableHead>
              <TableHead>ETD / ETA</TableHead>
              <TableHead>Last checked</TableHead>
              <TableHead>Batch</TableHead>
              <TableHead className="text-right">Refresh</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {list.items.map((row) => (
              <TableRow
                key={row.id}
                className="cursor-pointer"
                onClick={() => router.push(`/shipments/${row.id}`)}
              >
                <TableCell>
                  <span className="font-mono text-sm text-secondary">
                    {row.container_number ?? row.bl_number ?? "No reference"}
                  </span>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    {row.carrier ?? "Carrier not recorded"}
                    {row.vessel ? ` · ${row.vessel}` : ""}
                  </p>
                </TableCell>
                <TableCell className="text-sm text-muted-foreground">
                  {row.port_of_loading ?? "—"} → {row.port_of_discharge ?? "—"}
                </TableCell>
                <TableCell>
                  <div className="flex flex-wrap items-center gap-1.5">
                    <Badge
                      variant="outline"
                      className={cn(
                        SHIPMENT_STATUS_CHIP[row.status as ShipmentStatus] ??
                          "border-border bg-muted text-muted-foreground",
                      )}
                    >
                      {labelFor(SHIPMENT_STATUS_LABELS, row.status)}
                    </Badge>
                    <span className="text-xs text-muted-foreground">
                      {labelFor(
                        SHIPMENT_MILESTONE_LABELS,
                        row.current_milestone ?? "unknown",
                      )}
                    </span>
                    {row.review_flagged ? <ReviewFlag reason={row.review_reason} /> : null}
                  </div>
                </TableCell>
                <TableCell className="whitespace-nowrap text-sm text-muted-foreground">
                  {formatDate(row.etd)} → {formatDate(row.eta)}
                </TableCell>
                <TableCell>
                  <StalenessIndicator
                    hours={row.hours_since_check}
                    lastCheckedAt={row.last_checked_at}
                    isStale={row.is_stale}
                    thresholdHours={row.stale_threshold_hours}
                  />
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    {sourceLabel(row.last_checked_source)}
                  </p>
                </TableCell>
                <TableCell onClick={(event) => event.stopPropagation()}>
                  {row.batch_number ? (
                    <Link
                      href={`/transactions/purchase/${row.transaction_id}`}
                      className="inline-flex items-center gap-1 font-mono text-sm text-secondary underline-offset-4 hover:underline"
                    >
                      {row.batch_number}
                      <ExternalLink className="h-3 w-3" aria-hidden="true" />
                    </Link>
                  ) : (
                    <span className="text-sm text-muted-foreground">—</span>
                  )}
                </TableCell>
                <TableCell className="text-right" onClick={(event) => event.stopPropagation()}>
                  {list.can_manage ? (
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={refreshing === row.id}
                      onClick={() => refresh(row)}
                      aria-label={`Refresh ${row.container_number ?? row.bl_number ?? "shipment"}`}
                    >
                      <RefreshCw
                        className={cn("h-3.5 w-3.5", refreshing === row.id && "animate-spin")}
                        aria-hidden="true"
                      />
                    </Button>
                  ) : null}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {list.items.map((row) => (
            <ShipmentCard
              key={row.id}
              shipment={row}
              canManage={list.can_manage}
              refreshing={refreshing === row.id}
              onRefresh={() => refresh(row)}
            />
          ))}
        </div>
      )}

      <div className="flex items-center justify-between text-sm text-muted-foreground">
        <p>
          {total} shipment{total === 1 ? "" : "s"} · page {page} of {totalPages}
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

function ReviewFlag({ reason }: { reason: string | null }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span tabIndex={0}>
          <Badge
            variant="outline"
            className="border-signal-review/35 bg-signal-review/10 text-signal-review"
          >
            <TriangleAlert className="mr-1 h-3 w-3" aria-hidden="true" />
            Needs a look
          </Badge>
        </span>
      </TooltipTrigger>
      <TooltipContent side="top" className="max-w-[22rem]">
        {reason ??
          "The last change to this shipment did not look plausible. It was saved anyway; somebody should confirm it."}
      </TooltipContent>
    </Tooltip>
  );
}

function ShipmentCard({
  shipment,
  canManage,
  refreshing,
  onRefresh,
}: {
  shipment: ShipmentListItem;
  canManage: boolean;
  refreshing: boolean;
  onRefresh: () => void;
}) {
  return (
    <article className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <Link
            href={`/shipments/${shipment.id}`}
            className="font-mono text-sm text-secondary underline-offset-4 hover:underline"
          >
            {shipment.container_number ?? shipment.bl_number ?? "No reference"}
          </Link>
          <p className="mt-0.5 truncate text-xs text-muted-foreground">
            {shipment.carrier ?? "Carrier not recorded"}
            {shipment.vessel ? ` · ${shipment.vessel}` : ""}
          </p>
        </div>
        <Badge
          variant="outline"
          className={cn(
            SHIPMENT_STATUS_CHIP[shipment.status as ShipmentStatus] ??
              "border-border bg-muted text-muted-foreground",
          )}
        >
          {labelFor(SHIPMENT_STATUS_LABELS, shipment.status)}
        </Badge>
      </div>

      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
        <Field label="Route">
          {shipment.port_of_loading ?? "—"} → {shipment.port_of_discharge ?? "—"}
        </Field>
        <Field label="Milestone">
          {labelFor(SHIPMENT_MILESTONE_LABELS, shipment.current_milestone ?? "unknown")}
        </Field>
        <Field label="ETD">{formatDate(shipment.etd)}</Field>
        <Field label="ETA">{formatDate(shipment.eta)}</Field>
      </dl>

      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border pt-3">
        <div className="space-y-0.5">
          <StalenessIndicator
            hours={shipment.hours_since_check}
            lastCheckedAt={shipment.last_checked_at}
            isStale={shipment.is_stale}
            thresholdHours={shipment.stale_threshold_hours}
          />
          <p className="text-xs text-muted-foreground">
            {sourceLabel(shipment.last_checked_source)}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {shipment.batch_number ? (
            <Button asChild size="sm" variant="ghost">
              <Link href={`/transactions/purchase/${shipment.transaction_id}`}>
                {shipment.batch_number}
              </Link>
            </Button>
          ) : null}
          {canManage ? (
            <Button
              size="sm"
              variant="outline"
              disabled={refreshing}
              onClick={onRefresh}
              aria-label="Refresh this shipment"
            >
              <RefreshCw
                className={cn("h-3.5 w-3.5", refreshing && "animate-spin")}
                aria-hidden="true"
              />
            </Button>
          ) : null}
        </div>
      </div>

      {shipment.review_flagged ? <ReviewFlag reason={shipment.review_reason} /> : null}
    </article>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-widest text-muted-foreground">
        {label}
      </dt>
      <dd className="mt-0.5 truncate text-foreground">{children}</dd>
    </div>
  );
}
