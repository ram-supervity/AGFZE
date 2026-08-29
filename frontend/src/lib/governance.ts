import type { PlatformRole } from "@/lib/roles";
import { hasAnyRole } from "@/lib/roles";

/**
 * The ten exception categories of the governing matrix, in the queue's tab order.
 *
 * All ten are listed, including the three nothing can raise yet. The server is what decides
 * whether a category is live - it sends `triggerable` and, where it is false, the reason - so
 * this list never has to be edited when a later step brings one of them to life.
 */
export const EXCEPTION_CATEGORIES = [
  "missing_mandatory_document",
  "mismatched_container_number",
  "invoice_amount_outside_tolerance",
  "quantity_variation_outside_tolerance",
  "unmatched_reference",
  "low_confidence",
  "duplicate_document",
  "shipment_status_unavailable",
  "approval_not_received",
  "integration_failure",
] as const;

export type ExceptionCategory = (typeof EXCEPTION_CATEGORIES)[number];

export const EXCEPTION_PRIORITIES = ["low", "medium", "high"] as const;
export type ExceptionPriority = (typeof EXCEPTION_PRIORITIES)[number];

export const PRIORITY_LABELS: Record<ExceptionPriority, string> = {
  low: "Low",
  medium: "Medium",
  high: "High",
};

export const PRIORITY_CHIP: Record<ExceptionPriority, string> = {
  low: "border-border bg-muted text-muted-foreground",
  medium: "border-signal-review/35 bg-signal-review/10 text-signal-review",
  high: "border-signal-blocked/35 bg-signal-blocked/10 text-signal-blocked",
};

export const APPROVAL_DECISIONS = [
  "pending",
  "approved",
  "rejected",
  "changes_requested",
] as const;

export type ApprovalDecision = (typeof APPROVAL_DECISIONS)[number];

export const DECISION_LABELS: Record<ApprovalDecision, string> = {
  pending: "Waiting on a decision",
  approved: "Approved",
  rejected: "Rejected",
  changes_requested: "Changes requested",
};

export const DECISION_CHIP: Record<ApprovalDecision, string> = {
  pending: "border-signal-review/35 bg-signal-review/10 text-signal-review",
  approved: "border-signal-confident/35 bg-signal-confident/10 text-signal-confident",
  rejected: "border-signal-blocked/35 bg-signal-blocked/10 text-signal-blocked",
  changes_requested: "border-signal-review/35 bg-signal-review/10 text-signal-review",
};

/** The two decisions that send a transaction back, and therefore need a stated reason. */
export const DECISIONS_NEEDING_REASON: readonly ApprovalDecision[] = [
  "rejected",
  "changes_requested",
];

export const MIN_DECISION_REASON = 10;
export const MIN_RESOLUTION_NOTE = 10;

export const RISK_LABELS: Record<string, string> = {
  clean: "Clean",
  watch: "Watch",
  elevated: "Elevated",
};

export const RISK_CHIP: Record<string, string> = {
  clean: "border-signal-confident/35 bg-signal-confident/10 text-signal-confident",
  watch: "border-signal-review/35 bg-signal-review/10 text-signal-review",
  elevated: "border-signal-blocked/35 bg-signal-blocked/10 text-signal-blocked",
};

/**
 * Only the HOD decides. Every other role reads the queue and the decision screen, and the API
 * refuses the write regardless of what this returns.
 */
export const APPROVAL_DECISION_ROLES: readonly PlatformRole[] = ["approver_hod", "admin"];

export function canDecideApprovals(roles: PlatformRole[]): boolean {
  return hasAnyRole(roles, APPROVAL_DECISION_ROLES);
}

/** The desks that may act on an exception at all; the category narrows it further, server-side. */
export const EXCEPTION_WORK_ROLES: readonly PlatformRole[] = [
  "purchase_user",
  "sales_user",
  "fa_user",
  "logistics_user",
  "finance_user",
  "admin",
];

export function canWorkExceptions(roles: PlatformRole[]): boolean {
  return hasAnyRole(roles, EXCEPTION_WORK_ROLES);
}

/**
 * The ageing colour ramp, computed from the hours the API reports against the threshold it also
 * reports. Nothing here hardcodes a number of hours: change the configured threshold and the ramp
 * moves with it.
 */
export type AgeBand = "fresh" | "warm" | "breached";

export function ageBand(hours: number, thresholdHours: number): AgeBand {
  if (thresholdHours <= 0) return "fresh";
  if (hours >= thresholdHours) return "breached";
  if (hours >= thresholdHours / 2) return "warm";
  return "fresh";
}

export const AGE_CHIP: Record<AgeBand, string> = {
  fresh: "border-border bg-muted text-muted-foreground",
  warm: "border-signal-review/35 bg-signal-review/10 text-signal-review",
  breached: "border-signal-blocked/35 bg-signal-blocked/10 text-signal-blocked",
};

/** Whole hours below a day, then whole days. An exception's age is read at a glance or not at all. */
export function formatAgeHours(hours: number): string {
  if (hours < 1) return "Under an hour";
  if (hours < 24) return `${Math.floor(hours)} hour${Math.floor(hours) === 1 ? "" : "s"}`;
  const days = Math.floor(hours / 24);
  return `${days} day${days === 1 ? "" : "s"}`;
}

export function ownerLabel(role: string): string {
  return role
    .split("_")
    .map((part) => (part === "hod" ? "HOD" : part.charAt(0).toUpperCase() + part.slice(1)))
    .join(" ");
}
