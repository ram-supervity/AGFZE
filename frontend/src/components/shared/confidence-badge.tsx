import { Badge } from "@/components/ui/badge";
import { BAND_CHIP, confidenceBand, formatConfidence } from "@/lib/intake";
import { cn } from "@/lib/utils";

export interface ConfidenceBadgeProps {
  label: string;
  confidence: number | null | undefined;
  className?: string;
}

/**
 * A category or type chip tinted by its confidence, using the platform's traffic-light triad.
 * The score is always shown as a number as well as a colour: colour alone is not information.
 */
export function ConfidenceBadge({ label, confidence, className }: ConfidenceBadgeProps) {
  const band = confidenceBand(confidence);
  return (
    <Badge
      variant="outline"
      className={cn("gap-1.5 font-medium", BAND_CHIP[band], className)}
      title={`AI confidence ${formatConfidence(confidence)}`}
    >
      <span>{label}</span>
      <span aria-hidden="true" className="opacity-40">
        ·
      </span>
      <span className="tabular-nums">{formatConfidence(confidence)}</span>
    </Badge>
  );
}
