"use client";

import { RefreshCw, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useSession } from "next-auth/react";
import { useState } from "react";
import toast from "react-hot-toast";

import { PageHeader } from "@/components/shared/page-header";
import { IssueLog } from "@/components/shipments/issue-log";
import { ManualUpdateForm } from "@/components/shipments/manual-update-form";
import { MilestoneTimeline } from "@/components/shipments/milestone-timeline";
import { StalenessIndicator } from "@/components/shipments/staleness-indicator";
import { CollapsiblePanel } from "@/components/transactions/collapsible-panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  ApiError,
  logShipmentIssue,
  refreshShipment,
  updateShipment,
  type DocumentSummary,
  type ShipmentDetail,
  type ShipmentManualUpdate,
} from "@/lib/api-client";
import { labelFor } from "@/lib/intake";
import {
  BILL_OF_LADING_TYPE_LABELS,
  SHIPMENT_MILESTONE_LABELS,
  SHIPMENT_STATUS_CHIP,
  SHIPMENT_STATUS_LABELS,
  formatDate,
  formatDateTime,
  sourceLabel,
  trackingModeNote,
  type ShipmentStatus,
} from "@/lib/shipments";
import { formatQuantity, workspacePath } from "@/lib/transactions";
import { cn } from "@/lib/utils";

export interface ShipmentWorkspaceProps {
  initial: ShipmentDetail;
  documents: DocumentSummary[];
}

/**
 * One shipment, in full.
 *
 * The manual entry form sits open on the page rather than behind a dialog or an "override"
 * disclosure, because for almost every shipment here it is not an exception to the normal way of
 * working - it *is* the normal way of working. Refresh sits beside it and says honestly what it
 * found, which today is usually that no carrier source exists to ask.
 */
