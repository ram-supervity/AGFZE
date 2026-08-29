import { getClientEnv, getServerEnv } from "@/lib/env";
import { noteResponse } from "@/lib/offline-state";

export interface ErrorDetail {
  code: string;
  message: string;
  field?: string | null;
}

export interface ResponseEnvelope<T> {
  success: boolean;
  data: T | null;
  message?: string | null;
  errors?: ErrorDetail[] | null;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly errors: ErrorDetail[];

  constructor(status: number, code: string, message: string, errors: ErrorDetail[] = []) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.errors = errors;
  }
}

export interface ApiFetchOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  accessToken?: string;
  signal?: AbortSignal;
}

/** Mirrors the backend `UserRead` schema, keys exactly as the API serialises them. */
export interface UserProfile {
  id: string;
  subject_id: string;
  entra_object_id: string | null;
  email: string;
  display_name: string;
  roles: string[];
  default_stream_filter: string | null;
  notification_channel: string;
  is_active: boolean;
  /** False until the account has finished or dismissed the first-login walkthrough. */
  has_completed_onboarding: boolean;
  created_at: string;
  last_login_at: string | null;
}

/** Mirrors the backend `EmailMessageRead` schema. */
export interface EmailMessage {
  id: string;
  sender_address: string | null;
  sender_name: string | null;
  subject: string | null;
  /** Plain text. Rendered as text, never as markup. */
  body_text: string | null;
  received_at: string;
  has_attachments: boolean;
}

export interface DocumentSummary {
  id: string;
  filename: string;
  content_type: string;
  byte_size: number;
  document_type: string | null;
  territory: string | null;
  page_count: number | null;
  extraction_status: string;
  classification_confidence: number | null;
  needs_review: boolean;
  confirmed_at: string | null;
  transaction_id: string | null;
  created_at: string;
  thumbnail_url: string | null;
}

export interface RequestSummary {
  id: string;
  request_code: string;
  source: string;
  category: string | null;
  category_confidence: number | null;
  category_overridden: boolean;
  stream: string | null;
  status: string;
  needs_review: boolean;
  created_at: string;
  updated_at: string;
  subject: string | null;
  sender_address: string | null;
  document_count: number;
}

export interface RequestDetail extends RequestSummary {
  category_rationale: string | null;
  original_category: string | null;
  category_override_reason: string | null;
  category_overridden_at: string | null;
  original_stream: string | null;
  classification_error: string | null;
  email: EmailMessage | null;
  documents: DocumentSummary[];
}

export interface PageInfo {
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
}

export interface RequestQueue {
  items: RequestSummary[];
  page: PageInfo;
}

export interface FieldSchemaRead {
  name: string;
  label: string;
  type: string;
  required: boolean;
  tolerance: number | null;
  section: string;
  description: string;
}

export interface ExtractedField {
  id: string;
  field_name: string;
  field_value: string | null;
  confidence: number | null;
  rationale: string | null;
  source_page: number | null;
  source_reference: Record<string, unknown> | null;
  has_conflict: boolean;
  conflicting_values: string[];
  is_overridden: boolean;
  original_ai_value: string | null;
  original_confidence: number | null;
  override_reason: string | null;
  overridden_at: string | null;
  overridden_by_name: string | null;
  label: string | null;
  type: string;
  required: boolean;
  section: string;
  /** True when the field's original confidence sat below the configured threshold. */
  reason_required: boolean;
}

export interface DocumentListItem {
  id: string;
  request_id: string;
  request_code: string | null;
  filename: string;
  document_type: string | null;
  territory: string | null;
  extraction_status: string;
  classification_confidence: number | null;
  needs_review: boolean;
  confirmed_at: string | null;
  page_count: number | null;
  byte_size: number;
  created_at: string;
  /** Set once matching has tied the document to a batch. */
  transaction_id: string | null;
  thumbnail_url: string | null;
}

export interface DocumentList {
  items: DocumentListItem[];
  page: PageInfo;
}

export interface DocumentDetail extends DocumentListItem {
  content_type: string;
  content_hash: string;
  classification_rationale: string | null;
  original_document_type: string | null;
  document_type_hint: string | null;
  extraction_error: string | null;
  uploaded_by_name: string | null;
  confirmed_by_name: string | null;
  source_url: string | null;
  page_image_urls: string[];
  fields: ExtractedField[];
  schema_fields: FieldSchemaRead[];
  confidence_threshold: number;
  mandatory_documents: string[];
}

export interface MatchCandidate {
  transaction_id: string;
  batch_number: string;
  supplier_name: string | null;
  contract_number: string | null;
  score: number;
  rationale: string;
}

/** Mirrors the backend `MatchOutcomeRead`. */
export interface MatchOutcome {
  outcome:
    | "auto_linked"
    | "suggested"
    | "new_transaction"
    | "duplicate_linked"
    | "superseded"
    | "already_linked"
    | "no_reference"
    | "not_applicable";
  message: string;
  transaction_id: string | null;
  batch_number: string | null;
  score: number | null;
  method: string | null;
  candidates: MatchCandidate[];
  needs_user_decision: boolean;
}

export interface CommodityCode {
  code: string;
  display_name: string;
  is_active: boolean;
}

export interface PurchaseLeg {
  id: string;
  supplier_name: string | null;
  supplier_invoice_number: string | null;
  contract_number: string | null;
  invoice_status: string;
  amount: string | null;
  rate: string | null;
  advance_payment_percent: string | null;
  hedge_date: string | null;
  /** The hedging day's range. `hedge_low_price` is discovery's "LLME" — the low end of it. */
  hedge_low_price: string | null;
  hedge_high_price: string | null;
  port_of_loading: string | null;
  created_at: string;
  updated_at: string;
}

export interface SalesLeg {
  id: string;
  customer_name: string;
  territory: string;
  sales_contract_no: string;
  contracted_quantity_mt: string | null;
  sales_invoice_number: string | null;
  bl_reference: string | null;
  payment_condition: string;
  customer_fixation_status: string;
  fixation_rate: string | null;
  fixation_date: string | null;
  port_of_discharge: string | null;
  inland_container_depot: string | null;
  /** What the sales-side document said the grade was, kept verbatim for the code comparison. */
  extracted_commodity_value: string | null;
  created_at: string;
  updated_at: string;
}

/**
 * The buying side's context for the sales workspace's comparison card.
 *
 * There is deliberately no purchase-side commodity *description* here. Comparing one against the
 * sales-side wording is the false positive the platform must not produce: a China-bound shipment
 * legitimately describes the same grade differently. Only the resolved code is compared.
 */
export interface LinkedPurchaseContext {
  present: boolean;
  supplier_name: string | null;
  contract_number: string | null;
  supplier_invoice_number: string | null;
  invoice_status: string | null;
  port_of_loading: string | null;
  amount: string | null;
  rate: string | null;
  commodity_code: string | null;
  sales_document_commodity_value: string | null;
  commodity_code_mismatch: boolean;
  message: string | null;
}

/** Everything invoiced against one sales contract number, summed across every shipment on it. */
export interface ContractCoverage {
  sales_contract_no: string;
  contracted_quantity_mt: string | null;
  invoiced_quantity_mt: string;
  remaining_quantity_mt: string | null;
  shipment_count: number;
  state: "partial" | "complete" | "exceeded" | "unknown";
  ratio: number;
  message: string;
}

/** One draft the platform produced. A regeneration adds another; nothing is overwritten. */
export interface GeneratedDraft {
  id: string;
  filename: string;
  document_type: string | null;
  byte_size: number;
  created_at: string;
  generated_by_name: string | null;
  download_url: string | null;
  version: number;
}

/** The FA leg. Three named columns, and everything configuration adds beyond them. */
export interface FaLeg {
  id: string;
  counterparty_name: string | null;
  fa_contract_reference: string | null;
  document_type: string | null;
  /** Keyed by configured field name. Never written except through the validated field path. */
  extra_fields: Record<string, string>;
  created_at: string;
  updated_at: string;
}

/**
 * One configured FA field, exactly as `document_type_schemas` describes it.
 *
 * The Additional FA Fields panel renders from this list and from nothing else, which is why it
 * needs no code change when the business settles what FA's fields are.
 */
