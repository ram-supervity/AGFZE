"use client";

import { useEffect, useState } from "react";

import { ChangeReasonField } from "@/components/admin/change-reason-field";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { reasonIsValid, scopeLabel, UNIT_LABELS, type ThresholdUnit } from "@/lib/admin";
import type { RuleConfigurationRow } from "@/lib/api-client";

export interface RuleEditDialogProps {
  row: RuleConfigurationRow | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  saving: boolean;
  onSave: (body: {
    change_reason: string;
    threshold_value?: string;
    is_active?: boolean;
    description?: string;
  }) => Promise<void>;
}

/**
 * Edit one threshold.
 *
 * The rule, the check and the scope are shown and are not editable. They are the row's identity:
 * changing any of them would make this a different configuration wearing an existing row's audit
 * history, and a new scope is a new row rather than an edit to an old one. The API's update
 * schema has no field for them either, so this is not a UI-only restriction.
 */
export function RuleEditDialog({ row, open, onOpenChange, saving, onSave }: RuleEditDialogProps) {
  const [value, setValue] = useState("");
  const [description, setDescription] = useState("");
  const [active, setActive] = useState(true);
  const [reason, setReason] = useState("");

  useEffect(() => {
    if (!row) return;
    setValue(row.threshold_value);
    setDescription(row.description ?? "");
    setActive(row.is_active);
    setReason("");
  }, [row]);

  if (!row) return null;

  const numeric = value.trim() !== "" && !Number.isNaN(Number(value));
  const changed =
    value !== row.threshold_value ||
    description !== (row.description ?? "") ||
    active !== row.is_active;
  const ready = numeric && changed && reasonIsValid(reason);

  async function submit() {
    if (!row || !ready) return;
    await onSave({
      change_reason: reason.trim(),
      threshold_value: value.trim(),
      is_active: active,
      description: description.trim(),
    });
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <div className="space-y-1.5">
          <DialogTitle>
            {row.rule_id} · {row.check_key.replace(/_/g, " ")}
          </DialogTitle>
          <DialogDescription>
            {row.rule_title ? `${row.rule_title}. ` : ""}
            {row.rule_statement ?? "This threshold is read by the rule engine at evaluation time."}
          </DialogDescription>
        </div>

        <dl className="grid grid-cols-2 gap-3 rounded-md border border-border bg-surface px-3 py-2.5 text-sm">
          <div>
            <dt className="text-xs uppercase tracking-wide text-muted-foreground">Scope</dt>
            <dd className="text-foreground">{scopeLabel(row)}</dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-wide text-muted-foreground">Unit</dt>
            <dd className="text-foreground">
              {UNIT_LABELS[row.threshold_unit as ThresholdUnit] ?? row.threshold_unit}
            </dd>
          </div>
        </dl>

        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="rule-threshold">Threshold value</Label>
            <Input
              id="rule-threshold"
              value={value}
              inputMode="decimal"
              onChange={(event) => setValue(event.target.value)}
              aria-invalid={!numeric || undefined}
            />
            <p className="text-xs text-muted-foreground">
              Every evaluation from now on reads the new value. Decisions already recorded keep the
              value that was live when they were made.
            </p>
            {numeric ? null : (
              <p role="alert" className="text-xs text-signal-blocked">
                This has to be a number.
              </p>
            )}
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="rule-description">Description</Label>
            <Textarea
              id="rule-description"
              rows={2}
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
          </div>

          <label className="flex items-start gap-2.5 text-sm">
            <input
              type="checkbox"
              className="mt-0.5 h-4 w-4 rounded border-input"
              checked={active}
              onChange={(event) => setActive(event.target.checked)}
            />
            <span>
              <span className="font-medium text-foreground">Active</span>
              <span className="mt-0.5 block text-xs text-muted-foreground">
                Deactivating a row makes the engine fall back to a broader one, or to its built-in
                cautious default where there is none. It never turns the check off.
              </span>
            </span>
          </label>

          <ChangeReasonField
            id="rule-reason"
            value={reason}
            onChange={setReason}
            subject={`${row.rule_id}'s ${row.check_key.replace(/_/g, " ")} threshold`}
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
