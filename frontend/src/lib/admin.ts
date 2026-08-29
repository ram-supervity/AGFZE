import type { PlatformRole } from "@/lib/roles";
import { hasAnyRole } from "@/lib/roles";

/**
 * The administration areas that exist, and the only ones that exist.
 *
 * Two other things this platform stores are technically configuration and deliberately have no
 * screen: the tracker/SAP/DMS endpoints are infrastructure and change by deployment, and the
 * rule-to-exception-category mapping is seed data that decides which desk owns which failure.
 * Neither is listed here, and adding one would be a change to what this platform lets somebody
 * edit at runtime, not a cosmetic addition to a menu.
 *
 * Report *distribution* is the one piece of configuration whose effect is that somebody is
 * contacted, which is exactly why it belongs on a screen with a mandatory reason and an audit
 * trail rather than in an environment variable nobody can review. Report *templates* are the
 * newest entry: the governing material asks for the exact report structures to be confirmed with
 * AGFZE, and a conversation is not a release.
 */
export const ADMIN_AREAS = [
  {
    key: "users",
    label: "Users & roles",
    href: "/admin/users",
    summary:
      "Every account mirrored from the identity provider, with the roles it holds. Editing a role writes to Keycloak first and mirrors here only once Keycloak confirms it.",
  },
  {
    key: "rules",
    label: "Rules & thresholds",
    href: "/admin/rules",
    summary:
      "Every tolerance, limit and threshold the rule engine compares against, editable with a stated reason and no deployment.",
  },
  {
    key: "document-types",
    label: "Document types",
    href: "/admin/document-types",
    summary:
      "The field list extraction reads for each document type, and the mandatory-document checklist each territory's pack is measured against.",
  },
  {
    key: "audit",
    label: "Audit explorer",
    href: "/admin/audit",
    summary:
      "Every governance event recorded since the platform's first day, filterable and exportable. Read-only, always — the trail is append-only.",
  },
  {
    key: "report-distribution",
    label: "Report distribution",
    href: "/admin/report-distribution",
    summary:
      "Which roles receive the daily and monthly reports, and on which channel. Empty until somebody configures it, and a report reaches nobody until they do.",
  },
  {
    key: "report-templates",
    label: "Report templates",
    href: "/admin/report-templates",
    summary:
      "Which sections each report carries, in what order, and which figures go in each. Structure only — every number is still computed from the governed tables when the report is generated.",
  },
  {
    key: "integrations",
    label: "Integration monitor",
    href: "/admin/integrations",
    summary:
      "What each approved transaction owes the tracker, SAP and the document store — what succeeded, what failed, and what is waiting on a person.",
  },
] as const;

export type AdminAreaKey = (typeof ADMIN_AREAS)[number]["key"];

/** Admin for everything under /admin, except the audit explorer, which the Auditor also reads. */
export const ADMIN_ROLES: readonly PlatformRole[] = ["admin"];
export const AUDIT_ROLES: readonly PlatformRole[] = ["admin", "auditor"];

export function canAdminister(roles: PlatformRole[]): boolean {
  return hasAnyRole(roles, ADMIN_ROLES);
}

export function canReadAudit(roles: PlatformRole[]): boolean {
  return hasAnyRole(roles, AUDIT_ROLES);
}

/**
 * The floor a change reason is held to, matching what the API enforces.
 *
 * The dialog disables Save below it. That is a convenience: the server rejects the same request
 * with the same floor, so a client that skipped the check gets nowhere.
 */
export const MIN_CHANGE_REASON = 10;

export function reasonIsValid(reason: string): boolean {
  return reason.trim().length >= MIN_CHANGE_REASON;
}

export const THRESHOLD_UNITS = ["percent", "currency", "count", "ratio", "score"] as const;
export type ThresholdUnit = (typeof THRESHOLD_UNITS)[number];

export const UNIT_LABELS: Record<ThresholdUnit, string> = {
  percent: "%",
  currency: "currency",
  count: "count",
  ratio: "ratio",
  score: "score",
};

/** How a threshold reads on the row: the number, then what the number is measured in. */
export function formatThreshold(value: string | number, unit: string): string {
  const rendered = typeof value === "number" ? String(value) : value;
  const trimmed = rendered.includes(".")
    ? rendered.replace(/0+$/, "").replace(/\.$/, "")
    : rendered;
  return unit === "percent" ? `${trimmed}%` : `${trimmed} ${UNIT_LABELS[unit as ThresholdUnit] ?? unit}`;
}

