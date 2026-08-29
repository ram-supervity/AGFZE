"use client";

import { History, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import type { ExtractedField } from "@/lib/api-client";
import { BAND_BORDER, BAND_TEXT, confidenceBand, formatConfidence } from "@/lib/intake";
import { cn, formatDateTime } from "@/lib/utils";

const MIN_REASON = 5;

export interface FieldEditorProps {
  field: ExtractedField;
  editable: boolean;
  saving: boolean;
  onSave: (value: string | null, reason: string | null) => Promise<void>;
}

function inputType(type: string): string {
  if (type === "date") return "date";
  if (type === "number" || type === "currency") return "text";
  return "text";
}

export function FieldEditor({ field, editable, saving, onSave }: FieldEditorProps) {
  const [value, setValue] = useState(field.field_value ?? "");
  const [reason, setReason] = useState("");
  const [showHistory, setShowHistory] = useState(false);

  useEffect(() => {
    setValue(field.field_value ?? "");
    setReason("");
  }, [field.field_value, field.id]);

  const band = confidenceBand(field.confidence);
  const dirty = (value.trim() || null) !== (field.field_value ?? null);
  const needsReason = field.reason_required;
  const reasonMissing = needsReason && reason.trim().length < MIN_REASON;
  const label = field.label ?? field.field_name;

  return (
    <div
      className={cn(
        "space-y-2 rounded-md border border-border border-l-4 bg-card p-3",
        BAND_BORDER[band],
      )}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <label
          htmlFor={`field-${field.id}`}
          className="text-xs font-medium uppercase tracking-widest text-muted-foreground"
        >
          {label}
          {field.required ? <span className="ml-1 text-signal-blocked">*</span> : null}
        </label>
        <span className={cn("text-xs font-medium tabular-nums", BAND_TEXT[band])}>
          {formatConfidence(field.confidence)}
        </span>
      </div>

      <Input
        id={`field-${field.id}`}
        type={inputType(field.type)}
        value={value}
        disabled={!editable || saving}
        placeholder={field.field_value === null ? "Not found in the document" : undefined}
        onChange={(event) => setValue(event.target.value)}
      />

      {field.has_conflict ? (
        <p className="flex items-start gap-1.5 text-xs text-signal-review">
          <TriangleAlert className="mt-0.5 h-3 w-3 shrink-0" aria-hidden="true" />
          <span>
            Read differently on more than one page: {field.conflicting_values.join(" · ")}. Pick
            the correct value.
          </span>
        </p>
      ) : null}

      {field.rationale ? (
        <p className="text-xs leading-relaxed text-muted-foreground">
          {field.rationale}
          {field.source_page ? ` (page ${field.source_page})` : ""}
        </p>
      ) : null}

      {editable && dirty ? (
        <div className="space-y-2 border-t border-border pt-2">
          {needsReason ? (
            <div className="space-y-1.5">
              <label
                htmlFor={`reason-${field.id}`}
                className="text-xs font-medium text-foreground"
              >
                Reason for the correction (required — this field was extracted below the
                confidence threshold)
              </label>
              <Textarea
                id={`reason-${field.id}`}
                rows={2}
                value={reason}
                placeholder="What does the source document actually say?"
                onChange={(event) => setReason(event.target.value)}
              />
            </div>
          ) : null}
          <div className="flex gap-2">
            <Button
              size="sm"
              disabled={saving || reasonMissing}
              onClick={() => onSave(value.trim() || null, reason.trim() || null)}
            >
              {saving ? "Saving…" : "Save"}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              disabled={saving}
              onClick={() => {
                setValue(field.field_value ?? "");
                setReason("");
              }}
            >
              Reset
            </Button>
          </div>
        </div>
      ) : null}

      {field.is_overridden ? (
        <div className="border-t border-border pt-2">
          <button
            type="button"
            onClick={() => setShowHistory((open) => !open)}
            className="flex items-center gap-1.5 text-xs text-secondary underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            aria-expanded={showHistory}
          >
            <History className="h-3 w-3" aria-hidden="true" />
            {showHistory ? "Hide override history" : "Corrected by a person — show history"}
          </button>
          {showHistory ? (
            <dl className="mt-2 space-y-1 rounded-md bg-surface p-2.5 text-xs">
              <div className="flex justify-between gap-3">
                <dt className="text-muted-foreground">Original AI value</dt>
                <dd className="break-words text-right text-foreground">
                  {field.original_ai_value ?? "Not found"}
                </dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-muted-foreground">Original confidence</dt>
                <dd className="tabular-nums text-foreground">
                  {formatConfidence(field.original_confidence)}
                </dd>
              </div>
              {field.override_reason ? (
                <div>
                  <dt className="text-muted-foreground">Reason</dt>
                  <dd className="mt-0.5 break-words text-foreground">{field.override_reason}</dd>
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
