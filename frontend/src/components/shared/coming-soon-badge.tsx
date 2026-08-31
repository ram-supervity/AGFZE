import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

export function ComingSoonBadge({ className }: { className?: string }) {
  return (
    <Badge
      variant="muted"
      className={cn("shrink-0 px-space-075 py-0 text-body-xs uppercase tracking-[0.12em]", className)}
    >
      Coming soon
    </Badge>
  );
}
