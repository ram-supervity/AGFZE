import { FileText } from "lucide-react";
import Link from "next/link";

import { ConfidenceBadge } from "@/components/shared/confidence-badge";
import { Badge } from "@/components/ui/badge";
import type { DocumentSummary } from "@/lib/api-client";
import {
  DOCUMENT_TYPE_LABELS,
  EXTRACTION_STATUS_LABELS,
  formatBytes,
  labelFor,
} from "@/lib/intake";

export function AttachmentGrid({ documents }: { documents: DocumentSummary[] }) {
  return (
    <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
      {documents.map((document) => (
        <li key={document.id}>
          <Link
            href={`/documents/${document.id}`}
            className="flex h-full flex-col overflow-hidden rounded-lg border border-border bg-card transition-colors hover:border-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <div className="flex h-36 items-center justify-center overflow-hidden border-b border-border bg-surface">
              {document.thumbnail_url ? (
                // The signed, short-lived URL the API minted for this page image.
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={document.thumbnail_url}
                  alt={`First page of ${document.filename}`}
                  className="h-full w-full object-cover object-top"
                />
              ) : (
                <FileText className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
              )}
            </div>
            <div className="flex flex-1 flex-col gap-2 p-3">
              <p className="line-clamp-2 break-words text-sm font-medium text-foreground">
                {document.filename}
              </p>
              <div className="flex flex-wrap items-center gap-1.5">
                {document.document_type ? (
                  <ConfidenceBadge
                    label={labelFor(DOCUMENT_TYPE_LABELS, document.document_type)}
                    confidence={document.classification_confidence}
                  />
                ) : (
                  <Badge variant="muted">Not classified yet</Badge>
                )}
                <Badge variant="muted">
                  {labelFor(EXTRACTION_STATUS_LABELS, document.extraction_status)}
                </Badge>
                {document.transaction_id ? (
                  <Badge
                    variant="outline"
                    className="border-signal-confident/35 bg-signal-confident/10 text-signal-confident"
                  >
                    Matched to a batch
                  </Badge>
                ) : null}
              </div>
              <p className="mt-auto text-xs text-muted-foreground">
                {formatBytes(document.byte_size)}
                {document.page_count ? ` · ${document.page_count} page${
                  document.page_count === 1 ? "" : "s"
                }` : ""}
              </p>
            </div>
          </Link>
        </li>
      ))}
    </ul>
  );
}
