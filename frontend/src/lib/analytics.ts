import type { PlatformRole } from "@/lib/roles";
import { hasAnyRole } from "@/lib/roles";
import { TRANSACTION_STATUS_LABELS, type TransactionStatus } from "@/lib/transactions";

/**
 * Turning a figure's declared drill-through into a real URL.
 *
 * Every figure the API returns carries the screen it belongs to and the filters that reproduce
 * it. This is the one place that turns that pair into a link, so a tile, a chart segment, a
 * report row and a legend entry all navigate to exactly the same filtered query - and so a figure
 * that arrives without a target renders as text rather than as a link that goes nowhere.
 */
export const DRILL_THROUGH_ROUTES: Record<string, string> = {
  transactions: "/transactions",
  exceptions: "/exceptions",
  approvals: "/approvals",
  shipments: "/shipments",
  documents: "/documents",
  integrations: "/admin/integrations",
  reports: "/reports",
};

export interface DrillThrough {
  target?: string | null;
  filters?: Record<string, unknown> | null;
}

export function drillThroughHref(figure: DrillThrough): string | null {
  const route = figure.target ? DRILL_THROUGH_ROUTES[figure.target] : undefined;
  if (!route) return null;

  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(figure.filters ?? {})) {
    if (value === null || value === undefined || value === "") continue;
    search.set(key, String(value));
  }
  const query = search.toString();
  return query ? `${route}?${query}` : route;
}

/**
 * The five phases of the lifecycle, and which statuses sit in each.
 *
 * The API counts every status separately, and the table beside the chart shows all of them. The
 * donut groups them because ten ordered segments cannot be told apart by colour at any size - the
 * ordinal ramp behind it only carries five distinguishable . Nothing is hidden by the
 * grouping: each arc names the statuses inside it and drills through to them.
 */
export const LIFECYCLE_PHASES = [
  {
    key: "intake",
    label: "Intake",
    statuses: ["received", "classified", "extraction_pending", "extracted"],
  },
  { key: "preparation", label: "In preparation", statuses: ["matched", "validation_pending"] },
  { key: "decision", label: "Awaiting a decision", statuses: ["approval_pending"] },
  { key: "posting", label: "Approved, posting", statuses: ["approved", "integration_pending"] },
  { key: "committed", label: "Committed", statuses: ["committed"] },
] as const satisfies readonly {
  key: string;
  label: string;
  statuses: readonly TransactionStatus[];
}[];

export type LifecyclePhase = (typeof LIFECYCLE_PHASES)[number]["key"];

export interface StatusFigure {
  key: string;
  label: string;
  value: number | null;
  target?: string | null;
  filters?: Record<string, unknown> | null;
}

export interface PhaseSlice {
  key: string;
  label: string;
  value: number;
  statuses: { status: string; label: string; value: number }[];
  href: string | null;
}

export function statusOf(figure: { key: string }): string {
  return figure.key.split(".").pop() ?? figure.key;
}

export function phaseSlices(figures: StatusFigure[]): PhaseSlice[] {
  const byStatus = new Map(figures.map((figure) => [statusOf(figure), figure]));

  return LIFECYCLE_PHASES.map((phase) => {
    const statuses = phase.statuses.map((status) => ({
      status,
      label: TRANSACTION_STATUS_LABELS[status] ?? status,
      value: Number(byStatus.get(status)?.value ?? 0),
    }));
    return {
      key: phase.key,
      label: phase.label,
      value: statuses.reduce((total, row) => total + row.value, 0),
      statuses,
      // One phase covers several statuses, so the link carries the phase rather than pretending
      // to be a single-status filter it is not.
      href: drillThroughHref({
        target: "transactions",
        filters: phase.statuses.length === 1 ? { status: phase.statuses[0] } : {},
      }),
    };
  });
}

/** Which roles get the Analytics and Reports screens in the sidebar. */
export const ANALYTICS_ROLES: readonly PlatformRole[] = [
  "approver_hod",
  "finance_user",
  "admin",
  "auditor",
];

/** Who may ask for a new report. Enforced by the API on every call; this only hides the link. */
export const REPORT_GENERATOR_ROLES: readonly PlatformRole[] = ["admin", "approver_hod"];

export function canGenerateReports(roles: PlatformRole[]): boolean {
  return hasAnyRole(roles, REPORT_GENERATOR_ROLES);
}

export const REPORT_TYPES = ["daily", "monthly", "adhoc"] as const;
export type ReportType = (typeof REPORT_TYPES)[number];

