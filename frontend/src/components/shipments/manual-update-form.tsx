"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import type { ShipmentDetail, ShipmentManualUpdate } from "@/lib/api-client";
import { labelFor } from "@/lib/intake";
import {
  BILL_OF_LADING_TYPE_LABELS,
  SHIPMENT_MILESTONE_LABELS,
  SHIPMENT_STATUS_LABELS,
} from "@/lib/shipments";

export interface ManualUpdateFormProps {
  shipment: ShipmentDetail;
  saving: boolean;
  onSave: (update: ShipmentManualUpdate) => Promise<void>;
}

interface FormState {
  status: string;
  milestone: string;
  etd: string;
  eta: string;
  carrier: string;
  vessel: string;
  port_of_loading: string;
  port_of_discharge: string;
  bl_number: string;
  bl_type: string;
  original_bl_received: boolean;
  note: string;
}

function initial(shipment: ShipmentDetail): FormState {
  const bill = shipment.bills_of_lading[0];
  return {
    status: shipment.status,
    milestone: shipment.current_milestone ?? "unknown",
    etd: shipment.etd ?? "",
    eta: shipment.eta ?? "",
    carrier: shipment.carrier ?? "",
    vessel: shipment.vessel ?? "",
    port_of_loading: shipment.port_of_loading ?? "",
    port_of_discharge: shipment.port_of_discharge ?? "",
    bl_number: shipment.bl_number ?? "",
    bl_type: bill?.bl_type ?? "original",
    original_bl_received: bill?.is_original_received ?? false,
    note: "",
  };
}

function trimmed(value: string): string | null {
  const cleaned = value.trim();
  return cleaned === "" ? null : cleaned;
}

/**
 * Recording where the cargo actually is, by hand.
 *
 * This is the primary path, not a fallback, and it is built like one. Almost every shipment on
 * this platform has no carrier tracking source behind it, so this form is what the logistics desk
 * uses every morning - and it therefore gets the same care as any other form here: real labels,
 * the platform's own vocabularies in real selects, and an optional note that lands on the
 * shipment's timeline so the next person knows where the figure came from.
 *
 * It writes the identical columns an adapter's result would, through the identical server
 * function, and is subject to the same plausibility check. What it is not is a text box marked
 * "override".
 */
