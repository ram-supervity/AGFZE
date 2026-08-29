import { Badge } from "@/components/ui/badge";
import type { ShipmentTimelineEntry } from "@/lib/api-client";
import { labelFor } from "@/lib/intake";
import {
  SHIPMENT_MILESTONE_LABELS,
  SHIPMENT_STATUS_LABELS,
  formatDateTime,
  sourceLabel,
} from "@/lib/shipments";

export interface MilestoneTimelineProps {
  entries: ShipmentTimelineEntry[];
}

/**
 * The shipment's history, derived from the audit trail rather than from a table of its own.
 *
 * There is no `shipment_milestones` table behind this and there is not going to be one. Every
 * status and milestone change is already audit-logged, and a second store of the same facts would
 * be a second thing to keep in  - with the certainty that one day this timeline and the trail
 * an auditor reads would disagree, and nobody would be able to say which was right.
 */
export function MilestoneTimeline({ entries }: MilestoneTimelineProps) {
  if (entries.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        Nothing has happened to this shipment yet beyond its creation.
      </p>
    );
  }

  return (
    <ol className="relative space-y-5 border-l border-border pl-5">
      {entries.map((entry, index) => (
        <li key={`${entry.occurred_at}-${index}`} className="relative">
          <span
            aria-hidden="true"
            className="absolute -left-[1.5625rem] top-1.5 h-2 w-2 rounded-full bg-secondary ring-4 ring-card"
          />
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
            <p className="text-sm font-medium text-foreground">{entry.summary}</p>
            {entry.milestone ? (
              <Badge variant="muted">
                {labelFor(SHIPMENT_MILESTONE_LABELS, entry.milestone)}
              </Badge>
            ) : null}
            {entry.status ? (
              <Badge variant="outline">
                {labelFor(SHIPMENT_STATUS_LABELS, entry.status)}
              </Badge>
            ) : null}
          </div>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {formatDateTime(entry.occurred_at)}
            {entry.actor_name ? ` · ${entry.actor_name}` : ""}
            {entry.source ? ` · ${sourceLabel(entry.source)}` : ""}
          </p>
          {entry.detail ? (
            <p className="mt-1 text-sm leading-relaxed text-muted-foreground">{entry.detail}</p>
          ) : null}
        </li>
      ))}
    </ol>
  );
}
