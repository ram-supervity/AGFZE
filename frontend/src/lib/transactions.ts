import type { PlatformRole } from "@/lib/roles";
import { hasAnyRole } from "@/lib/roles";

/**
 * Mirrors the backend `TransactionStatus` vocabulary.
 *
 * The first four are the intake states a transaction inherits from its request; `matched`
 * through `approval_pending` are the preparation states; `approved` is the approver's decision;
 * and `integration_pending` and `committed` are the two the integration hub adds. `committed` is
 * where the lifecycle ends today.
 *
 * `closed` is deliberately absent. The backend declares it, no code path sets it, and a status
 * this list named would put a state on the screen that no transaction can ever be in.
 */
export const TRANSACTION_STATUSES = [
  "received",
  "classified",
  "extraction_pending",
  "extracted",
  "matched",
  "validation_pending",
  "approval_pending",
  "approved",
  "integration_pending",
  "committed",
] as const;

export type TransactionStatus = (typeof TRANSACTION_STATUSES)[number];

export const TRANSACTION_STATUS_LABELS: Record<TransactionStatus, string> = {
  received: "Received",
  classified: "Classified",
  extraction_pending: "Extraction pending",
  extracted: "Extracted",
  matched: "Matched",
  validation_pending: "Validation pending",
  approval_pending: "Approval pending",
  approved: "Approved",
  integration_pending: "Integration pending",
  committed: "Committed",
};

/** Colour-coded to the state machine, using the platform's traffic-light triad. */
export const TRANSACTION_STATUS_CHIP: Record<TransactionStatus, string> = {
  received: "border-border bg-muted text-muted-foreground",
  classified: "border-border bg-muted text-muted-foreground",
  extraction_pending: "border-border bg-muted text-muted-foreground",
  extracted: "border-border bg-muted text-muted-foreground",
  matched: "border-signal-review/35 bg-signal-review/10 text-signal-review",
  validation_pending: "border-signal-review/35 bg-signal-review/10 text-signal-review",
  approval_pending: "border-signal-confident/35 bg-signal-confident/10 text-signal-confident",
  approved: "border-signal-confident/35 bg-signal-confident/10 text-signal-confident",
  // Amber, not green: the deal is approved but its postings are not all resolved, and the board
  // should not read as finished while somebody still owes a system a posting.
  integration_pending: "border-signal-review/35 bg-signal-review/10 text-signal-review",
  committed: "border-signal-confident/45 bg-signal-confident/15 text-signal-confident",
};

/** The states in which a transaction's figures are no longer editable by its preparing desk. */
export const LOCKED_TRANSACTION_STATUSES: readonly TransactionStatus[] = [
  "approval_pending",
  "approved",
  "integration_pending",
  "committed",
];

export const INVOICE_STATUSES = ["provisional", "final"] as const;
export type InvoiceStatus = (typeof INVOICE_STATUSES)[number];

export const INVOICE_STATUS_LABELS: Record<InvoiceStatus, string> = {
  provisional: "Provisional",
  final: "Final",
};

export const PRICE_BASES = ["fixed", "lme_percent"] as const;
export type PriceBasis = (typeof PRICE_BASES)[number];

export const PRICE_BASIS_LABELS: Record<PriceBasis, string> = {
  fixed: "Fixed price",
  lme_percent: "Percentage of LME",
};

export const MATCH_METHOD_LABELS: Record<string, string> = {
  batch_number: "Matched on the batch number quoted on the document",
  fuzzy_auto: "Matched automatically on contract, supplier and quantity",
  suggestion_confirmed: "A suggested match confirmed by the preparing user",
  manual: "Registered by hand, with no email or document trigger",
  new_batch: "Opened as a new batch because nothing open matched",
  supersession: "A final invoice superseded the provisional figures",
  duplicate_link: "A repeated document linked to the batch it already belonged to",
};

export const MATCH_OUTCOME_LABELS: Record<string, string> = {
  auto_linked: "Matched",
  suggested: "Needs your decision",
  new_transaction: "New batch opened",
  duplicate_linked: "Repeated document",
  superseded: "Final invoice applied",
  already_linked: "Already linked",
  no_reference: "Nothing to match on",
  not_applicable: "Not a purchase document",
  // The sales side's own band. Nothing matched, and unlike the purchase side that does not open
  // a new batch: a sale is of cargo already bought, so a person names the batch instead.
  no_purchase_match: "No purchase transaction matched",
};

