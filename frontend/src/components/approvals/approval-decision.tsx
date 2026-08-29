"use client";

import { ArrowUpRight, CircleCheck, CircleX, Sparkles } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useSession } from "next-auth/react";
import { useState } from "react";
import toast from "react-hot-toast";

import { AiDisclaimer } from "@/components/shared/ai-disclaimer";
import { PageHeader } from "@/components/shared/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, decideApproval, type ApprovalDetail } from "@/lib/api-client";
import {
  AGE_CHIP,
  DECISION_CHIP,
  DECISION_LABELS,
  DECISIONS_NEEDING_REASON,
  MIN_DECISION_REASON,
  RISK_CHIP,
  RISK_LABELS,
  ageBand,
  formatAgeHours,
  type ApprovalDecision,
} from "@/lib/governance";
import { labelFor } from "@/lib/intake";
import {
  INVOICE_STATUS_LABELS,
  PRICE_BASIS_LABELS,
  formatMoney,
  formatQuantity,
} from "@/lib/transactions";
import { cn, formatDateTime } from "@/lib/utils";

export interface ApprovalDecisionScreenProps {
  initial: ApprovalDetail;
  canDecide: boolean;
  overdueThresholdHours: number;
}

export function ApprovalDecisionScreen({
  initial,
  canDecide,
  overdueThresholdHours,
}: ApprovalDecisionScreenProps) {
  const router = useRouter();
  const { data: session } = useSession();
  const [detail, setDetail] = useState(initial);
  const [choice, setChoice] = useState<ApprovalDecision | null>(null);
  const [reason, setReason] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);

  const decidable = canDecide && detail.can_decide && detail.decision === "pending";
  const needsReason = choice !== null && DECISIONS_NEEDING_REASON.includes(choice);
  const reasonTooShort = needsReason && reason.trim().length < MIN_DECISION_REASON;
  const band = ageBand(detail.age_hours, overdueThresholdHours);
  const failing = detail.rule_evaluations.filter((rule) => !rule.passed);

  async function send(decision: ApprovalDecision, confirmed: boolean) {
    const token = session?.accessToken;
    if (!token) {
      toast.error("Your session has expired. Sign in again to record this decision.");
      return;
    }
    setBusy(true);
    try {
      const result = await decideApproval(token, detail.id, {
        decision,
        reason: reason.trim() || null,
        confirm_above_threshold: confirmed,
      });
      setDetail((current) => ({
        ...current,
        decision: result.decision,
        decided_at: result.decided_at,
        decided_by_name: result.decided_by_name,
        reason: result.reason,
        can_decide: false,
      }));
      setConfirming(false);
      setChoice(null);
      setReason("");
      toast.success(
        decision === "approved"
          ? `${detail.batch_number} is approved. Nothing has been posted to any other system — that connection does not exist yet.`
          : `${detail.batch_number} has gone back to the desk that raised it, editable, with your reason on it.`,
      );
      router.refresh();
    } catch (error) {
      toast.error(
        error instanceof ApiError ? error.message : "The decision could not be recorded.",
      );
    } finally {
      setBusy(false);
    }
  }

  function approve() {
    if (detail.requires_confirmation) {
      setConfirming(true);
      return;
    }
    void send("approved", false);
  }

  return (
    <div className="space-y-6 pb-8">
      <PageHeader
        title={detail.batch_number}
        description={
          detail.counterparty
            ? `${detail.counterparty}${detail.contract_number ? ` · ${detail.contract_number}` : ""}`
            : "No counterparty recorded on this transaction."
        }
        actions={
          <Button asChild variant="outline" size="sm">
            <Link href="/approvals">Back to the queue</Link>
          </Button>
        }
      />

      <AiDisclaimer />

      <div className="flex flex-wrap items-center gap-2">
        <Badge
          variant="outline"
          className={cn(DECISION_CHIP[detail.decision as ApprovalDecision])}
        >
          {DECISION_LABELS[detail.decision as ApprovalDecision] ?? detail.decision}
        </Badge>
        <Badge variant="outline" className={cn(RISK_CHIP[detail.risk.label])}>
          {RISK_LABELS[detail.risk.label] ?? detail.risk.label} risk
        </Badge>
        <Badge variant="outline" className={cn(AGE_CHIP[band])}>
          Waiting {formatAgeHours(detail.age_hours)}
        </Badge>
        <Badge variant="outline">{formatMoney(detail.value, detail.currency)}</Badge>
        <Badge variant="muted">{formatQuantity(detail.quantity_mt)}</Badge>
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <div className="space-y-4">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2">
                <Sparkles className="h-4 w-4 text-secondary" aria-hidden="true" />
                What this is, in short
              </CardTitle>
            </CardHeader>
            <CardContent className="pt-0">
              {detail.ai_summary.available && detail.ai_summary.summary ? (
                <>
                  <p className="whitespace-pre-line text-sm leading-relaxed text-foreground">
                    {detail.ai_summary.summary}
                  </p>
                  <p className="mt-3 text-xs text-muted-foreground">
                    Written by the model from the transaction&apos;s own data
                    {detail.ai_summary.generated_at
                      ? ` on ${formatDateTime(detail.ai_summary.generated_at)}`
                      : ""}
                    . It summarises; it does not decide. Everything it describes is set out in
                    full below.
                  </p>
                </>
              ) : (
                <p className="rounded-md border border-border bg-surface px-3 py-2.5 text-sm text-muted-foreground">
                  {detail.ai_summary.unavailable_reason ??
                    "No summary is available for this transaction."}
                </p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle>The transaction itself</CardTitle>
            </CardHeader>
            <CardContent className="pt-0">
              <dl className="grid gap-3 sm:grid-cols-2">
                <Fact label="Batch">{detail.batch_number}</Fact>
                <Fact label="Request">{detail.request_code ?? "—"}</Fact>
                <Fact label="Supplier">{detail.counterparty ?? "Not recorded"}</Fact>
                <Fact label="Contract">{detail.contract_number ?? "Not recorded"}</Fact>
                <Fact label="Supplier invoice">
                  {detail.supplier_invoice_number ?? "Not recorded"}
                </Fact>
                <Fact label="Invoice status">
                  {labelFor(INVOICE_STATUS_LABELS, detail.invoice_status)}
                </Fact>
                <Fact label="Commodity">{detail.commodity_name ?? "Not resolved"}</Fact>
                <Fact label="Quantity">{formatQuantity(detail.quantity_mt)}</Fact>
                <Fact label="Rate">{formatMoney(detail.rate, detail.currency)}</Fact>
                <Fact label="Invoice value">{formatMoney(detail.value, detail.currency)}</Fact>
                <Fact label="Price basis">
                  {labelFor(PRICE_BASIS_LABELS, detail.price_basis)}
                  {detail.lme_percentage ? ` · ${detail.lme_percentage}%` : ""}
                </Fact>
                <Fact label="Port of loading">{detail.port_of_loading ?? "Not recorded"}</Fact>
                <Fact label="Submitted by">
                  {detail.submitted_by_name ?? detail.requested_by_name ?? "—"}
                  {detail.submitted_at ? ` · ${formatDateTime(detail.submitted_at)}` : ""}
                </Fact>
                <Fact label="Hedge date">{detail.hedge_date ?? "Not fixed"}</Fact>
              </dl>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2">
                {failing.length === 0 ? (
                  <CircleCheck className="h-4 w-4 text-signal-confident" aria-hidden="true" />
                ) : (
                  <CircleX className="h-4 w-4 text-signal-blocked" aria-hidden="true" />
                )}
                Checks
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 pt-0">
              {detail.rule_evaluations.map((rule) => (
                <div
                  key={rule.id}
                  className={cn(
                    "rounded-md border px-3 py-2 text-sm",
                    rule.passed
                      ? rule.acknowledged
                        ? "border-signal-review/35 bg-signal-review/5"
                        : "border-signal-confident/35 bg-signal-confident/5"
                      : "border-signal-blocked/35 bg-signal-blocked/10",
                  )}
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-xs font-semibold">{rule.rule_id}</span>
                    <span className="font-medium text-foreground">
                      {rule.title ?? rule.check_key?.replace(/_/g, " ") ?? "Check"}
                    </span>
                    {rule.acknowledged ? (
                      <Badge
                        variant="outline"
                        className="border-signal-review/35 bg-signal-review/10 text-signal-review"
                      >
                        Accepted by hand
                      </Badge>
                    ) : null}
                  </div>
                  <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                    {rule.message}
                  </p>
                  {rule.acknowledged && rule.acknowledgement_reason ? (
                    <p className="mt-1 text-xs text-muted-foreground">
                      {rule.acknowledged_by_name ?? "A platform user"}:{" "}
                      {rule.acknowledgement_reason}
                    </p>
                  ) : null}
                </div>
              ))}
            </CardContent>
          </Card>
        </div>

        <div className="space-y-4">
          {decidable ? (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle>Your decision</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 pt-0">
                <div className="flex flex-wrap gap-2">
                  <Button
                    variant={choice === "rejected" ? "secondary" : "outline"}
                    size="sm"
                    onClick={() => setChoice(choice === "rejected" ? null : "rejected")}
                  >
                    Reject
                  </Button>
                  <Button
                    variant={choice === "changes_requested" ? "secondary" : "outline"}
                    size="sm"
                    onClick={() =>
                      setChoice(choice === "changes_requested" ? null : "changes_requested")
                    }
                  >
                    Request changes
                  </Button>
                </div>

                {needsReason ? (
                  <div className="space-y-1.5">
                    <Label htmlFor="decision-reason">
                      Why (required — the desk has to know what to change)
                    </Label>
                    <Textarea
                      id="decision-reason"
                      rows={3}
                      value={reason}
                      onChange={(event) => setReason(event.target.value)}
                    />
                    {reasonTooShort ? (
                      <p className="text-xs text-muted-foreground">
                        At least {MIN_DECISION_REASON} characters.
                      </p>
                    ) : null}
                    <Button
                      size="sm"
                      disabled={busy || reasonTooShort}
                      onClick={() => choice && send(choice, false)}
                    >
                      {busy
                        ? "Recording…"
                        : choice === "rejected"
                          ? "Reject this transaction"
                          : "Send it back for changes"}
                    </Button>
                  </div>
                ) : null}

                <div className="border-t border-border pt-3">
                  <Button className="w-full" disabled={busy} onClick={approve}>
                    {busy ? "Recording…" : "Approve"}
                  </Button>
                  <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
                    Approving moves this transaction to Approved and stops there. Nothing is posted
                    to SAP, a tracker or a document store — none of those connections exist yet.
                    Rejecting or requesting changes returns it to the desk, editable, with your
                    reason attached; neither is a dead end.
                  </p>
                </div>
              </CardContent>
            </Card>
          ) : (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle>Decision</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2 pt-0 text-sm">
                {detail.decision === "pending" ? (
                  <p className="text-muted-foreground">
                    This transaction is waiting on the department head. You can read everything
                    here; only an approver can decide.
                  </p>
                ) : (
                  <>
                    <p className="text-foreground">
                      {DECISION_LABELS[detail.decision as ApprovalDecision] ?? detail.decision} by{" "}
                      {detail.decided_by_name ?? "an approver"}
                      {detail.decided_at ? ` · ${formatDateTime(detail.decided_at)}` : ""}
                    </p>
                    {detail.reason ? (
                      <p className="leading-relaxed text-muted-foreground">{detail.reason}</p>
                    ) : null}
                  </>
                )}
              </CardContent>
            </Card>
          )}

          <Card>
            <CardHeader className="pb-3">
              <CardTitle>Why it is ranked as it is</CardTitle>
            </CardHeader>
            <CardContent className="pt-0">
              <ul className="space-y-1.5 text-sm text-muted-foreground">
                {detail.risk.reasons.map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
              {detail.open_exception_count > 0 ? (
                <p className="mt-3 text-sm text-signal-review">
                  {detail.open_exception_count} exception
                  {detail.open_exception_count === 1 ? " is" : "s are"} still open against this
                  batch.
                </p>
              ) : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle>Check it yourself</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 pt-0">
              {detail.documents.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No source document is attached to this transaction.
                </p>
              ) : (
                <ul className="space-y-1.5">
                  {detail.documents.map((document) => (
                    <li key={document.id}>
                      <Link
                        href={`/documents/${document.id}`}
                        className="flex items-center gap-1.5 text-sm text-secondary underline-offset-4 hover:underline"
                      >
                        <span className="truncate">{document.filename}</span>
                        <ArrowUpRight className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
              <Link
                href={`/transactions/purchase/${detail.transaction_id}`}
                className="flex items-center gap-1.5 pt-1 text-sm text-secondary underline-offset-4 hover:underline"
              >
                Open the full transaction record
                <ArrowUpRight className="h-3.5 w-3.5" aria-hidden="true" />
              </Link>
            </CardContent>
          </Card>
        </div>
      </div>

      <Dialog open={confirming} onOpenChange={setConfirming}>
        <DialogContent className="max-w-lg">
          <DialogTitle>Confirm this approval</DialogTitle>
          <DialogDescription>
            {detail.batch_number} is worth {formatMoney(detail.value, detail.currency)}, above the{" "}
            {formatMoney(detail.confirmation_threshold, detail.currency)} threshold configured for
            a second confirmation. Approving records the decision against your account and moves
            the transaction to Approved.
          </DialogDescription>
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setConfirming(false)} disabled={busy}>
              Cancel
            </Button>
            <Button onClick={() => send("approved", true)} disabled={busy}>
              {busy ? "Recording…" : "Confirm and approve"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-xs font-medium uppercase tracking-widest text-muted-foreground">
        {label}
      </dt>
      <dd className="break-words text-sm text-foreground">{children}</dd>
    </div>
  );
}
