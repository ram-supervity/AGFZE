"use client";

import { FileText } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import type { TransactionDetail } from "@/lib/api-client";
import {
  DOCUMENT_TYPE_LABELS,
  EXTRACTION_STATUS_LABELS,
  formatBytes,
  labelFor,
} from "@/lib/intake";
import { MATCH_METHOD_LABELS } from "@/lib/transactions";
import { formatDateTime } from "@/lib/utils";

export function MatchingPanel({ detail }: { detail: TransactionDetail }) {
  return (
    <div className="space-y-4">
      <dl className="grid gap-3 sm:grid-cols-2">
        <div>
          <dt className="text-xs font-medium uppercase tracking-widest text-muted-foreground">
            How it was matched
          </dt>
          <dd className="mt-1 text-sm text-foreground">
            {detail.match_method
              ? (MATCH_METHOD_LABELS[detail.match_method] ?? detail.match_method)
              : "No matching decision has been recorded."}
          </dd>
        </div>
        <div>
          <dt className="text-xs font-medium uppercase tracking-widest text-muted-foreground">
            Match score
          </dt>
          <dd className="mt-1 text-sm tabular-nums text-foreground">
            {detail.match_score ?? "Not scored"}
          </dd>
        </div>
        <div>
          <dt className="text-xs font-medium uppercase tracking-widest text-muted-foreground">
            Originating request
          </dt>
          <dd className="mt-1 text-sm">
            <Link
              href={`/inbox/${detail.request_id}`}
              className="text-secondary underline-offset-4 hover:underline"
            >
              {detail.request_code ?? "Open the request"}
            </Link>
          </dd>
        </div>
        <div>
          <dt className="text-xs font-medium uppercase tracking-widest text-muted-foreground">
            Batch number
          </dt>
          <dd className="mt-1 font-mono text-sm text-foreground">{detail.batch_number}</dd>
        </div>
      </dl>

      {detail.match_rationale ? (
        <p className="rounded-md border border-border bg-surface px-3 py-2 text-sm leading-relaxed text-muted-foreground">
          {detail.match_rationale}
        </p>
      ) : null}

      {detail.commodity_needs_review ? (
        <p className="rounded-md border border-signal-review/35 bg-signal-review/10 px-3 py-2 text-sm text-foreground">
          The grade read from the document
          {detail.extracted_commodity_value
            ? ` — "${detail.extracted_commodity_value}" — `
            : " "}
          matches no active commodity code. Set it in the Extraction panel before submitting.
        </p>
      ) : null}

      <div className="space-y-2">
        <h3 className="text-xs font-medium uppercase tracking-widest text-muted-foreground">
          Linked documents ({detail.documents.length})
        </h3>
        {detail.documents.length === 0 ? (
          <p className="rounded-md border border-dashed border-border bg-surface px-3 py-6 text-center text-sm text-muted-foreground">
            No documents attached yet. That is a normal state for a transaction registered by
            hand — attach them from the inbox upload screen, or as the supplier sends them.
          </p>
        ) : (
          <ul className="space-y-2">
            {detail.documents.map((document) => (
              <li key={document.id}>
                <Link
                  href={`/documents/${document.id}`}
                  className="flex items-start gap-3 rounded-md border border-border bg-surface px-3 py-2 transition-colors hover:border-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <FileText
                    className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground"
                    aria-hidden="true"
                  />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm text-foreground">{document.filename}</p>
                    <p className="text-xs text-muted-foreground">
                      {formatBytes(document.byte_size)} ·{" "}
                      {formatDateTime(document.created_at)}
                    </p>
                  </div>
                  <div className="flex shrink-0 flex-wrap items-center gap-1.5">
                    <Badge variant="muted">
                      {labelFor(DOCUMENT_TYPE_LABELS, document.document_type)}
                    </Badge>
                    <Badge variant="outline">
                      {labelFor(EXTRACTION_STATUS_LABELS, document.extraction_status)}
                    </Badge>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
