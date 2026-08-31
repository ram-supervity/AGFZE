"use client";

import { useEffect, useState } from "react";

import { ChangeReasonField } from "@/components/admin/change-reason-field";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { documentTypeLabel, reasonIsValid, territoryLabel } from "@/lib/admin";
import type { DocumentSchemaField, DocumentTypeSchemaRow } from "@/lib/api-client";

export interface DocumentTypeDialogProps {
  row: DocumentTypeSchemaRow | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  documentTypes: string[];
  saving: boolean;
  onSave: (body: {
    change_reason: string;
    field_schema: { fields: DocumentSchemaField[] };
    mandatory_documents: string[];
  }) => Promise<void>;
}

const FIELD_TYPES = ["string", "number", "date", "boolean"] as const;

/**
 * Edit a document type's field list and its territory's mandatory-document checklist.
 *
 * `document_type` and `territory` are shown and are not editable, on the same reasoning as a
 * rule's scope: the row carries the history of everything extracted under it, and re-pointing it
 * at another document type would silently rewrite what those extractions were measured against.
 *
 * Fields are edited as rows rather than as raw JSON. The field list is what every extraction
 * prompt is built from, and a malformed schema does not fail loudly - it quietly extracts
 * nothing - so this asks for a name and a type per row instead of trusting a text area.
 */
export function DocumentTypeDialog({
  row,
  open,
  onOpenChange,
  documentTypes,
  saving,
  onSave,
}: DocumentTypeDialogProps) {
  const [fields, setFields] = useState<DocumentSchemaField[]>([]);
  const [mandatory, setMandatory] = useState<string[]>([]);
  const [reason, setReason] = useState("");

  useEffect(() => {
    if (!row) return;
    setFields((row.field_schema?.fields ?? []).map((field) => ({ ...field })));
    setMandatory([...row.mandatory_documents]);
    setReason("");
  }, [row]);

  if (!row) return null;

  const named = fields.every((field) => field.name.trim() && field.type.trim());
  const unique = new Set(fields.map((field) => field.name.trim())).size === fields.length;
  const ready = fields.length > 0 && named && unique && reasonIsValid(reason);

  function updateField(index: number, patch: Partial<DocumentSchemaField>) {
    setFields((rows) => rows.map((field, i) => (i === index ? { ...field, ...patch } : field)));
  }

  async function submit() {
    if (!row || !ready) return;
    await onSave({
      change_reason: reason.trim(),
      field_schema: {
        ...row.field_schema,
        fields: fields.map((field) => ({ ...field, name: field.name.trim() })),
      },
      mandatory_documents: mandatory,
    });
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-3xl">
        <div className="space-y-1.5">
          <DialogTitle>
            {documentTypeLabel(row.document_type)} · {territoryLabel(row.territory)}
          </DialogTitle>
          <DialogDescription>
            These fields are what the extraction prompt asks the model to read out of every
            document of this type. Documents already extracted keep whatever they were read with;
            this changes what happens from now on.
          </DialogDescription>
        </div>

        <div className="max-h-[46vh] space-y-4 overflow-y-auto pr-1">
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label>Extracted fields</Label>
              <Button
                size="sm"
                variant="outline"
                onClick={() =>
                  setFields((rows) => [
                    ...rows,
                    { name: "", label: "", type: "string", required: false },
                  ])
                }
              >
                Add field
              </Button>
            </div>

            <ul className="space-y-2">
              {fields.map((field, index) => (
                <li
                  key={index}
                  className="grid gap-2 rounded-medium border-thin border-border bg-elevation-sunken p-2.5 sm:grid-cols-[1fr_1fr_7rem_5rem_2.5rem]"
                >
                  <Input
                    aria-label={`Field ${index + 1} name`}
                    value={field.name}
                    placeholder="field_name"
                    onChange={(event) => updateField(index, { name: event.target.value })}
                  />
                  <Input
                    aria-label={`Field ${index + 1} label`}
                    value={field.label ?? ""}
                    placeholder="Label shown to a reader"
                    onChange={(event) => updateField(index, { label: event.target.value })}
                  />
                  <select
                    aria-label={`Field ${index + 1} type`}
                    value={field.type}
                    onChange={(event) => updateField(index, { type: event.target.value })}
                    className="h-control-md rounded-control border-thin border-input bg-elevation-default px-space-100 text-body-sm"
                  >
                    {FIELD_TYPES.map((type) => (
                      <option key={type} value={type}>
                        {type}
                      </option>
                    ))}
                  </select>
                  <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
                    <input
                      type="checkbox"
                      className="h-4 w-4 rounded-control border-input"
                      checked={Boolean(field.required)}
                      onChange={(event) =>
                        updateField(index, { required: event.target.checked })
                      }
                    />
                    Required
                  </label>
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label={`Remove ${field.name || `field ${index + 1}`}`}
                    onClick={() => setFields((rows) => rows.filter((_, i) => i !== index))}
                  >
                    ✕
                  </Button>
                </li>
              ))}
            </ul>
            {unique ? null : (
              <p role="alert" className="text-xs text-signal-blocked">
                Two fields share a name. Every field name has to be unique.
              </p>
            )}
          </div>

          <div className="space-y-2">
            <Label>Mandatory documents for this territory</Label>
            <p className="text-xs text-muted-foreground">
              The checklist BR-04 measures a document pack against. Removing one stops it being
              required; it does not delete anything already received.
            </p>
            <div className="flex flex-wrap gap-2">
              {documentTypes.map((type) => (
                <label
                  key={type}
                  className="inline-flex items-center gap-space-075 rounded-control border-thin border-border px-space-100 py-space-050 text-body-sm"
                >
                  <input
                    type="checkbox"
                    className="h-4 w-4 rounded border-input"
                    checked={mandatory.includes(type)}
                    onChange={(event) =>
                      setMandatory((rows) =>
                        event.target.checked
                          ? [...rows, type]
                          : rows.filter((value) => value !== type),
                      )
                    }
                  />
                  {documentTypeLabel(type)}
                </label>
              ))}
            </div>
          </div>

          <ChangeReasonField
            id="schema-reason"
            value={reason}
            onChange={setReason}
            subject={`the ${documentTypeLabel(row.document_type).toLowerCase()} schema`}
            disabled={saving}
          />
        </div>

        <div className="flex justify-end gap-2 pt-2">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={!ready || saving}>
            {saving ? "Saving…" : "Save change"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
