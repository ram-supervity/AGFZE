"use client";

import { ArrowUpRight, CircleCheck, CircleX, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useSession } from "next-auth/react";
import { useMemo, useState } from "react";
import toast from "react-hot-toast";

import { PageHeader } from "@/components/shared/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  ApiError,
  resolveExceptionCase,
  type CommodityCode,
  type ExceptionCaseDetail,
  type TransactionField,
} from "@/lib/api-client";
import {
  AGE_CHIP,
  MIN_RESOLUTION_NOTE,
  PRIORITY_CHIP,
  PRIORITY_LABELS,
  ageBand,
  formatAgeHours,
  ownerLabel,
  type ExceptionPriority,
} from "@/lib/governance";
import { formatMoney } from "@/lib/transactions";
import { cn, formatDateTime } from "@/lib/utils";

export interface ExceptionWorkspaceProps {
  initial: ExceptionCaseDetail;
  /** The transaction's editable fields, so a correction can be offered inline. */
  fields: TransactionField[];
  commodities: CommodityCode[];
}

const MIN_CORRECTION_REASON = 5;

export function ExceptionWorkspace({ initial, fields, commodities }: ExceptionWorkspaceProps) {
  const { data: session } = useSession();
  const [detail, setDetail] = useState(initial);
  const [note, setNote] = useState("");
  const [fieldName, setFieldName] = useState("");
  const [fieldValue, setFieldValue] = useState("");
  const [fieldReason, setFieldReason] = useState("");
  const [busy, setBusy] = useState<"resolve" | "escalate" | null>(null);

  const token = session?.accessToken;
  const open = detail.resolved_at === null;
  const band = ageBand(detail.age_hours, detail.ageing_threshold_hours);

  // The same correction control the purchase workspace uses, offered for one field at a time so
  // the act stays legible: this correction, on this case, for this stated reason.
  const editable = useMemo(
    () => fields.filter((field) => field.editable),
    [fields],
  );
  const selected = editable.find((field) => field.name === fieldName) ?? null;
  const reasonMissing = Boolean(
    selected?.reason_required && fieldReason.trim().length < MIN_CORRECTION_REASON,
  );
  const noteTooShort = note.trim().length < MIN_RESOLUTION_NOTE;

  async function submit(escalate: boolean) {
    if (!token) {
      toast.error("Your session has expired. Sign in again to act on this exception.");
      return;
    }
    setBusy(escalate ? "escalate" : "resolve");
    try {
      const updated = await resolveExceptionCase(token, detail.id, {
        resolution_note: note.trim(),
        correction:
          !escalate && selected
            ? {
                name: selected.name,
                value: fieldValue.trim() || null,
                reason: fieldReason.trim() || undefined,
              }
            : null,
        escalate_to_hod: escalate,
      });
      setDetail(updated);
      setNote("");
      setFieldName("");
      setFieldValue("");
      setFieldReason("");
      toast.success(
        escalate
          ? "Escalated. The case stays open — nothing about the underlying problem has changed, and no message has been sent to anyone."
          : "Resolved. The check behind this case now passes.",
      );
    } catch (error) {
      toast.error(
        error instanceof ApiError
          ? error.message
          : "The exception could not be updated. Nothing has changed.",
      );
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title={detail.exception_label ?? detail.exception_type}
        description={detail.summary}
        actions={
          <Button asChild variant="outline" size="sm">
            <Link href="/exceptions">Back to the queue</Link>
          </Button>
        }
      />

      <div className="flex flex-wrap items-center gap-2">
        <Badge
          variant="outline"
          className={cn(PRIORITY_CHIP[detail.priority as ExceptionPriority])}
        >
          {PRIORITY_LABELS[detail.priority as ExceptionPriority] ?? detail.priority} priority
        </Badge>
        <Badge variant="muted">Owned by {ownerLabel(detail.owner_role)}</Badge>
        <Badge variant="outline" className={cn(AGE_CHIP[band])}>
          {open ? "Open for " : "Took "}
          {formatAgeHours(detail.age_hours)}
        </Badge>
        {detail.escalated ? (
          <Badge
            variant="outline"
            className="border-signal-blocked/35 bg-signal-blocked/10 text-signal-blocked"
          >
            Escalated to HOD
          </Badge>
        ) : null}
        {detail.resolved_at ? (
          <Badge
            variant="outline"
            className="border-signal-confident/35 bg-signal-confident/10 text-signal-confident"
          >
            Resolved {formatDateTime(detail.resolved_at)}
          </Badge>
        ) : null}
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <div className="space-y-4">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2">
                {detail.rule_now_passes === true ? (
                  <CircleCheck className="h-4 w-4 text-signal-confident" aria-hidden="true" />
                ) : detail.rule_now_passes === false ? (
                  <CircleX className="h-4 w-4 text-signal-blocked" aria-hidden="true" />
                ) : (
                  <TriangleAlert className="h-4 w-4 text-signal-review" aria-hidden="true" />
                )}
                What triggered this
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4 pt-0">
              <dl className="grid gap-3 sm:grid-cols-2">
                <Fact label="Rule">
                  {detail.rule_id ? (
                    <span className="font-mono">
                      {detail.rule_id}
                      {detail.check_key ? ` · ${detail.check_key.replace(/_/g, " ")}` : ""}
                    </span>
                  ) : (
                    "No business rule — raised by the intake pipeline"
                  )}
                </Fact>
                <Fact label="Field">{detail.field_name ?? "Not tied to one field"}</Fact>
                <Fact label="Expected">{detail.expected_value ?? "Not recorded"}</Fact>
                <Fact label="Found">{detail.actual_value ?? "Not recorded"}</Fact>
              </dl>

              {detail.current_evaluation ? (
                <div
                  className={cn(
                    "rounded-md border px-3 py-2.5 text-sm",
                    detail.current_evaluation.passed
                      ? "border-signal-confident/35 bg-signal-confident/10"
                      : "border-signal-blocked/35 bg-signal-blocked/10",
                  )}
                >
                  <p className="text-xs font-medium uppercase tracking-widest text-muted-foreground">
                    Where the check stands right now
                  </p>
                  <p className="mt-1 leading-relaxed text-foreground">
                    {detail.current_evaluation.message}
                  </p>
                </div>
              ) : null}
            </CardContent>
          </Card>

          {open ? (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle>Act on it</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4 pt-0">
                {detail.resolve_blocked_reason ? (
                  <p className="rounded-md border border-signal-review/35 bg-signal-review/10 px-3 py-2 text-sm text-foreground">
                    {detail.resolve_blocked_reason}
                  </p>
                ) : null}

                <div className="space-y-1.5">
                  <Label htmlFor="exc-note">
                    What you did, or why this needs somebody else (required)
                  </Label>
                  <Textarea
                    id="exc-note"
                    rows={3}
                    value={note}
                    disabled={!detail.can_resolve && !detail.can_escalate}
                    placeholder="For example: the contract states 97%; the transaction had been keyed at 95%."
                    onChange={(event) => setNote(event.target.value)}
                  />
                  {noteTooShort ? (
                    <p className="text-xs text-muted-foreground">
                      At least {MIN_RESOLUTION_NOTE} characters. This is the record of what
                      happened.
                    </p>
                  ) : null}
                </div>

                {detail.transaction_id && editable.length > 0 ? (
                  <div className="space-y-3 rounded-md border border-border bg-surface p-3">
                    <div className="space-y-1.5">
                      <Label htmlFor="exc-field">
                        Correct a field on the transaction (optional)
                      </Label>
                      <Select
                        id="exc-field"
                        value={fieldName}
                        disabled={!detail.can_resolve}
                        onChange={(event) => {
                          const next = event.target.value;
                          setFieldName(next);
                          setFieldValue(
                            editable.find((field) => field.name === next)?.value ?? "",
                          );
                          setFieldReason("");
                        }}
                      >
                        <option value="">Change nothing</option>
                        {editable.map((field) => (
                          <option key={field.name} value={field.name}>
                            {field.label}
                          </option>
                        ))}
                      </Select>
                    </div>

                    {selected ? (
                      <>
                        <div className="space-y-1.5">
                          <Label htmlFor="exc-value">{selected.label}</Label>
                          {selected.type === "enum" || selected.type === "commodity" ? (
                            <Select
                              id="exc-value"
                              value={fieldValue}
                              onChange={(event) => setFieldValue(event.target.value)}
                            >
                              {selected.type === "commodity" ? (
                                <>
                                  <option value="">Not resolved</option>
                                  {commodities.map((commodity) => (
                                    <option key={commodity.code} value={commodity.code}>
                                      {commodity.display_name} ({commodity.code})
                                    </option>
                                  ))}
                                </>
                              ) : (
                                selected.options.map((option) => (
                                  <option key={option} value={option}>
                                    {option}
                                  </option>
                                ))
                              )}
                            </Select>
                          ) : (
                            <Input
                              id="exc-value"
                              type={selected.type === "date" ? "date" : "text"}
                              inputMode={selected.type === "number" ? "decimal" : undefined}
                              value={fieldValue}
                              onChange={(event) => setFieldValue(event.target.value)}
                            />
                          )}
                          <p className="text-xs text-muted-foreground">
                            Currently {selected.value ?? "not recorded"}. Saving re-runs every
                            check, exactly as the transaction workspace does.
                          </p>
                        </div>

                        {selected.reason_required ? (
                          <div className="space-y-1.5">
                            <Label htmlFor="exc-field-reason">
                              Reason for the correction (required — this value was extracted below
                              the confidence threshold)
                            </Label>
                            <Textarea
                              id="exc-field-reason"
                              rows={2}
                              value={fieldReason}
                              onChange={(event) => setFieldReason(event.target.value)}
                            />
                          </div>
                        ) : null}
                      </>
                    ) : null}
                  </div>
                ) : null}

                <div className="flex flex-wrap gap-2">
                  <Button
                    disabled={
                      !detail.can_resolve || busy !== null || noteTooShort || reasonMissing
                    }
                    onClick={() => submit(false)}
                  >
                    {busy === "resolve" ? "Resolving…" : "Resolve"}
                  </Button>
                  <Button
                    variant="outline"
                    disabled={!detail.can_escalate || busy !== null || noteTooShort}
                    onClick={() => submit(true)}
                  >
                    {busy === "escalate" ? "Escalating…" : "Escalate to HOD"}
                  </Button>
                </div>

                <p className="text-xs leading-relaxed text-muted-foreground">
                  Resolving requires the check behind this case to actually pass afterwards; a note
                  on its own will be refused. Escalating does not claim the problem is fixed — it
                  raises the case&apos;s priority and leaves it open. Neither action sends a
                  message to anyone: this platform has no outbound notification yet.
                </p>
              </CardContent>
            </Card>
          ) : (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle>How it was closed</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2 pt-0 text-sm">
                <p className="leading-relaxed text-foreground">
                  {detail.resolution_note ?? "No note was recorded."}
                </p>
                <p className="text-xs text-muted-foreground">
                  {detail.resolved_by_name ?? "A platform user"}
                  {detail.resolved_at ? ` · ${formatDateTime(detail.resolved_at)}` : ""}
                </p>
              </CardContent>
            </Card>
          )}
        </div>

        <div className="space-y-4">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle>The deal behind it</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 pt-0 text-sm">
              {detail.transaction_id ? (
                <>
                  <dl className="space-y-2">
                    <Fact label="Batch">{detail.batch_number ?? "—"}</Fact>
                    <Fact label="Counterparty">{detail.counterparty ?? "Not recorded"}</Fact>
                    <Fact label="Value">
                      {detail.value ? formatMoney(detail.value, detail.currency ?? "USD") : "—"}
                    </Fact>
                    <Fact label="Status">
                      {detail.transaction_status?.replace(/_/g, " ") ?? "—"}
                    </Fact>
                  </dl>
                  <Button asChild variant="outline" size="sm">
                    <Link href={`/transactions/purchase/${detail.transaction_id}`}>
                      Open the transaction
                      <ArrowUpRight className="ml-1 h-3.5 w-3.5" aria-hidden="true" />
                    </Link>
                  </Button>
                </>
              ) : (
                <p className="text-muted-foreground">
                  This case was raised before the document reached a batch, so there is no
                  transaction to open yet.
                </p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle>Source documents</CardTitle>
            </CardHeader>
            <CardContent className="pt-0">
              {detail.documents.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  Nothing is attached to this case yet.
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
            </CardContent>
          </Card>

          {detail.escalated ? (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle>Escalation</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2 pt-0 text-sm">
                <p className="leading-relaxed text-foreground">
                  {detail.escalation_note ?? "No note was recorded."}
                </p>
                <p className="text-xs text-muted-foreground">
                  Raised by {detail.escalated_by_name ?? "a platform user"}
                  {detail.escalated_at ? ` · ${formatDateTime(detail.escalated_at)}` : ""}. Visible
                  here only — no notification was sent.
                </p>
              </CardContent>
            </Card>
          ) : null}
        </div>
      </div>
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
