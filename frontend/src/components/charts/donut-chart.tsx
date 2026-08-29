"use client";

import Link from "next/link";
import { useId, useState } from "react";

import { cn } from "@/lib/utils";

export interface DonutSlice {
  key: string;
  label: string;
  value: number;
  /** Where this arc drills through to. Null renders the row as text rather than a dead link. */
  href?: string | null;
  detail?: string | null;
}

export interface DonutChartProps {
  slices: DonutSlice[];
  totalLabel: string;
  className?: string;
}

const SIZE = 168;
const RADIUS = 68;
const STROKE = 22;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;
// A 2px gap of surface between adjacent arcs, so two neighbouring steps of one ramp stay
// separable at a glance and for a reader who cannot tell the two steps apart by colour.
const GAP = 2;

// The ordinal ramp, in order. These are lifecycle phases, not unrelated categories: earliest is
// lightest and the last is darkest, and the sequence is the encoding. Five steps because five is
// how many steps of one hue stay distinguishable against this surface - the table underneath
// carries every individual status.
const PHASE_TOKENS = [
  "hsl(var(--chart-phase-1))",
  "hsl(var(--chart-phase-2))",
  "hsl(var(--chart-phase-3))",
  "hsl(var(--chart-phase-4))",
  "hsl(var(--chart-phase-5))",
];

export function DonutChart({ slices, totalLabel, className }: DonutChartProps) {
  const titleId = useId();
  const [active, setActive] = useState<string | null>(null);

  const total = slices.reduce((sum, slice) => sum + slice.value, 0);
  const drawable = slices.filter((slice) => slice.value > 0);

  let offset = 0;
  const arcs = drawable.map((slice, index) => {
    const fraction = slice.value / total;
    const length = Math.max(0, CIRCUMFERENCE * fraction - GAP);
    const arc = {
      ...slice,
      colour: PHASE_TOKENS[slices.findIndex((row) => row.key === slice.key) % PHASE_TOKENS.length],
      dash: `${length} ${CIRCUMFERENCE - length}`,
      rotation: (offset / CIRCUMFERENCE) * 360 - 90,
      percent: fraction * 100,
      index,
    };
    offset += CIRCUMFERENCE * fraction;
    return arc;
  });

  return (
    <div className={cn("flex flex-col gap-5 sm:flex-row sm:items-center", className)}>
      <div className="relative shrink-0 self-center">
        <svg
          width={SIZE}
          height={SIZE}
          viewBox={`0 0 ${SIZE} ${SIZE}`}
          role="img"
          aria-labelledby={titleId}
        >
          <title id={titleId}>{`${totalLabel}: ${total}`}</title>
          <circle
            cx={SIZE / 2}
            cy={SIZE / 2}
            r={RADIUS}
            fill="none"
            stroke="hsl(var(--chart-grid))"
            strokeWidth={STROKE}
            opacity={total === 0 ? 1 : 0.35}
          />
          {arcs.map((arc) => (
            <circle
              key={arc.key}
              cx={SIZE / 2}
              cy={SIZE / 2}
              r={RADIUS}
              fill="none"
              stroke={arc.colour}
              strokeWidth={active === arc.key ? STROKE + 4 : STROKE}
              strokeDasharray={arc.dash}
              strokeDashoffset={0}
              transform={`rotate(${arc.rotation} ${SIZE / 2} ${SIZE / 2})`}
              className="transition-[stroke-width]"
              onMouseEnter={() => setActive(arc.key)}
              onMouseLeave={() => setActive(null)}
            />
          ))}
        </svg>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-2xl font-semibold tabular-nums text-foreground">{total}</span>
          <span className="max-w-[7rem] text-center text-[0.7rem] leading-tight text-muted-foreground">
            {totalLabel}
          </span>
        </div>
      </div>

      {/* The legend is also the table view: every phase is named and numbered in text, so identity
          never depends on telling two steps of one ramp apart. Width-capped so the label and its
          count stay near each other - a name on the far left and a number on the far right of a
          wide card is two columns nobody can read across. */}
      <ul className="w-full min-w-0 max-w-sm space-y-1.5">
        {slices.map((slice, index) => {
          const swatch = PHASE_TOKENS[index % PHASE_TOKENS.length];
          const share = total > 0 ? Math.round((slice.value / total) * 100) : 0;
          const body = (
            <>
              <span
                aria-hidden="true"
                className="mt-1 h-2.5 w-2.5 shrink-0 rounded-sm"
                style={{ backgroundColor: swatch }}
              />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm text-foreground">{slice.label}</span>
                {slice.detail ? (
                  <span className="block truncate text-xs text-muted-foreground">
                    {slice.detail}
                  </span>
                ) : null}
              </span>
              <span className="shrink-0 text-sm tabular-nums text-foreground">{slice.value}</span>
              <span className="w-9 shrink-0 text-right text-xs tabular-nums text-muted-foreground">
                {share}%
              </span>
            </>
          );

          return (
            <li key={slice.key}>
              {slice.href ? (
                <Link
                  href={slice.href}
                  onMouseEnter={() => setActive(slice.key)}
                  onMouseLeave={() => setActive(null)}
                  className={cn(
                    "flex items-start gap-2 rounded-md px-2 py-1 transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    active === slice.key && "bg-muted",
                  )}
                >
                  {body}
                </Link>
              ) : (
                <span className="flex items-start gap-2 px-2 py-1">{body}</span>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
