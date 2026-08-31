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
import type { SalesLeg } from "@/lib/api-client";
import { formatMoney } from "@/lib/transactions";
import { formatDateTime } from "@/lib/utils";

export interface PriceFixationDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  leg: SalesLeg;
  currency: string;
  saving: boolean;
  /** Written through the ordinary field-correction path, not a bespoke endpoint. */
  onRecord: (rate: string, fixedOn: string) => Promise<void>;
}

/**
 * Record the rate and the date on which the customer fixed their price.
 *
 * The two values go out as an ordinary field correction, so they carry the same provenance
 * record and trigger the same synchronous re-validation as any other change. The status moves
 * from `unfixed` to `fixed` on the server as a consequence of both being present, rather than
 * being a third thing the user has to remember to set.
 */
export function PriceFixationDialog({
  open,
  onOpenChange,
  leg,
  currency,
  saving,
  onRecord,
}: PriceFixationDialogProps) {
  const [rate, setRate] = useState(leg.fixation_rate ?? "");
  const [fixedOn, setFixedOn] = useState(
    leg.fixation_date ?? new Date().toISOString().slice(0, 10),
  );

  const ready = rate.trim() !== "" && Number.isFinite(Number.parseFloat(rate)) && fixedOn !== "";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <div className="space-y-1.5">
          <DialogTitle>Record price fixation</DialogTitle>
          <DialogDescription>
            The rate and the date the customer fixed at. Both are recorded against your account
            and re-run every check on this transaction.
          </DialogDescription>
        </div>

        {leg.customer_fixation_status === "fixed" ? (
          <p className="rounded-medium border-thin border-pill-amber-border bg-pill-amber-bg px-space-150 py-space-100 text-body-sm text-foreground">
            This customer has already fixed at{" "}
            {formatMoney(leg.fixation_rate, currency)}
            {leg.fixation_date ? ` on ${formatDateTime(leg.fixation_date)}` : ""}. Recording again
            corrects that figure, and the change is kept on the record.
          </p>
        ) : null}

        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="fixation-rate">Fixation rate ({currency} per MT)</Label>
            <Input
              id="fixation-rate"
              inputMode="decimal"
              value={rate}
              onChange={(event) => setRate(event.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="fixation-date">Fixation date</Label>
            <Input
              id="fixation-date"
              type="date"
              value={fixedOn}
              onChange={(event) => setFixedOn(event.target.value)}
            />
          </div>
        </div>

        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
            Cancel
          </Button>
          <Button
            disabled={!ready || saving}
            onClick={() => onRecord(rate.trim(), fixedOn)}
          >
            {saving ? "Recording…" : "Record fixation"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
