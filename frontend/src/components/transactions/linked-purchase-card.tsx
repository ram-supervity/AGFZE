"use client";

import { CircleCheck, TriangleAlert } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import type { LinkedPurchaseContext, TransactionDetail } from "@/lib/api-client";
import { INVOICE_STATUS_LABELS } from "@/lib/transactions";
import { labelFor } from "@/lib/intake";
import { formatMoney } from "@/lib/transactions";
import { cn } from "@/lib/utils";

export interface LinkedPurchaseCardProps {
  detail: TransactionDetail;
  linked: LinkedPurchaseContext;
}

/**
 * The buy side of the same physical cargo, shown beside the sell side.
 *
 * One comparison is made here and one only: the batch's resolved commodity code against the
 * grade the sales document reported. Those are shared by construction between the legs, so a
 * disagreement can only mean this shipment was attached to the wrong batch - which is worth
 * shouting about.
 *
 * What is deliberately *not* shown, and never compared, is the free-text commodity description
 * on either side. A China-bound shipment legitimately carries different customs wording for the
 * same underlying code than the purchase paperwork used. Flagging that would raise a warning on
 * nearly every export the desk makes, and a warning that is usually wrong is worse than none.
 */
export function LinkedPurchaseCard({ detail, linked }: LinkedPurchaseCardProps) {
  const mismatch = linked.commodity_code_mismatch;

  return (
    <section
      className={cn(
        "space-y-3 rounded-lg border bg-card p-4",
        mismatch ? "border-pill-red-border bg-pill-red-bg" : "border-border",
      )}
      aria-label="Linked purchase leg"
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold text-foreground">Linked purchase leg</h2>
          <p className="mt-0.5 text-xs text-muted-foreground">
            The buy side of this same batch, and the one code comparison that matters.
          </p>
        </div>
        {mismatch ? (
          <Badge
            variant="outline"
            className="border-pill-red-border bg-pill-red-bg text-pill-red-text"
          >
            <TriangleAlert className="mr-1 h-3 w-3" aria-hidden="true" />
            Commodity code mismatch
          </Badge>
        ) : (
          <Badge
            variant="outline"
            className="border-pill-green-border bg-pill-green-bg text-pill-green-text"
          >
            <CircleCheck className="mr-1 h-3 w-3" aria-hidden="true" />
            Codes agree
          </Badge>
        )}
      </div>

      <div
        className={cn(
          "rounded-md border px-3 py-2.5",
          mismatch
            ? "border-pill-red-border bg-pill-red-bg"
            : "border-border bg-surface",
        )}
      >
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
          <div>
            <p className="text-xs font-medium uppercase tracking-widest text-muted-foreground">
              Batch commodity code
            </p>
            <p className="mt-0.5 font-mono text-sm font-semibold text-foreground">
              {linked.commodity_code ?? "Not resolved"}
            </p>
          </div>
          <div>
            <p className="text-xs font-medium uppercase tracking-widest text-muted-foreground">
              Reported on the sales document
            </p>
            <p className="mt-0.5 font-mono text-sm font-semibold text-foreground">
              {linked.sales_document_commodity_value ?? "Not stated"}
            </p>
          </div>
        </div>
        {linked.message ? (
          <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{linked.message}</p>
        ) : null}
      </div>

      {linked.present ? (
        <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <Item label="Supplier" value={linked.supplier_name} />
          <Item label="Purchase contract" value={linked.contract_number} mono />
          <Item label="Supplier invoice" value={linked.supplier_invoice_number} mono />
          <Item
            label="Purchase invoice status"
            value={
              linked.invoice_status
                ? labelFor(INVOICE_STATUS_LABELS, linked.invoice_status)
                : null
            }
          />
          <Item label="Port of loading" value={linked.port_of_loading} />
          <Item
            label="Purchase value"
            value={linked.amount ? formatMoney(linked.amount, detail.currency) : null}
          />
        </dl>
      ) : (
        <p className="rounded-md border border-pill-amber-border bg-pill-amber-bg px-3 py-2 text-sm text-foreground">
          This transaction carries no purchase leg. The sales leg was attached with an explicit
          acknowledgement that no purchase counterpart exists for this cargo yet.
        </p>
      )}
    </section>
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
    <div>
      <dt className="text-xs font-medium uppercase tracking-widest text-muted-foreground">
        {label}
      </dt>
      <dd className={cn("mt-0.5 text-sm text-foreground", mono && "font-mono")}>
        {value ?? "-"}
      </dd>
    </div>
  );
}
