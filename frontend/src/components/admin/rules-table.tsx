"use client";

import { SlidersHorizontal } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useSession } from "next-auth/react";
import { useState } from "react";
import toast from "react-hot-toast";

import { RuleEditDialog } from "@/components/admin/rule-edit-dialog";
import { EmptyState } from "@/components/shared/empty-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatThreshold, scopeLabel } from "@/lib/admin";
import {
  ApiError,
  updateRuleConfiguration,
  type RuleConfigurationList,
  type RuleConfigurationRow,
} from "@/lib/api-client";
import { formatDateTime } from "@/lib/utils";

export interface RulesTableProps {
  data: RuleConfigurationList;
  filters: { ruleId: string; stream: string };
}

/**
 * Every configured threshold in one table, with no special-casing by which  seeded a row.
 *
 * The purchase tolerances from , the sales contract-coverage rule from  and the
 * FA-scoped defaults from  all render through the same cells and edit through the same
 * dialog. That this component contains no branch on the rule identifier is the point: it is what
 * proves `rule_configurations` was genuinely built as a generic store rather than as three
 * shapes that happen to share a table.
 */
export function RulesTable({ data, filters }: RulesTableProps) {
  const router = useRouter();
  const params = useSearchParams();
  const { data: session } = useSession();
  const [editing, setEditing] = useState<RuleConfigurationRow | null>(null);
  const [saving, setSaving] = useState(false);

  function navigate(changes: Record<string, string | null>) {
    const next = new URLSearchParams(params.toString());
    for (const [key, value] of Object.entries(changes)) {
      if (!value) next.delete(key);
      else next.set(key, value);
    }
    router.push(`/admin/rules${next.toString() ? `?${next.toString()}` : ""}`);
  }

  async function save(body: {
    change_reason: string;
    threshold_value?: string;
    is_active?: boolean;
    description?: string;
  }) {
    const token = session?.accessToken;
    if (!token || !editing) {
      toast.error("Your session has expired. Sign in again to make this change.");
      return;
    }
    setSaving(true);
    try {
      await updateRuleConfiguration(token, editing.id, body);
      toast.success(`${editing.rule_id} · ${editing.check_key.replace(/_/g, " ")} updated.`);
      setEditing(null);
      router.refresh();
    } catch (error) {
      toast.error(
        error instanceof ApiError ? error.message : "The threshold could not be changed.",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-3 rounded-lg border border-border bg-surface p-4 sm:grid-cols-3">
        <div className="space-y-1.5">
          <Label htmlFor="rule-filter">Rule</Label>
          <Select
            id="rule-filter"
            value={filters.ruleId}
            onChange={(event) => navigate({ rule_id: event.target.value || null })}
          >
            <option value="">Every rule</option>
            {data.rule_ids.map((id) => (
              <option key={id} value={id}>
                {id}
              </option>
            ))}
          </Select>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="stream-filter">Business stream</Label>
          <Select
            id="stream-filter"
            value={filters.stream}
            onChange={(event) => navigate({ stream: event.target.value || null })}
          >
            <option value="">Every scope</option>
            {data.streams.map((stream) => (
              <option key={stream} value={stream}>
                {stream}
              </option>
            ))}
          </Select>
        </div>

        {filters.ruleId || filters.stream ? (
          <div className="flex items-end">
            <Button variant="ghost" size="sm" onClick={() => router.push("/admin/rules")}>
              Clear filters
            </Button>
          </div>
        ) : null}
      </div>

      {data.items.length === 0 ? (
        <EmptyState
          icon={SlidersHorizontal}
          title="Nothing matches those filters"
          description="Clear the filters to see every configured threshold."
        />
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Rule</TableHead>
              <TableHead>Check</TableHead>
              <TableHead>Scope</TableHead>
              <TableHead className="text-right">Value</TableHead>
              <TableHead>State</TableHead>
              <TableHead>Last changed</TableHead>
              <TableHead className="text-right">Action</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.items.map((row) => (
              <TableRow key={row.id} className="align-top">
                <TableCell>
                  <span className="font-mono text-sm text-foreground">{row.rule_id}</span>
                  {row.rule_title ? (
                    <p className="mt-0.5 max-w-[16rem] text-xs text-muted-foreground">
                      {row.rule_title}
                    </p>
                  ) : null}
                </TableCell>

                <TableCell className="text-sm text-foreground">
                  {row.check_key.replace(/_/g, " ")}
                  {row.description ? (
                    <p className="mt-0.5 max-w-[22rem] text-xs text-muted-foreground">
                      {row.description}
                    </p>
                  ) : null}
                </TableCell>

                <TableCell className="text-sm text-muted-foreground">{scopeLabel(row)}</TableCell>

                <TableCell className="whitespace-nowrap text-right font-mono text-sm text-foreground">
                  {formatThreshold(row.threshold_value, row.threshold_unit)}
                </TableCell>

                <TableCell>
                  <Badge variant={row.is_active ? "secondary" : "muted"}>
                    {row.is_active ? "Active" : "Inactive"}
                  </Badge>
                </TableCell>

                <TableCell className="text-sm text-muted-foreground">
                  {formatDateTime(row.changed_at)}
                  <p className="mt-0.5 text-xs">
                    {row.changed_by_name ?? "Seeded with the platform"}
                  </p>
                  <p
                    className="mt-0.5 max-w-[20rem] text-xs italic"
                    title={row.change_reason}
                  >
                    “{row.change_reason}”
                  </p>
                </TableCell>

                <TableCell className="text-right">
                  <Button size="sm" variant="outline" onClick={() => setEditing(row)}>
                    Edit
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      <RuleEditDialog
        row={editing}
        open={editing !== null}
        onOpenChange={(open) => (open ? null : setEditing(null))}
        saving={saving}
        onSave={save}
      />
    </div>
  );
}
