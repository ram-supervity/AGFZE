"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { BUSINESS_STREAMS, STREAM_LABELS } from "@/lib/intake";
import { TRANSACTION_STATUSES, TRANSACTION_STATUS_LABELS } from "@/lib/transactions";

export interface TransactionFiltersProps {
  search: string;
  stream: string;
  status: string;
  dealType: string;
  dateFrom: string;
  dateTo: string;
}

export function TransactionFilters(initial: TransactionFiltersProps) {
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
    router.push(`/transactions?${next.toString()}`);
  }

  const active = Boolean(
    initial.search ||
      initial.stream ||
      initial.status ||
      initial.dealType ||
      initial.dateFrom ||
      initial.dateTo,
  );

  return (
    <form
      className="grid gap-space-150 rounded-medium border-thin border-border bg-elevation-default p-space-200 sm:grid-cols-2 xl:grid-cols-6"
      onSubmit={(event) => {
        event.preventDefault();
        apply({ search: search.trim() || null });
      }}
    >
      <div className="space-y-1.5 sm:col-span-2 xl:col-span-1">
        <Label htmlFor="tx-search">Search</Label>
        <Input
          id="tx-search"
          value={search}
          placeholder="Batch, contract, supplier, invoice"
          onChange={(event) => setSearch(event.target.value)}
        />
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="tx-stream">Stream</Label>
        <Select
          id="tx-stream"
          value={initial.stream}
          onChange={(event) => apply({ stream: event.target.value || null })}
        >
          <option value="">All streams</option>
          {BUSINESS_STREAMS.map((value) => (
            <option key={value} value={value}>
              {STREAM_LABELS[value]}
            </option>
          ))}
        </Select>
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="tx-status">Status</Label>
        <Select
          id="tx-status"
          value={initial.status}
          onChange={(event) => apply({ status: event.target.value || null })}
        >
          <option value="">Any state</option>
          {TRANSACTION_STATUSES.map((value) => (
            <option key={value} value={value}>
              {TRANSACTION_STATUS_LABELS[value]}
            </option>
          ))}
        </Select>
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="tx-deal-type">Deal type</Label>
        <Select
          id="tx-deal-type"
          value={initial.dealType}
          onChange={(event) => apply({ deal_type: event.target.value || null })}
        >
          <option value="">All deals</option>
          <option value="b2b">B2B only</option>
          <option value="standard">Standard only</option>
        </Select>
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="tx-from">Opened from</Label>
        <Input
          id="tx-from"
          type="date"
          value={initial.dateFrom}
          onChange={(event) => apply({ date_from: event.target.value || null })}
        />
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="tx-to">Opened to</Label>
        <Input
          id="tx-to"
          type="date"
          value={initial.dateTo}
          onChange={(event) => apply({ date_to: event.target.value || null })}
        />
      </div>

      <div className="flex gap-2 sm:col-span-2 xl:col-span-6">
        <Button type="submit" variant="outline" size="sm">
          Search
        </Button>
        {active ? (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => router.push("/transactions")}
          >
            Clear filters
          </Button>
        ) : null}
      </div>
    </form>
  );
}
