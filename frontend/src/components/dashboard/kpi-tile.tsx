import { ArrowUpRight } from "lucide-react";
import Link from "next/link";

import { drillThroughHref, formatFigure } from "@/lib/analytics";
import type { Figure } from "@/lib/api-client";
import { cn } from "@/lib/utils";

export interface KpiTileProps {
  figure: Figure;
  className?: string;
}

/**
 * One number on the dashboard, and the way into the rows behind it.
 *
 * A tile whose figure declares no drill-through renders as a plain card rather than as a link
 * that goes nowhere. A tile whose figure is zero renders the zero: an empty queue and an absent
 * tile look identical, and only one of them means anything.
 */
export function KpiTile({ figure, className }: KpiTileProps) {
  const href = drillThroughHref(figure);

  const body = (
    <>
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs font-medium uppercase tracking-widest text-muted-foreground">
          {figure.label}
        </p>
        {href ? (
          <ArrowUpRight
            className="h-3.5 w-3.5 shrink-0 text-muted-foreground transition-colors group-hover:text-accent"
            aria-hidden="true"
          />
        ) : null}
      </div>
      <p className="mt-2 text-3xl font-semibold tabular-nums tracking-tight text-foreground">
        {formatFigure(figure.value, figure.unit)}
      </p>
      {figure.note ? (
        <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">{figure.note}</p>
      ) : null}
    </>
  );

  if (!href) {
    return (
      <div className={cn("rounded-lg border border-border bg-card p-4", className)}>{body}</div>
    );
  }

  return (
    <Link
      href={href}
      className={cn(
        "group block rounded-lg border border-border bg-card p-4 transition-colors hover:border-accent/45 hover:bg-surface focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        className,
      )}
    >
      {body}
    </Link>
  );
}
