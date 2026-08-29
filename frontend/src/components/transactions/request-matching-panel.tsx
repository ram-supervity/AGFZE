"use client";

import { DocumentMatchPanel } from "@/components/transactions/document-match-panel";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { DocumentSummary } from "@/lib/api-client";

export interface RequestMatchingPanelProps {
  documents: DocumentSummary[];
  canResolve: boolean;
}

/**
 * What matching did with each of this request's confirmed documents.
 *
 * Only confirmed documents appear: matching is triggered by confirmation, so a document still
 * under review has no outcome to report and inventing a provisional one would be misleading.
 */
export function RequestMatchingPanel({ documents, canResolve }: RequestMatchingPanelProps) {
  const confirmed = documents.filter((document) => Boolean(document.confirmed_at));
  if (confirmed.length === 0) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Matching outcome</CardTitle>
        <CardDescription>
          Where each confirmed document on this request ended up.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {confirmed.map((document) => (
          <div key={document.id} className="space-y-2">
            <p className="truncate text-xs font-medium uppercase tracking-widest text-muted-foreground">
              {document.filename}
            </p>
            <DocumentMatchPanel
              documentId={document.id}
              confirmed
              canResolve={canResolve}
            />
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
