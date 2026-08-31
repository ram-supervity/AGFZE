"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";

import { ConfidenceBadge } from "@/components/shared/confidence-badge";
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
import type { RequestQueue } from "@/lib/api-client";
import {
  CATEGORY_LABELS,
  STATUS_LABELS,
  STREAM_LABELS,
  labelFor,
} from "@/lib/intake";
import { formatDateTime } from "@/lib/utils";

export function RequestQueueTable({ queue }: { queue: RequestQueue }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { page, total_pages: totalPages, total } = queue.page;

  function goTo(target: number) {
    const next = new URLSearchParams(searchParams.toString());
    next.set("page", String(target));
    router.push(`/inbox?${next.toString()}`);
  }

  return (
    <div className="space-y-3">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Request</TableHead>
            <TableHead>Subject</TableHead>
            <TableHead>Category</TableHead>
            <TableHead>Stream</TableHead>
            <TableHead>Status</TableHead>
            <TableHead className="text-right">Documents</TableHead>
            <TableHead>Received</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {queue.items.map((request) => (
            <TableRow key={request.id} className="cursor-pointer">
              <TableCell className="font-medium">
                <Link
                  href={`/inbox/${request.id}`}
                  className="text-secondary underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {request.request_code}
                </Link>
                <p className="mt-0.5 text-xs capitalize text-muted-foreground">{request.source}</p>
              </TableCell>
              <TableCell className="max-w-sm">
                <Link href={`/inbox/${request.id}`} className="block">
                  <span className="line-clamp-1 text-foreground">
                    {request.subject ?? "No subject"}
                  </span>
                  <span className="line-clamp-1 text-xs text-muted-foreground">
                    {request.sender_address ?? "Uploaded through the portal"}
                  </span>
                </Link>
              </TableCell>
              <TableCell>
                <div className="space-y-1">
                  {request.category ? (
                    <div className="flex flex-wrap items-center gap-1.5">
                      <ConfidenceBadge
                        label={labelFor(CATEGORY_LABELS, request.category)}
                        confidence={request.category_confidence}
                      />
                      {request.deal_direction && request.deal_direction !== "not_trade" ? (
                        <Badge
                          variant="outline"
                          className={
                            request.deal_direction === "sales"
                              ? "border-pill-green-border bg-pill-green-bg text-pill-green-text text-body-xs"
                              : "border-pill-blue-border bg-pill-blue-bg text-pill-blue-text text-body-xs"
                          }
                        >
                          {request.deal_direction === "sales" ? "Sales deal" : "Purchase deal"}
                        </Badge>
                      ) : null}
                      {request.category_overridden ? (
                        <Badge variant="muted" className="text-body-xs uppercase tracking-wider">
                          Corrected
                        </Badge>
                      ) : null}
                    </div>
                  ) : (
                    <span className="text-sm text-muted-foreground">Not classified yet</span>
                  )}
                  {request.transaction_id ? (
                    <div>
                      <Link
                        href={
                          request.transaction_leg_type === "sales" || request.deal_direction === "sales"
                            ? `/transactions/sales/${request.transaction_id}`
                            : `/transactions/purchase/${request.transaction_id}`
                        }
                        className="inline-flex items-center gap-1 text-xs font-medium text-secondary hover:underline"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <span>
                          Open {request.transaction_leg_type === "sales" || request.deal_direction === "sales" ? "Sales" : "Purchase"} Workspace →
                        </span>
                      </Link>
                    </div>
                  ) : null}
                </div>
              </TableCell>
              <TableCell className="text-sm text-muted-foreground">
                {labelFor(STREAM_LABELS, request.stream)}
              </TableCell>
              <TableCell>
                <div className="flex flex-wrap items-center gap-1.5">
                  <Badge variant="muted">{labelFor(STATUS_LABELS, request.status)}</Badge>
                  {request.needs_review ? (
                    <Badge
                      variant="outline"
                      className="border-pill-amber-border bg-pill-amber-bg text-pill-amber-text"
                    >
                      Needs review
                    </Badge>
                  ) : null}
                </div>
              </TableCell>
              <TableCell className="text-right tabular-nums">{request.document_count}</TableCell>
              <TableCell className="whitespace-nowrap text-sm text-muted-foreground">
                {formatDateTime(request.created_at)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      <div className="flex items-center justify-between text-sm text-muted-foreground">
        <p>
          {total} request{total === 1 ? "" : "s"} · page {page} of {totalPages}
        </p>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={page <= 1}
            onClick={() => goTo(page - 1)}
          >
            Previous
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={page >= totalPages}
            onClick={() => goTo(page + 1)}
          >
            Next
          </Button>
        </div>
      </div>
    </div>
  );
}
