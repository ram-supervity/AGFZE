import { CheckCircle2, Clock, Loader2, TriangleAlert, UserRoundCheck } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import {
  INTEGRATION_STATUS_CHIP,
  INTEGRATION_STATUS_LABELS,
  INTEGRATION_STATUS_NOTES,
  type IntegrationJobStatus,
} from "@/lib/integrations";
import { cn } from "@/lib/utils";

export interface IntegrationStatusBadgeProps {
  status: string;
  /** True where a success came from a person confirming they finished the posting themselves. */
  completedManually?: boolean;
  className?: string;
}

const ICONS: Record<IntegrationJobStatus, typeof Clock> = {
  queued: Clock,
  processing: Loader2,
  succeeded: CheckCircle2,
  failed: TriangleAlert,
  awaiting_manual_action: UserRoundCheck,
};

/**
 * One job's state, with the two that must never look alike given different colours and icons.
 *
 * A failed job is blocked-red with a warning triangle: something went wrong and technical support
 * owns it. A job awaiting manual action is review-amber with a person: nothing went wrong, and
 * somebody has a task. Rendering them identically would be the single most misleading thing this
 * screen could do.
 *
 * A success that came from a person says so on the badge itself rather than only in a tooltip -
 * "Posted by hand" is a different fact from "Posted", and both are true things worth reading at a
 * glance.
 */
export function IntegrationStatusBadge({
  status,
  completedManually = false,
  className,
}: IntegrationStatusBadgeProps) {
  const known = status as IntegrationJobStatus;
  const Icon = ICONS[known] ?? Clock;
  const manual = completedManually && status === "succeeded";
  const label = manual ? "Posted by hand" : (INTEGRATION_STATUS_LABELS[known] ?? status);
  const note = manual
    ? "This posting was completed outside the platform by a person, who confirmed it here with the reference shown. It was not made automatically."
    : (INTEGRATION_STATUS_NOTES[known] ?? "");

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span tabIndex={0}>
          <Badge
            variant="outline"
            className={cn(
              INTEGRATION_STATUS_CHIP[known] ?? "border-border bg-muted text-muted-foreground",
              className,
            )}
          >
            <Icon
              className={cn("mr-1 h-3 w-3", status === "processing" && "animate-spin")}
              aria-hidden="true"
            />
            {label}
          </Badge>
        </span>
      </TooltipTrigger>
      <TooltipContent side="top" className="max-w-[24rem]">
        {note}
      </TooltipContent>
    </Tooltip>
  );
}
