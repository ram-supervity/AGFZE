"use client";

import { useId, useState } from "react";

import { useElementWidth } from "@/hooks/use-element-width";
import { cn } from "@/lib/utils";

export interface LineSeries {
  key: string;
  label: string;
  /** Null is a genuine gap - nothing was approved that day - and is drawn as a break, not a zero. */
  points: (number | null)[];
  unit?: string;
  /**
   * Dash this series.
   *
   * Not decoration. Two measures of the same thing coincide exactly whenever there is one data
   * point behind them - mean and median turnaround are identical on any day with a single
   * approval, which is most days - and two solid lines drawn over each other show only the one
   * painted last. A dashed line over a solid one stays visible through the overlap, and stays
   * legible for a reader who cannot separate the two colours.
   */
  dashed?: boolean;
}

export interface LineChartProps {
  labels: string[];
  series: LineSeries[];
  valueLabel: string;
  className?: string;
}

// The width drawn at before the container has been measured, and on a server render.
const FALLBACK_WIDTH = 640;
const HEIGHT = 200;
const PAD_LEFT = 44;
const PAD_RIGHT = 12;
const PAD_TOP = 12;
const PAD_BOTTOM = 26;

// Categorical slots one and two, in the fixed order the palette declares. Two series at most on
// this chart; a third measure gets its own chart rather than a third line and never a second axis.
const SERIES_TOKENS = ["hsl(var(--chart-1))", "hsl(var(--chart-2))"];

function niceCeiling(value: number): number {
  if (value <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  return Math.ceil(value / magnitude) * magnitude;
}

export function LineChart({ labels, series, valueLabel, className }: LineChartProps) {
  const titleId = useId();
  const [hover, setHover] = useState<number | null>(null);
  // Drawn at the card's real pixel width rather than stretched from a fixed box, so the same
  // chart reads identically in a half-width dashboard panel and across the analytics page.
  const [frame, width] = useElementWidth<HTMLDivElement>(FALLBACK_WIDTH);

  const values = series
    .flatMap((row) => row.points)
    .filter((value): value is number => value !== null);
  const ceiling = niceCeiling(Math.max(...values, 0));
  const plotWidth = width - PAD_LEFT - PAD_RIGHT;
  const plotHeight = HEIGHT - PAD_TOP - PAD_BOTTOM;

  const x = (index: number) =>
    PAD_LEFT + (labels.length <= 1 ? plotWidth / 2 : (index / (labels.length - 1)) * plotWidth);
  const y = (value: number) => PAD_TOP + plotHeight - (value / ceiling) * plotHeight;

  const ticks = [0, 0.5, 1].map((fraction) => ({
    value: ceiling * fraction,
    y: PAD_TOP + plotHeight - fraction * plotHeight,
  }));

  // As many date labels as fit without colliding, from the width actually available.
  const stride = Math.max(1, Math.ceil(labels.length / Math.max(2, Math.floor(plotWidth / 90))));

  return (
    <div ref={frame} className={cn("space-y-3", className)}>
      <ul className="flex flex-wrap items-center gap-x-4 gap-y-1">
        {series.map((row, index) => (
          <li key={row.key} className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <svg width="18" height="6" aria-hidden="true" className="shrink-0">
              <line
                x1="0"
                y1="3"
                x2="18"
                y2="3"
                stroke={SERIES_TOKENS[index % SERIES_TOKENS.length]}
                strokeWidth={2}
                strokeLinecap="round"
                strokeDasharray={row.dashed ? "4 3" : undefined}
              />
            </svg>
            {row.label}
          </li>
        ))}
      </ul>

      <svg
        width={width}
        height={HEIGHT}
        viewBox={`0 0 ${width} ${HEIGHT}`}
        // Centred so the pre-measurement render - a server render, or a browser without a
        // ResizeObserver - sits in the middle of its card rather than against one edge.
        className="mx-auto block"
        role="img"
        aria-labelledby={titleId}
        onMouseLeave={() => setHover(null)}
      >
        <title id={titleId}>{valueLabel}</title>

        {ticks.map((tick) => (
          <g key={tick.value}>
            <line
              x1={PAD_LEFT}
              x2={width - PAD_RIGHT}
              y1={tick.y}
              y2={tick.y}
              stroke="hsl(var(--chart-grid))"
              strokeWidth={1}
            />
            <text
              x={PAD_LEFT - 8}
              y={tick.y + 3}
              textAnchor="end"
              className="fill-muted-foreground text-[9px] tabular-nums"
            >
              {Math.round(tick.value)}
            </text>
          </g>
        ))}

        {labels.map((label, index) =>
          index % stride === 0 ? (
            <text
              key={label}
              x={x(index)}
              y={HEIGHT - 8}
              textAnchor="middle"
              className="fill-muted-foreground text-[9px]"
            >
              {label}
            </text>
          ) : null,
        )}

        {series.map((row, seriesIndex) => {
          const colour = SERIES_TOKENS[seriesIndex % SERIES_TOKENS.length];
          // A null point breaks the path rather than being drawn through: a day with no approvals
          // has no turnaround, and joining across it would draw a measurement nobody took.
          const segments: string[] = [];
          let current: string[] = [];
          row.points.forEach((value, index) => {
            if (value === null) {
              if (current.length > 1) segments.push(current.join(" "));
              current = [];
              return;
            }
            current.push(`${current.length === 0 ? "M" : "L"}${x(index)},${y(value)}`);
          });
          if (current.length > 1) segments.push(current.join(" "));

          return (
            <g key={row.key}>
              {segments.map((path) => (
                <path
                  key={path.slice(0, 24)}
                  d={path}
                  fill="none"
                  stroke={colour}
                  strokeWidth={2}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeDasharray={row.dashed ? "5 4" : undefined}
                />
              ))}
              {row.points.map((value, index) =>
                value === null ? null : (
                  <circle
                    key={`${row.key}-${index}`}
                    cx={x(index)}
                    cy={y(value)}
                    r={hover === index ? 5 : 3}
                    fill={colour}
                    // A surface ring, so an overlapping point on the second series still reads
                    // as its own mark rather than merging into the first.
                    stroke="hsl(var(--card))"
                    strokeWidth={2}
                  />
                ),
              )}
            </g>
          );
        })}

        {labels.map((label, index) => (
          <rect
            key={`hit-${label}`}
            x={x(index) - plotWidth / Math.max(1, labels.length * 2)}
            y={PAD_TOP}
            width={plotWidth / Math.max(1, labels.length)}
            height={plotHeight}
            fill="transparent"
            onMouseEnter={() => setHover(index)}
          />
        ))}

        {hover !== null ? (
          <line
            x1={x(hover)}
            x2={x(hover)}
            y1={PAD_TOP}
            y2={PAD_TOP + plotHeight}
            stroke="hsl(var(--chart-grid))"
            strokeWidth={1}
          />
        ) : null}
      </svg>

      <p className="min-h-[1.25rem] text-xs text-muted-foreground" aria-live="polite">
        {hover === null
          ? `${labels.length} point${labels.length === 1 ? "" : "s"} · ${valueLabel}`
          : `${labels[hover]} — ${series
              .map(
                (row) =>
                  `${row.label}: ${
                    row.points[hover] === null
                      ? "no data"
                      : `${row.points[hover]}${row.unit ?? ""}`
                  }`,
              )
              .join(" · ")}`}
      </p>
    </div>
  );
}
