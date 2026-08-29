import type { PlatformRole } from "@/lib/roles";
import { hasAnyRole } from "@/lib/roles";

/**
 * Mirrors the backend `ShipmentStatus` vocabulary. Four values, and the same four whether a
 * carrier reported them or a person typed them in - there is no `manually_tracked` state here
 * and there is deliberately not going to be one.
 */
export const SHIPMENT_STATUSES = ["on_schedule", "delayed", "arrived", "exception"] as const;
export type ShipmentStatus = (typeof SHIPMENT_STATUSES)[number];

export const SHIPMENT_STATUS_LABELS: Record<ShipmentStatus, string> = {
  on_schedule: "On schedule",
  delayed: "Delayed",
  arrived: "Arrived",
  exception: "Exception",
};

/** The platform's traffic-light triad, used here exactly as validation and confidence use it. */
export const SHIPMENT_STATUS_CHIP: Record<ShipmentStatus, string> = {
  on_schedule: "border-signal-confident/35 bg-signal-confident/10 text-signal-confident",
  delayed: "border-signal-review/35 bg-signal-review/10 text-signal-review",
  arrived: "border-signal-confident/35 bg-signal-confident/10 text-signal-confident",
  exception: "border-signal-blocked/45 bg-signal-blocked/10 text-signal-blocked",
};

/** Mirrors the backend `ShipmentMilestone` vocabulary, in the order cargo actually moves. */
export const SHIPMENT_MILESTONES = [
  "booked",
  "gate_in",
  "loaded",
  "departed",
  "in_transit",
  "transhipped",
  "arrived",
  "discharged",
  "gate_out",
  "delivered",
  "unknown",
] as const;
export type ShipmentMilestone = (typeof SHIPMENT_MILESTONES)[number];

export const SHIPMENT_MILESTONE_LABELS: Record<ShipmentMilestone, string> = {
  booked: "Booked",
  gate_in: "Gated in",
  loaded: "Loaded on board",
  departed: "Departed",
  in_transit: "In transit",
  transhipped: "Transhipped",
  arrived: "Arrived at port",
  discharged: "Discharged",
  gate_out: "Gated out",
  delivered: "Delivered",
  unknown: "Not yet reported",
};

export const BILL_OF_LADING_TYPES = ["original", "seaway", "draft"] as const;
export type BillOfLadingType = (typeof BILL_OF_LADING_TYPES)[number];

export const BILL_OF_LADING_TYPE_LABELS: Record<BillOfLadingType, string> = {
  original: "Original B/L",
  seaway: "Seaway bill",
  draft: "Draft B/L",
};

export const SHIPMENT_ISSUE_TYPES = ["quality", "damage", "detention", "other"] as const;
export type ShipmentIssueType = (typeof SHIPMENT_ISSUE_TYPES)[number];

export const SHIPMENT_ISSUE_TYPE_LABELS: Record<ShipmentIssueType, string> = {
  quality: "Quality",
  damage: "Damage",
  detention: "Detention / demurrage",
  other: "Other",
};

/**
 * The desks that may change a shipment: refresh it, correct it by hand, or log an issue against
 * it. Reading the board is open to every signed-in account. This decides only what the UI offers;
 * the API enforces the same list on every call.
 */
export const SHIPMENT_WRITE_ROLES: readonly PlatformRole[] = ["logistics_user", "admin"];

export function canManageShipments(roles: PlatformRole[]): boolean {
  return hasAnyRole(roles, SHIPMENT_WRITE_ROLES);
}

/** How the last update arrived. Provenance, shown as a caption - never as a mode. */
export function sourceLabel(source: string | null): string {
  if (!source) return "Not yet checked";
  if (source === "manual") return "Entered by hand";
  return `Reported by ${source}`;
}

/**
 * Time since anybody established where the cargo is, in the plainest words available.
 *
 * Deliberately simpler than the formal exception the same figure may eventually trigger: this is
 * an always-visible caption on every row, and it has to read at a glance.
 */
export function stalenessLabel(hours: number, lastCheckedAt: string | null): string {
  if (!lastCheckedAt) return "Never checked";
  if (hours < 1) return "Checked just now";
  if (hours < 24) return `Checked ${Math.round(hours)}h ago`;
  const days = Math.floor(hours / 24);
  return `Checked ${days} day${days === 1 ? "" : "s"} ago`;
}

export function stalenessTone(isStale: boolean, lastCheckedAt: string | null): string {
  if (!lastCheckedAt || isStale) {
    return "border-signal-review/35 bg-signal-review/10 text-signal-review";
  }
  return "border-border bg-muted text-muted-foreground";
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "-";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return parsed.toLocaleDateString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "-";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return parsed.toLocaleString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/**
 * The one sentence the dashboard says about automated tracking, and it is an honest one.
 *
 * No carrier's tracking API is specified for this platform, so no adapter ships and every
 * shipment is kept current by hand. Saying that plainly is better than leaving somebody to press
 * Refresh repeatedly and wonder why nothing ever changes.
 */
export function trackingModeNote(adaptersAvailable: number): string {
  if (adaptersAvailable > 0) {
    return `${adaptersAvailable} carrier tracking source${adaptersAvailable === 1 ? " is" : "s are"
      } connected. Shipments they do not cover are kept current by hand, on these same fields.`;
  }
  return "No carrier tracking source is connected, so every shipment here is kept current by hand. Manual entry writes the same fields, is audited the same way, and reads identically to an automatic update.";
}
