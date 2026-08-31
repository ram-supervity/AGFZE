"use client";

import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export interface ChartFrameProps {
  title: string;
  description?: string;
  /** The sentence that has to travel with the figure, where one does. Rendered, never optional. */
  disclosure?: string | null;
  actions?: ReactNode;
  emptyIcon?: LucideIcon;
  emptyMessage?: string;
  isEmpty?: boolean;
  className?: string;
  children: ReactNode;
}

/**
 * The shell every chart on this platform sits in.
 *
 * It exists so three things are impossible to forget: a chart always has a title that names what
 * it plots, a chart with nothing in it says so in words rather than drawing an empty axis, and a
 * figure that needs a disclosure carries it on screen next to the picture rather than in a
 * tooltip somebody has to find.
 */
export function ChartFrame({
  title,
  description,
  disclosure,
  actions,
  emptyIcon: EmptyIcon,
  emptyMessage,
  isEmpty = false,
  className,
  children,
}: ChartFrameProps) {
  return (
    <section
      className={cn("rounded-medium border-thin border-border bg-elevation-default p-space-300 shadow-raised", className)}
      aria-label={title}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <h3 className="text-h5 font-semibold text-foreground">{title}</h3>
          {description ? (
            <p className="text-body-xs leading-relaxed text-muted-foreground">{description}</p>
          ) : null}
        </div>
        {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
      </div>

      <div className="mt-4">
        {isEmpty ? (
          <div className="flex flex-col items-center justify-center gap-space-100 rounded-medium border-thin border-dashed border-border bg-elevation-sunken px-space-200 py-space-500 text-center">
            {EmptyIcon ? (
              <EmptyIcon className="size-icon-medium text-icon-subtle" aria-hidden="true" />
            ) : null}
            <p className="text-sm text-muted-foreground">
              {emptyMessage ?? "Nothing has happened in this period yet."}
            </p>
          </div>
        ) : (
          children
        )}
      </div>

      {disclosure ? (
        <p className="mt-4 border-t border-border pt-3 text-xs leading-relaxed text-muted-foreground">
          {disclosure}
        </p>
      ) : null}
    </section>
  );
}
