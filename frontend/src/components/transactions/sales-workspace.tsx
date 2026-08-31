"use client";

import Link from "next/link";
import { useSession } from "next-auth/react";
import { useCallback, useMemo, useRef, useState } from "react";
import toast from "react-hot-toast";

import { PageViewer } from "@/components/intake/page-viewer";
import { AiDisclaimer } from "@/components/shared/ai-disclaimer";
import { PageHeader } from "@/components/shared/page-header";
import { CollapsiblePanel } from "@/components/transactions/collapsible-panel";
import { GenerateDraftPanel } from "@/components/transactions/generate-draft-panel";
import { HistoryPanel } from "@/components/transactions/history-panel";
import { IntegrationPanel } from "@/components/transactions/integration-panel";
import { LinkedPurchaseCard } from "@/components/transactions/linked-purchase-card";
import { LinkedShipmentCard } from "@/components/transactions/linked-shipment-card";
import { MatchingPanel } from "@/components/transactions/matching-panel";
import { PriceFixationDialog } from "@/components/transactions/price-fixation-dialog";
import { QuantityMeter } from "@/components/transactions/quantity-meter";
import {
  MIN_REASON,
  TransactionFieldEditor,
  type FieldDraft,
} from "@/components/transactions/transaction-field-editor";
import { ValidationPanel } from "@/components/transactions/validation-panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import {
  ApiError,
  acknowledgeTolerance,
  correctTransactionFields,
  fetchDocumentDetail,
  fetchTransactionDetail,
  submitTransaction,
  type CommodityCode,
  type DocumentDetail,
  type RuleEvaluation,
  type TransactionDetail,
  type TransactionField,
} from "@/lib/api-client";
import { labelFor } from "@/lib/intake";
import {
  FIXATION_STATUS_LABELS,
  GENERATED_DOCUMENT_LABELS,
  GENERATED_DOCUMENT_NOTES,
  PAYMENT_CONDITION_LABELS,
  SALES_GENERATED_DOCUMENT_TYPES,
  TERRITORY_LABELS,
  LOCKED_TRANSACTION_STATUSES,
  TRANSACTION_STATUS_CHIP,
  TRANSACTION_STATUS_LABELS,
  formatMoney,
  formatQuantity,
  submitBlocker,
  type TransactionStatus,
} from "@/lib/transactions";
import { cn } from "@/lib/utils";

export interface SalesWorkspaceProps {
  initial: TransactionDetail;
  initialDocument: DocumentDetail | null;
  commodities: CommodityCode[];
  canEdit: boolean;
}

/**
 * The sell side of one batch.
 *
 * The split layout, the Extraction / Matching / Validation / History accordion and the sticky
 * save-and-submit bar are the Purchase Transaction Workspace's, reused component for component
 * rather than rebuilt. What is genuinely new here are three panels, and they sit above the
 * accordion rather than inside it because none of them is something a user should have to open:
 *
 * - the linked purchase leg, so the two sides of one cargo are visible together and a genuine
 *   commodity-code disagreement is impossible to miss;
 * - the quantity meter, which is a fact about the whole sales contract rather than this shipment;
 * - the draft panel, which is the desk's actual daily work on this screen.
 *
 * Submit stays disabled with the specific still-failing rule named, exactly as on the purchase
 * side - and on a sales transaction that reason is very often BR-07's missing final bill of
 * lading, which is a real answer rather than a generic "not ready".
 */
