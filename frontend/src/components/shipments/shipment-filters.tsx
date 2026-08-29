"use client";

import { LayoutGrid, Rows3 } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { SHIPMENT_STATUSES, SHIPMENT_STATUS_LABELS, type ShipmentStatus } from "@/lib/shipments";
import { cn } from "@/lib/utils";

export type ShipmentView = "table" | "cards";

export interface ShipmentFiltersProps {
  search: string;
  status: string;
  carrier: string;
  portOfDischarge: string;
  staleOnly: boolean;
  carriers: string[];
  ports: string[];
  view: ShipmentView;
  onViewChange: (view: ShipmentView) => void;
}

/**
 * The board's filters, and its view toggle.
 *
 * Filters go through the URL, so a filtered board is a link somebody can send to the person who
 * has to deal with it - which on this screen is the whole point, because "these six containers
 * have gone quiet" is a message one desk sends another.
 */
export function ShipmentFilters({
  search,
  status,
  carrier,
  portOfDischarge,
  staleOnly,
  carriers,
  ports,
  view,
  onViewChange,
}: ShipmentFiltersProps) {
  const router = useRouter();
  const params = useSearchParams();
  const [term, setTerm] = useState(search);

  function navigate(changes: Record<string, string>) {
    const next = new URLSearchParams(params.toString());
    for (const [key, value] of Object.entries(changes)) {
      if (value) next.set(key, value);
      else next.delete(key);
    }
    next.set("page", "1");
    router.push(`/shipments?${next.toString()}`);
  }

  const filtered = Boolean(search || status || carrier || portOfDischarge || staleOnly);

  return (
    <div className="space-y-3 rounded-lg border border-border bg-surface p-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div className="space-y-1.5">
          <Label htmlFor="shipment-search">Container, B/L or vessel</Label>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              navigate({ search: term.trim() });
            }}
          >
            <Input
              id="shipment-search"
              value={term}
              placeholder="MSKU7781234"
              onChange={(event) => setTerm(event.target.value)}
            />
          </form>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="shipment-status">Status</Label>
          <Select
            id="shipment-status"
            value={status}
            onChange={(event) => navigate({ status: event.target.value })}
          >
            <option value="">Every status</option>
            {SHIPMENT_STATUSES.map((value) => (
              <option key={value} value={value}>
                {SHIPMENT_STATUS_LABELS[value as ShipmentStatus]}
              </option>
            ))}
          </Select>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="shipment-carrier">Carrier</Label>
          <Select
            id="shipment-carrier"
            value={carrier}
            onChange={(event) => navigate({ carrier: event.target.value })}
          >
            <option value="">Every carrier</option>
            {carriers.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </Select>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="shipment-port">Port of discharge</Label>
          <Select
            id="shipment-port"
            value={portOfDischarge}
            onChange={(event) => navigate({ port_of_discharge: event.target.value })}
          >
            <option value="">Every port</option>
            {ports.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </Select>
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            size="sm"
            variant={staleOnly ? "secondary" : "outline"}
            onClick={() => navigate({ stale_only: staleOnly ? "" : "true" })}
          >
            Not checked recently
          </Button>
          {filtered ? (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => router.push("/shipments")}
            >
              Clear filters
            </Button>
          ) : null}
        </div>

        <div
          className="flex items-center gap-1 rounded-md border border-border bg-card p-0.5"
          role="group"
          aria-label="View"
        >
          {(
            [
              { key: "table" as const, label: "Table", icon: Rows3 },
              { key: "cards" as const, label: "Cards", icon: LayoutGrid },
            ]
          ).map((option) => {
            const Icon = option.icon;
            const active = view === option.key;
            return (
              <button
                key={option.key}
                type="button"
                aria-pressed={active}
                onClick={() => onViewChange(option.key)}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded px-2.5 py-1 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  active
                    ? "bg-secondary/15 text-foreground"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                <Icon className="h-3.5 w-3.5" aria-hidden="true" />
                {option.label}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