/** The severities the rule engine reports, and how each is presented. */
export type RuleSeverity = "hard" | "acknowledgeable" | "informational";

export const SEVERITY_LABELS: Record<RuleSeverity, string> = {
  hard: "Must be corrected",
  acknowledgeable: "May be acknowledged",
  informational: "For information",
};

/**
 * The desks that may create, correct and submit a purchase transaction. The approver signs off
 * from Step 4 onwards rather than preparing, and the auditor observes. This decides only what the
 * UI offers; the API enforces the same list on every call.
 */
export const PURCHASE_WRITE_ROLES: readonly PlatformRole[] = ["purchase_user", "admin"];

/** The selling desk owns its own deals, exactly as the buying desk owns theirs. */
export const SALES_WRITE_ROLES: readonly PlatformRole[] = ["sales_user", "admin"];

/** And so does the FA desk, on AGFZE's second business line. The same sentence a third time. */
export const FA_WRITE_ROLES: readonly PlatformRole[] = ["fa_user", "admin"];

export function canWriteTransactions(roles: PlatformRole[]): boolean {
  return hasAnyRole(roles, PURCHASE_WRITE_ROLES);
}

export function canWriteSales(roles: PlatformRole[]): boolean {
  return hasAnyRole(roles, SALES_WRITE_ROLES);
}

export function canWriteFa(roles: PlatformRole[]): boolean {
  return hasAnyRole(roles, FA_WRITE_ROLES);
}

export const TERRITORIES = ["india", "china", "japan", "other"] as const;
export type Territory = (typeof TERRITORIES)[number];

export const TERRITORY_LABELS: Record<Territory, string> = {
  india: "India",
  china: "China",
  japan: "Japan",
  other: "Other",
};

export const PAYMENT_CONDITIONS = ["CAD", "TT"] as const;
export type PaymentCondition = (typeof PAYMENT_CONDITIONS)[number];

export const PAYMENT_CONDITION_LABELS: Record<PaymentCondition, string> = {
  CAD: "Cash against documents",
  TT: "Telegraphic transfer",
};

export const FIXATION_STATUSES = ["unfixed", "fixed"] as const;
export type FixationStatus = (typeof FIXATION_STATUSES)[number];

export const FIXATION_STATUS_LABELS: Record<FixationStatus, string> = {
  unfixed: "Not yet fixed",
  fixed: "Fixed",
};

/** The four documents this platform writes. Nothing else is generatable. */
export const GENERATED_DOCUMENT_TYPES = [
  "draft_contract",
  "draft_invoice",
  "draft_performa_invoice",
  "draft_bank_cover_letter",
] as const;
export type GeneratedDocumentType = (typeof GENERATED_DOCUMENT_TYPES)[number];

export const GENERATED_DOCUMENT_LABELS: Record<GeneratedDocumentType, string> = {
  draft_contract: "Draft sales contract",
  draft_invoice: "Draft sales invoice",
  draft_performa_invoice: "Draft Performa invoice",
  draft_bank_cover_letter: "Draft bank cover letter",
};

/**
 * What each generated document is for, shown beside the choice.
 *
 * The Performa invoice's note earns its place: it is the one document here that is *correct*
 * without a weight slip behind it, and a preparer who did not know that would reasonably assume
 * the platform had produced an unfinished invoice.
 */
export const GENERATED_DOCUMENT_NOTES: Record<GeneratedDocumentType, string> = {
  draft_contract: "The sales contract, from the recorded terms.",
  draft_invoice: "The commercial invoice, stating the shipped weight. Needs a bill of lading.",
  draft_performa_invoice:
    "The advance invoice, raised before the cargo is weighed. It states the contracted quantity, not a shipped weight, and needs no weight slip or bill of lading.",
  draft_bank_cover_letter:
    "The covering note for a documentary set going to the bank. It lists what is enclosed and carries no commercial terms of its own.",
};

/**
 * How a sales leg came to sit on the transaction it sits on. Four routes, and no fifth in which
 * the platform guessed - which is the same reason there is no merge anywhere in the app.
 */