export function ManualUpdateForm({ shipment, saving, onSave }: ManualUpdateFormProps) {
  const [form, setForm] = useState<FormState>(() => initial(shipment));
  const [touchedBill, setTouchedBill] = useState(false);

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  async function submit() {
    const update: ShipmentManualUpdate = {
      status: form.status,
      milestone: form.milestone,
      etd: trimmed(form.etd),
      eta: trimmed(form.eta),
      carrier: trimmed(form.carrier),
      vessel: trimmed(form.vessel),
      port_of_loading: trimmed(form.port_of_loading),
      port_of_discharge: trimmed(form.port_of_discharge),
      bl_number: trimmed(form.bl_number),
      note: trimmed(form.note),
    };
    // The bill of lading is only asserted when somebody has actually touched it. Sending it on
    // every status correction would let a routine milestone update quietly claim the original
    // has arrived - which is the one field BR-07 blocks a submission on.
    if (touchedBill) {
      update.bl_type = form.bl_type;
      update.original_bl_received = form.original_bl_received;
    }
    await onSave(update);
    setForm((current) => ({ ...current, note: "" }));
    setTouchedBill(false);
  }

  return (
    <div className="space-y-5">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <div className="space-y-1.5">
          <Label htmlFor="manual-status">Status</Label>
          <Select
            id="manual-status"
            value={form.status}
            disabled={saving}
            onChange={(event) => set("status", event.target.value)}
          >
            {shipment.statuses.map((value) => (
              <option key={value} value={value}>
                {labelFor(SHIPMENT_STATUS_LABELS, value)}
              </option>
            ))}
          </Select>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="manual-milestone">Milestone</Label>
          <Select
            id="manual-milestone"
            value={form.milestone}
            disabled={saving}
            onChange={(event) => set("milestone", event.target.value)}
          >
            {shipment.milestones.map((value) => (
              <option key={value} value={value}>
                {labelFor(SHIPMENT_MILESTONE_LABELS, value)}
              </option>
            ))}
          </Select>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="manual-carrier">Carrier</Label>
          <Input
            id="manual-carrier"
            value={form.carrier}
            disabled={saving}
            onChange={(event) => set("carrier", event.target.value)}
          />
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="manual-vessel">Vessel / voyage</Label>
          <Input
            id="manual-vessel"
            value={form.vessel}
            disabled={saving}
            onChange={(event) => set("vessel", event.target.value)}
          />
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="manual-pol">Port of loading</Label>
          <Input
            id="manual-pol"
            value={form.port_of_loading}
            disabled={saving}
            onChange={(event) => set("port_of_loading", event.target.value)}
          />
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="manual-pod">Port of discharge</Label>
          <Input
            id="manual-pod"
            value={form.port_of_discharge}
            disabled={saving}
            onChange={(event) => set("port_of_discharge", event.target.value)}
          />
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="manual-etd">ETD</Label>
          <Input
            id="manual-etd"
            type="date"
            value={form.etd}
            disabled={saving}
            onChange={(event) => set("etd", event.target.value)}
          />
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="manual-eta">ETA</Label>
          <Input
            id="manual-eta"
            type="date"
            value={form.eta}
            disabled={saving}
            onChange={(event) => set("eta", event.target.value)}
          />
          <p className="text-xs text-muted-foreground">
            An ETA that jumps a long way forward is saved and flagged for somebody to confirm,
            never refused.
          </p>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="manual-bl">B/L number</Label>
          <Input
            id="manual-bl"
            value={form.bl_number}
            disabled={saving}
            onChange={(event) => set("bl_number", event.target.value)}
          />
        </div>
      </div>

      <fieldset className="space-y-3 rounded-medium border-thin border-border bg-elevation-sunken p-4">
        <legend className="px-1 text-xs font-semibold uppercase tracking-widest text-muted-foreground">
          Bill of lading
        </legend>
        <p className="text-sm text-muted-foreground">
          Whether the original is physically in hand is what BR-07 holds a sales submission on.
          It is a statement about a piece of paper on somebody&apos;s desk, so it is recorded here
          rather than inferred from a file.
        </p>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="manual-bl-type">Type</Label>
            <Select
              id="manual-bl-type"
              value={form.bl_type}
              disabled={saving}
              onChange={(event) => {
                setTouchedBill(true);
                set("bl_type", event.target.value);
              }}
            >
              {shipment.bill_of_lading_types.map((value) => (
                <option key={value} value={value}>
                  {labelFor(BILL_OF_LADING_TYPE_LABELS, value)}
                </option>
              ))}
            </Select>
          </div>
          <div className="flex items-end">
            <label className="flex items-center gap-2 text-sm text-foreground">
              <input
                type="checkbox"
                className="h-4 w-4 rounded border-input accent-secondary"
                checked={form.original_bl_received}
                disabled={saving}
                onChange={(event) => {
                  setTouchedBill(true);
                  set("original_bl_received", event.target.checked);
                }}
              />
              The original has been received
            </label>
          </div>
        </div>
      </fieldset>

      <div className="space-y-1.5">
        <Label htmlFor="manual-note">Note (optional)</Label>
        <Textarea
          id="manual-note"
          value={form.note}
          disabled={saving}
          placeholder="Confirmed with the carrier's Dubai office by telephone."
          onChange={(event) => set("note", event.target.value)}
        />
        <p className="text-xs text-muted-foreground">
          Goes onto this shipment&apos;s milestone timeline, so the next person can see where the
          figure came from.
        </p>
      </div>

      <div className="flex justify-end">
        <Button onClick={submit} disabled={saving}>
          {saving ? "Saving…" : "Record this update"}
        </Button>
      </div>
    </div>
  );
}
