"use client";

import { Download, ScrollText } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useSession } from "next-auth/react";
import { useState } from "react";
import toast from "react-hot-toast";

import { EmptyState } from "@/components/shared/empty-state";
import { Badge } from "@/components/ui/badge";
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
  actorLabel,
  entityTypeLabel,
  eventTypeLabel,
  metadataSummary,
  type AuditFilters,
} from "@/lib/audit";
import { ApiError, downloadAuditExport, type AuditEventList } from "@/lib/api-client";
import { formatDateTime } from "@/lib/utils";

export interface AuditExplorerProps {
  data: AuditEventList;
  filters: AuditFilters;
}

const ACTOR_TYPE_CHIP: Record<string, string> = {
  user: "border-border bg-muted text-muted-foreground",
  system: "border-pill-blue-border bg-pill-blue-bg text-pill-blue-text",
  agent: "border-pill-amber-border bg-pill-amber-bg text-pill-amber-text",
};

/**
 * The append-only trail, read.
 *
 * The event-type and entity-type filters are populated from what the API found in the data, not
 * from a list held here. Ten steps have contributed event types and an eleventh will contribute
 * more; a hardcoded list would be wrong the day a new one is first recorded.
 *
 * The metadata column shows a summary and never a document's text or a model prompt. That holds
 * at three levels: no call site in the platform writes such content into an audit payload, the
 * read layer redacts by key and truncates by length on the way out, and this cell renders only
 * the first few keys of what it is handed.
 */
export function AuditExplorer({ data, filters }: AuditExplorerProps) {
  const router = useRouter();
  const params = useSearchParams();
  const { data: session } = useSession();
  const [exporting, setExporting] = useState(false);

  const { page, total_pages: totalPages, total } = data.page;

  function navigate(changes: Record<string, string | null>) {
    const next = new URLSearchParams(params.toString());
    for (const [key, value] of Object.entries(changes)) {
      if (!value) next.delete(key);
      else next.set(key, value);
    }
    if (!("page" in changes)) next.delete("page");
    router.push(`/admin/audit${next.toString() ? `?${next.toString()}` : ""}`);
  }

  async function exportCsv() {
    const token = session?.accessToken;
    if (!token) {
      toast.error("Your session has expired. Sign in again to export.");
      return;
    }
    setExporting(true);
    try {
      // Streamed by the API row by row; the browser saves it straight out of the response rather
      // than the page assembling a table in memory first.
      const blob = await downloadAuditExport(token, filters as Record<string, string | undefined>);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `agfze-audit-${new Date().toISOString().slice(0, 10)}.csv`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
      toast.success("Export downloaded. The export itself is on the audit trail.");
    } catch (error) {
      toast.error(
        error instanceof ApiError ? error.message : "The export could not be produced.",
      );
    } finally {
      setExporting(false);
    }
  }

  const filtered = Object.values(filters).some(Boolean);

  return (
    <div className="space-y-4">
      <div className="grid gap-3 rounded-lg border border-border bg-surface p-4 sm:grid-cols-2 xl:grid-cols-3">
        <div className="space-y-1.5">
          <Label htmlFor="audit-from">From</Label>
          <Input
            id="audit-from"
            type="date"
            value={(filters.date_from ?? "").slice(0, 10)}
            onChange={(event) =>
              navigate({
                date_from: event.target.value ? `${event.target.value}T00:00:00Z` : null,
              })
            }
          />
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="audit-to">To</Label>
          <Input
            id="audit-to"
            type="date"
            value={(filters.date_to ?? "").slice(0, 10)}
            onChange={(event) =>
              navigate({ date_to: event.target.value ? `${event.target.value}T23:59:59Z` : null })
            }
          />
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="audit-event-type">Event type</Label>
          <Select
            id="audit-event-type"
            value={filters.event_type ?? ""}
            onChange={(event) => navigate({ event_type: event.target.value || null })}
          >
            <option value="">Every event type</option>
            {data.event_types.map((type) => (
              <option key={type} value={type}>
                {eventTypeLabel(type)}
              </option>
            ))}
          </Select>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="audit-actor">Actor</Label>
          <Select
            id="audit-actor"
            value={filters.actor_id ?? ""}
            onChange={(event) => navigate({ actor_id: event.target.value || null })}
          >
            <option value="">Anybody, and the platform itself</option>
            {data.actors.map((actor) => (
              <option key={actor.id} value={actor.id}>
                {actor.display_name}
              </option>
            ))}
          </Select>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="audit-entity-type">Entity</Label>
          <Select
            id="audit-entity-type"
            value={filters.entity_type ?? ""}
            onChange={(event) => navigate({ entity_type: event.target.value || null })}
          >
            <option value="">Every kind of record</option>
            {data.entity_types.map((type) => (
              <option key={type} value={type}>
                {entityTypeLabel(type)}
              </option>
            ))}
          </Select>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="audit-search">Entity reference</Label>
          <Input
            id="audit-search"
            defaultValue={filters.search ?? ""}
            placeholder="An id, or a kind of record"
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                navigate({ search: (event.target as HTMLInputElement).value || null });
              }
            }}
          />
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground">
          {total.toLocaleString("en-GB")} event{total === 1 ? "" : "s"}
          {filtered ? " matching these filters" : " recorded since the platform's first day"}.
        </p>
        <div className="flex gap-2">
          {filtered ? (
            <Button variant="ghost" size="sm" onClick={() => router.push("/admin/audit")}>
              Clear filters
            </Button>
          ) : null}
          <Button variant="outline" size="sm" disabled={exporting} onClick={exportCsv}>
            <Download className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
            {exporting ? "Preparing…" : "Export CSV"}
          </Button>
        </div>
      </div>

      {data.items.length === 0 ? (
        <EmptyState
          icon={ScrollText}
          title={filtered ? "Nothing matches those filters" : "No events recorded yet"}
          description={
            filtered
              ? "Widen the date range, or clear the filters to see the whole trail."
              : "Every governance-relevant action is written here as it happens."
          }
        />
      ) : (
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>When</TableHead>
                <TableHead>Actor</TableHead>
                <TableHead>Event</TableHead>
                <TableHead>Entity</TableHead>
                <TableHead>Detail</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.items.map((row) => (
                <TableRow key={row.id} className="align-top">
                  <TableCell className="whitespace-nowrap text-sm text-muted-foreground">
                    {formatDateTime(row.occurred_at)}
                  </TableCell>

                  <TableCell className="text-sm text-foreground">
                    {actorLabel(row.actor_type, row.actor_name, null)}
                    <Badge
                      variant="outline"
                      className={`ml-1.5 px-1.5 py-0 text-body-xs ${ACTOR_TYPE_CHIP[row.actor_type] ?? ""}`}
                    >
                      {row.actor_type}
                    </Badge>
                  </TableCell>

                  <TableCell className="text-sm text-foreground">
                    {eventTypeLabel(row.event_type)}
                    <p className="mt-0.5 font-mono text-xs text-muted-foreground">
                      {row.event_type}
                    </p>
                  </TableCell>

                  <TableCell className="text-sm text-muted-foreground">
                    {entityTypeLabel(row.entity_type)}
                    {row.entity_id ? (
                      <p className="mt-0.5 max-w-[14rem] truncate font-mono text-xs" title={row.entity_id}>
                        {row.entity_id}
                      </p>
                    ) : null}
                  </TableCell>

                  <TableCell className="max-w-[26rem] text-xs leading-relaxed text-muted-foreground">
                    {metadataSummary(row.metadata)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <div className="flex items-center justify-between text-sm text-muted-foreground">
        <p>
          Page {page} of {totalPages}
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
