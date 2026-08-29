"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type { IntegrationJobDetail } from "@/lib/api-client";
import { INTEGRATION_TARGET_LABELS, MIN_MANUAL_NOTE, type IntegrationTarget } from "@/lib/integrations";

export interface ManualCompletionDialogProps {
  job: IntegrationJobDetail | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  saving: boolean;
  onConfirm: (externalReference: string, note: string) => Promise<void>;
}

/**
 * Confirm that a posting the platform could not make was genuinely made by a person.
 *
 * Deliberately not a one-click "mark as done". This is the only place in the platform where a
 * `succeeded` job appears without an adapter having succeeded, so it asks for the two things that
 * make that claim checkable afterwards: the reference the receiving system produced, and a note
 * saying what was actually done. The dialog says plainly that the result will always be shown as
 * a manual completion, so nobody presses the button expecting it to look automated.
 */
export function ManualCompletionDialog({
  job,
  open,
  onOpenChange,
  saving,
  onConfirm,
}: ManualCompletionDialogProps) {
  const [reference, setReference] = useState("");
  const [note, setNote] = useState("");

  const ready = reference.trim().length > 0 && note.trim().length >= MIN_MANUAL_NOTE;
  const target = job
    ? (INTEGRATION_TARGET_LABELS[job.target_system as IntegrationTarget] ?? job.target_system)
    : "";

  async function submit() {
    if (!job || !ready) return;
    await onConfirm(reference.trim(), note.trim());
    setReference("");
    setNote("");
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <div className="space-y-1.5">
          <DialogTitle>Confirm this posting was completed by hand</DialogTitle>
          <DialogDescription>
            {job?.batch_number ? `${job.batch_number} · ` : ""}
            {target}. This records that <em>you</em> completed the posting outside the platform.
            It is stored and displayed as a manual completion, always, and is never presented as
            something the platform did automatically.
          </DialogDescription>
        </div>

        {job?.manual_instruction ? (
          <p className="rounded-md border border-border bg-surface px-3 py-2 text-sm text-muted-foreground">
            {job.manual_instruction}
          </p>
        ) : null}

        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="manual-reference">Reference from the receiving system</Label>
            <Input
              id="manual-reference"
              value={reference}
              onChange={(event) => setReference(event.target.value)}
              placeholder="e.g. the SAP document number, or the DMS document id"
              autoComplete="off"
            />
            <p className="text-xs text-muted-foreground">
              Required. A completion with nothing to point at is not evidence that anything was
              posted.
            </p>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="manual-note">What was done</Label>
            <Textarea
              id="manual-note"
              value={note}
              onChange={(event) => setNote(event.target.value)}
              rows={3}
              placeholder="Keyed the prepared payload into SAP and confirmed the document number against the posting."
            />
            <p className="text-xs text-muted-foreground">
              At least {MIN_MANUAL_NOTE} characters, on the audit trail against your account. This
              is the only record of a posting the platform did not make itself.
            </p>
          </div>
        </div>

        <div className="flex justify-end gap-2 pt-2">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={!ready || saving}>
            {saving ? "Recording…" : "Confirm manual completion"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
