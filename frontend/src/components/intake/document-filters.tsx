"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import {
  DOCUMENT_TYPES,
  DOCUMENT_TYPE_LABELS,
  EXTRACTION_STATUSES,
  EXTRACTION_STATUS_LABELS,
} from "@/lib/intake";

export interface DocumentFiltersProps {
  search: string;
  documentType: string;
  status: string;
  dateFrom: string;
  dateTo: string;
}

export function DocumentFilters(initial: DocumentFiltersProps) {
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
    next.delete("page");
    router.push(`/documents?${next.toString()}`);
  }

  const active = Boolean(
    initial.search || initial.documentType || initial.status || initial.dateFrom || initial.dateTo,
  );

  return (
    <form
      className="grid gap-3 rounded-lg border border-border bg-surface p-4 sm:grid-cols-2 xl:grid-cols-5"
      onSubmit={(event) => {
        event.preventDefault();
        apply({ search: search.trim() || null });
      }}
    >
      <div className="space-y-1.5 sm:col-span-2 xl:col-span-1">
        <Label htmlFor="doc-search">Search</Label>
        <Input
          id="doc-search"
          value={search}
          placeholder="Filename, request code, extracted value"
          onChange={(event) => setSearch(event.target.value)}
        />
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="doc-type">Document type</Label>
        <Select
          id="doc-type"
          value={initial.documentType}
          onChange={(event) => apply({ document_type: event.target.value || null })}
        >
          <option value="">All types</option>
          {DOCUMENT_TYPES.map((value) => (
            <option key={value} value={value}>
              {DOCUMENT_TYPE_LABELS[value]}
            </option>
          ))}
        </Select>
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="doc-status">Extraction</Label>
        <Select
          id="doc-status"
          value={initial.status}
          onChange={(event) => apply({ status: event.target.value || null })}
        >
          <option value="">Any state</option>
          {EXTRACTION_STATUSES.map((value) => (
            <option key={value} value={value}>
              {EXTRACTION_STATUS_LABELS[value]}
            </option>
          ))}
        </Select>
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="doc-from">Received from</Label>
        <Input
          id="doc-from"
          type="date"
          value={initial.dateFrom}
          onChange={(event) => apply({ date_from: event.target.value || null })}
        />
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="doc-to">Received to</Label>
        <Input
          id="doc-to"
          type="date"
          value={initial.dateTo}
          onChange={(event) => apply({ date_to: event.target.value || null })}
        />
      </div>

      <div className="flex gap-2 sm:col-span-2 xl:col-span-5">
        <Button type="submit" variant="outline" size="sm">
          Search
        </Button>
        {active ? (
          <Button type="button" variant="ghost" size="sm" onClick={() => router.push("/documents")}>
            Clear filters
          </Button>
        ) : null}
      </div>
    </form>
  );
}
