"use client";

import { History } from "lucide-react";
import { useState } from "react";

import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import type { CommodityCode, TransactionField } from "@/lib/api-client";
import { BAND_BORDER, BAND_TEXT, confidenceBand, formatConfidence } from "@/lib/intake";
import { INVOICE_STATUS_LABELS, PRICE_BASIS_LABELS } from "@/lib/transactions";
import { cn, formatDateTime } from "@/lib/utils";

export const MIN_REASON = 5;

const OPTION_LABELS: Record<string, Record<string, string>> = {
  invoice_status: INVOICE_STATUS_LABELS,
  price_basis: PRICE_BASIS_LABELS,
};

export interface FieldDraft {
  value: string;
  reason: string;
}

export interface TransactionFieldEditorProps {
  field: TransactionField;
  commodities: CommodityCode[];
  disabled: boolean;
  draft: FieldDraft | undefined;
  onDraftChange: (draft: FieldDraft | null) => void;
}

/**
 * One editable value, left-bordered in its confidence colour.
 *
 * The colour and the reason gate both come from what the machine originally scored for the
 * extracted field behind this one - the same convention and the same threshold the document
 * review screen applies, so a value does not change meaning by moving between screens. Edits are
 * held as drafts and written by the workspace's Save action, so one correction and ten are the
 * same single, audited change.
 */
export function TransactionFieldEditor({
  field,
  commodities,
  disabled,
  draft,
  onDraftChange,
}: TransactionFieldEditorProps) {
  const [showHistory, setShowHistory] = useState(false);

  const stored = field.value ?? "";
  const value = draft?.value ?? stored;
  const reason = draft?.reason ?? "";
  const dirty = (value.trim() || null) !== (field.value ?? null);
  const band = confidenceBand(field.source_confidence);
  const inputId = `tx-field-${field.name}`;

  function update(next: Partial<FieldDraft>) {
    const merged = { value, reason, ...next };
    // A value put back to what it already was stops being a draft at all.
    if ((merged.value.trim() || null) === (field.value ?? null) && merged.reason.trim() === "") {
      onDraftChange(null);
      return;
    }
    onDraftChange(merged);
  }

  return (
    <div
      className={cn(
        "space-y-2 rounded-md border border-border border-l-4 bg-card p-3",
        BAND_BORDER[band],
        dirty && "ring-1 ring-secondary/40",
      )}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <label
          htmlFor={inputId}
          className="text-xs font-medium uppercase tracking-widest text-muted-foreground"
        >
          {field.label}
        </label>
        <span className={cn("text-xs font-medium tabular-nums", BAND_TEXT[band])}>
          {field.source_confidence === null
            ? "Entered by hand"
            : formatConfidence(field.source_confidence)}
        </span>
      </div>

      {field.type === "enum" ? (
        <Select
          id={inputId}
          value={value}
          disabled={disabled}
          onChange={(event) => update({ value: event.target.value })}
        >
          {field.options.map((option) => (
            <option key={option} value={option}>
              {OPTION_LABELS[field.name]?.[option] ?? option}
            </option>
          ))}
        </Select>
      ) : field.type === "commodity" ? (
        <Select
          id={inputId}
          value={value}
          disabled={disabled}
          onChange={(event) => update({ value: event.target.value })}
        >
          <option value="">Not resolved</option>
          {commodities.map((commodity) => (
            <option key={commodity.code} value={commodity.code}>
              {commodity.display_name} ({commodity.code})
            </option>
          ))}
        </Select>
      ) : (
        <Input
          id={inputId}
          type={field.type === "date" ? "date" : "text"}
          inputMode={field.type === "number" ? "decimal" : undefined}
          value={value}
          disabled={disabled}
          placeholder={field.value === null ? "Not recorded" : undefined}
          onChange={(event) => update({ value: event.target.value })}
        />
      )}

      {dirty && field.reason_required ? (
        <div className="space-y-1.5 border-t border-border pt-2">
          <label htmlFor={`${inputId}-reason`} className="text-xs font-medium text-foreground">
            Reason for the correction (required — this value was extracted below the confidence
            threshold)
          </label>
          <Textarea
            id={`${inputId}-reason`}
            rows={2}
            value={reason}
            placeholder="What does the source document actually say?"
            onChange={(event) => update({ reason: event.target.value })}
          />
          {reason.trim().length < MIN_REASON ? (
            <p className="text-xs text-signal-blocked">
              At least {MIN_REASON} characters, please. This goes on the record.
            </p>
          ) : null}
        </div>
      ) : null}

      {field.is_overridden ? (
        <div className="border-t border-border pt-2">
          <button
            type="button"
            onClick={() => setShowHistory((open) => !open)}
            aria-expanded={showHistory}
            className="flex items-center gap-1.5 text-xs text-secondary underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <History className="h-3 w-3" aria-hidden="true" />
            {showHistory ? "Hide correction history" : "Corrected by a person — show history"}
          </button>
          {showHistory ? (
            <dl className="mt-2 space-y-1 rounded-md bg-surface p-2.5 text-xs">
              <div className="flex justify-between gap-3">
                <dt className="text-muted-foreground">Original value</dt>
                <dd className="break-words text-right text-foreground">
                  {field.original_ai_value ?? "Not recorded"}
                </dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-muted-foreground">Original confidence</dt>
                <dd className="tabular-nums text-foreground">
                  {field.original_confidence === null
                    ? "Entered by hand"
                    : formatConfidence(field.original_confidence)}
                </dd>
              </div>
              {field.override_reason ? (
                <div>
                  <dt className="text-muted-foreground">Reason</dt>
                  <dd className="mt-0.5 break-words text-foreground">
                    {field.override_reason}
                  </dd>
                </div>
              ) : null}
              <div className="flex justify-between gap-3">
                <dt className="text-muted-foreground">Corrected by</dt>
                <dd className="text-right text-foreground">
                  {field.overridden_by_name ?? "A platform user"}
                  {field.overridden_at ? ` · ${formatDateTime(field.overridden_at)}` : ""}
                </dd>
              </div>
            </dl>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
