"use client";

import { Ship, TriangleAlert } from "lucide-react";
import Link from "next/link";

import { StalenessIndicator } from "@/components/shipments/staleness-indicator";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { LinkedShipment } from "@/lib/api-client";
import { labelFor } from "@/lib/intake";
import {
  SHIPMENT_MILESTONE_LABELS,
  SHIPMENT_STATUS_CHIP,
  SHIPMENT_STATUS_LABELS,
  formatDate,
  sourceLabel,
  type ShipmentStatus,
} from "@/lib/shipments";
import { cn } from "@/lib/utils";

export interface LinkedShipmentCardProps {
  shipments: LinkedShipment[];
}

/**
 * Where this batch's cargo actually is, on the screen the desk preparing the deal is looking at.
 *
 * A genuinely new addition to two already-shipped workspaces rather than a placeholder finally
 * being filled, so it is built to stand on its own: it says nothing when there is no shipment
 * record, which is a real and common state, and it never implies a status the platform does not
 * have.
 *
 * `original_bl_received` is here for a specific reason. It is the field BR-07 holds a sales
 * submission on, and the preparing desk seeing "submission is blocked" needs to be able to see,
 * in the same glance, that the reason is a piece of paper that has not arrived.
 */
export function LinkedShipmentCard({ shipments }: LinkedShipmentCardProps) {
  if (shipments.length === 0) {
    return (
      <section
        className="space-y-2 rounded-lg border border-dashed border-border bg-surface p-4"
        aria-label="Linked shipment"
      >
        <div className="flex items-center gap-2">
          <Ship className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
          <h2 className="text-sm font-semibold text-foreground">Linked shipment</h2>
        </div>
        <p className="text-sm text-muted-foreground">
          No shipment record exists for this batch yet. One appears as soon as a container number
          is extracted from a linked document, or when the logistics desk opens one by hand.
        </p>
      </section>
    );
  }

  return (
    <section
      className="space-y-3 rounded-lg border border-border bg-card p-4"
      aria-label="Linked shipment"
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Ship className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
          <h2 className="text-sm font-semibold text-foreground">
            Linked shipment{shipments.length === 1 ? "" : "s"}
          </h2>
        </div>
        <Badge variant="muted">{shipments.length}</Badge>
      </div>

      <ul className="space-y-3">
        {shipments.map((shipment) => (
          <li
            key={shipment.id}
            className="space-y-2 rounded-md border border-border bg-surface px-3 py-2.5"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="font-mono text-sm text-secondary">
                {shipment.container_number ?? shipment.bl_number ?? "No reference"}
              </span>
              <div className="flex flex-wrap items-center gap-1.5">
                <Badge
                  variant="outline"
                  className={cn(
                    SHIPMENT_STATUS_CHIP[shipment.status as ShipmentStatus] ??
                      "border-border bg-muted text-muted-foreground",
                  )}
                >
                  {labelFor(SHIPMENT_STATUS_LABELS, shipment.status)}
                </Badge>
                <Badge variant="muted">
                  {labelFor(
                    SHIPMENT_MILESTONE_LABELS,
                    shipment.current_milestone ?? "unknown",
                  )}
                </Badge>
              </div>
            </div>

            <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm sm:grid-cols-4">
              <Item label="Carrier" value={shipment.carrier} />
              <Item label="Vessel" value={shipment.vessel} />
              <Item label="ETD" value={formatDate(shipment.etd)} />
              <Item label="ETA" value={formatDate(shipment.eta)} />
            </dl>

            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex flex-wrap items-center gap-2">
                <StalenessIndicator
                  hours={shipment.hours_since_check}
                  lastCheckedAt={shipment.last_checked_at}
                  isStale={shipment.is_stale}
                />
                <span className="text-xs text-muted-foreground">
                  {sourceLabel(shipment.last_checked_source)}
                </span>
                {shipment.original_bl_received ? (
                  <Badge
                    variant="outline"
                    className="border-signal-confident/35 bg-signal-confident/10 text-signal-confident"
                  >
                    Original B/L received
                  </Badge>
                ) : (
                  <Badge
                    variant="outline"
                    className="border-signal-review/35 bg-signal-review/10 text-signal-review"
                  >
                    Original B/L not yet in hand
                  </Badge>
                )}
                {shipment.review_flagged ? (
                  <Badge
                    variant="outline"
                    className="border-signal-review/35 bg-signal-review/10 text-signal-review"
                  >
                    <TriangleAlert className="mr-1 h-3 w-3" aria-hidden="true" />
                    Needs a look
                  </Badge>
                ) : null}
              </div>
              <Button asChild size="sm" variant="ghost">
                <Link href={`/shipments/${shipment.id}`}>Open shipment</Link>
              </Button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Item({ label, value }: { label: string; value: string | null }) {
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-widest text-muted-foreground">
        {label}
      </dt>
      <dd className="mt-0.5 truncate text-foreground">{value ?? "—"}</dd>
    </div>
  );
}
