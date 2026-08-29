import { Clock } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { stalenessLabel, stalenessTone } from "@/lib/shipments";
import { cn } from "@/lib/utils";

export interface StalenessIndicatorProps {
  hours: number;
  lastCheckedAt: string | null;
  isStale: boolean;
  thresholdHours?: number;
  className?: string;
}

/**
 * How long since anybody established where this cargo is.
 *
 * Always visible, on every row, whether the shipment is fresh or not - because the useful thing
 * about this figure is that it is always there, not that it appears once something is wrong.
 *
 * Deliberately simpler than the exception the same figure may eventually trigger, and deliberately
 * separate from it. This says "checked 3 days ago". The exception queue says who owns the problem,
 * how long it has been open and what has to happen. Collapsing the two would either clutter the
 * board with case management or hide the plain fact behind a queue nobody has opened.
 */
export function StalenessIndicator({
  hours,
  lastCheckedAt,
  isStale,
  thresholdHours,
  className,
}: StalenessIndicatorProps) {
  return (
    <Badge
      variant="outline"
      className={cn(stalenessTone(isStale, lastCheckedAt), className)}
      title={
        isStale && thresholdHours
          ? `Past the configured ${thresholdHours}-hour threshold, so an exception is opened against this shipment.`
          : undefined
      }
    >
      <Clock className="mr-1 h-3 w-3" aria-hidden="true" />
      {stalenessLabel(hours, lastCheckedAt)}
    </Badge>
  );
}
