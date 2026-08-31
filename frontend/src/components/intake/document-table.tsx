"use client";

import { FileText } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

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
import type { DocumentList, DocumentListItem } from "@/lib/api-client";
import {
  DOCUMENT_TYPE_LABELS,
  EXTRACTION_STATUS_LABELS,
  formatBytes,
  labelFor,
} from "@/lib/intake";
import { formatDateTime } from "@/lib/utils";

export function DocumentTable({ list }: { list: DocumentList }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [hovered, setHovered] = useState<DocumentListItem | null>(null);
  const { page, total_pages: totalPages, total } = list.page;

  function goTo(target: number) {
    const next = new URLSearchParams(searchParams.toString());
    next.set("page", String(target));
    router.push(`/documents?${next.toString()}`);
  }

  return (
    <div className="relative space-y-3">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Filename</TableHead>
            <TableHead>Type</TableHead>
            <TableHead>Request</TableHead>
            <TableHead>Extraction</TableHead>
            <TableHead>Linked transaction</TableHead>
            <TableHead>Received</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {list.items.map((document) => (
            <TableRow
              key={document.id}
              onMouseEnter={() => setHovered(document)}
              onMouseLeave={() => setHovered((current) => (current?.id === document.id ? null : current))}
            >
              <TableCell className="max-w-xs">
                <Link
                  href={`/documents/${document.id}`}
                  className="flex items-center gap-2 text-secondary underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <FileText className="h-4 w-4 shrink-0" aria-hidden="true" />
                  <span className="truncate">{document.filename}</span>
                </Link>
                <p className="mt-0.5 pl-6 text-xs text-muted-foreground">
                  {formatBytes(document.byte_size)}
                  {document.page_count
                    ? ` · ${document.page_count} page${document.page_count === 1 ? "" : "s"}`
                    : ""}
                </p>
              </TableCell>
              <TableCell>
                {document.document_type ? (
                  <ConfidenceBadge
                    label={labelFor(DOCUMENT_TYPE_LABELS, document.document_type)}
                    confidence={document.classification_confidence}
                  />
                ) : (
                  <Badge variant="muted">Not classified yet</Badge>
                )}
              </TableCell>
              <TableCell>
                {document.request_id ? (
                  <Link
                    href={`/inbox/${document.request_id}`}
                    className="text-sm text-secondary underline-offset-4 hover:underline"
                  >
                    {document.request_code ?? "Open request"}
                  </Link>
                ) : (
                  // A draft this platform wrote. Nothing received it, so there is no request to
                  // open - and a link to one would be a dead end dressed up as a route somewhere.
                  <span className="text-sm text-muted-foreground">Generated here</span>
                )}
              </TableCell>
              <TableCell>
                <div className="flex flex-wrap items-center gap-1.5">
                  <Badge variant="muted">
                    {labelFor(EXTRACTION_STATUS_LABELS, document.extraction_status)}
                  </Badge>
                  {document.confirmed_at ? (
                    <Badge
                      variant="outline"
                      className="border-pill-green-border bg-pill-green-bg text-pill-green-text"
                    >
                      Confirmed
                    </Badge>
                  ) : document.needs_review ? (
                    <Badge
                      variant="outline"
                      className="border-pill-amber-border bg-pill-amber-bg text-pill-amber-text"
                    >
                      Needs review
                    </Badge>
                  ) : null}
                </div>
              </TableCell>
              <TableCell className="text-sm text-muted-foreground">
                {document.transaction_id ? (
                  <Link
                    href={`/transactions/purchase/${document.transaction_id}`}
                    className="text-secondary underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    Open transaction
                  </Link>
                ) : (
                  // Honestly empty: nothing has been matched to a batch yet.
                  "-"
                )}
              </TableCell>
              <TableCell className="whitespace-nowrap text-sm text-muted-foreground">
                {formatDateTime(document.created_at)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      {hovered?.thumbnail_url ? (
        <div className="pointer-events-none fixed bottom-space-300 right-space-300 z-raised hidden w-56 overflow-hidden rounded-medium border-thin border-border bg-elevation-overlay shadow-raised lg:block">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={hovered.thumbnail_url}
            alt={`First page of ${hovered.filename}`}
            className="h-72 w-full object-cover object-top"
          />
          <p className="truncate border-t border-border px-3 py-2 text-xs text-muted-foreground">
            {hovered.filename}
          </p>
        </div>
      ) : null}

      <div className="flex items-center justify-between text-sm text-muted-foreground">
        <p>
          {total} document{total === 1 ? "" : "s"} · page {page} of {totalPages}
        </p>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => goTo(page - 1)}>
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
