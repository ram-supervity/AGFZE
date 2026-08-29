"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useSession } from "next-auth/react";
import { useMemo, useState } from "react";
import toast from "react-hot-toast";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { ApiError, bulkApprove, type ApprovalQueue } from "@/lib/api-client";
import {
  AGE_CHIP,
  DECISION_CHIP,
  DECISION_LABELS,
  RISK_CHIP,
  RISK_LABELS,
  ageBand,
  formatAgeHours,
  type ApprovalDecision,
} from "@/lib/governance";
import { formatMoney, formatQuantity } from "@/lib/transactions";
import { cn } from "@/lib/utils";

export interface ApprovalTableProps {
  queue: ApprovalQueue;
  canDecide: boolean;
}

const RANKS: { key: string; label: string }[] = [
  { key: "age", label: "Longest waiting" },
  { key: "value", label: "Largest value" },
  { key: "risk", label: "Highest risk" },
];

export function ApprovalTable({ queue, canDecide }: ApprovalTableProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { data: session } = useSession();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [confirming, setConfirming] = useState(false);
  const [running, setRunning] = useState(false);

  const { page, total_pages: totalPages, total } = queue.page;
  const eligible = useMemo(
    () => queue.items.filter((row) => row.risk.bulk_eligible && row.decision === "pending"),
    [queue.items],
  );
  const chosen = queue.items.filter((row) => selected.has(row.id));

  function navigate(changes: Record<string, string>) {
    const next = new URLSearchParams(searchParams.toString());
    for (const [key, value] of Object.entries(changes)) next.set(key, value);
    router.push(`/approvals?${next.toString()}`);
  }

  function toggle(id: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function runBulk() {
    const token = session?.accessToken;
    if (!token) {
      toast.error("Your session has expired. Sign in again to approve these.");
      return;
    }
    setRunning(true);
    try {
      const result = await bulkApprove(token, chosen.map((row) => row.id));
      setConfirming(false);
      setSelected(new Set());
      if (result.approved_count > 0) {
        toast.success(
          `${result.approved_count} transaction${result.approved_count === 1 ? "" : "s"} approved, each one individually. Nothing has been posted anywhere else.`,
        );
      }
      for (const skipped of result.rejected) {
        toast.error(`${skipped.batch_number ?? "One transaction"}: ${skipped.message}`);
      }
      router.refresh();
    } catch (error) {
      toast.error(
        error instanceof ApiError ? error.message : "The batch approval could not be completed.",
      );
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-xs font-medium uppercase tracking-widest text-muted-foreground">
            Rank by
          </span>
          {RANKS.map((rank) => (
            <Button
              key={rank.key}
              size="sm"
              variant={queue.rank_by === rank.key ? "secondary" : "outline"}
              onClick={() => navigate({ rank_by: rank.key, page: "1" })}
            >
              {rank.label}
            </Button>
          ))}
        </div>

        {canDecide ? (
          <Button
            size="sm"
            disabled={chosen.length === 0}
            onClick={() => setConfirming(true)}
          >
            Approve {chosen.length > 0 ? `${chosen.length} selected` : "selected"}
          </Button>
        ) : null}
      </div>

      {canDecide && eligible.length === 0 && queue.items.length > 0 ? (
        <p className="rounded-md border border-border bg-surface px-3 py-2 text-xs text-muted-foreground">
          None of these qualifies for a batch decision. That is reserved for the lowest risk tier:
          under {formatMoney(queue.bulk_value_ceiling, "USD")}, with nothing acknowledged by hand
          and no exception in its history. Everything else is decided one at a time.
        </p>
      ) : null}

      <Table>
        <TableHeader>
          <TableRow>
            {canDecide ? <TableHead className="w-10" /> : null}
            <TableHead>Batch / counterparty</TableHead>
            <TableHead>Decision</TableHead>
            <TableHead className="text-right">Value</TableHead>
            <TableHead>Risk</TableHead>
            <TableHead>Waiting</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {queue.items.map((row) => {
            const band = ageBand(row.age_hours, queue.overdue_threshold_hours);
            const selectable = canDecide && row.risk.bulk_eligible && row.decision === "pending";
            return (
              <TableRow
                key={row.id}
                className="cursor-pointer"
                onClick={() => router.push(`/approvals/${row.id}`)}
              >
                {canDecide ? (
                  <TableCell onClick={(event) => event.stopPropagation()}>
                    {selectable ? (
                      <input
                        type="checkbox"
                        aria-label={`Select ${row.batch_number} for batch approval`}
                        checked={selected.has(row.id)}
                        onChange={() => toggle(row.id)}
                        className="h-4 w-4 rounded border-input accent-secondary"
                      />
                    ) : (
                      // Greyed out rather than selectable-then-refused: the server would reject
                      // it anyway, and offering the checkbox would be a promise it cannot keep.
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <span
                            tabIndex={0}
                            aria-label="Not eligible for a batch decision"
                            className="inline-block h-4 w-4 rounded border border-border bg-muted"
                          />
                        </TooltipTrigger>
                        <TooltipContent side="right" className="max-w-[18rem]">
                          {row.risk.reasons.join(" ")}
                        </TooltipContent>
                      </Tooltip>
                    )}
                  </TableCell>
                ) : null}
                <TableCell className="max-w-xs">
                  <span className="font-mono text-sm text-secondary">{row.batch_number}</span>
                  <p className="line-clamp-1 text-xs text-muted-foreground">
                    {row.counterparty ?? "No counterparty recorded"}
                    {row.quantity_mt ? ` · ${formatQuantity(row.quantity_mt)}` : ""}
                  </p>
                </TableCell>
                <TableCell>
                  <Badge
                    variant="outline"
                    className={cn(DECISION_CHIP[row.decision as ApprovalDecision])}
                  >
                    {DECISION_LABELS[row.decision as ApprovalDecision] ?? row.decision}
                  </Badge>
                </TableCell>
                <TableCell className="whitespace-nowrap text-right tabular-nums">
                  {formatMoney(row.value, row.currency)}
                  {row.requires_confirmation ? (
                    <p className="text-[10px] uppercase tracking-wider text-signal-review">
                      Confirmation required
                    </p>
                  ) : null}
                </TableCell>
                <TableCell>
                  <Badge variant="outline" className={cn(RISK_CHIP[row.risk.label])}>
                    {RISK_LABELS[row.risk.label] ?? row.risk.label}
                  </Badge>
                </TableCell>
                <TableCell className="whitespace-nowrap">
                  <Badge variant="outline" className={cn(AGE_CHIP[band])}>
                    {formatAgeHours(row.age_hours)}
                  </Badge>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>

      <div className="flex items-center justify-between text-sm text-muted-foreground">
        <p>
          {total} approval{total === 1 ? "" : "s"} · page {page} of {totalPages}
        </p>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={page <= 1}
            onClick={() => navigate({ page: String(page - 1) })}
          >
            Previous
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={page >= totalPages}
            onClick={() => navigate({ page: String(page + 1) })}
          >
            Next
          </Button>
        </div>
      </div>

      <Dialog open={confirming} onOpenChange={setConfirming}>
        <DialogContent className="max-w-xl">
          <DialogTitle>Approve {chosen.length} transactions</DialogTitle>
          <DialogDescription>
            Each of these is approved on its own, checked on its own and recorded on the audit
            trail on its own - exactly as if you had opened them one at a time. Approving moves
            them to Approved and does nothing else.
          </DialogDescription>
          <ul className="max-h-72 space-y-1.5 overflow-y-auto rounded-md border border-border bg-surface p-3">
            {chosen.map((row) => (
              <li key={row.id} className="flex items-center justify-between gap-3 text-sm">
                <span className="font-mono text-secondary">{row.batch_number}</span>
                <span className="truncate text-muted-foreground">
                  {row.counterparty ?? "No counterparty"}
                </span>
                <span className="whitespace-nowrap tabular-nums text-foreground">
                  {formatMoney(row.value, row.currency)}
                </span>
              </li>
            ))}
          </ul>
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setConfirming(false)} disabled={running}>
              Cancel
            </Button>
            <Button onClick={runBulk} disabled={running}>
              {running ? "Approving…" : `Approve ${chosen.length}`}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
