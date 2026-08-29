import type { PlatformRole } from "@/lib/roles";
import { hasAnyRole } from "@/lib/roles";

/** Mirrors the backend `IntegrationTargetSystem` vocabulary. Three systems, and only three. */
export const INTEGRATION_TARGETS = ["tracker", "sap", "dms"] as const;
export type IntegrationTarget = (typeof INTEGRATION_TARGETS)[number];

export const INTEGRATION_TARGET_LABELS: Record<IntegrationTarget, string> = {
  tracker: "Excel tracker",
  sap: "SAP",
  dms: "Document management",
};

/**
 * Mirrors the backend `IntegrationJobStatus` vocabulary, including its fifth value.
 *
 * `awaiting_manual_action` is not a variant of failure and must never be presented as one. It
 * means the platform has done everything it can - the payload is prepared, the pack is compiled -
 * and a person has to finish the posting in a system this platform cannot reach.
 */
export const INTEGRATION_JOB_STATUSES = [
  "queued",
  "processing",
  "succeeded",
  "failed",
  "awaiting_manual_action",
] as const;
export type IntegrationJobStatus = (typeof INTEGRATION_JOB_STATUSES)[number];

export const INTEGRATION_STATUS_LABELS: Record<IntegrationJobStatus, string> = {
  queued: "Queued",
  processing: "In progress",
  succeeded: "Posted",
  failed: "Failed",
  awaiting_manual_action: "Waiting on a person",
};

/**
 * The platform's traffic-light triad, with the two states that must never look alike given
 * deliberately different colours: a failure is blocked-red, a job waiting on somebody is
 * review-amber. They mean different things and call for different actions.
 */
export const INTEGRATION_STATUS_CHIP: Record<IntegrationJobStatus, string> = {
  queued: "border-border bg-muted text-muted-foreground",
  processing: "border-border bg-muted text-muted-foreground",
  succeeded: "border-signal-confident/35 bg-signal-confident/10 text-signal-confident",
  failed: "border-signal-blocked/45 bg-signal-blocked/10 text-signal-blocked",
  awaiting_manual_action: "border-signal-review/35 bg-signal-review/10 text-signal-review",
};

/** What each state actually means, in the words the screen shows on hover. */
export const INTEGRATION_STATUS_NOTES: Record<IntegrationJobStatus, string> = {
  queued: "Not attempted yet, or waiting out the backoff before its next automatic attempt.",
  processing: "An attempt is running now.",
  succeeded: "The receiving system holds this posting, and gave back the reference shown.",
  failed:
    "Every automatic attempt has been used up and the posting was not accepted. An exception is open against it for technical support.",
  awaiting_manual_action:
    "Not a failure and not a success. This deployment has no automated route to that system, so the platform has prepared everything needed and a person completes the posting.",
};

/** The desks that may act on an integration job. Reading one is open to any signed-in account. */
export const INTEGRATION_WRITE_ROLES: readonly PlatformRole[] = ["admin"];

export function canManageIntegrations(roles: PlatformRole[]): boolean {
  return hasAnyRole(roles, INTEGRATION_WRITE_ROLES);
}

/** Retry is for a genuine automated failure, and for nothing else. */
export function canRetry(status: string): boolean {
  return status === "failed";
}

/** Manual completion resolves the state retry cannot touch. Never the same button. */
export function canCompleteManually(status: string): boolean {
  return status === "awaiting_manual_action";
}

/**
 * How a succeeded job describes itself.
 *
 * A manual completion always says so. This is the single most important label in the module: a
 * posting a person made by hand must never be readable as one the platform made.
 */
export function successProvenance(completedManually: boolean, byName: string | null): string {
  if (!completedManually) return "Posted automatically by the platform";
  return byName
    ? `Completed by hand and confirmed by ${byName}`
    : "Completed by hand and confirmed by an administrator";
}

/** Attempts used against the ceiling, for the badge on every row. */
export function attemptLabel(attempts: number, maxAttempts: number): string {
  if (attempts === 0) return "No attempts yet";
  return `Attempt ${attempts}${maxAttempts ? ` of ${maxAttempts}` : ""}`;
}

/**
 * Why a job is waiting, said without apology.
 *
 * A target this deployment cannot post to automatically is a configuration fact, not a fault, and
 * the monitor says so rather than leaving an administrator to wonder what broke.
 */
export function targetAvailabilityNote(target: string, configured: boolean): string {
  const label = INTEGRATION_TARGET_LABELS[target as IntegrationTarget] ?? target;
  if (configured) {
    return `${label} is configured on this deployment, so jobs are posted automatically.`;
  }
  return `${label} has no endpoint configured on this deployment. Its jobs are prepared in full and completed by a person — that is the expected outcome here, not a failure.`;
}

/** The reason a manual completion demands, held to the same length the API enforces. */
export const MIN_MANUAL_NOTE = 10;
