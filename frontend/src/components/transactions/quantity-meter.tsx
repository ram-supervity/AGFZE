"use client";

import { Badge } from "@/components/ui/badge";
import type { ContractCoverage } from "@/lib/api-client";
import {
  COVERAGE_BAR,
  COVERAGE_LABELS,
  COVERAGE_TONE,
  formatQuantity,
  type CoverageState,
} from "@/lib/transactions";
import { cn } from "@/lib/utils";

export interface QuantityMeterProps {
  coverage: ContractCoverage;
}

/**
 * Everything invoiced against this sales contract, summed across every shipment on it, against
 * the total the contract actually covers.
 *
 * The figure is deliberately not this shipment's. A sales contract is commonly fulfilled across
 * several shipments, so "have we invoiced more than we agreed" is a question about the contract,
 * and answering it from one shipment would always answer it wrong.
 *
 * The colours are the platform's existing red/amber/green language. Part-shipped reads green,
 * not amber: a contract with more shipments to come is the normal condition of a live deal, and
 * colouring it as a warning would teach people to ignore warnings.
 */
export function QuantityMeter({ coverage }: QuantityMeterProps) {
  const state = coverage.state as CoverageState;
  const percent = Math.max(0, Math.min(100, Math.round(coverage.ratio * 100)));
  // Over-invoiced, the bar is full and the overspill is stated in words rather than drawn past
  // the end of a track that cannot show it.
  const width = state === "exceeded" ? 100 : percent;

  return (
    <section
      className={cn("space-y-3 rounded-lg border bg-card p-4", state === "exceeded" && "border-signal-blocked/45")}
      aria-label="Sales contract quantity coverage"
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold text-foreground">Contract quantity</h2>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Summed across every shipment on sales contract{" "}
            <span className="font-mono">{coverage.sales_contract_no}</span>.
          </p>
        </div>
        <Badge variant="outline" className={COVERAGE_TONE[state]}>
          {COVERAGE_LABELS[state]}
        </Badge>
      </div>

      <div className="space-y-1.5">
        <div
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={percent}
          aria-label={`${percent}% of the contracted quantity invoiced`}
          className="h-2.5 w-full overflow-hidden rounded-full bg-muted"
        >
          <div
            className={cn("h-full rounded-full transition-[width] duration-300", COVERAGE_BAR[state])}
            style={{ width: `${width}%` }}
          />
        </div>
        <div className="flex flex-wrap items-baseline justify-between gap-2 text-xs">
          <span className="tabular-nums text-foreground">
            {formatQuantity(coverage.invoiced_quantity_mt)} invoiced
          </span>
          <span className="tabular-nums text-muted-foreground">
            {coverage.contracted_quantity_mt
              ? `${formatQuantity(coverage.contracted_quantity_mt)} contracted`
              : "no contracted total recorded"}
          </span>
        </div>
      </div>

      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <div>
          <dt className="text-xs font-medium uppercase tracking-widest text-muted-foreground">
            Shipments
          </dt>
          <dd className="mt-0.5 text-sm tabular-nums text-foreground">
            {coverage.shipment_count}
          </dd>
        </div>
        <div>
          <dt className="text-xs font-medium uppercase tracking-widest text-muted-foreground">
            {state === "exceeded" ? "Over by" : "Still to ship"}
          </dt>
          <dd
            className={cn(
              "mt-0.5 text-sm tabular-nums",
              state === "exceeded" ? "text-signal-blocked" : "text-foreground",
            )}
          >
            {coverage.remaining_quantity_mt
              ? formatQuantity(
                state === "exceeded"
                  ? String(Math.abs(Number.parseFloat(coverage.remaining_quantity_mt)))
                  : coverage.remaining_quantity_mt,
              )
              : "-"}
          </dd>
        </div>
        <div>
          <dt className="text-xs font-medium uppercase tracking-widest text-muted-foreground">
            Invoiced
          </dt>
          <dd className="mt-0.5 text-sm tabular-nums text-foreground">{percent}%</dd>
        </div>
      </dl>

      <p
        className={cn(
          "rounded-md border px-3 py-2 text-sm leading-relaxed",
          state === "exceeded"
            ? "border-pill-red-border bg-pill-red-bg text-foreground"
            : "border-border bg-surface text-muted-foreground",
        )}
      >
        {coverage.message}
      </p>
    </section>
  );
}
