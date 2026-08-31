"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { forwardRef, type ButtonHTMLAttributes } from "react";

import { Badge } from "@/components/ui/badge";
import { useRovingTabs } from "@/lib/use-roving-tabs";
import type { ExceptionCategoryInfo } from "@/lib/api-client";
import { cn } from "@/lib/utils";

export interface CategoryTabsProps {
  categories: ExceptionCategoryInfo[];
  active: string;
  total: number;
}

/**
 * All ten tabs of the governing matrix, always.
 *
 * The three that nothing can raise yet are rendered exactly like the seven that can, because
 * that is the truth of them: they are real categories with real owners that simply have nothing
 * in them. Marking them as "coming soon" would be wrong the moment a later step starts filling
 * them, and hiding them would make this screen need restructuring when it does.
 */
export function CategoryTabs({ categories, active, total }: CategoryTabsProps) {
  const router = useRouter();
  const searchParams = useSearchParams();

  function select(category: string) {
    const next = new URLSearchParams(searchParams.toString());
    if (category) next.set("exception_type", category);
    else next.delete("exception_type");
    next.delete("page");
    router.push(`/exceptions?${next.toString()}`);
  }

  // "All categories" first, then the ten. Kept as one list so the keyboard navigation counts and
  // indexes exactly what is rendered, rather than the tabs plus a special case.
  const tabs = [
    { key: "", label: "All categories", count: total, title: undefined as string | undefined },
    ...categories.map((category) => ({
      key: category.category,
      label: category.label,
      count: category.open_count,
      title: category.dormant_reason ?? category.description,
    })),
  ];
  const activeIndex = Math.max(
    0,
    tabs.findIndex((tab) => tab.key === active),
  );
  const { tabProps } = useRovingTabs(tabs.length, (index) => select(tabs[index].key));

  return (
    <div
      role="tablist"
      aria-label="Exception categories"
      className="flex flex-wrap gap-1.5 border-b border-border pb-3"
    >
      {tabs.map((tab, index) => (
        <Tab
          key={tab.key || "all"}
          label={tab.label}
          count={tab.count}
          selected={index === activeIndex}
          title={tab.title}
          onSelect={() => select(tab.key)}
          {...tabProps(index, index === activeIndex)}
        />
      ))}
    </div>
  );
}

const Tab = forwardRef<
  HTMLButtonElement,
  {
    label: string;
    count: number;
    selected: boolean;
    title?: string;
    onSelect: () => void;
  } & Omit<ButtonHTMLAttributes<HTMLButtonElement>, "onSelect">
>(function Tab({ label, count, selected, title, onSelect, ...rest }, ref) {
  return (
    <button
      ref={ref}
      type="button"
      role="tab"
      aria-selected={selected}
      title={title}
      onClick={onSelect}
      {...rest}
      className={cn(
        "inline-flex items-center gap-space-100 rounded-control px-space-150 py-space-075 text-body-sm transition-colors focus-visible:outline-none focus-visible:ring-thick focus-visible:ring-ring",
        selected
          ? "bg-secondary/15 font-medium text-foreground"
          : "text-muted-foreground hover:bg-elevation-hovered hover:text-foreground",
      )}
    >
      <span>{label}</span>
      <Badge variant={count > 0 ? "secondary" : "muted"} className="tabular-nums">
        {count}
      </Badge>
    </button>
  );
});
