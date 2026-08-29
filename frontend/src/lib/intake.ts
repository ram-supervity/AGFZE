import type { PlatformRole } from "@/lib/roles";
import { hasAnyRole } from "@/lib/roles";

/** Mirrors the backend `RequestCategory` vocabulary exactly. */
export const REQUEST_CATEGORIES = [
  "purchase",
  "sales",
  "fa",
  "logistics",
  "approval",
  "follow_up",
  "informational",
  "exception",
] as const;

export type RequestCategory = (typeof REQUEST_CATEGORIES)[number];

export const CATEGORY_LABELS: Record<RequestCategory, string> = {
  purchase: "Purchase",
  sales: "Sales",
  fa: "FA",
  logistics: "Logistics",
  approval: "Approval",
  follow_up: "Follow-up",
  informational: "Informational",
  exception: "Exception",
};

export const BUSINESS_STREAMS = ["scrap", "fa"] as const;
export type BusinessStream = (typeof BUSINESS_STREAMS)[number];

export const STREAM_LABELS: Record<BusinessStream, string> = {
  scrap: "Scrap",
  fa: "Finished aluminium",
};

/** The four states this step owns. The rest of the lifecycle arrives from Step 3 onwards. */
export const REQUEST_STATUSES = [
  "received",
  "classified",
  "extraction_pending",
  "extracted",
] as const;

export type RequestStatus = (typeof REQUEST_STATUSES)[number];

export const STATUS_LABELS: Record<RequestStatus, string> = {
  received: "Received",
  classified: "Classified",
  extraction_pending: "Extraction pending",
  extracted: "Extracted",
};

export const DOCUMENT_TYPES = [
  "invoice",
  "contract",
  "bl",
  "shipping_document",
  "tracker",
  "approval_evidence",
  "fa_document",
  "unknown",
] as const;

export type DocumentType = (typeof DOCUMENT_TYPES)[number];

export const DOCUMENT_TYPE_LABELS: Record<DocumentType, string> = {
  invoice: "Invoice",
  contract: "Contract",
  bl: "Bill of lading",
  shipping_document: "Shipping document",
  tracker: "Tracker",
  approval_evidence: "Approval evidence",
  fa_document: "FA document",
  unknown: "Unidentified",
};

export const TERRITORIES = ["india", "china", "japan", "other"] as const;
export type Territory = (typeof TERRITORIES)[number];

export const TERRITORY_LABELS: Record<Territory, string> = {
  india: "India",
  china: "China",
  japan: "Japan",
  other: "Other",
};

export const EXTRACTION_STATUSES = ["pending", "processing", "completed", "failed"] as const;
export type ExtractionStatus = (typeof EXTRACTION_STATUSES)[number];

export const EXTRACTION_STATUS_LABELS: Record<ExtractionStatus, string> = {
  pending: "Queued",
  processing: "Extracting",
  completed: "Extracted",
  failed: "Needs review",
};

/**
 * The desks that own the work correct it. The approver reviews and signs off rather than acting
 * as the correcting party, and the auditor observes. This only decides what the UI offers - the
 * API enforces the same list server-side on every call.
 */
export const CORRECTION_ROLES: readonly PlatformRole[] = [
  "purchase_user",
  "sales_user",
  "fa_user",
  "logistics_user",
  "admin",
];

export function canCorrect(roles: PlatformRole[]): boolean {
  return hasAnyRole(roles, CORRECTION_ROLES);
}

/**
 * The display banding for a confidence score: green at or above 0.9, amber between 0.7 and 0.9,
 * red below 0.7. Deliberately separate from the configurable threshold that decides whether a
 * correction needs a recorded reason - that one is served by the API per document.
 */
export type ConfidenceBand = "confident" | "review" | "blocked";

export function confidenceBand(confidence: number | null | undefined): ConfidenceBand {
  if (confidence === null || confidence === undefined) return "blocked";
  if (confidence >= 0.9) return "confident";
  if (confidence >= 0.7) return "review";
  return "blocked";
}

export const BAND_TEXT: Record<ConfidenceBand, string> = {
  confident: "text-signal-confident",
  review: "text-signal-review",
  blocked: "text-signal-blocked",
};

export const BAND_BORDER: Record<ConfidenceBand, string> = {
  confident: "border-l-signal-confident",
  review: "border-l-signal-review",
  blocked: "border-l-signal-blocked",
};

export const BAND_CHIP: Record<ConfidenceBand, string> = {
  confident: "border-signal-confident/35 bg-signal-confident/10 text-signal-confident",
  review: "border-signal-review/35 bg-signal-review/10 text-signal-review",
  blocked: "border-signal-blocked/35 bg-signal-blocked/10 text-signal-blocked",
};

export function formatConfidence(confidence: number | null | undefined): string {
  if (confidence === null || confidence === undefined) return "No score";
  return `${Math.round(confidence * 100)}%`;
}

export function labelFor<T extends string>(
  labels: Record<T, string>,
  value: string | null | undefined,
  fallback = "—",
): string {
  if (!value) return fallback;
  return (labels as Record<string, string>)[value] ?? value;
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** Client-side pre-check only. The server re-decides from the file's real leading bytes. */
export const ACCEPTED_EXTENSIONS = [
  ".pdf",
  ".docx",
  ".xlsx",
  ".xls",
  ".csv",
  ".jpg",
  ".jpeg",
  ".png",
] as const;

export const ACCEPTED_MIME_TYPES = [
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  "application/vnd.ms-excel",
  "text/csv",
  "image/jpeg",
  "image/png",
] as const;

export const MAX_UPLOAD_BYTES = 25 * 1024 * 1024;

export function validateFileClientSide(file: File): string | null {
  const name = file.name.toLowerCase();
  const extensionOk = ACCEPTED_EXTENSIONS.some((extension) => name.endsWith(extension));
  if (!extensionOk) {
    return "Only PDF, Word, Excel, CSV, JPEG and PNG files are accepted.";
  }
  if (file.size === 0) return "The file is empty.";
  if (file.size > MAX_UPLOAD_BYTES) {
    return `The file is ${formatBytes(file.size)}; the limit is 25 MB.`;
  }
  return null;
}
