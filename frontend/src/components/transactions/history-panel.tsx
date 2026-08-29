"use client";

import type { StatusEvent, TransactionDetail } from "@/lib/api-client";
import { TRANSACTION_STATUS_LABELS, type TransactionStatus } from "@/lib/transactions";
import { labelFor } from "@/lib/intake";
import { formatDateTime } from "@/lib/utils";

function detailFor(event: StatusEvent): string | null {
  const metadata = event.metadata ?? {};
  if (Array.isArray(metadata.changes)) {
    const names = metadata.changes
      .map((change) => (change as { field?: string }).field)
      .filter((name): name is string => Boolean(name));
    return names.length > 0 ? `Fields: ${names.join(", ")}` : null;
  }
  if (typeof metadata.rule_id === "string") {
    return `${metadata.rule_id}${
      typeof metadata.reason === "string" ? ` — ${metadata.reason}` : ""
    }`;
  }
  if (Array.isArray(metadata.blocking_rules)) {
    const ids = metadata.blocking_rules
      .map((rule) => (rule as { rule_id?: string }).rule_id)
      .filter((id): id is string => Boolean(id));
    return ids.length > 0 ? `Blocked by ${ids.join(", ")}` : null;
  }
  if (typeof metadata.method === "string") return metadata.method.replace(/_/g, " ");
  if (typeof metadata.origin === "string") return metadata.origin.replace(/_/g, " ");
  return null;
}

/**
 * The real timeline, derived from the append-only audit trail rather than from a status column.
 * Nothing is inferred: every row here is an event somebody or something actually recorded.
 */
export function HistoryPanel({ detail }: { detail: TransactionDetail }) {
  if (detail.history.length === 0) {
    return (
      <p className="rounded-md border border-dashed border-border bg-surface px-4 py-8 text-center text-sm text-muted-foreground">
        Nothing has been recorded against this transaction yet.
      </p>
    );
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        Currently{" "}
        <span className="font-medium text-foreground">
          {labelFor(TRANSACTION_STATUS_LABELS, detail.status as TransactionStatus)}
        </span>
        {detail.submitted_at
          ? ` since ${formatDateTime(detail.submitted_at)}, submitted by ${
              detail.submitted_by_name ?? "a platform user"
            }.`
          : "."}
      </p>

      <ol className="space-y-0">
        {detail.history.map((event, index) => {
          const extra = detailFor(event);
          return (
            <li key={`${event.occurred_at}-${index}`} className="flex gap-3">
              <div className="flex flex-col items-center">
                <span
                  aria-hidden="true"
                  className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-secondary"
                />
                {index < detail.history.length - 1 ? (
                  <span aria-hidden="true" className="w-px flex-1 bg-border" />
                ) : null}
              </div>
              <div className="min-w-0 flex-1 pb-4">
                <p className="text-sm text-foreground">{event.summary}</p>
                <p className="text-xs text-muted-foreground">
                  {formatDateTime(event.occurred_at)}
                  {event.actor_name ? ` · ${event.actor_name}` : " · System"}
                </p>
                {extra ? (
                  <p className="mt-0.5 break-words text-xs text-muted-foreground">{extra}</p>
                ) : null}
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
