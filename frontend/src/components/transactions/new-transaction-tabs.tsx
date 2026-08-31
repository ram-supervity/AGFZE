"use client";

import { forwardRef, useState, type ButtonHTMLAttributes } from "react";

import { NewFaTransactionForm } from "@/components/transactions/new-fa-transaction-form";
import { NewSalesLegForm } from "@/components/transactions/new-sales-leg-form";
import { NewTransactionForm } from "@/components/transactions/new-transaction-form";
import type { CommodityCode, FaFieldSchema } from "@/lib/api-client";
import { useRovingTabs } from "@/lib/use-roving-tabs";
import { cn } from "@/lib/utils";

export interface NewTransactionTabsProps {
  commodities: CommodityCode[];
  faFieldSchema: FaFieldSchema[];
  canRegisterPurchase: boolean;
  canAttachSales: boolean;
  canRegisterFa: boolean;
}

type Path = "purchase" | "sales" | "fa";

const PATHS: { key: Path; title: string; hint: string }[] = [
  {
    key: "purchase",
    title: "Purchase deal",
    hint: "Opens a new batch for material AGFZE is buying.",
  },
  {
    key: "sales",
    title: "Sales deal",
    hint: "Attaches the sell side to a batch that already exists.",
  },
  {
    key: "fa",
    title: "FA transaction",
    hint: "Opens its own record on AGFZE's second business line.",
  },
];

/**
 * The three registration paths, and the reason they are not all alike.
 *
 * A purchase is where a batch begins, so registering one creates a transaction. A sale is of
 * cargo already bought, so registering one attaches to a transaction rather than creating a
 * second record for the same physical material. FA takes the purchase shape rather than the sales
 * one, and that is not an oversight: FA is a structurally separate business line, not the other
 * side of a scrap cargo, so there is nothing for it to attach to.
 *
 * Putting all three behind one "new transaction" button that behaved differently would hide
 * exactly the distinctions that keep this platform free of a merge.
 *
 * The strip carries the same roving tabindex the exception queue's categories do. Without it each
 * path sits in the page's tab order, so somebody reaching the form itself by keyboard steps
 * through all three first, and the arrow keys - which is what a tablist is expected to answer to -
 * do nothing at all.
 */
export function NewTransactionTabs({
  commodities,
  faFieldSchema,
  canRegisterPurchase,
  canAttachSales,
  canRegisterFa,
}: NewTransactionTabsProps) {
  const permitted: Record<Path, boolean> = {
    purchase: canRegisterPurchase,
    sales: canAttachSales,
    fa: canRegisterFa,
  };
  const available = PATHS.filter((path) => permitted[path.key]);
  const [path, setPath] = useState<Path>(available[0]?.key ?? "purchase");
  const activeIndex = Math.max(
    0,
    available.findIndex((entry) => entry.key === path),
  );
  const { tabProps } = useRovingTabs(available.length, (index) => {
    const next = available[index];
    if (next) setPath(next.key);
  });

  return (
    <div className="space-y-6">
      {available.length > 1 ? (
        <div className="flex flex-wrap gap-2" role="tablist" aria-label="What are you registering">
          {available.map((entry, index) => (
            <PathTab
              key={entry.key}
              title={entry.title}
              hint={entry.hint}
              selected={index === activeIndex}
              onSelect={() => setPath(entry.key)}
              {...tabProps(index, index === activeIndex)}
            />
          ))}
        </div>
      ) : null}

      {path === "sales" ? (
        <NewSalesLegForm />
      ) : path === "fa" ? (
        <NewFaTransactionForm extraFields={faFieldSchema} />
      ) : (
        <NewTransactionForm commodities={commodities} />
      )}
    </div>
  );
}

const PathTab = forwardRef<
  HTMLButtonElement,
  {
    title: string;
    hint: string;
    selected: boolean;
    onSelect: () => void;
  } & Omit<ButtonHTMLAttributes<HTMLButtonElement>, "onSelect" | "title">
>(function PathTab({ title, hint, selected, onSelect, ...rest }, ref) {
  return (
    <button
      ref={ref}
      type="button"
      role="tab"
      aria-selected={selected}
      onClick={onSelect}
      {...rest}
      className={cn(
        "rounded-control border-thin px-space-150 py-space-100 text-left text-body-sm transition-colors",
        "focus-visible:outline-none focus-visible:ring-thick focus-visible:ring-ring",
        selected
          ? "border-secondary bg-secondary/10 text-foreground"
          : "border-border bg-elevation-default text-muted-foreground hover:text-foreground",
      )}
    >
      <span className="block font-medium">{title}</span>
      <span className="block text-xs">{hint}</span>
    </button>
  );
});
