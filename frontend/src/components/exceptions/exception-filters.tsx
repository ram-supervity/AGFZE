"use client";

import { useRouter, useSearchParams } from "next/navigation";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { ownerLabel } from "@/lib/governance";
import { PLATFORM_ROLES } from "@/lib/roles";

export interface ExceptionFiltersProps {
  ownerRole: string;
  status: string;
  minAgeHours: string;
  /** From the API, so the ageing options describe the threshold actually configured. */
  thresholdHours: number;
}

export function ExceptionFilters({
  ownerRole,
  status,
  minAgeHours,
  thresholdHours,
}: ExceptionFiltersProps) {
  const router = useRouter();
  const searchParams = useSearchParams();

  function apply(changes: Record<string, string | null>) {
    const next = new URLSearchParams(searchParams.toString());
    for (const [key, value] of Object.entries(changes)) {
      if (value === null || value === "") next.delete(key);
      else next.set(key, value);
    }
    next.delete("page");
    router.push(`/exceptions?${next.toString()}`);
  }

  const active = Boolean(ownerRole || minAgeHours || status !== "open");

  return (
    <div className="grid gap-3 rounded-lg border border-border bg-surface p-4 sm:grid-cols-2 xl:grid-cols-4">
      <div className="space-y-1.5">
        <Label htmlFor="exc-owner">Owned by</Label>
        <Select
          id="exc-owner"
          value={ownerRole}
          onChange={(event) => apply({ owner_role: event.target.value || null })}
        >
          <option value="">Any desk</option>
          {PLATFORM_ROLES.map((role) => (
            <option key={role} value={role}>
              {ownerLabel(role)}
            </option>
          ))}
        </Select>
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="exc-status">State</Label>
        <Select
          id="exc-status"
          value={status}
          onChange={(event) => apply({ status: event.target.value })}
        >
          <option value="open">Still open</option>
          <option value="resolved">Resolved</option>
          <option value="all">Everything</option>
        </Select>
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="exc-age">Open for at least</Label>
        <Select
          id="exc-age"
          value={minAgeHours}
          onChange={(event) => apply({ min_age_hours: event.target.value || null })}
        >
          <option value="">Any age</option>
          <option value="4">4 hours</option>
          <option value="24">A day</option>
          <option value={String(thresholdHours)}>
            The {thresholdHours}-hour threshold
          </option>
          <option value="168">A week</option>
        </Select>
      </div>

      {active ? (
        <div className="flex items-end">
          <Button variant="ghost" size="sm" onClick={() => router.push("/exceptions")}>
            Clear filters
          </Button>
        </div>
      ) : null}
    </div>
  );
}
