"use client";

import { ConfidenceBadge } from "@/components/shared/confidence-badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type { FaFieldSchema, TransactionField } from "@/lib/api-client";
import type { FieldDraft } from "@/components/transactions/transaction-field-editor";
import { MIN_REASON } from "@/components/transactions/transaction-field-editor";
import { cn } from "@/lib/utils";

export interface FaFieldsPanelProps {
  /** The configured schema. The only thing that decides what this panel renders. */
  schema: FaFieldSchema[];
  /** The current values and provenance for those fields, keyed by name. */
  fields: TransactionField[];
  disabled: boolean;
  drafts: Record<string, FieldDraft>;
  onDraftChange: (name: string, draft: FieldDraft | null) => void;
}

/**
 * The Additional FA Fields panel.
 *
 * **There is not one FA field name anywhere in this file, and there must never be one.** The
 * panel is handed a `DocumentTypeSchema`'s field definitions and renders a control per entry from
 * that entry's own configured type. Nothing here knows that FA currently has a rate and an
 * amount, and nothing here would have to change if the business decided tomorrow that it also has
 * a service period, a fee basis and a regulator reference.
 *
 * That is the concrete proof of the platform's flexible-field promise. AGFZE's own material says
 * FA's fields are not finalised; a panel with a hardcoded list would have quietly turned that
 * openness into a release-blocking dependency the first time somebody agreed a new field.
 */
export function FaFieldsPanel({
  schema,
  fields,
  disabled,
  drafts,
  onDraftChange,
}: FaFieldsPanelProps) {
  if (schema.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No additional FA fields are configured beyond the ones shown above. When the business
        agrees what else an FA transaction records, those fields are added to the FA document
        schema and appear here - this panel needs no change to show them.
      </p>
    );
  }

  const byName = new Map(fields.map((field) => [field.name, field]));

  // Grouped by the section each field declares, so a schema that organises its fields is rendered
  // the way it organised them rather than as one flat list.
  const sections = new Map<string, FaFieldSchema[]>();
  for (const definition of schema) {
    const section = definition.section || "Additional FA fields";
    const bucket = sections.get(section);
    if (bucket) bucket.push(definition);
    else sections.set(section, [definition]);
  }

  return (
    <div className="space-y-5">
      <p className="text-sm text-muted-foreground">
        Rendered from the configured FA document schema. Adding a field to that schema adds it
        here, editable and audited, with no change to this screen.
      </p>

      {Array.from(sections.entries()).map(([section, definitions]) => (
        <section key={section} className="space-y-3">
          {sections.size > 1 ? (
            <h3 className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">
              {section}
            </h3>
          ) : null}
          <div className="space-y-3">
            {definitions.map((definition) => (
              <SchemaField
                key={definition.name}
                definition={definition}
                field={byName.get(definition.name)}
                disabled={disabled}
                draft={drafts[definition.name]}
                onDraftChange={(draft) => onDraftChange(definition.name, draft)}
              />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

/**
 * How a configured type becomes an input control.
 *
 * A type the platform does not recognise renders as plain text, which is the safe reading of a
 * type nobody has taught it yet: a wrong control on a field somebody configured is recoverable,
 * a crashed panel is not.
 */
function controlFor(type: string): { element: "input" | "textarea"; inputType?: string } {
  switch (type) {
    case "number":
    case "currency":
    case "quantity":
      return { element: "input", inputType: "decimal" };
    case "date":
      return { element: "input", inputType: "date" };
    case "text":
      return { element: "textarea" };
    default:
      return { element: "input" };
  }
}

function SchemaField({
  definition,
  field,
  disabled,
  draft,
  onDraftChange,
}: {
  definition: FaFieldSchema;
  field: TransactionField | undefined;
  disabled: boolean;
  draft: FieldDraft | undefined;
  onDraftChange: (draft: FieldDraft | null) => void;
}) {
  const control = controlFor(definition.type);
  const current = draft?.value ?? field?.value ?? "";
  const reason = draft?.reason ?? "";
  const editable = !disabled && (field?.editable ?? false);
  const reasonRequired = Boolean(field?.reason_required) && draft !== undefined;
  const reasonMissing = reasonRequired && reason.trim().length < MIN_REASON;
  const inputId = `fa-field-${definition.name}`;

  function change(value: string) {
    if (value === (field?.value ?? "") && reason.trim() === "") onDraftChange(null);
    else onDraftChange({ value, reason });
  }

  return (
    <div className="space-y-1.5 rounded-md border border-border bg-surface px-3 py-2.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Label htmlFor={inputId}>
          {definition.label}
          {definition.required ? (
            <span className="ml-1 text-signal-blocked" aria-hidden="true">
              *
            </span>
          ) : null}
        </Label>
        {field?.source_confidence !== null && field?.source_confidence !== undefined ? (
          <ConfidenceBadge label="Read at" confidence={field.source_confidence} />
        ) : null}
      </div>

      {control.element === "textarea" ? (
        <Textarea
          id={inputId}
          rows={2}
          value={current}
          disabled={!editable}
          onChange={(event) => change(event.target.value)}
        />
      ) : (
        <Input
          id={inputId}
          type={control.inputType === "date" ? "date" : "text"}
          inputMode={control.inputType === "decimal" ? "decimal" : undefined}
          value={current}
          disabled={!editable}
          onChange={(event) => change(event.target.value)}
        />
      )}

      {definition.description ? (
        <p className="text-xs leading-relaxed text-muted-foreground">{definition.description}</p>
      ) : null}

      {reasonRequired ? (
        <div className="space-y-1.5 pt-1">
          <Label htmlFor={`${inputId}-reason`}>Reason for the correction</Label>
          <Input
            id={`${inputId}-reason`}
            value={reason}
            disabled={!editable}
            placeholder="Why this value is being changed"
            onChange={(event) => onDraftChange({ value: current, reason: event.target.value })}
            className={cn(reasonMissing && "border-signal-blocked/60")}
          />
          {reasonMissing ? (
            <p className="text-xs text-signal-blocked">
              At least {MIN_REASON} characters. This value was read below the confidence
              threshold, so the correction goes on the record with a reason.
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
