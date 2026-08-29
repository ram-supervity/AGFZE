"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import {
  BUSINESS_STREAMS,
  CATEGORY_LABELS,
  REQUEST_CATEGORIES,
  STREAM_LABELS,
} from "@/lib/intake";

export interface InboxFiltersProps {
  category: string;
  stream: string;
  needsReview: boolean;
  search: string;
}

export function InboxFilters(initial: InboxFiltersProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [search, setSearch] = useState(initial.search);

  useEffect(() => {
    setSearch(initial.search);
  }, [initial.search]);

  function apply(changes: Record<string, string | null>) {
    const next = new URLSearchParams(searchParams.toString());
    for (const [key, value] of Object.entries(changes)) {
      if (value === null || value === "") next.delete(key);
      else next.set(key, value);
    }
    // Any filter change returns to the first page; page 4 of the old result set is meaningless.
    next.delete("page");
    router.push(`/inbox?${next.toString()}`);
  }

  const active = Boolean(initial.category || initial.stream || initial.needsReview || initial.search);

  return (
    <form
      className="grid gap-3 rounded-lg border border-border bg-surface p-4 sm:grid-cols-2 lg:grid-cols-4"
      onSubmit={(event) => {
        event.preventDefault();
        apply({ search: search.trim() || null });
      }}
    >
      <div className="space-y-1.5">
        <Label htmlFor="inbox-search">Search</Label>
        <Input
          id="inbox-search"
          value={search}
          placeholder="Request code, subject, sender, filename"
          onChange={(event) => setSearch(event.target.value)}
        />
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="inbox-category">Category</Label>
        <Select
          id="inbox-category"
          value={initial.category}
          onChange={(event) => apply({ category: event.target.value || null })}
        >
          <option value="">All categories</option>
          {REQUEST_CATEGORIES.map((category) => (
            <option key={category} value={category}>
              {CATEGORY_LABELS[category]}
            </option>
          ))}
        </Select>
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="inbox-stream">Stream</Label>
        <Select
          id="inbox-stream"
          value={initial.stream}
          onChange={(event) => apply({ stream: event.target.value || null })}
        >
          <option value="">Both streams</option>
          {BUSINESS_STREAMS.map((stream) => (
            <option key={stream} value={stream}>
              {STREAM_LABELS[stream]}
            </option>
          ))}
        </Select>
      </div>

      <div className="flex items-end gap-2">
        <label className="flex h-9 flex-1 items-center gap-2 rounded-md border border-input bg-background px-3 text-sm">
          <input
            type="checkbox"
            className="h-3.5 w-3.5 accent-[hsl(var(--signal-review))]"
            checked={initial.needsReview}
            onChange={(event) => apply({ needs_review: event.target.checked ? "true" : null })}
          />
          <span>Needs review</span>
        </label>
        <Button type="submit" variant="outline" size="sm" className="h-9">
          Search
        </Button>
        {active ? (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-9"
            onClick={() => router.push("/inbox")}
          >
            Clear
          </Button>
        ) : null}
      </div>
    </form>
  );
}