export interface FaFieldSchema {
  name: string;
  label: string;
  type: string;
  required: boolean;
  section: string;
  description: string;
}

export interface RuleEvaluation {
  id: string;
  rule_id: string;
  check_key: string | null;
  passed: boolean;
  severity: string;
  field_name: string | null;
  expected_value: string | null;
  actual_value: string | null;
  message: string;
  acknowledged: boolean;
  acknowledgement_reason: string | null;
  acknowledged_at: string | null;
  evaluated_at: string;
  title: string | null;
  statement: string | null;
  acknowledged_by_name: string | null;
}

export interface TransactionField {
  name: string;
  label: string;
  owner: string;
  type: string;
  value: string | null;
  section: string;
  /** What the machine originally scored for the extracted field behind this one. */
  source_confidence: number | null;
  reason_required: boolean;
  is_overridden: boolean;
  original_ai_value: string | null;
  original_confidence: number | null;
  override_reason: string | null;
  overridden_by_name: string | null;
  overridden_at: string | null;
  options: string[];
  editable: boolean;
}

export interface StatusEvent {
  occurred_at: string;
  event_type: string;
  summary: string;
  actor_name: string | null;
  metadata: Record<string, unknown>;
}

export interface TransactionListItem {
  id: string;
  transaction_code: string;
  batch_number: string;
  stream: string;
  status: string;
  commodity_code: string | null;
  commodity_name: string | null;
  quantity_mt: string | null;
  price_basis: string | null;
  lme_percentage: string | null;
  currency: string;
  created_at: string;
  updated_at: string;
  counterparty: string | null;
  /** The desk's own short form of that name, derived on read rather than stored. */
  counterparty_code: string | null;
  contract_number: string | null;
  invoice_status: string | null;
  value: string | null;
  age_days: number;
  document_count: number;
  failing_rule_count: number;
  /** Which legs the transaction actually carries, so a row opens in the right workspace. */
  has_purchase_leg: boolean;
  has_sales_leg: boolean;
  has_fa_leg: boolean;
  /**
   * A joint B2B purchase, and the partner it is shared with. The tag only — no profit split,
   * shared expense or loss allocation is modelled anywhere yet.
   */
  is_b2b: boolean;
  b2b_partner_name: string | null;
  /**
   * Real from Step 6. Null still means something specific: no shipment record exists for this
   * transaction, which is not the same claim as "on schedule".
   */
  shipment_status: string | null;
  shipment_stale: boolean;
  shipment_count: number;
}

export interface TransactionList {
  items: TransactionListItem[];
  page: PageInfo;
}

export interface TransactionDetail extends TransactionListItem {
  request_id: string;
  request_code: string | null;
  match_method: string | null;
  match_score: string | null;
  match_rationale: string | null;
  extracted_commodity_value: string | null;
  commodity_needs_review: boolean;
  submitted_at: string | null;
  submitted_by_name: string | null;
  created_by_name: string | null;
  closed_at: string | null;
  purchase_leg: PurchaseLeg | null;
  /** Populated from Step 5. The field was always declared; it was simply always empty. */
  sales_leg: SalesLeg | null;
  /** Populated from Step 6, the third leg to arrive without the response shape changing. */
  fa_leg: FaLeg | null;
  /** The schema-driven extras, ready to render. Empty for every non-FA transaction. */
  fa_extra_fields: TransactionField[];
  fa_field_schema: FaFieldSchema[];
  /** Every shipment carrying this batch, and every container it was loaded into. */
  linked_shipments: LinkedShipment[];
  containers: ShipmentContainer[];
  /** The three postings this transaction owes the outside world. Empty until it is approved. */
  integration_jobs: IntegrationJob[];
  /** Whether the reader may act on those jobs. Decided server-side, never by the screen. */
  can_manage_integrations: boolean;
  linked_purchase: LinkedPurchaseContext | null;
  contract_coverage: ContractCoverage | null;
  generated_drafts: GeneratedDraft[];
  /** True when BR-07's draft check passes: a draft or original B/L, or a recorded reference. */
  can_generate_draft: boolean;
  draft_blocker: string | null;
  documents: DocumentSummary[];
  rule_evaluations: RuleEvaluation[];
  fields: TransactionField[];
  history: StatusEvent[];
  confidence_threshold: number;
  can_edit: boolean;
  can_submit: boolean;
  blocking_rules: string[];
}

// --- shipments ---------------------------------------------------------------------------------
//
// One shape for a shipment, not two. Nothing on these types says whether a carrier or a person
// established the values, because the screen does not branch on it and must not learn to.

export interface ShipmentContainer {
  id: string;
  container_number: string;
  seal_number: string | null;
  quantity_mt: string | null;
  created_at: string;
}

export interface BillOfLading {
  id: string;
  bl_type: string;
  bl_number: string | null;
  /** The field BR-07's submission check now actually reads. */
  is_original_received: boolean;
  document_id: string | null;
  received_at: string | null;
  created_at: string;
}

export interface ShipmentIssue {
  id: string;
  issue_type: string;
  description: string;
  document_id: string | null;
  logged_by_name: string | null;
  logged_at: string;
  resolved_at: string | null;
}

export interface ShipmentListItem {
  id: string;
  transaction_id: string;
  batch_number: string | null;
  container_number: string | null;
  bl_number: string | null;
  carrier: string | null;
  vessel: string | null;
  port_of_loading: string | null;
  port_of_discharge: string | null;
  etd: string | null;
  eta: string | null;
  current_milestone: string | null;
  status: string;
  last_checked_at: string | null;
  /** `manual`, or the adapter's name. Provenance only; it changes nothing about the row. */
  last_checked_source: string | null;
  /** Computed by the server on every read from `last_checked_at`; never a stored flag. */
  hours_since_check: number;
  is_stale: boolean;
  stale_threshold_hours: number;
  consecutive_failures: number;
  last_error: string | null;
  review_flagged: boolean;
  review_reason: string | null;
  counterparty: string | null;
}

export interface ShipmentTimelineEntry {
  occurred_at: string;
  event_type: string;
  summary: string;
  milestone: string | null;
  status: string | null;
  source: string | null;
  actor_name: string | null;
  detail: string | null;
}

export interface ShipmentLinkedTransaction {
  id: string;
  batch_number: string;
  stream: string;
  status: string;
  counterparty: string | null;
  contract_number: string | null;
  commodity_name: string | null;
  quantity_mt: string | null;
  currency: string;
  has_purchase_leg: boolean;
  has_sales_leg: boolean;
  has_fa_leg: boolean;
}

export interface ShipmentDetail extends ShipmentListItem {
  container: ShipmentContainer | null;
  containers: ShipmentContainer[];
  bills_of_lading: BillOfLading[];
  issues: ShipmentIssue[];
  /** Derived from `audit_events` on every read. There is no history table behind this. */
  timeline: ShipmentTimelineEntry[];
  transaction: ShipmentLinkedTransaction | null;
  milestones: string[];
  statuses: string[];
  bill_of_lading_types: string[];
  issue_types: string[];
  can_manage: boolean;
  carrier_adapters_available: number;
  created_at: string;
}

export interface ShipmentList {
  items: ShipmentListItem[];
  page: PageInfo;
  carriers: string[];
  ports_of_discharge: string[];
  stale_threshold_hours: number;
  /** Zero on every deployment that ships today, and the dashboard says so plainly. */
  carrier_adapters_available: number;
  can_manage: boolean;
}

/** A shipment as a transaction workspace shows it. */
export interface LinkedShipment {
  id: string;
  container_number: string | null;
  bl_number: string | null;
  carrier: string | null;
  vessel: string | null;
  port_of_loading: string | null;
  port_of_discharge: string | null;
  etd: string | null;
  eta: string | null;
  current_milestone: string | null;
  status: string;
  last_checked_at: string | null;
  last_checked_source: string | null;
  hours_since_check: number;
  is_stale: boolean;
  review_flagged: boolean;
  /** The field BR-07 blocks submission on, in front of the desk that has to act on it. */
  original_bl_received: boolean;
}