export const REPORT_TYPE_LABELS: Record<ReportType, string> = {
  daily: "Daily",
  monthly: "Monthly",
  adhoc: "Ad-hoc",
};

export const REPORT_TYPE_CHIP: Record<ReportType, string> = {
  daily: "border-border bg-muted text-muted-foreground",
  monthly: "border-secondary/35 bg-secondary/10 text-secondary",
  adhoc: "border-accent/35 bg-accent/10 text-accent",
};

export const REPORT_FORMATS = ["pdf", "xlsx"] as const;
export type ReportFormat = (typeof REPORT_FORMATS)[number];

export const REPORT_FORMAT_LABELS: Record<ReportFormat, string> = {
  pdf: "PDF",
  xlsx: "Excel",
};

export const REPORT_STREAMS = ["both", "scrap", "fa"] as const;

export const REPORT_STREAM_LABELS: Record<string, string> = {
  both: "Both streams",
  scrap: "Scrap",
  fa: "FA",
};

/** How each dashboard panel is titled, and the order each desk sees them in. */
export const PANEL_LABELS: Record<string, string> = {
  transactions: "Transactions",
  exceptions: "Exceptions",
  approvals: "Approvals",
  shipments: "Cargo",
  integrations: "Downstream postings",
  automation: "Automation",
};

const PANEL_ORDER = ["transactions", "exceptions", "approvals", "shipments", "integrations"];

/**
 * The panel this account leads with, first; everything else in its usual order.
 *
 * Emphasis, never exclusion. A Logistics User opens on cargo and still sees the exception queue
 * underneath it; what any of those panels may contain was already decided by the query that
 * filled it, server-side.
 */
export function orderedPanels(emphasis: string): string[] {
  const rest = PANEL_ORDER.filter((panel) => panel !== emphasis);
  return PANEL_ORDER.includes(emphasis) ? [emphasis, ...rest] : PANEL_ORDER;
}

const NUMBER = new Intl.NumberFormat("en-GB");
const DECIMAL = new Intl.NumberFormat("en-GB", { maximumFractionDigits: 1 });

export function formatFigure(value: number | null | undefined, unit = "count"): string {
  if (value === null || value === undefined) return "—";
  if (unit === "percent") return `${DECIMAL.format(value)}%`;
  if (unit === "hours") return `${DECIMAL.format(value)}h`;
  return NUMBER.format(value);
}

export function formatHours(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  if (value < 48) return `${DECIMAL.format(value)}h`;
  return `${DECIMAL.format(value / 24)}d`;
}

const DATE_TIME = new Intl.DateTimeFormat("en-GB", {
  dateStyle: "medium",
  timeStyle: "short",
  timeZone: "UTC",
});

const DATE_ONLY = new Intl.DateTimeFormat("en-GB", { dateStyle: "medium", timeZone: "UTC" });

export function formatMoment(value: string | null | undefined): string {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "—" : `${DATE_TIME.format(parsed)} UTC`;
}

export function formatDay(value: string | null | undefined): string {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "—" : DATE_ONLY.format(parsed);
}

/** `2026-08-28`, the form both the date inputs and the API query parameters use. */
export function isoDate(value: Date): string {
  return value.toISOString().slice(0, 10);
}

export function daysAgo(days: number): string {
  const moment = new Date();
  moment.setUTCDate(moment.getUTCDate() - days);
  return isoDate(moment);
}

/**
 * How stale the figures on screen are, said plainly.
 *
 * The API caches an aggregate for a few tens of seconds and returns the age of what it served.
 * Showing it costs a line of text and means nobody has to wonder whether a screen is live.
 */
export function freshnessNote(ageSeconds: number, ttlSeconds: number): string {
  if (ageSeconds <= 0) {
    return "Computed just now, directly from the transaction records.";
  }
  const rounded = Math.round(ageSeconds);
  return `Computed ${rounded} second${rounded === 1 ? "" : "s"} ago and cached for up to ${ttlSeconds}s.`;
}

/** Chart data with nothing in it is a real state, and it reads differently from an error. */
export function isEmptySeries(values: (number | null | undefined)[]): boolean {
  return values.every((value) => !value);
}

export function toCsv(columns: { key: string; label: string }[], rows: Record<string, unknown>[]): string {
  const escape = (value: unknown): string => {
    if (value === null || value === undefined) return "";
    const rendered = String(value);
    return /[",\n]/.test(rendered) ? `"${rendered.replace(/"/g, '""')}"` : rendered;
  };
  return [
    columns.map((column) => escape(column.label)).join(","),
    ...rows.map((row) => columns.map((column) => escape(row[column.key])).join(",")),
  ].join("\n");
}