export function SalesWorkspace({
  initial,
  initialDocument,
  commodities,
  canEdit,
}: SalesWorkspaceProps) {
  const { data: session } = useSession();
  const [detail, setDetail] = useState(initial);
  const [document, setDocument] = useState(initialDocument);
  const [drafts, setDrafts] = useState<Record<string, FieldDraft>>({});
  const [saving, setSaving] = useState(false);
  const [acknowledging, setAcknowledging] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [fixationOpen, setFixationOpen] = useState(false);
  const fieldsRef = useRef<HTMLDivElement>(null);

  const token = session?.accessToken;
  // Locked from the moment it leaves the desk: waiting on a decision, decided, or being posted
  // downstream. A figure corrected after the approver saw it, or after SAP was told about it,
  // would put this platform and the systems it feeds out of step with each other.
  const locked = LOCKED_TRANSACTION_STATUSES.includes(detail.status as TransactionStatus);
  const editable = canEdit && detail.can_edit && !locked;
  const blocker = useMemo(() => submitBlocker(detail.rule_evaluations), [detail.rule_evaluations]);
  const failing = detail.rule_evaluations.filter((rule) => !rule.passed).length;
  const sales = detail.sales_leg;

  const sections = useMemo(() => groupBySection(detail.fields), [detail.fields]);
  const pending = Object.entries(drafts);
  const missingReason = pending.some(([name, draft]) => {
    const field = detail.fields.find((row) => row.name === name);
    return Boolean(field?.reason_required) && draft.reason.trim().length < MIN_REASON;
  });

  const refresh = useCallback(async () => {
    if (!token) return;
    try {
      setDetail(await fetchTransactionDetail(token, detail.id));
    } catch {
      // A failed refresh leaves the screen showing what it already had, which is still true.
    }
  }, [token, detail.id]);

  const openDocument = useCallback(
    async (documentId: string) => {
      if (!token) return;
      try {
        setDocument(await fetchDocumentDetail(token, documentId));
      } catch {
        // The panels are the substance of this page; a viewer that cannot load its pages is not
        // a reason to replace them with an error.
      }
    },
    [token],
  );

  async function save() {
    if (!token) {
      toast.error("Your session has expired. Sign in again to save these corrections.");
      return;
    }
    if (pending.length === 0) return;

    setSaving(true);
    try {
      const updated = await correctTransactionFields(
        token,
        detail.id,
        pending.map(([name, draft]) => ({
          name,
          value: draft.value.trim() || null,
          reason: draft.reason.trim() || undefined,
        })),
      );
      setDetail(updated);
      setDrafts({});
      toast.success(
        `${pending.length} field${pending.length === 1 ? "" : "s"} corrected. Validation has been re-run.`,
      );
    } catch (error) {
      toast.error(
        error instanceof ApiError ? error.message : "The corrections could not be saved.",
      );
    } finally {
      setSaving(false);
    }
  }

  async function recordFixation(rate: string, fixedOn: string) {
    if (!token) {
      toast.error("Your session has expired. Sign in again to record this fixation.");
      return;
    }
    setSaving(true);
    try {
      // The ordinary correction endpoint. A fixation is a change to the deal, and it earns the
      // same provenance record and the same re-validation as any other.
      setDetail(
        await correctTransactionFields(token, detail.id, [
          { name: "fixation_rate", value: rate },
          { name: "fixation_date", value: fixedOn },
        ]),
      );
      setFixationOpen(false);
      toast.success("Price fixation recorded. Every check has been re-run against it.");
    } catch (error) {
      toast.error(
        error instanceof ApiError ? error.message : "The fixation could not be recorded.",
      );
    } finally {
      setSaving(false);
    }
  }

  async function acknowledge(rule: RuleEvaluation, reason: string) {
    if (!token) {
      toast.error("Your session has expired. Sign in again to acknowledge this.");
      return;
    }
    setAcknowledging(rule.id);
    try {
      setDetail(
        await acknowledgeTolerance(token, detail.id, {
          rule_id: rule.rule_id,
          check_key: rule.check_key,
          reason,
        }),
      );
      toast.success(`${rule.rule_id} acknowledged and recorded against your account.`);
    } catch (error) {
      toast.error(
        error instanceof ApiError ? error.message : "The acknowledgement could not be recorded.",
      );
    } finally {
      setAcknowledging(null);
    }
  }

  async function submit() {
    if (!token) {
      toast.error("Your session has expired. Sign in again to submit.");
      return;
    }
    setSubmitting(true);
    try {
      const result = await submitTransaction(token, detail.id);
      setDetail((current) => ({
        ...current,
        status: result.status,
        submitted_at: result.submitted_at,
        can_edit: false,
        can_submit: false,
      }));
      toast.success(
        `Batch ${detail.batch_number} is waiting for departmental approval. Nothing has been posted or sent anywhere else.`,
      );
    } catch (error) {
      toast.error(
        error instanceof ApiError ? error.message : "The transaction could not be submitted.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  const submitButton = (
    <Button
      onClick={submit}
      disabled={
        !editable ||
        submitting ||
        Boolean(blocker) ||
        pending.length > 0 ||
        detail.rule_evaluations.length === 0
      }
    >
      {locked ? "Submitted for approval" : submitting ? "Submitting…" : "Submit for approval"}
    </Button>
  );

  return (
    <div className="space-y-6 pb-24">
      <PageHeader
        title={detail.batch_number}
        description={
          sales
            ? `${sales.customer_name} · ${sales.sales_contract_no}`
            : "No sales leg is attached to this transaction."
        }
        actions={
          <div className="flex flex-wrap gap-2">
            {detail.purchase_leg ? (
              <Button asChild variant="outline" size="sm">
                <Link href={`/transactions/purchase/${detail.id}`}>Purchase view</Link>
              </Button>
            ) : null}
            <Button asChild variant="outline" size="sm">
              <Link href="/transactions">Back to transactions</Link>
            </Button>
          </div>
        }
      />

      <AiDisclaimer />

      <div className="flex flex-wrap items-center gap-2">
        <Badge
          variant="outline"
          className={cn(
            TRANSACTION_STATUS_CHIP[detail.status as TransactionStatus] ??
            "border-border bg-muted text-muted-foreground",
          )}
        >
          {labelFor(TRANSACTION_STATUS_LABELS, detail.status)}
        </Badge>
        {sales ? (
          <>
            <Badge variant="muted">{labelFor(TERRITORY_LABELS, sales.territory)}</Badge>
            <Badge variant="muted">
              {labelFor(PAYMENT_CONDITION_LABELS, sales.payment_condition)}
            </Badge>
            <Badge
              variant="outline"
              className={cn(
                sales.customer_fixation_status === "fixed"
                  ? "border-signal-confident/35 bg-signal-confident/10 text-signal-confident"
                  : "border-signal-review/35 bg-signal-review/10 text-signal-review",
              )}
            >
              Price {labelFor(FIXATION_STATUS_LABELS, sales.customer_fixation_status)}
              {sales.fixation_rate
                ? ` · ${formatMoney(sales.fixation_rate, detail.currency)}`
                : ""}
            </Badge>
          </>
        ) : null}
        <Badge variant="muted">
          {detail.commodity_name ?? detail.commodity_code ?? "Grade not resolved"}
        </Badge>
        <Badge variant="outline">{formatQuantity(detail.quantity_mt)}</Badge>
        {failing > 0 ? (
          <Badge
            variant="outline"
            className="border-signal-blocked/35 bg-signal-blocked/10 text-signal-blocked"
          >
            {failing} check{failing === 1 ? "" : "s"} outstanding
          </Badge>
        ) : null}
      </div>

      {locked ? (
        <p className="rounded-md border border-signal-confident/35 bg-signal-confident/10 px-4 py-3 text-sm text-foreground">
          {lockedNote(detail.status, detail.integration_jobs.length)} No new draft may be generated
          against it either - a draft that differed from what the approver was shown would be worse
          than none.
        </p>
      ) : null}

      {/* The three sales-specific panels, prominent and never collapsed. */}
      <div className="grid gap-4 xl:grid-cols-2">
        {detail.linked_purchase ? (
          <LinkedPurchaseCard detail={detail} linked={detail.linked_purchase} />
        ) : null}
        {detail.contract_coverage ? (
          <QuantityMeter coverage={detail.contract_coverage} />
        ) : null}
      </div>

      {/* New to this screen in Step 6. It matters most here: BR-07 blocks a sales submission on
          whether the original bill of lading has physically arrived, and this is where that fact
          now lives. */}
      {detail.linked_shipments.length > 0 ? (
        <LinkedShipmentCard shipments={detail.linked_shipments} />
      ) : null}

      {/* Where this batch stands with the tracker, SAP and the document store. New to this
          screen in Step 7 and the second retrofit to it, so it is built to stand on its own: it
          renders nothing at all until an approval has actually raised the three jobs. */}
      <IntegrationPanel
        jobs={detail.integration_jobs}
        transactionId={detail.id}
        canManage={detail.can_manage_integrations}
      />

      {canEdit ? (
        <GenerateDraftPanel
          transactionId={detail.id}
          drafts={detail.generated_drafts || []}
          canGenerate={editable && detail.can_generate_draft}
          blocker={
            locked
              ? "This transaction is awaiting approval, so its draft is frozen with it."
              : detail.draft_blocker
          }
          accessToken={token}
          title="Draft sales documents"
          description="Populated from this transaction's own data into an approved Word template. For internal review only."
          documentTypes={SALES_GENERATED_DOCUMENT_TYPES}
          documentLabels={GENERATED_DOCUMENT_LABELS}
          documentNotes={GENERATED_DOCUMENT_NOTES}
          defaultDocumentType="draft_contract"
          onGenerated={refresh}
          onRequestChanges={() => {
            fieldsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
            toast(
              "A draft says what the transaction says. Correct the fields below, save, then generate again - the earlier draft stays on the record.",
              { icon: "✎" },
            );
          }}
        />
      ) : null}

      <div className="grid gap-6 lg:grid-cols-2">
        <div className="lg:sticky lg:top-20 lg:h-[calc(100vh-9rem)]">
          {document ? (
            <div className="flex h-full flex-col gap-3">
              {detail.documents.length > 1 ? (
                <div className="flex flex-wrap gap-1.5">
                  {detail.documents.map((row) => (
                    <Button
                      key={row.id}
                      size="sm"
                      variant={row.id === document.id ? "secondary" : "outline"}
                      onClick={() => openDocument(row.id)}
                    >
                      <span className="max-w-[12rem] truncate">{row.filename}</span>
                    </Button>
                  ))}
                </div>
              ) : null}
              <div className="min-h-0 flex-1">
                <PageViewer
                  filename={document.filename}
                  pageUrls={document.page_image_urls}
                  sourceUrl={document.source_url}
                  contentType={document.content_type}
                />
              </div>
            </div>
          ) : (
            <div className="flex h-full flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-border bg-surface px-6 py-16 text-center">
              <p className="text-sm font-medium text-foreground">No viewable document yet</p>
              <p className="max-w-sm text-sm text-muted-foreground">
                Attach the bill of lading and the customer&apos;s paperwork and they appear here.
                A generated draft is a Word document rather than a page image, so it opens through
                the draft panel above.
              </p>
              <Button asChild variant="outline" size="sm">
                <Link href="/inbox/upload">Upload documents</Link>
              </Button>
            </div>
          )}
        </div>

        <div className="space-y-4" ref={fieldsRef}>
          <CollapsiblePanel
            title="Extraction"
            description="The deal's own fields, coloured by the confidence the machine reported for them."
            defaultOpen
            badge={
              sales && editable ? (
                <span
                  role="button"
                  tabIndex={0}
                  onClick={(event) => {
                    event.stopPropagation();
                    setFixationOpen(true);
                  }}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.stopPropagation();
                      setFixationOpen(true);
                    }
                  }}
                  className="rounded-md border border-secondary/50 bg-secondary/10 px-2 py-1 text-xs font-medium text-foreground transition-colors hover:bg-secondary/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  Record price fixation
                </span>
              ) : undefined
            }
          >
            {sections.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                This transaction carries no editable fields.
              </p>
            ) : (
              <div className="space-y-5">
                {sections.map(([section, fields]) => (
                  <section key={section} className="space-y-3">
                    <h3 className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">
                      {section}
                    </h3>
                    <div className="space-y-3">
                      {fields.map((field) => (
                        <TransactionFieldEditor
                          key={field.name}
                          field={field}
                          commodities={commodities}
                          disabled={!editable || saving || !field.editable}
                          draft={drafts[field.name]}
                          onDraftChange={(draft) =>
                            setDrafts((current) => {
                              const next = { ...current };
                              if (draft === null) delete next[field.name];
                              else next[field.name] = draft;
                              return next;
                            })
                          }
                        />
                      ))}
                    </div>
                  </section>
                ))}
              </div>
            )}
          </CollapsiblePanel>

          <CollapsiblePanel
            title="Matching"
            description="How this shipment was tied to the batch, and what is linked to it."
            badge={
              <Badge variant="muted">
                {detail.documents.length} document{detail.documents.length === 1 ? "" : "s"}
              </Badge>
            }
          >
            <MatchingPanel detail={detail} />
          </CollapsiblePanel>

          <CollapsiblePanel
            title="Validation"
            description="Every business rule that has been evaluated against this transaction."
            defaultOpen
            badge={
              failing > 0 ? (
                <Badge
                  variant="outline"
                  className="border-signal-blocked/35 bg-signal-blocked/10 text-signal-blocked"
                >
                  {failing} outstanding
                </Badge>
              ) : (
                <Badge
                  variant="outline"
                  className="border-signal-confident/35 bg-signal-confident/10 text-signal-confident"
                >
                  All checks pass
                </Badge>
              )
            }
          >
            <ValidationPanel
              rules={detail.rule_evaluations}
              canAcknowledge={editable}
              acknowledging={acknowledging}
              onAcknowledge={acknowledge}
            />
          </CollapsiblePanel>

          <CollapsiblePanel
            title="History"
            description="The status timeline and audit trail behind this transaction."
          >
            <HistoryPanel detail={detail} />
          </CollapsiblePanel>
        </div>
      </div>

      {sales && editable ? (
        <PriceFixationDialog
          open={fixationOpen}
          onOpenChange={setFixationOpen}
          leg={sales}
          currency={detail.currency}
          saving={saving}
          onRecord={recordFixation}
        />
      ) : null}

      {canEdit ? (
        <div className="fixed inset-x-0 bottom-0 z-30 border-t border-border bg-card/95 backdrop-blur lg:left-16">
          <div className="mx-auto flex max-w-[100rem] flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-6">
            <p className="min-w-0 flex-1 text-xs text-muted-foreground">
              {locked
                ? lockedNote(detail.status, detail.integration_jobs.length)
                : pending.length > 0
                  ? `${pending.length} unsaved change${pending.length === 1 ? "" : "s"}. Saving re-runs every check.`
                  : blocker
                    ? blocker
                    : "Every applicable check passes. Submitting moves this to the approval queue and does nothing else."}
            </p>
            <div className="flex shrink-0 gap-2">
              <Button
                variant="outline"
                onClick={save}
                disabled={!editable || saving || pending.length === 0 || missingReason}
              >
                {saving
                  ? "Saving…"
                  : pending.length > 0
                    ? `Save ${pending.length} change${pending.length === 1 ? "" : "s"}`
                    : "Save changes"}
              </Button>
              {(blocker || pending.length > 0) && !locked ? (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <span tabIndex={0}>{submitButton}</span>
                  </TooltipTrigger>
                  <TooltipContent side="top" align="end" className="max-w-[22rem]">
                    {pending.length > 0
                      ? "Save your changes first; the checks are re-run against them."
                      : blocker}
                  </TooltipContent>
                </Tooltip>
              ) : (
                submitButton
              )}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function groupBySection(fields: TransactionField[]): [string, TransactionField[]][] {
  const grouped = new Map<string, TransactionField[]>();
  for (const field of fields) {
    const section = field.section || "Details";
    const bucket = grouped.get(section);
    if (bucket) bucket.push(field);
    else grouped.set(section, [field]);
  }
  return Array.from(grouped.entries());
}

/**
 * What being locked actually means right now, in the state the transaction is genuinely in.
 *
 * Deliberately three sentences rather than one: "with the approver", "approved and being posted"
 * and "posted everywhere it has to be" are different facts, and a single reassuring line covering
 * all three would be a claim about two of them that is only true of the last.
 */
function lockedNote(status: string, jobCount: number): string {
  if (status === "committed") {
    return "Every downstream posting for this batch is resolved, so its figures are final here. The panel above shows where each one landed and which of them a person completed by hand.";
  }
  if (status === "integration_pending" || (status === "approved" && jobCount > 0)) {
    return "This transaction is approved and its three downstream postings are in progress. Its figures are locked so what the platform sends and what SAP, the tracker and the document store hold cannot drift apart. It reaches Committed once all three are resolved.";
  }
  return "This transaction is waiting for departmental approval, so its figures are locked. Nothing has been posted to SAP, the tracker or the document store: those postings are raised by the approval itself, not before it.";
}