/**
 * What a row's scope actually narrows it to, in words.
 *
 * A row scoped to nothing is the fall-back every transaction lands on when no narrower row
 * exists, and saying so plainly matters: an administrator editing it is changing the default for
 * everything, not for one commodity.
 */
export function scopeLabel(row: {
  scope_commodity_code: string | null;
  scope_transaction_type: string | null;
  scope_stream: string | null;
}): string {
  const parts: string[] = [];
  if (row.scope_commodity_code) parts.push(row.scope_commodity_code);
  if (row.scope_transaction_type) parts.push(row.scope_transaction_type.replace(/_/g, " "));
  if (row.scope_stream) parts.push(`${row.scope_stream} stream`);
  return parts.length > 0 ? parts.join(" · ") : "Applies to everything";
}

export const DOCUMENT_TYPE_LABELS: Record<string, string> = {
  invoice: "Invoice",
  contract: "Contract",
  bl: "Bill of lading",
  bl_draft: "Draft bill of lading",
  shipping_document: "Shipping document",
  tracker: "Tracker extract",
  approval_evidence: "Approval evidence",
  fa_document: "FA document",
  draft_contract: "Draft contract (generated)",
  draft_invoice: "Draft invoice (generated)",
  draft_performa_invoice: "Draft Performa invoice (generated)",
  draft_bank_cover_letter: "Draft bank cover letter (generated)",
  unknown: "Unclassified",
};

export function documentTypeLabel(value: string): string {
  return DOCUMENT_TYPE_LABELS[value] ?? value.replace(/_/g, " ");
}

export const TERRITORY_LABELS: Record<string, string> = {
  india: "India",
  china: "China",
  japan: "Japan",
  other: "Other",
};

export function territoryLabel(value: string | null): string {
  return value ? (TERRITORY_LABELS[value] ?? value) : "Every territory";
}

export const REPORT_TYPE_LABELS: Record<string, string> = {
  daily: "Daily operations",
  monthly: "Monthly management",
  adhoc: "Ad-hoc",
};

/** What each kind of section actually puts on the page, said once so the dialog need not. */
export const SECTION_KIND_LABELS: Record<string, string> = {
  kpi_grid: "Figure grid",
  breakdown: "Breakdown table",
  table: "Table",
  ai_summary: "AI summary paragraph",
  note: "Note",
};

/**
 * Where a section's numbers come from.
 *
 * Named for what the reader sees rather than for the function that assembles it: an administrator
 * choosing a section is choosing a subject, not a code path.
 */
export const SECTION_SOURCE_LABELS: Record<string, string> = {
  headline: "Headline figures",
  transactions_by_status: "Transactions by status",
  exceptions_by_category: "Exceptions by category and age",
  approvals: "Approval queue",
  integrations: "Downstream postings",
  shipments: "Cargo",
  extraction_by_document_type: "Extraction by document type",
  turnaround_trend: "Turnaround and automation by day",
  transaction_detail: "The transactions themselves",
};

export function sectionKindLabel(value: string): string {
  return SECTION_KIND_LABELS[value] ?? value.replace(/_/g, " ");
}

export function sectionSourceLabel(value: string): string {
  return SECTION_SOURCE_LABELS[value] ?? value.replace(/_/g, " ");
}

/**
 * A figure key as a person reads it.
 *
 * Deliberately a formatter rather than a lookup table: the headline block's keys come from the
 * API, and a table here would silently print a raw key the day the service computes a new one.
 */
export function headlineFigureLabel(value: string): string {
  const words = value.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function reportTypeLabel(value: string): string {
  return REPORT_TYPE_LABELS[value] ?? value.replace(/_/g, " ");
}

/**
 * What choosing a channel actually does, said plainly.
 *
 * The wording matters because the channel is a ceiling and not a floor, which is not obvious from
 * the word "Email" on its own. Choosing email permits an email; it does not impose one on somebody
 * who never asked to be emailed, because a recipient's own notification preference still governs.
 */
export function channelNote(channel: string): string {
  if (channel === "in_app") {
    return "A notification inside the platform only. No email is sent, even to recipients who have asked to be emailed.";
  }
  return "A notification inside the platform, plus an email to recipients whose own notification preference is email. It never emails somebody who did not ask to be.";
}