export const ATTACHMENT_LABELS: Record<string, string> = {
  auto_matched: "Matched automatically to an existing batch",
  suggestion_confirmed: "A suggested batch confirmed by the Sales User",
  user_selected: "A batch the Sales User searched for and selected",
  no_purchase_acknowledged:
    "Attached with an explicit acknowledgement that no purchase counterpart exists yet",
};

/**
 * The quantity meter's state, in the same red/amber/green language confidence and validation
 * already use elsewhere in the app.
 *
 * `partial` is deliberately green-adjacent rather than a warning: a part-shipped sales contract
 * is the normal condition of a live deal, and colouring it amber would train people to ignore
 * amber. Only `exceeded` - more invoiced than was ever contracted - is a problem.
 */
export type CoverageState = "partial" | "complete" | "exceeded" | "unknown";

export const COVERAGE_LABELS: Record<CoverageState, string> = {
  partial: "Part-shipped",
  complete: "Fully shipped",
  exceeded: "Over-invoiced",
  unknown: "No contracted total recorded",
};

export const COVERAGE_TONE: Record<CoverageState, string> = {
  partial: "border-signal-confident/35 bg-signal-confident/10 text-signal-confident",
  complete: "border-signal-confident/35 bg-signal-confident/10 text-signal-confident",
  exceeded: "border-signal-blocked/45 bg-signal-blocked/10 text-signal-blocked",
  unknown: "border-signal-review/35 bg-signal-review/10 text-signal-review",
};

export const COVERAGE_BAR: Record<CoverageState, string> = {
  partial: "bg-signal-confident",
  complete: "bg-signal-confident",
  exceeded: "bg-signal-blocked",
  unknown: "bg-signal-review",
};

/**
 * Which workspace a transaction belongs in, decided by the legs it actually carries.
 *
 * FA first, because an FA transaction is a structurally separate business line and can carry no
 * other leg - there is no ambiguity to resolve. Between the other two the sell side wins, because
 * the sales workspace shows the purchase leg beside it and the purchase workspace does not show
 * the sales leg. A user who wants the buying view has a link to it from there.
 */
export function workspacePath(transaction: {
  id: string;
  has_sales_leg?: boolean;
  has_fa_leg?: boolean;
}): string {
  if (transaction.has_fa_leg) return `/transactions/fa/${transaction.id}`;
  return transaction.has_sales_leg
    ? `/transactions/sales/${transaction.id}`
    : `/transactions/purchase/${transaction.id}`;
}

export function deskLabel(transaction: {
  has_sales_leg?: boolean;
  has_purchase_leg?: boolean;
  has_fa_leg?: boolean;
}): string {
  if (transaction.has_fa_leg) return "FA";
  if (transaction.has_sales_leg && transaction.has_purchase_leg) return "Purchase + Sales";
  if (transaction.has_sales_leg) return "Sales";
  if (transaction.has_purchase_leg) return "Purchase";
  return "No leg";
}

export function formatMoney(
  value: string | number | null | undefined,
  currency = "USD",
): string {
  if (value === null || value === undefined || value === "") return "—";
  const amount = typeof value === "number" ? value : Number.parseFloat(value);
  if (Number.isNaN(amount)) return String(value);
  return `${amount.toLocaleString("en-GB", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })} ${currency}`;
}

export function formatQuantity(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const amount = typeof value === "number" ? value : Number.parseFloat(value);
  if (Number.isNaN(amount)) return String(value);
  return `${amount.toLocaleString("en-GB", {
    minimumFractionDigits: 3,
    maximumFractionDigits: 3,
  })} MT`;
}

export function formatAge(days: number): string {
  if (days <= 0) return "Today";
  if (days === 1) return "1 day";
  return `${days} days`;
}

export function isBlocking(rule: { passed: boolean }): boolean {
  return !rule.passed;
}

export function isAcknowledgeable(rule: { passed: boolean; severity: string }): boolean {
  return !rule.passed && rule.severity === "acknowledgeable";
}

/** The single, specific reason the submit button is disabled, or null when it is not. */
export function submitBlocker(
  rules: { passed: boolean; rule_id: string; check_key: string | null; message: string }[],
): string | null {
  const failing = rules.find((rule) => !rule.passed);
  if (!failing) return null;
  const check = failing.check_key ? ` (${failing.check_key.replace(/_/g, " ")})` : "";
  return `${failing.rule_id}${check}: ${failing.message}`;
}
