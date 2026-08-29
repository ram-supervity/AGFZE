import { Card, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { ComingSoonBadge } from "@/components/shared/coming-soon-badge";
import type { NavItem } from "@/lib/navigation";

export function ModuleStatusCard({ item }: { item: NavItem }) {
  const Icon = item.icon;

  return (
    <Card className="h-full shadow-none">
      <CardHeader className="flex flex-row items-start gap-3 space-y-0">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
          <Icon className="h-4 w-4" aria-hidden="true" />
        </span>
        <div className="min-w-0 flex-1 space-y-1.5">
          <CardTitle className="text-base font-semibold">{item.label}</CardTitle>
          <CardDescription className="leading-relaxed">{item.summary}</CardDescription>
        </div>
        <ComingSoonBadge />
      </CardHeader>
      {item.availableFrom ? (
        <CardFooter className="border-t border-border px-6 py-3 text-xs text-muted-foreground">
          Arrives in {item.availableFrom}
        </CardFooter>
      ) : null}
    </Card>
  );
}