export function ShipmentWorkspace({ initial, documents }: ShipmentWorkspaceProps) {
  const { data: session } = useSession();
  const [shipment, setShipment] = useState(initial);
  const [refreshing, setRefreshing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [loggingIssue, setLoggingIssue] = useState(false);

  const token = session?.accessToken;
  const bill = shipment.bills_of_lading[0];

  async function refresh() {
    if (!token) {
      toast.error("Your session has expired. Sign in again to refresh this shipment.");
      return;
    }
    setRefreshing(true);
    try {
      const result = await refreshShipment(token, shipment.id);
      setShipment(result.shipment);
      if (result.attempted && result.updated) toast.success(result.message);
      else toast(result.message, { icon: "✎" });
    } catch (error) {
      toast.error(
        error instanceof ApiError ? error.message : "The shipment could not be refreshed.",
      );
    } finally {
      setRefreshing(false);
    }
  }

  async function save(update: ShipmentManualUpdate) {
    if (!token) {
      toast.error("Your session has expired. Sign in again to record this update.");
      return;
    }
    setSaving(true);
    try {
      const updated = await updateShipment(token, shipment.id, update);
      setShipment(updated);
      if (updated.review_flagged) {
        toast(
          updated.review_reason ??
          "That change has been saved and flagged for somebody to confirm.",
          { icon: "⚠" },
        );
      } else {
        toast.success("Shipment updated and added to its milestone timeline.");
      }
    } catch (error) {
      toast.error(
        error instanceof ApiError ? error.message : "The update could not be recorded.",
      );
    } finally {
      setSaving(false);
    }
  }

  async function logIssue(issue: {
    issue_type: string;
    description: string;
    document_id: string | null;
  }) {
    if (!token) {
      toast.error("Your session has expired. Sign in again to log this issue.");
      return;
    }
    setLoggingIssue(true);
    try {
      await logShipmentIssue(token, shipment.id, issue);
      const { fetchShipmentDetail } = await import("@/lib/api-client");
      setShipment(await fetchShipmentDetail(token, shipment.id));
      toast.success("Issue logged against this shipment.");
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "The issue could not be logged.");
    } finally {
      setLoggingIssue(false);
    }
  }

  const reference = shipment.container_number ?? shipment.bl_number ?? "Shipment";

  return (
    <div className="space-y-6">
      <PageHeader
        title={reference}
        description={
          [shipment.carrier, shipment.vessel].filter(Boolean).join(" · ") ||
          "No carrier or vessel recorded for this shipment yet."
        }
        actions={
          <div className="flex flex-wrap gap-2">
            {shipment.can_manage ? (
              <Button variant="outline" size="sm" disabled={refreshing} onClick={refresh}>
                <RefreshCw
                  className={cn("mr-1.5 h-3.5 w-3.5", refreshing && "animate-spin")}
                  aria-hidden="true"
                />
                {refreshing ? "Checking…" : "Refresh status"}
              </Button>
            ) : null}
            <Button asChild variant="outline" size="sm">
              <Link href="/shipments">Back to shipments</Link>
            </Button>
          </div>
        }
      />

      <div className="flex flex-wrap items-center gap-2">
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
          {labelFor(SHIPMENT_MILESTONE_LABELS, shipment.current_milestone ?? "unknown")}
        </Badge>
        <StalenessIndicator
          hours={shipment.hours_since_check}
          lastCheckedAt={shipment.last_checked_at}
          isStale={shipment.is_stale}
          thresholdHours={shipment.stale_threshold_hours}
        />
        <span className="text-xs text-muted-foreground">
          {sourceLabel(shipment.last_checked_source)}
          {shipment.last_checked_at ? ` · ${formatDateTime(shipment.last_checked_at)}` : ""}
        </span>
      </div>

      {shipment.review_flagged ? (
        <p className="flex items-start gap-2 rounded-md border border-signal-review/35 bg-signal-review/10 px-4 py-3 text-sm text-foreground">
          <TriangleAlert
            className="mt-0.5 h-4 w-4 shrink-0 text-signal-review"
            aria-hidden="true"
          />
          <span>
            {shipment.review_reason ??
              "The last change to this shipment did not look plausible."}{" "}
            It was saved regardless - correcting a wrong figure matters more than refusing a
            surprising one - but somebody should confirm it against the carrier.
          </span>
        </p>
      ) : null}

      {shipment.last_error ? (
        <p className="rounded-md border border-signal-blocked/35 bg-signal-blocked/10 px-4 py-3 text-sm text-foreground">
          The last tracking attempt failed: {shipment.last_error}
          {shipment.consecutive_failures > 1
            ? ` That is ${shipment.consecutive_failures} in a row.`
            : ""}
        </p>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <CollapsiblePanel
            title="Record the status by hand"
            description="What the carrier told you, written straight onto the shipment. The same fields, the same audit trail and the same checks an automatic reading gets."
            defaultOpen
            badge={
              shipment.carrier_adapters_available === 0 ? (
                <Badge variant="muted">No carrier source connected</Badge>
              ) : undefined
            }
          >
            {shipment.can_manage ? (
              <ManualUpdateForm shipment={shipment} saving={saving} onSave={save} />
            ) : (
              <p className="text-sm text-muted-foreground">
                {trackingModeNote(shipment.carrier_adapters_available)} Updating a shipment
                belongs to the logistics desk; your role reads the board.
              </p>
            )}
          </CollapsiblePanel>

          <CollapsiblePanel
            title="Milestone timeline"
            description="Derived from this shipment's audit trail. There is no separate history table behind it."
            defaultOpen
            badge={<Badge variant="muted">{shipment.timeline.length} events</Badge>}
          >
            <MilestoneTimeline entries={shipment.timeline} />
          </CollapsiblePanel>

          <CollapsiblePanel
            title="Post-delivery issues"
            description="Quality, damage, detention or anything else that went wrong after the cargo left."
            defaultOpen={shipment.issues.length > 0}
            badge={
              shipment.issues.length > 0 ? (
                <Badge
                  variant="outline"
                  className="border-signal-review/35 bg-signal-review/10 text-signal-review"
                >
                  {shipment.issues.length} logged
                </Badge>
              ) : undefined
            }
          >
            <IssueLog
              issues={shipment.issues}
              issueTypes={shipment.issue_types}
              documents={documents}
              canLog={shipment.can_manage}
              saving={loggingIssue}
              onLog={logIssue}
            />
          </CollapsiblePanel>
        </div>

        <div className="space-y-4">
          <section
            className="space-y-3 rounded-lg border border-border bg-card p-4"
            aria-label="Linked transaction"
          >
            <h2 className="text-sm font-semibold text-foreground">Linked transaction</h2>
            {shipment.transaction ? (
              <>
                <dl className="space-y-2.5">
                  <Item label="Batch" value={shipment.transaction.batch_number} mono />
                  <Item label="Counterparty" value={shipment.transaction.counterparty} />
                  <Item label="Contract" value={shipment.transaction.contract_number} mono />
                  <Item label="Commodity" value={shipment.transaction.commodity_name} />
                  <Item
                    label="Quantity"
                    value={
                      shipment.transaction.quantity_mt
                        ? formatQuantity(shipment.transaction.quantity_mt)
                        : null
                    }
                  />
                </dl>
                <Button asChild size="sm" variant="outline" className="w-full">
                  <Link
                    href={workspacePath({
                      id: shipment.transaction.id,
                      has_sales_leg: shipment.transaction.has_sales_leg,
                      has_fa_leg: shipment.transaction.has_fa_leg,
                    })}
                  >
                    Open the transaction
                  </Link>
                </Button>
              </>
            ) : (
              <p className="text-sm text-muted-foreground">
                This shipment is not linked to a transaction.
              </p>
            )}
          </section>

          <section
            className="space-y-3 rounded-lg border border-border bg-card p-4"
            aria-label="Shipment details"
          >
            <h2 className="text-sm font-semibold text-foreground">Shipment</h2>
            <dl className="space-y-2.5">
              <Item label="Container" value={shipment.container_number} mono />
              <Item label="Seal" value={shipment.container?.seal_number ?? null} mono />
              <Item label="B/L number" value={shipment.bl_number} mono />
              <Item label="Port of loading" value={shipment.port_of_loading} />
              <Item label="Port of discharge" value={shipment.port_of_discharge} />
              <Item label="ETD" value={formatDate(shipment.etd)} />
              <Item label="ETA" value={formatDate(shipment.eta)} />
            </dl>
          </section>

          <section
            className="space-y-3 rounded-lg border border-border bg-card p-4"
            aria-label="Bill of lading"
          >
            <h2 className="text-sm font-semibold text-foreground">Bill of lading</h2>
            {bill ? (
              <>
                <dl className="space-y-2.5">
                  <Item
                    label="Type"
                    value={labelFor(BILL_OF_LADING_TYPE_LABELS, bill.bl_type)}
                  />
                  <Item label="Number" value={bill.bl_number} mono />
                  <Item
                    label="Original received"
                    value={
                      bill.is_original_received
                        ? formatDateTime(bill.received_at)
                        : "Not yet in hand"
                    }
                  />
                </dl>
                <p className="text-xs leading-relaxed text-muted-foreground">
                  This is the field BR-07 holds a sales submission on - not the document type of
                  whatever file happens to be attached.
                </p>
              </>
            ) : (
              <p className="text-sm text-muted-foreground">
                No bill of lading has been recorded against this shipment yet. Record one in the
                manual panel; until then BR-07 falls back to the looser document-type signal.
              </p>
            )}
          </section>

          {shipment.containers.length > 1 ? (
            <section
              className="space-y-2 rounded-lg border border-border bg-card p-4"
              aria-label="Other containers on this batch"
            >
              <h2 className="text-sm font-semibold text-foreground">
                Other containers on this batch
              </h2>
              <ul className="space-y-1">
                {shipment.containers
                  .filter((row) => row.container_number !== shipment.container_number)
                  .map((row) => (
                    <li key={row.id} className="font-mono text-sm text-muted-foreground">
                      {row.container_number}
                    </li>
                  ))}
              </ul>
              <p className="text-xs text-muted-foreground">
                A batch loaded into several containers is ordinary, and nothing flags it.
              </p>
            </section>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function Item({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string | null;
  mono?: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="text-xs font-medium uppercase tracking-widest text-muted-foreground">
        {label}
      </dt>
      <dd className={cn("text-right text-sm text-foreground", mono && "font-mono")}>
        {value ?? "-"}
      </dd>
    </div>
  );
}
