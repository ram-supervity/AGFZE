"use client";

import { Share2 } from "lucide-react";
import { useSession } from "next-auth/react";
import { useEffect, useState } from "react";

import { EmptyState } from "@/components/shared/empty-state";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, fetchTransactionGraph, type TransactionGraph } from "@/lib/api-client";

const LABELS: Record<string, string> = {
  TradeTransaction: "Transaction",
  PurchaseLeg: "Purchase leg",
  SalesLeg: "Sales leg",
  FaLeg: "FA leg",
  Document: "Document",
  EmailMessage: "Email",
  Container: "Container",
  Shipment: "Shipment",
  Supplier: "Supplier",
  Customer: "Customer",
  ApprovalTask: "Approval",
  ExceptionCase: "Exception",
  IntegrationJob: "Posting",
  DocumentPack: "Document pack",
};

/**
 * What this transaction is connected to, read from the graph projection.
 *
 * Rendered as a grouped list rather than a node-link canvas, and that is a deliberate choice
 * rather than a shortcut. The question this answers - "what is attached to this deal, and did the
 * posting come from the email I think it did" - is read, not explored: a force-directed diagram of
 * fifteen nodes is harder to read than the same fifteen grouped by what they are, and it cannot be
 * used by anybody navigating with a keyboard or a screen reader. Every row here is real text.
 *
 * It states plainly when the projection is unavailable. An empty diagram would say this deal is
 * connected to nothing, which is a claim about the deal rather than about the deployment.
 */
export function TracePanel({ transactionId }: { transactionId: string }) {
  const { data: session } = useSession();
  const [graph, setGraph] = useState<TransactionGraph | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = session?.accessToken;
    if (!token) return;
    let cancelled = false;

    setLoading(true);
    fetchTransactionGraph(token, transactionId)
      .then((data) => {
        if (!cancelled) setGraph(data);
      })
      .catch((error) => {
        if (cancelled) return;
        setFailure(
          error instanceof ApiError ? error.message : "The trace could not be loaded.",
        );
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [session?.accessToken, transactionId]);

  if (loading) {
    return (
      <div className="space-y-2">
        <Skeleton className="h-5 w-40" />
        <Skeleton className="h-5 w-64" />
        <Skeleton className="h-5 w-52" />
      </div>
    );
  }

  if (failure) {
    return <EmptyState icon={Share2} title="The trace could not be loaded" description={failure} />;
  }

  if (!graph?.available) {
    return (
      <EmptyState
        icon={Share2}
        title="No trace is available"
        description="This deployment keeps no traceability projection, so there is nothing to draw. Everything it would show — the documents, containers, approvals and postings on this transaction — is on this page already."
      />
    );
  }

  const grouped = new Map<string, typeof graph.nodes>();
  for (const node of graph.nodes) {
    if (node.label === "TradeTransaction") continue;
    grouped.set(node.label, [...(grouped.get(node.label) ?? []), node]);
  }

  if (grouped.size === 0) {
    return (
      <EmptyState
        icon={Share2}
        title="Nothing is linked to this transaction yet"
        description="No document, container, approval or posting has been connected to it so far."
      />
    );
  }

  return (
    <div className="space-y-4">
      <p className="text-xs text-muted-foreground">
        Read from a projection that may lag the record by a few minutes. The transaction itself is
        always authoritative.
      </p>
      {[...grouped.entries()].map(([label, nodes]) => (
        <div key={label} className="space-y-1.5">
          <h3 className="text-xs font-medium uppercase tracking-widest text-muted-foreground">
            {LABELS[label] ?? label}
            <Badge variant="muted" className="ml-2 tabular-nums">
              {nodes.length}
            </Badge>
          </h3>
          <ul className="space-y-1">
            {nodes.map((node) => (
              <li key={node.id} className="truncate text-sm text-foreground">
                {node.title}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}
