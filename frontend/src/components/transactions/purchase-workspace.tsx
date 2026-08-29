"use client";

import Link from "next/link";
import { useSession } from "next-auth/react";
import { useCallback, useMemo, useState } from "react";
import toast from "react-hot-toast";

import { PageViewer } from "@/components/intake/page-viewer";
import { AiDisclaimer } from "@/components/shared/ai-disclaimer";
import { PageHeader } from "@/components/shared/page-header";
import { CollapsiblePanel } from "@/components/transactions/collapsible-panel";
import { HistoryPanel } from "@/components/transactions/history-panel";
import { TracePanel } from "@/components/transactions/trace-panel";
import { IntegrationPanel } from "@/components/transactions/integration-panel";
import { LinkedShipmentCard } from "@/components/transactions/linked-shipment-card";
import { MatchingPanel } from "@/components/transactions/matching-panel";
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
  submitTransaction,
  type CommodityCode,
  type DocumentDetail,
  type RuleEvaluation,
  type TransactionDetail,
  type TransactionField,
} from "@/lib/api-client";
import { labelFor } from "@/lib/intake";
import {
  INVOICE_STATUS_LABELS,
  LOCKED_TRANSACTION_STATUSES,
  TRANSACTION_STATUS_CHIP,
  TRANSACTION_STATUS_LABELS,
  formatMoney,
  formatQuantity,
  submitBlocker,
  type TransactionStatus,
} from "@/lib/transactions";
import { cn } from "@/lib/utils";

export interface PurchaseWorkspaceProps {
  initial: TransactionDetail;
  /** The first linked document, already loaded server-side so the viewer has pages to show. */
  initialDocument: DocumentDetail | null;
  commodities: CommodityCode[];
  canEdit: boolean;
}

export function PurchaseWorkspace({
  initial,
  initialDocument,
  commodities,
  canEdit,
}: PurchaseWorkspaceProps) {
  const { data: session } = useSession();
  const [detail, setDetail] = useState(initial);
  const [document, setDocument] = useState(initialDocument);
  const [drafts, setDrafts] = useState<Record<string, FieldDraft>>({});
  const [saving, setSaving] = useState(false);
  const [acknowledging, setAcknowledging] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const token = session?.accessToken;
  // Locked from the moment it leaves the desk: waiting on a decision, decided, or being posted
  // downstream. A figure corrected after the approver saw it, or after SAP was told about it,
  // would put this platform and the systems it feeds out of step with each other.
  const locked = LOCKED_TRANSACTION_STATUSES.includes(detail.status as TransactionStatus);
  const editable = canEdit && detail.can_edit && !locked;
  const blocker = useMemo(() => submitBlocker(detail.rule_evaluations), [detail.rule_evaluations]);
  const failing = detail.rule_evaluations.filter((rule) => !rule.passed).length;

  const sections = useMemo(() => groupBySection(detail.fields), [detail.fields]);
  const pending = Object.entries(drafts);
  const missingReason = pending.some(([name, draft]) => {
    const field = detail.fields.find((row) => row.name === name);
    return Boolean(field?.reason_required) && draft.reason.trim().length < MIN_REASON;
  });

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
        `Batch ${detail.batch_number} is waiting for departmental approval. Nothing has been posted anywhere else.`,
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
          detail.counterparty
            ? `${detail.counterparty}${
                detail.contract_number ? ` · ${detail.contract_number}` : ""
              }`
            : "No counterparty recorded on this transaction yet."
        }
        actions={
          <Button asChild variant="outline" size="sm">
            <Link href="/transactions">Back to transactions</Link>
          </Button>
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
        {detail.invoice_status ? (
          <Badge variant="muted">
            {labelFor(INVOICE_STATUS_LABELS, detail.invoice_status)} invoice
          </Badge>
        ) : null}
        <Badge variant="muted">
          {detail.commodity_name ?? detail.commodity_code ?? "Grade not resolved"}
        </Badge>
        <Badge variant="outline">{formatQuantity(detail.quantity_mt)}</Badge>
        <Badge variant="outline">{formatMoney(detail.value, detail.currency)}</Badge>
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
          {lockedNote(detail.status, detail.integration_jobs.length)}
        </p>
      ) : null}

      {/* Where this batch's cargo actually is. New to this screen in Step 6, and shown above the
          accordion rather than inside it: a preparing user blocked by a missing original bill of
          lading should not have to open a panel to find out why. */}
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
              <p className="text-sm font-medium text-foreground">No documents attached yet</p>
              <p className="max-w-sm text-sm text-muted-foreground">
                This transaction was registered without a source document, which is a normal
                starting state. Attach the supplier&apos;s paperwork and it appears here.
              </p>
              <Button asChild variant="outline" size="sm">
                <Link href="/inbox/upload">Upload documents</Link>
              </Button>
            </div>
          )}
        </div>

        <div className="space-y-4">
          <CollapsiblePanel
            title="Extraction"
            description="The deal's own fields, coloured by the confidence the machine reported for them."
            defaultOpen
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
                          disabled={!editable || saving}
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
            description="How this transaction was matched, and what is linked to it."
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
            title="Trace"
            description="What this transaction is connected to, across the documents, containers, approvals and postings around it."
          >
            <TracePanel transactionId={detail.id} />
          </CollapsiblePanel>

          <CollapsiblePanel
            title="History"
            description="The status timeline and audit trail behind this transaction."
          >
            <HistoryPanel detail={detail} />
          </CollapsiblePanel>
        </div>
      </div>

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
