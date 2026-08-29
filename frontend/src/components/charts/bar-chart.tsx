"use client";

import Link from "next/link";
import { useId } from "react";

import { cn } from "@/lib/utils";

export interface BarDatum {
  key: string;
  label: string;
  value: number;
  href?: string | null;
  /** A second line under the label - the ageing split, the field count, whatever the row means. */
  detail?: string | null;
  /** Rendered at the end of the bar. Percentages read better with their sign attached. */
  display?: string;
}

export interface BarChartProps {
  data: BarDatum[];
  /** Fixes the axis where the natural maximum would be misleading - 100 for a percentage. */
  max?: number;
  valueLabel: string;
  className?: string;
}

/**
 * A horizontal bar chart, drawn as rows rather than as an SVG plot.
 *
 * Horizontal because these categories have long names - "Quantity variation outside tolerance"
 * does not fit under a vertical bar at any readable size - and rows because every bar here is a
 * link into the queue behind it, which wants a real, full-width hit target.
 *
 * One series, so there is no legend: the title names what is plotted. Every bar is directly
 * labelled with its value, which is also what discharges the contrast relief rule the palette
 * carries on this surface.
 */
export function BarChart({ data, max, valueLabel, className }: BarChartProps) {
  const titleId = useId();
  const ceiling = Math.max(max ?? 0, ...data.map((row) => row.value), 1);

  return (
    <ul className={cn("space-y-2.5", className)} aria-describedby={titleId}>
      <span id={titleId} className="sr-only">
        {valueLabel}
      </span>
      {data.map((row) => {
        const width = Math.max(row.value > 0 ? 1.5 : 0, (row.value / ceiling) * 100);
        const body = (
          <>
            <div className="flex items-baseline justify-between gap-3">
              <span className="min-w-0 truncate text-sm text-foreground">{row.label}</span>
              <span className="shrink-0 text-sm font-medium tabular-nums text-foreground">
                {row.display ?? row.value}
              </span>
            </div>
            <div className="mt-1.5 h-2 w-full overflow-hidden rounded-sm bg-chart-grid/45">
              <div
                className="h-full rounded-sm bg-chart-1"
                style={{ width: `${width}%` }}
                aria-hidden="true"
              />
            </div>
            {row.detail ? (
              <p className="mt-1 text-xs text-muted-foreground">{row.detail}</p>
            ) : null}
          </>
        );

        return (
          <li key={row.key}>
            {row.href ? (
              <Link
                href={row.href}
                className="block rounded-md px-2 py-1.5 transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                {body}
              </Link>
            ) : (
              <div className="px-2 py-1.5">{body}</div>
            )}
          </li>
        );
      })}
    </ul>
  );
}
