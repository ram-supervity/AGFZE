"use client";

import { useSession } from "next-auth/react";
import { useState } from "react";
import toast from "react-hot-toast";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, reclassifyDocument } from "@/lib/api-client";
import {
  DOCUMENT_TYPES,
  DOCUMENT_TYPE_LABELS,
  TERRITORIES,
  TERRITORY_LABELS,
} from "@/lib/intake";

const MIN_REASON = 5;

export interface ReclassifyDialogProps {
  documentId: string;
  currentType: string | null;
  currentTerritory: string | null;
  onQueued: (jobId: string) => void;
}

export function ReclassifyDialog({
  documentId,
  currentType,
  currentTerritory,
  onQueued,
}: ReclassifyDialogProps) {
  const { data: session } = useSession();
  const [open, setOpen] = useState(false);
  const [documentType, setDocumentType] = useState(currentType ?? "invoice");
  const [territory, setTerritory] = useState(currentTerritory ?? "");
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);

  async function submit() {
    if (!session?.accessToken) {
      toast.error("Your session has expired. Sign in again to reclassify.");
      return;
    }
    setSaving(true);
    try {
      const accepted = await reclassifyDocument(session.accessToken, documentId, {
        document_type: documentType,
        territory: territory || null,
        reason: reason.trim(),
      });
      setOpen(false);
      setReason("");
      toast.success("Re-extraction queued against the new schema.");
      onQueued(accepted.job_id);
    } catch (error) {
      toast.error(
        error instanceof ApiError ? error.message : "The document could not be reclassified.",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline">Reclassify document type</Button>
      </DialogTrigger>
      <DialogContent className="max-w-lg">
        <DialogTitle>Reclassify this document</DialogTitle>
        <DialogDescription>
          Extraction re-runs against the chosen type&apos;s configured schema. Corrections you have
          already made are kept; the AI&apos;s original type stays on the record.
        </DialogDescription>

        <div className="space-y-4 pt-2">
          <div className="space-y-1.5">
            <Label htmlFor="reclassify-type">Document type</Label>
            <Select
              id="reclassify-type"
              value={documentType}
              onChange={(event) => setDocumentType(event.target.value)}
            >
              {DOCUMENT_TYPES.map((value) => (
                <option key={value} value={value}>
                  {DOCUMENT_TYPE_LABELS[value]}
                </option>
              ))}
            </Select>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="reclassify-territory">Territory</Label>
            <Select
              id="reclassify-territory"
              value={territory}
              onChange={(event) => setTerritory(event.target.value)}
            >
              <option value="">Leave as it is</option>
              {TERRITORIES.map((value) => (
                <option key={value} value={value}>
                  {TERRITORY_LABELS[value]}
                </option>
              ))}
            </Select>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="reclassify-reason">Reason (required)</Label>
            <Textarea
              id="reclassify-reason"
              value={reason}
              placeholder="Why is this the right document type?"
              onChange={(event) => setReason(event.target.value)}
            />
          </div>

          <div className="flex gap-2">
            <Button onClick={submit} disabled={saving || reason.trim().length < MIN_REASON}>
              {saving ? "Queuing…" : "Reclassify and re-extract"}
            </Button>
            <Button variant="ghost" onClick={() => setOpen(false)} disabled={saving}>
              Cancel
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