export interface ShipmentManualUpdate {
  status?: string | null;
  milestone?: string | null;
  eta?: string | null;
  etd?: string | null;
  carrier?: string | null;
  vessel?: string | null;
  port_of_loading?: string | null;
  port_of_discharge?: string | null;
  bl_number?: string | null;
  bl_type?: string | null;
  original_bl_received?: boolean | null;
  bl_document_id?: string | null;
  note?: string | null;
}

export interface ShipmentRefreshResult {
  shipment: ShipmentDetail;
  /** False when no adapter handles this shipment - the ordinary case, and not a failure. */
  attempted: boolean;
  updated: boolean;
  adapter: string | null;
  message: string;
  plausibility_flagged: boolean;
}

export interface FaTransactionCreate {
  counterparty_name: string;
  fa_contract_reference?: string | null;
  document_type?: string | null;
  batch_number?: string | null;
  commodity_code?: string | null;
  quantity_mt?: string | null;
  currency: string;
  /** Keyed by configured field name. The server refuses anything the schema does not carry. */
  extra_fields: Record<string, string>;
}

export interface SubmissionResult {
  transaction_id: string;
  status: string;
  submitted_at: string | null;
  blocking_rules: string[];
}

export interface JobStatus {
  id: string;
  job_type: string;
  status: "queued" | "processing" | "completed" | "failed";
  progress: number;
  result_ref: string | null;
  error_message: string | null;
  transaction_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface UploadAccepted {
  request_id: string;
  request_code: string;
  job_id: string;
  document_ids: string[];
  rejected: { filename: string; reason: string }[];
}

/**
 * Server renders reach the API over the container network, the browser over the published port.
 * Outside Docker both resolve to the same value, so this collapses to one URL.
 */
function apiBaseUrl(): string {
  const base =
    typeof window === "undefined"
      ? getServerEnv().API_INTERNAL_BASE_URL
      : getClientEnv().NEXT_PUBLIC_API_BASE_URL;
  return base.replace(/\/+$/, "");
}

export async function apiFetch<T>(
  path: string,
  { method = "GET", body, accessToken, signal }: ApiFetchOptions = {},
): Promise<ResponseEnvelope<T>> {
  // Offline, a request that would change something is refused here rather than attempted.
  // The service worker will not cache it and will never replay it later, so letting it go would
  // produce a network error the user could easily read as "nothing happened" - when what they
  // need told is that the action needs a connection and has not been taken. Read requests are
  // still attempted: the worker may have a cached copy to answer with.
  if (
    typeof navigator !== "undefined" &&
    navigator.onLine === false &&
    method !== "GET"
  ) {
    throw new ApiError(
      0,
      "offline",
      "This action needs a connection. Nothing has been sent, and nothing has been saved — reconnect and try again.",
    );
  }

  const base = apiBaseUrl();
  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  // Only ever a token handed in by the caller from the server-side session; nothing is read back
  // out of browser storage.
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;

  let response: Response;
  try {
    response = await fetch(`${base}/${path.replace(/^\/+/, "")}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
      cache: "no-store",
    });
  } catch (cause) {
    if (signal?.aborted) throw cause;
    throw new ApiError(0, "network_error", "The API could not be reached.");
  }

  // The service worker stamps anything it served out of storage, so the banner can say how old
  // what is on screen actually is instead of presenting it as live.
  if (typeof window !== "undefined") noteResponse(response.headers);

  const text = await response.text();
  let payload: ResponseEnvelope<T> | null = null;
  if (text.trim().length > 0) {
    try {
      payload = JSON.parse(text) as ResponseEnvelope<T>;
    } catch {
      throw new ApiError(
        response.status,
        "invalid_response",
        "The API returned a response that could not be read.",
      );
    }
  }

  if (!response.ok || payload?.success === false) {
    const detail = payload?.errors?.[0];
    throw new ApiError(
      response.status,
      detail?.code ?? "request_failed",
      payload?.message ?? detail?.message ?? `The API returned HTTP ${response.status}.`,
      payload?.errors ?? [],
    );
  }

  if (!payload) {
    throw new ApiError(response.status, "empty_response", "The API returned an empty response.");
  }

  return payload;
}

export async function fetchCurrentUser(accessToken: string): Promise<UserProfile> {
  const envelope = await apiFetch<UserProfile>("/users/me", { accessToken });
  if (!envelope.data) {
    throw new ApiError(
      502,
      "empty_response",
      "The API returned no profile for the signed-in account.",
    );
  }
  return envelope.data;
}

export function buildQuery(params: Record<string, string | number | boolean | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === "") continue;
    search.set(key, String(value));
  }
  const rendered = search.toString();
  return rendered ? `?${rendered}` : "";
}

function unwrap<T>(envelope: ResponseEnvelope<T>): T {
  if (envelope.data === null || envelope.data === undefined) {
    throw new ApiError(502, "empty_response", "The API returned no data for this request.");
  }
  return envelope.data;
}

export async function fetchRequestQueue(
  accessToken: string,
  params: Record<string, string | number | boolean | undefined>,
): Promise<RequestQueue> {
  return unwrap(await apiFetch<RequestQueue>(`/requests${buildQuery(params)}`, { accessToken }));
}

export async function fetchRequestDetail(
  accessToken: string,
  id: string,
): Promise<RequestDetail> {
  return unwrap(await apiFetch<RequestDetail>(`/requests/${id}`, { accessToken }));
}

export interface ReplyDraft {
  id: string;
  request_id: string;
  status: "draft" | "sent" | "failed" | "withdrawn";
  subject: string | null;
  /** Exactly what was composed, disclaimer included. Never reconstructed from a template. */
  body_text: string;
  failure_reason: string | null;
  composed_at: string;
  composed_by_name: string | null;
  sent_at: string | null;
  sent_by_name: string | null;
}

export interface ReplyDraftList {
  items: ReplyDraft[];
  recipient_address: string | null;
  /** False where this deployment can compose a reply and cannot send one. */
  outbound_enabled: boolean;
}

export async function fetchRequestReplies(
  accessToken: string,
  requestId: string,
): Promise<ReplyDraftList> {
  return unwrap(
    await apiFetch<ReplyDraftList>(`/requests/${requestId}/replies`, { accessToken }),
  );
}

/** Writes a draft. Contacts no mailbox, on any deployment. */
export async function composeRequestReply(
  accessToken: string,
  requestId: string,
  body: { message: string },
): Promise<ReplyDraft> {
  return unwrap(
    await apiFetch<ReplyDraft>(`/requests/${requestId}/replies`, {
      method: "POST",
      accessToken,
      body,
    }),
  );
}

/**
 * The one call in this client that puts a message into somebody else's inbox.
 *
 * Deliberately its own function rather than a flag on the compose call: a caller cannot reach it
 * by accident, and a reader of this file can find every send path by finding this name.
 */
export async function sendRequestReply(
  accessToken: string,
  requestId: string,
  draftId: string,
): Promise<ReplyDraft> {
  return unwrap(
    await apiFetch<ReplyDraft>(`/requests/${requestId}/replies/${draftId}/send`, {
      method: "POST",
      accessToken,
    }),
  );
}

export async function withdrawRequestReply(
  accessToken: string,
  requestId: string,
  draftId: string,
): Promise<ReplyDraft> {
  return unwrap(
    await apiFetch<ReplyDraft>(`/requests/${requestId}/replies/${draftId}/withdraw`, {
      method: "POST",
      accessToken,
    }),
  );
}

export async function overrideRequestCategory(
  accessToken: string,
  id: string,
  body: { category: string; stream?: string | null; reason: string },
): Promise<RequestDetail> {
  return unwrap(
    await apiFetch<RequestDetail>(`/requests/${id}/category`, {
      method: "PATCH",
      accessToken,
      body,
    }),
  );
}

export async function fetchDocumentList(
  accessToken: string,
  params: Record<string, string | number | boolean | undefined>,
): Promise<DocumentList> {
  return unwrap(await apiFetch<DocumentList>(`/documents${buildQuery(params)}`, { accessToken }));
}

export async function fetchDocumentDetail(
  accessToken: string,
  id: string,
): Promise<DocumentDetail> {
  return unwrap(await apiFetch<DocumentDetail>(`/documents/${id}`, { accessToken }));
}

export async function correctDocumentFields(
  accessToken: string,
  id: string,
  corrections: { field_name: string; value: string | null; reason?: string }[],
): Promise<DocumentDetail> {
  return unwrap(
    await apiFetch<DocumentDetail>(`/documents/${id}/fields`, {
      method: "PATCH",
      accessToken,
      body: { corrections },
    }),
  );
}

export async function reclassifyDocument(
  accessToken: string,
  id: string,
  body: { document_type: string; territory?: string | null; reason: string },
): Promise<{ document_id: string; job_id: string }> {
  return unwrap(
    await apiFetch<{ document_id: string; job_id: string }>(`/documents/${id}/reclassify`, {
      method: "POST",
      accessToken,
      body,
    }),
  );
}

export interface ConfirmationResult {
  document_id: string;
  request_id: string;
  extraction_status: string;
  confirmed_at: string;
  /** What matching did with the document the moment it was confirmed. */
  matching: MatchOutcome | null;
}

export async function confirmDocumentExtraction(
  accessToken: string,
  id: string,
): Promise<ConfirmationResult> {
  return unwrap(
    await apiFetch<ConfirmationResult>(`/documents/${id}/confirm`, {
      method: "POST",
      accessToken,
    }),
  );
}

export async function fetchTransactionList(
  accessToken: string,
  params: Record<string, string | number | boolean | undefined>,
): Promise<TransactionList> {
  return unwrap(
    await apiFetch<TransactionList>(`/transactions${buildQuery(params)}`, { accessToken }),
  );
}

export async function fetchTransactionDetail(
  accessToken: string,
  id: string,
): Promise<TransactionDetail> {
  return unwrap(await apiFetch<TransactionDetail>(`/transactions/${id}`, { accessToken }));
}

export async function fetchCommodityCodes(accessToken: string): Promise<CommodityCode[]> {
  return unwrap(
    await apiFetch<CommodityCode[]>("/transactions/commodity-codes", { accessToken }),
  );
}

export interface PurchaseTransactionCreate {
  stream: string;
  batch_number?: string | null;
  supplier_name: string;
  contract_number?: string | null;
  supplier_invoice_number?: string | null;
  invoice_status: string;
  commodity_code?: string | null;
  quantity_mt?: string | null;
  price_basis: string;
  lme_percentage?: string | null;
  currency: string;
  rate?: string | null;
  amount?: string | null;
  advance_payment_percent?: string | null;
  hedge_date?: string | null;
  hedge_low_price?: string | null;
  hedge_high_price?: string | null;
  port_of_loading?: string | null;
}

export async function createTransaction(
  accessToken: string,
  body: PurchaseTransactionCreate,
): Promise<TransactionDetail> {
  return unwrap(
    await apiFetch<TransactionDetail>("/transactions", {
      method: "POST",
      accessToken,
      body,
    }),
  );
}

export async function correctTransactionFields(
  accessToken: string,
  id: string,
  changes: { name: string; value: string | null; reason?: string }[],
): Promise<TransactionDetail> {
  return unwrap(
    await apiFetch<TransactionDetail>(`/transactions/${id}/fields`, {
      method: "PATCH",
      accessToken,
      body: { changes },
    }),
  );
}

export async function acknowledgeTolerance(
  accessToken: string,
  id: string,
  body: { rule_id: string; check_key?: string | null; reason: string },
): Promise<TransactionDetail> {
  return unwrap(
    await apiFetch<TransactionDetail>(`/transactions/${id}/acknowledge-tolerance`, {
      method: "POST",
      accessToken,
      body,
    }),
  );
}

export interface SalesLegCreate {
  customer_name: string;
  territory: string;
  sales_contract_no: string;
  payment_condition: string;
  contracted_quantity_mt?: string | null;
  quantity_mt?: string | null;
  sales_invoice_number?: string | null;
  bl_reference?: string | null;
  port_of_discharge?: string | null;
  inland_container_depot?: string | null;
  customer_fixation_status?: string;
  fixation_rate?: string | null;
  fixation_date?: string | null;
  document_id?: string | null;
  /** The explicit, visible acknowledgement required when no purchase counterpart exists. */
  acknowledge_no_purchase_leg?: boolean;
  acknowledgement_note?: string | null;
}

export interface SalesAttachmentResult {
  transaction: TransactionDetail;
  attachment: string;
  commodity_code_mismatch: boolean;
  commodity_message: string | null;
}

export async function attachSalesLeg(
  accessToken: string,
  id: string,
  body: SalesLegCreate,
): Promise<SalesAttachmentResult> {
  return unwrap(
    await apiFetch<SalesAttachmentResult>(`/transactions/${id}/sales-leg`, {
      method: "POST",
      accessToken,
      body,
    }),
  );
}

export interface DraftGenerationAccepted {
  transaction_id: string;
  document_type: string;
  job_id: string;
}

/**
 * Queue a draft generation. Returns the job id to poll through the existing job endpoint.
 *
 * The document produced is a draft for a person to read. There is no companion call anywhere in
 * this client that sends it to anybody, and there is not meant to be.
 */
export async function generateDraft(
  accessToken: string,
  id: string,
  documentType: string,
): Promise<DraftGenerationAccepted> {
  return unwrap(
    await apiFetch<DraftGenerationAccepted>(`/transactions/${id}/generate-draft`, {
      method: "POST",
      accessToken,
      body: { document_type: documentType },
    }),
  );
}

export async function submitTransaction(
  accessToken: string,
  id: string,
): Promise<SubmissionResult> {
  return unwrap(
    await apiFetch<SubmissionResult>(`/transactions/${id}/submit`, {
      method: "POST",
      accessToken,
    }),
  );
}

export async function fetchDocumentMatch(
  accessToken: string,
  documentId: string,
): Promise<MatchOutcome> {
  return unwrap(
    await apiFetch<MatchOutcome>(`/documents/${documentId}/match`, { accessToken }),
  );
}

export async function resolveDocumentMatch(
  accessToken: string,
  documentId: string,
  body: { decision: "confirm" | "reject"; transaction_id?: string | null },
): Promise<MatchOutcome> {
  return unwrap(
    await apiFetch<MatchOutcome>(`/documents/${documentId}/match`, {
      method: "POST",
      accessToken,
      body,
    }),
  );
}

export async function fetchJobStatus(accessToken: string, jobId: string): Promise<JobStatus> {
  return unwrap(await apiFetch<JobStatus>(`/jobs/${jobId}/status`, { accessToken }));
}

/**
 * Multipart upload with real per-file progress, which `fetch` cannot report - only
 * XMLHttpRequest exposes an upload progress event. Browser-only by construction.
 */
export function uploadDocuments(
  accessToken: string,
  form: FormData,
  onProgress?: (percent: number) => void,
): Promise<UploadAccepted> {
  const base = getClientEnv().NEXT_PUBLIC_API_BASE_URL.replace(/\/+$/, "");
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("POST", `${base}/documents/upload`);
    request.setRequestHeader("Authorization", `Bearer ${accessToken}`);
    request.setRequestHeader("Accept", "application/json");

    request.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable && onProgress) {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    });

    request.addEventListener("error", () =>
      reject(new ApiError(0, "network_error", "The API could not be reached.")),
    );
    request.addEventListener("abort", () =>
      reject(new ApiError(0, "aborted", "The upload was cancelled.")),
    );
    request.addEventListener("load", () => {
      let payload: ResponseEnvelope<UploadAccepted> | null = null;
      try {
        payload = JSON.parse(request.responseText) as ResponseEnvelope<UploadAccepted>;
      } catch {
        reject(
          new ApiError(
            request.status,
            "invalid_response",
            "The API returned a response that could not be read.",
          ),
        );
        return;
      }
      if (request.status >= 400 || payload?.success === false || !payload?.data) {
        const detail = payload?.errors?.[0];
        reject(
          new ApiError(
            request.status,
            detail?.code ?? "request_failed",
            payload?.message ?? detail?.message ?? `The API returned HTTP ${request.status}.`,
            payload?.errors ?? [],
          ),
        );
        return;
      }
      resolve(payload.data);
    });

    request.send(form);
  });
}

// --- exceptions and approvals ------------------------------------------------------------------

/** One of the ten queue tabs, exactly as the server describes it. */
export interface ExceptionCategoryInfo {
  category: string;
  label: string;
  owner_role: string;
  shared_with: string[];
  /** False for a category nothing in the platform can raise yet. */
  triggerable: boolean;
  description: string;
  dormant_reason: string | null;
  open_count: number;
}

export interface ExceptionCase {
  id: string;
  exception_type: string;
  exception_label: string | null;
  rule_id: string | null;
  check_key: string | null;
  owner_role: string;
  priority: string;
  summary: string;
  field_name: string | null;
  expected_value: string | null;
  actual_value: string | null;
  opened_at: string;
  resolved_at: string | null;
  escalated: boolean;
  transaction_id: string | null;
  document_id: string | null;
  batch_number: string | null;
  counterparty: string | null;
  value: string | null;
  currency: string | null;
  assigned_to_name: string | null;
  /** Computed by the server on every read from `opened_at`; never a stored flag. */
  age_hours: number;
  age_days: number;
  overdue: boolean;
  ageing_threshold_hours: number;
}

export interface ExceptionCaseDetail extends ExceptionCase {
  request_id: string | null;
  resolution_note: string | null;
  resolved_by_name: string | null;
  escalated_at: string | null;
  escalated_by_name: string | null;
  escalation_note: string | null;
  transaction_status: string | null;
  current_evaluation: RuleEvaluation | null;
  /** Null where the case has no rule behind it to re-check, such as a low-confidence read. */
  rule_now_passes: boolean | null;
  documents: DocumentSummary[];
  can_resolve: boolean;
  can_escalate: boolean;
  resolve_blocked_reason: string | null;
}

export interface ExceptionQueue {
  items: ExceptionCase[];
  page: PageInfo;
  categories: ExceptionCategoryInfo[];
  ageing_threshold_hours: number;
}

export interface ExceptionResolution {
  resolution_note: string;
  correction?: { name: string; value: string | null; reason?: string } | null;
  escalate_to_hod?: boolean;
}

export interface ApprovalRisk {
  label: string;
  score: number;
  reasons: string[];
  acknowledged_tolerance: boolean;
  prior_exception: boolean;
  /** The server's own verdict, and the only one that counts when the batch is submitted. */
  bulk_eligible: boolean;
}

export interface ApprovalListItem {
  id: string;
  transaction_id: string;
  batch_number: string;
  counterparty: string | null;
  contract_number: string | null;
  commodity_name: string | null;
  quantity_mt: string | null;
  value: string | null;
  currency: string;
  decision: string;
  requested_at: string;
  requested_by_name: string | null;
  decided_at: string | null;
  decided_by_name: string | null;
  reason: string | null;
  age_hours: number;
  age_days: number;
  overdue: boolean;
  risk: ApprovalRisk;
  requires_confirmation: boolean;
}

export interface ApprovalQueue {
  items: ApprovalListItem[];
  page: PageInfo;
  rank_by: string;
  confirmation_threshold: string;
  bulk_value_ceiling: string;
  overdue_threshold_hours: number;
  can_decide: boolean;
}

export interface ApprovalSummary {
  available: boolean;
  summary: string | null;
  what_to_check: string[];
  generated_at: string | null;
  /** Set when generation failed. The rest of the screen is complete without it. */
  unavailable_reason: string | null;
}

export interface ApprovalDetail extends ApprovalListItem {
  transaction_status: string;
  request_code: string | null;
  submitted_by_name: string | null;
  submitted_at: string | null;
  price_basis: string | null;
  lme_percentage: string | null;
  rate: string | null;
  invoice_status: string | null;
  supplier_invoice_number: string | null;
  port_of_loading: string | null;
  hedge_date: string | null;
  ai_summary: ApprovalSummary;
  rule_evaluations: RuleEvaluation[];
  documents: DocumentSummary[];
  open_exception_count: number;
  confirmation_threshold: string;
  can_decide: boolean;
}

export interface BulkApprovalOutcome {
  approval_id: string;
  transaction_id: string | null;
  batch_number: string | null;
  approved: boolean;
  message: string;
}

export interface BulkApprovalResult {
  approved: BulkApprovalOutcome[];
  rejected: BulkApprovalOutcome[];
  approved_count: number;
  skipped_count: number;
}

export async function fetchExceptionQueue(
  accessToken: string,
  params: Record<string, string | number | boolean | undefined>,
): Promise<ExceptionQueue> {
  return unwrap(
    await apiFetch<ExceptionQueue>(`/exceptions${buildQuery(params)}`, { accessToken }),
  );
}

export async function fetchExceptionCase(
  accessToken: string,
  id: string,
): Promise<ExceptionCaseDetail> {
  return unwrap(await apiFetch<ExceptionCaseDetail>(`/exceptions/${id}`, { accessToken }));
}

export async function resolveExceptionCase(
  accessToken: string,
  id: string,
  body: ExceptionResolution,
): Promise<ExceptionCaseDetail> {
  return unwrap(
    await apiFetch<ExceptionCaseDetail>(`/exceptions/${id}/resolve`, {
      method: "POST",
      accessToken,
      body,
    }),
  );
}

export async function fetchApprovalQueue(
  accessToken: string,
  params: Record<string, string | number | boolean | undefined>,
): Promise<ApprovalQueue> {
  return unwrap(await apiFetch<ApprovalQueue>(`/approvals${buildQuery(params)}`, { accessToken }));
}

export async function fetchApprovalDetail(
  accessToken: string,
  id: string,
): Promise<ApprovalDetail> {
  return unwrap(await apiFetch<ApprovalDetail>(`/approvals/${id}`, { accessToken }));
}

/**
 * Note what is absent: no decider and no timestamp. Both come from the verified token and the
 * server clock, and the endpoint has nowhere to put a client's version of either.
 */
export async function decideApproval(
  accessToken: string,
  id: string,
  body: { decision: string; reason?: string | null; confirm_above_threshold?: boolean },
): Promise<ApprovalListItem> {
  return unwrap(
    await apiFetch<ApprovalListItem>(`/approvals/${id}/decide`, {
      method: "POST",
      accessToken,
      body,
    }),
  );
}

export async function bulkApprove(
  accessToken: string,
  approvalIds: string[],
): Promise<BulkApprovalResult> {
  return unwrap(
    await apiFetch<BulkApprovalResult>("/approvals/bulk-decide", {
      method: "POST",
      accessToken,
      body: { approval_ids: approvalIds },
    }),
  );
}


// --- shipments ---------------------------------------------------------------------------------

export async function fetchShipmentList(
  accessToken: string,
  params: Record<string, string | number | boolean | undefined>,
): Promise<ShipmentList> {
  return unwrap(await apiFetch<ShipmentList>(`/shipments${buildQuery(params)}`, { accessToken }));
}

export async function fetchShipmentDetail(
  accessToken: string,
  id: string,
): Promise<ShipmentDetail> {
  return unwrap(await apiFetch<ShipmentDetail>(`/shipments/${id}`, { accessToken }));
}

/**
 * Pull this shipment's status through whatever carrier adapter handles it.
 *
 * Where none does - which today is every shipment - the result says so and the record stays open
 * for manual entry. That is a working outcome, and the screen renders it as one.
 */
export async function refreshShipment(
  accessToken: string,
  id: string,
): Promise<ShipmentRefreshResult> {
  return unwrap(
    await apiFetch<ShipmentRefreshResult>(`/shipments/${id}/refresh`, {
      method: "POST",
      accessToken,
    }),
  );
}

export async function updateShipment(
  accessToken: string,
  id: string,
  body: ShipmentManualUpdate,
): Promise<ShipmentDetail> {
  return unwrap(
    await apiFetch<ShipmentDetail>(`/shipments/${id}`, {
      method: "PATCH",
      accessToken,
      body,
    }),
  );
}

export async function logShipmentIssue(
  accessToken: string,
  id: string,
  body: { issue_type: string; description: string; document_id?: string | null },
): Promise<ShipmentIssue> {
  return unwrap(
    await apiFetch<ShipmentIssue>(`/shipments/${id}/issues`, {
      method: "POST",
      accessToken,
      body,
    }),
  );
}

/**
 * The configured FA fields with no named column, read before any transaction exists.
 *
 * The registration form and the workspace panel both render from this one source, so neither can
 * drift from the configuration or from the other.
 */
export async function fetchFaFieldSchema(accessToken: string): Promise<FaFieldSchema[]> {
  return unwrap(
    await apiFetch<FaFieldSchema[]>("/transactions/fa/schema", { accessToken }),
  );
}

export async function createFaTransaction(
  accessToken: string,
  body: FaTransactionCreate,
): Promise<TransactionDetail> {
  return unwrap(
    await apiFetch<TransactionDetail>("/transactions/fa", {
      method: "POST",
      accessToken,
      body,
    }),
  );
}

// --- integrations (Step 7) -----------------------------------------------------------------------

/** Mirrors the backend `IntegrationJobRead` schema. */
export interface IntegrationJob {
  id: string;
  transaction_id: string;
  target_system: string;
  target_label: string | null;
  status: string;
  external_reference: string | null;
  failure_reason: string | null;
  attempt_count: number;
  max_attempts: number;
  /**
   * Always present, never optional. A job that succeeded because a person finished the posting
   * by hand must never be readable as one the platform made itself.
   */
  completed_manually: boolean;
  completed_manually_by_name: string | null;
  completed_manually_at: string | null;
  manual_note: string | null;
  manual_instruction: string | null;
  last_attempted_at: string | null;
  /** Null for anything not waiting on the clock - including every job waiting on a person. */
  next_attempt_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface IntegrationJobDetail extends IntegrationJob {
  batch_number: string | null;
  counterparty: string | null;
  transaction_status: string | null;
  /** What a person needs in front of them to finish the posting. Business data only. */
  prepared_payload: Record<string, unknown> | null;
  /** Whether this deployment can post to that target automatically at all. */
  target_configured: boolean;
}

export interface IntegrationJobQueue {
  items: IntegrationJobDetail[];
  page: PageInfo;
  counts_by_target: Record<string, number>;
  counts_by_status: Record<string, number>;
  configured_targets: Record<string, boolean>;
  max_attempts: number;
}

export async function fetchIntegrationJobs(
  accessToken: string,
  params: Record<string, string | number | boolean | undefined>,
): Promise<IntegrationJobQueue> {
  return unwrap(
    await apiFetch<IntegrationJobQueue>(`/integrations/jobs${buildQuery(params)}`, {
      accessToken,
    }),
  );
}

/**
 * Re-queue and immediately re-attempt a job that genuinely failed.
 *
 * Deliberately not offered for a job awaiting manual action: there is nothing automated left to
 * attempt on one, and the API refuses it by name rather than quietly doing nothing.
 */
export async function retryIntegrationJob(
  accessToken: string,
  id: string,
): Promise<IntegrationJobDetail> {
  return unwrap(
    await apiFetch<IntegrationJobDetail>(`/integrations/jobs/${id}/retry`, {
      method: "POST",
      accessToken,
    }),
  );
}

/**
 * Record that a person completed the posting outside the platform.
 *
 * Both the reference and the note are required by the API. The resulting job is marked as a
 * manual completion for the rest of its life.
 */
export async function completeIntegrationJobManually(
  accessToken: string,
  id: string,
  body: { external_reference: string; note: string },
): Promise<IntegrationJobDetail> {
  return unwrap(
    await apiFetch<IntegrationJobDetail>(`/integrations/jobs/${id}/complete-manual`, {
      method: "POST",
      accessToken,
      body,
    }),
  );
}

// --- dashboard, analytics and reports (Step 8) ----------------------------------------------------

/** One number, and the query that reproduces it. Mirrors the backend `FigureRead` schema. */
export interface Figure {
  key: string;
  label: string;
  value: number | null;
  unit: string;
  /** Which screen the drill-through opens. Null where the figure is descriptive, not navigable. */
  target: string | null;
  filters: Record<string, unknown>;
  note: string | null;
}

export interface ExceptionAgeing {
  under_24h: number;
  "24_to_72h": number;
  over_72h: number;
}

export interface ExceptionCategoryCount {
  category: string;
  label: string;
  open_count: number;
  escalated_count: number;
  ageing: ExceptionAgeing;
  oldest_age_hours: number | null;
  target: string;
  filters: Record<string, unknown>;
}

export interface ExceptionSummary {
  categories: ExceptionCategoryCount[];
  total_open: number;
  over_72h: number;
  bands: { key: string; label: string; from_hours: number; to_hours: number | null }[];
  computed_at: string;
}

export interface ApprovalSummary {
  pending: number;
  oldest_waiting_hours: number | null;
  target: string;
  filters: Record<string, unknown>;
}

/**
 * Failed and awaiting-a-person are two fields here and are never added together anywhere.
 * A posting waiting on somebody is not a failure, and this interface makes that structural.
 */
export interface IntegrationSummary {
  by_status: Record<string, number>;
  failed: number;
  awaiting_manual_action: number;
  succeeded: number;
  in_flight: number;
  completed_manually: number;
  separation_note: string;
}

export interface ShipmentStatusCount {
  status: string;
  label: string;
  count: number;
  target: string;
  filters: Record<string, unknown>;
}

export interface ShipmentSummary {
  by_status: ShipmentStatusCount[];
  total: number;
  stale_count: number;
  stale_threshold_hours: number;
  stale_target: string;
  stale_filters: Record<string, unknown>;
}

export interface ExtractionByDocumentType {
  document_type: string;
  field_count: number;
  overridden_count: number;
  non_override_rate: number | null;
  target: string;
  filters: Record<string, unknown>;
}

/**
 * A non-override rate, and labelled as one everywhere it is rendered.
 *
 * `disclosure` travels with the figure rather than being written into the component, so no screen
 * can show this number without the sentence that says what it is and is not.
 */
export interface ExtractionSummary {
  field_count: number;
  overridden_count: number;
  non_override_rate: number | null;
  by_document_type: ExtractionByDocumentType[];
  measure: string;
  disclosure: string;
}

export interface TurnaroundSummary {
  sample_size: number;
  mean_hours: number | null;
  median_hours: number | null;
  fastest_hours: number | null;
  slowest_hours: number | null;
  definition: string;
}

export interface AutomationSummary {
  approved_count: number;
  exception_free_count: number;
  intervened_count: number;
  automation_rate: number | null;
  definition: string;
}

export interface TrendBucket {
  bucket_start: string;
  bucket_end: string;
  approved_count: number;
  mean_hours: number | null;
  median_hours: number | null;
  exception_free_count: number;
  intervened_count: number;
  automation_rate: number | null;
}

export interface DashboardSummary {
  generated_at: string;
  period: { start: string; end: string };
  /** Which panel this account's dashboard leads with. Ordering only; nothing is hidden by it. */
  emphasis: string;
  streams: string[];
  scope_note: string;
  tiles: Figure[];
  transactions_by_status: Figure[];
  exceptions: ExceptionSummary;
  approvals: ApprovalSummary;
  integrations: IntegrationSummary;
  shipments: ShipmentSummary;
  extraction: ExtractionSummary;
  turnaround: TurnaroundSummary;
  automation: AutomationSummary;
  turnaround_trend: TrendBucket[];
  definitions: Record<string, string>;
  cache_age_seconds: number;
  cache_ttl_seconds: number;
}

export interface KpiTrends {
  generated_at: string;
  period: { start: string; end: string };
  interval: string;
  streams: string[];
  scope_note: string;
  turnaround: TurnaroundSummary;
  automation: AutomationSummary;
  extraction: ExtractionSummary;
  series: TrendBucket[];
  transactions_by_status: Figure[];
  approval_decisions: Record<string, number>;
  definitions: Record<string, string>;
  cache_age_seconds: number;
  cache_ttl_seconds: number;
}

export interface ReportListItem {
  id: string;
  report_type: string;
  output_format: string;
  template_key: string;
  title: string;
  period_start: string;
  period_end: string;
  stream: string;
  status_filter: string | null;
  generation_reference: string;
  byte_size: number | null;
  generated_at: string;
  generated_by_name: string | null;
  /** True where nobody asked for it: the schedule produced it. */
  scheduled: boolean;
  ai_summary_error: string | null;
}

export interface ReportSection {
  key: string;
  title: string;
  kind: string;
  description: string | null;
  figures?: Figure[];
  columns?: { key: string; label: string }[];
  rows?: Record<string, unknown>[];
  note?: string | null;
  total?: number | null;
  text?: string | null;
  unavailable_reason?: string | null;
  ai_generated?: boolean;
  truncated?: boolean;
  total_matching?: number;
  target?: string | null;
  filters?: Record<string, unknown>;
}

export interface ReportContent {
  title: string;
  description: string;
  report_type: string;
  template_key: string;
  generation_reference: string;
  generated_at: string;
  generated_by: string | null;
  period: { start: string; end: string };
  stream: string;
  status_filter: string | null;
  sections: ReportSection[];
  disclosures: string[];
  definitions: Record<string, string>;
}

export interface ReportDetail extends ReportListItem {
  parameters: Record<string, unknown>;
  content: ReportContent;
  /** Short-lived and signed, minted per request. There is no permanent path to a report file. */
  download_url: string | null;
  audit_event_id: string | null;
  distribution_note: string;
}

export interface ReportList {
  items: ReportListItem[];
  page: PageInfo;
  can_generate: boolean;
}

export interface ReportGenerationAccepted {
  job_id: string;
  poll_url: string;
  message: string;
}

export async function fetchDashboardSummary(
  accessToken: string,
  params: Record<string, string | number | boolean | undefined> = {},
): Promise<DashboardSummary> {
  return unwrap(
    await apiFetch<DashboardSummary>(`/dashboards/summary${buildQuery(params)}`, { accessToken }),
  );
}

export async function fetchKpiTrends(
  accessToken: string,
  params: Record<string, string | number | boolean | undefined> = {},
): Promise<KpiTrends> {
  return unwrap(await apiFetch<KpiTrends>(`/dashboards/kpis${buildQuery(params)}`, { accessToken }));
}

export async function fetchReports(
  accessToken: string,
  params: Record<string, string | number | boolean | undefined> = {},
): Promise<ReportList> {
  return unwrap(await apiFetch<ReportList>(`/reports${buildQuery(params)}`, { accessToken }));
}

export async function fetchReportDetail(
  accessToken: string,
  id: string,
): Promise<ReportDetail> {
  return unwrap(await apiFetch<ReportDetail>(`/reports/${id}`, { accessToken }));
}

/**
 * Queue one generation. Every call produces a new report; nothing is ever overwritten, and the
 * platform sends the result to nobody.
 */
export async function requestReport(
  accessToken: string,
  body: {
    report_type: string;
    output_format: string;
    date_from: string;
    date_to: string;
    stream: string;
    status?: string | null;
  },
): Promise<ReportGenerationAccepted> {
  return unwrap(
    await apiFetch<ReportGenerationAccepted>("/reports", {
      method: "POST",
      accessToken,
      body,
    }),
  );
}

// --- administration, audit, settings and notifications (Step 9) -----------------------------------

/** Mirrors the backend `RuleConfigurationRead` schema. */
export interface RuleConfigurationRow {
  id: string;
  rule_id: string;
  check_key: string;
  scope_commodity_code: string | null;
  scope_transaction_type: string | null;
  scope_stream: string | null;
  threshold_value: string;
  threshold_unit: string;
  description: string | null;
  is_active: boolean;
  change_reason: string;
  changed_at: string;
  changed_by_name: string | null;
  rule_title: string | null;
  rule_statement: string | null;
}

export interface RuleConfigurationList {
  items: RuleConfigurationRow[];
  /** Read from the data, so a rule a later step seeds appears in the filter without a change. */
  rule_ids: string[];
  streams: string[];
}

export interface ReportDistributionRuleRow {
  id: string;
  report_type: string;
  recipient_roles: string[];
  recipient_user_ids: string[];
  channel: string;
  is_active: boolean;
  change_reason: string;
  changed_at: string;
  changed_by_name: string | null;
  /** Who the rule reaches as things stand, resolved server-side the way the sender resolves it. */
  recipient_names: string[];
}

export interface ReportDistributionRuleList {
  items: ReportDistributionRuleRow[];
  report_types: string[];
  channels: string[];
  roles: string[];
}

export interface ReportDistributionRuleBody {
  change_reason: string;
  report_type: string;
  recipient_roles: string[];
  recipient_user_ids: string[];
  channel: string;
  is_active: boolean;
}

export interface ReportTemplateSection {
  key: string;
  title: string;
  kind: string;
  source: string;
  description: string | null;
  figures: string[];
}

export interface ReportTemplateRow {
  id: string;
  template_key: string;
  report_type: string;
  title: string;
  description: string;
  sections: ReportTemplateSection[];
  disclosures: string[];
  wants_ai_summary: boolean;
  include_detail_rows: boolean;
  default_period_days: number;
  change_reason: string;
  changed_at: string;
  changed_by_name: string | null;
  section_count: number;
}

export interface ReportTemplateList {
  items: ReportTemplateRow[];
  report_types: string[];
  section_kinds: string[];
  section_sources: string[];
  /** The headline figures a KPI grid may narrow to, read from the service that computes them. */
  headline_figures: string[];
}

export interface ReportTemplateBody {
  change_reason: string;
  title?: string;
  description?: string;
  sections?: ReportTemplateSection[];
  disclosures?: string[];
}

export interface DocumentTypeSchemaRow {
  id: string;
  document_type: string;
  territory: string | null;
  field_schema: { fields?: DocumentSchemaField[] } & Record<string, unknown>;
  mandatory_documents: string[];
  change_reason: string;
  changed_at: string;
  changed_by_name: string | null;
  field_count: number;
  required_field_count: number;
}

export interface DocumentSchemaField {
  name: string;
  label?: string;
  type: string;
  required?: boolean;
  tolerance?: string | null;
  section?: string | null;
  description?: string | null;
}

export interface DocumentTypeSchemaList {
  items: DocumentTypeSchemaRow[];
  document_types: string[];
  territories: string[];
}

export interface AdminUser {
  id: string;
  email: string;
  display_name: string;
  roles: string[];
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
}

export interface AdminUserList {
  items: AdminUser[];
  assignable_roles: string[];
  /** Whether this deployment holds a Keycloak Admin API credential at all. */
  identity_provider_configured: boolean;
  provisioning_note: string;
}

export interface UserRoleUpdateResult {
  user: AdminUser;
  roles_added: string[];
  roles_removed: string[];
  identity_provider_confirmed: boolean;
}

export interface AuditEventRow {
  id: string;
  occurred_at: string;
  actor_id: string | null;
  actor_name: string | null;
  actor_email: string | null;
  actor_type: string;
  event_type: string;
  entity_type: string;
  entity_id: string | null;
  /** Redacted by key and bounded by length on the server. Never document or prompt text. */
  metadata: Record<string, unknown>;
}

export interface AuditActor {
  id: string;
  display_name: string;
  email: string;
}

export interface AuditEventList {
  items: AuditEventRow[];
  page: PageInfo;
  event_types: string[];
  entity_types: string[];
  actors: AuditActor[];
}

export interface NotificationRow {
  id: string;
  notification_type: string;
  message: string;
  /** Always an in-app path. Nothing here ever carries an absolute URL. */
  link: string | null;
  is_read: boolean;
  created_at: string;
}

export interface NotificationList {
  items: NotificationRow[];
  page: PageInfo;
  unread_count: number;
}

export interface MarkAllReadResult {
  marked: number;
  unread_count: number;
}

export async function fetchRuleConfigurations(
  accessToken: string,
  params: Record<string, string | number | boolean | undefined> = {},
): Promise<RuleConfigurationList> {
  return unwrap(
    await apiFetch<RuleConfigurationList>(`/admin/rules${buildQuery(params)}`, { accessToken }),
  );
}

/** The reason is mandatory here because it is mandatory on the server, not the other way round. */
export async function updateRuleConfiguration(
  accessToken: string,
  id: string,
  body: {
    change_reason: string;
    threshold_value?: string;
    is_active?: boolean;
    description?: string;
  },
): Promise<RuleConfigurationRow> {
  return unwrap(
    await apiFetch<RuleConfigurationRow>(`/admin/rules/${id}`, {
      method: "PATCH",
      accessToken,
      body,
    }),
  );
}

/** Record that this account has seen the first-login walkthrough. Self-only on the server. */
export async function completeOnboarding(accessToken: string): Promise<UserProfile> {
  return unwrap(
    await apiFetch<UserProfile>("/users/me/onboarding-complete", {
      method: "POST",
      accessToken,
    }),
  );
}

export interface GraphNodeRead {
  id: string;
  label: string;
  title: string;
}

export interface GraphEdgeRead {
  source: string;
  target: string;
  type: string;
}

export interface TransactionGraph {
  transaction_id: string;
  batch_number: string;
  /** False when no projection is configured or it could not be reached — which is not the same
   *  claim as "this transaction is connected to nothing". */
  available: boolean;
  nodes: GraphNodeRead[];
  edges: GraphEdgeRead[];
}

export async function fetchTransactionGraph(
  accessToken: string,
  transactionId: string,
): Promise<TransactionGraph> {
  return unwrap(
    await apiFetch<TransactionGraph>(`/transactions/${transactionId}/graph`, { accessToken }),
  );
}

export async function fetchReportDistributionRules(
  accessToken: string,
  params: Record<string, string | number | boolean | undefined> = {},
): Promise<ReportDistributionRuleList> {
  return unwrap(
    await apiFetch<ReportDistributionRuleList>(`/admin/report-distribution${buildQuery(params)}`, {
      accessToken,
    }),
  );
}

/** Adding a rule is the only thing that makes a scheduled report reach anybody. */
export async function createReportDistributionRule(
  accessToken: string,
  body: ReportDistributionRuleBody,
): Promise<ReportDistributionRuleRow> {
  return unwrap(
    await apiFetch<ReportDistributionRuleRow>("/admin/report-distribution", {
      method: "POST",
      accessToken,
      body,
    }),
  );
}

export async function updateReportDistributionRule(
  accessToken: string,
  id: string,
  body: ReportDistributionRuleBody,
): Promise<ReportDistributionRuleRow> {
  return unwrap(
    await apiFetch<ReportDistributionRuleRow>(`/admin/report-distribution/${id}`, {
      method: "PATCH",
      accessToken,
      body,
    }),
  );
}

/** What each report is made of. Never what it says: every figure is still computed at
 * generation time from the governed tables. */
export async function fetchReportTemplates(
  accessToken: string,
  params: Record<string, string | number | boolean | undefined> = {},
): Promise<ReportTemplateList> {
  return unwrap(
    await apiFetch<ReportTemplateList>(`/admin/report-templates${buildQuery(params)}`, {
      accessToken,
    }),
  );
}

export async function updateReportTemplate(
  accessToken: string,
  id: string,
  body: ReportTemplateBody,
): Promise<ReportTemplateRow> {
  return unwrap(
    await apiFetch<ReportTemplateRow>(`/admin/report-templates/${id}`, {
      method: "PATCH",
      accessToken,
      body,
    }),
  );
}

export async function fetchDocumentTypeSchemas(
  accessToken: string,
  params: Record<string, string | number | boolean | undefined> = {},
): Promise<DocumentTypeSchemaList> {
  return unwrap(
    await apiFetch<DocumentTypeSchemaList>(`/admin/document-types${buildQuery(params)}`, {
      accessToken,
    }),
  );
}

export async function updateDocumentTypeSchema(
  accessToken: string,
  id: string,
  body: {
    change_reason: string;
    field_schema?: { fields: DocumentSchemaField[] };
    mandatory_documents?: string[];
  },
): Promise<DocumentTypeSchemaRow> {
  return unwrap(
    await apiFetch<DocumentTypeSchemaRow>(`/admin/document-types/${id}`, {
      method: "PATCH",
      accessToken,
      body,
    }),
  );
}

export async function fetchAdminUsers(
  accessToken: string,
  params: Record<string, string | number | boolean | undefined> = {},
): Promise<AdminUserList> {
  return unwrap(
    await apiFetch<AdminUserList>(`/admin/users${buildQuery(params)}`, { accessToken }),
  );
}

/**
 * Override an account's roles.
 *
 * The API calls Keycloak first and commits nothing locally until Keycloak confirms, so a
 * rejection from this call means nothing changed anywhere — which is exactly what the screen
 * tells the administrator when it catches the error.
 */
export async function updateUserRoles(
  accessToken: string,
  body: { user_id: string; roles: string[]; change_reason: string },
): Promise<UserRoleUpdateResult> {
  return unwrap(
    await apiFetch<UserRoleUpdateResult>("/admin/users", {
      method: "PATCH",
      accessToken,
      body,
    }),
  );
}

export async function fetchAuditEvents(
  accessToken: string,
  params: Record<string, string | number | boolean | undefined> = {},
): Promise<AuditEventList> {
  return unwrap(await apiFetch<AuditEventList>(`/audit${buildQuery(params)}`, { accessToken }));
}

/**
 * The export URL, built rather than fetched.
 *
 * The response is a streamed CSV, not an envelope, so it is never pulled through `apiFetch` and
 * never buffered in the browser: the anchor hands the stream to the browser's own downloader.
 */
export function auditExportUrl(params: Record<string, string | undefined>): string {
  const base =
    typeof window === "undefined"
      ? getServerEnv().API_INTERNAL_BASE_URL
      : getClientEnv().NEXT_PUBLIC_API_BASE_URL;
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value) search.set(key, value);
  }
  const query = search.toString();
  return `${base.replace(/\/+$/, "")}/audit/export${query ? `?${query}` : ""}`;
}

/** Streams the export through the caller's own token and hands the browser a Blob to save. */
export async function downloadAuditExport(
  accessToken: string,
  params: Record<string, string | undefined>,
): Promise<Blob> {
  const response = await fetch(auditExportUrl(params), {
    headers: { Authorization: `Bearer ${accessToken}`, Accept: "text/csv" },
    cache: "no-store",
  });
  if (!response.ok) {
    throw new ApiError(response.status, "export_failed", "The audit export could not be produced.");
  }
  return response.blob();
}

export async function updateMyPreferences(
  accessToken: string,
  body: { notification_channel?: string; default_stream_filter?: string | null },
): Promise<UserProfile> {
  return unwrap(
    await apiFetch<UserProfile>("/users/me/preferences", {
      method: "PATCH",
      accessToken,
      body,
    }),
  );
}

export async function fetchNotifications(
  accessToken: string,
  params: Record<string, string | number | boolean | undefined> = {},
): Promise<NotificationList> {
  return unwrap(
    await apiFetch<NotificationList>(`/notifications${buildQuery(params)}`, { accessToken }),
  );
}

export async function markAllNotificationsRead(
  accessToken: string,
): Promise<MarkAllReadResult> {
  return unwrap(
    await apiFetch<MarkAllReadResult>("/notifications/mark-all-read", {
      method: "POST",
      accessToken,
    }),
  );
}


// --- push subscriptions (Step 10) -----------------------------------------------------------

export interface VapidPublicKey {
  public_key: string;
  /** False on a deployment that has generated no key pair. The screen says so rather than
      offering a button that cannot work. */
  configured: boolean;
}

export interface PushSubscriptionRecord {
  id: string;
  endpoint: string;
  user_agent: string | null;
  created_at: string;
  last_used_at: string | null;
}

export interface PushUnsubscribeResult {
  removed: number;
}

export async function fetchVapidPublicKey(accessToken: string): Promise<VapidPublicKey> {
  return unwrap(
    await apiFetch<VapidPublicKey>("/notifications/vapid-public-key", { accessToken }),
  );
}

export async function savePushSubscription(
  accessToken: string,
  body: { endpoint: string; keys: { p256dh: string; auth: string } },
): Promise<PushSubscriptionRecord> {
  return unwrap(
    await apiFetch<PushSubscriptionRecord>("/notifications/push-subscribe", {
      method: "POST",
      accessToken,
      body,
    }),
  );
}

/** Without an endpoint this forgets every browser on the account, which is what a sign-out on a
    shared machine should be able to ask for. */
export async function removePushSubscription(
  accessToken: string,
  endpoint?: string,
): Promise<PushUnsubscribeResult> {
  return unwrap(
    await apiFetch<PushUnsubscribeResult>("/notifications/push-subscribe", {
      method: "DELETE",
      accessToken,
      body: { endpoint: endpoint ?? null },
    }),
  );
}
