"use client";

import { ExternalLink, PlugZap, RefreshCw, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useSession } from "next-auth/react";
import { forwardRef, useState, type ButtonHTMLAttributes } from "react";
import toast from "react-hot-toast";

import { ManualCompletionDialog } from "@/components/integrations/manual-completion-dialog";
import { IntegrationStatusBadge } from "@/components/integrations/integration-status-badge";
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
import {
  ApiError,
  completeIntegrationJobManually,
  retryIntegrationJob,
  type IntegrationJobDetail,
  type IntegrationJobQueue,
} from "@/lib/api-client";
import {
  INTEGRATION_JOB_STATUSES,
  INTEGRATION_STATUS_LABELS,
  INTEGRATION_TARGETS,
  INTEGRATION_TARGET_LABELS,
  attemptLabel,
  canCompleteManually,
  canRetry,
  successProvenance,
  targetAvailabilityNote,
  type IntegrationTarget,
} from "@/lib/integrations";
import { useRovingTabs } from "@/lib/use-roving-tabs";
import { formatDateTime } from "@/lib/utils";

export interface IntegrationMonitorProps {
  queue: IntegrationJobQueue;
  filters: { target: string; status: string; transactionId: string };
}

/**
 * What was posted where, what failed, and what a person still owes.
 *
 * The screen's whole job is to keep three states visibly distinct, because collapsing any two of
 * them would mislead the person who has to act:
 *
 * - **posted** carries the reference the receiving system gave back, and says whether the posting
 *   was made automatically or confirmed by hand;
 * - **failed** carries the reason and a Retry, because there is a real automated attempt to make
 *   again;
 * - **waiting on a person** carries the prepared payload and a Confirm completion, because there
 *   is nothing automated left to attempt and pressing Retry on it could not help.
 *
 * The two actions are never the same button and never sit under the same label.
 */
export function IntegrationMonitor({ queue, filters }: IntegrationMonitorProps) {
  const router = useRouter();
  const params = useSearchParams();
  const { data: session } = useSession();
  const [working, setWorking] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<IntegrationJobDetail | null>(null);

  const token = session?.accessToken;
  const { page, total_pages: totalPages, total } = queue.page;

  function navigate(changes: Record<string, string | null>) {
    const next = new URLSearchParams(params.toString());
    for (const [key, value] of Object.entries(changes)) {
      if (value === null || value === "") next.delete(key);
      else next.set(key, value);
    }
    if (!("page" in changes)) next.delete("page");
    router.push(`/admin/integrations?${next.toString()}`);
  }

  async function retry(job: IntegrationJobDetail) {
    if (!token) {
      toast.error("Your session has expired. Sign in again to retry this job.");
      return;
    }
    setWorking(job.id);
    try {
      const updated = await retryIntegrationJob(token, job.id);
      if (updated.status === "succeeded") {
        toast.success(`${updated.target_label} accepted the posting: ${updated.external_reference}`);
      } else if (updated.status === "awaiting_manual_action") {
        toast(
          "Nothing was posted - that target has no endpoint configured here. Everything needed to complete it by hand is on the job.",
          { icon: "✎" },
        );
      } else {
        toast.error(updated.failure_reason ?? "The attempt failed again.");
      }
      router.refresh();
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "The job could not be retried.");
    } finally {
      setWorking(null);
    }
  }

  async function confirmManual(externalReference: string, note: string) {
    if (!token || !confirming) return;
    setWorking(confirming.id);
    try {
      await completeIntegrationJobManually(token, confirming.id, {
        external_reference: externalReference,
        note,
      });
      toast.success("Recorded as a manual completion against your account.");
      setConfirming(null);
      router.refresh();
    } catch (error) {
      toast.error(
        error instanceof ApiError ? error.message : "The completion could not be recorded.",
      );
    } finally {
      setWorking(null);
    }
  }

  const active = filters.target as IntegrationTarget | "";

  // "All systems" first, then the three targets. Kept as one list so the keyboard navigation
  // counts and indexes exactly what is rendered, rather than the tabs plus a special case.
  const tabs: {
    key: IntegrationTarget | "";
    label: string;
    count: number;
    title?: string;
  }[] = [
      {
        key: "",
        label: "All systems",
        count: Object.values(queue.counts_by_target).reduce((sum, value) => sum + value, 0),
      },
      ...INTEGRATION_TARGETS.map((target) => ({
        key: target,
        label: INTEGRATION_TARGET_LABELS[target],
        count: queue.counts_by_target[target] ?? 0,
        title: targetAvailabilityNote(target, Boolean(queue.configured_targets[target])),
      })),
    ];
  const activeIndex = Math.max(
    0,
    tabs.findIndex((tab) => tab.key === active),
  );
  const { tabProps } = useRovingTabs(tabs.length, (index) =>
    navigate({ target_system: tabs[index].key || null }),
  );

  return (
    <div className="space-y-4">
      <div
        role="tablist"
        aria-label="Target systems"
        className="flex flex-wrap gap-1.5 border-b border-border pb-3"
      >
        {tabs.map((tab, index) => (
          <TargetTab
            key={tab.key || "all"}
            label={tab.label}
            count={tab.count}
            selected={index === activeIndex}
            title={tab.title}
            onSelect={() => navigate({ target_system: tab.key || null })}
            {...tabProps(index, index === activeIndex)}
          />
        ))}
      </div>

      {active ? (
        <p className="text-sm leading-relaxed text-muted-foreground">
          {targetAvailabilityNote(active, Boolean(queue.configured_targets[active]))}
        </p>
      ) : (
        <p className="text-sm leading-relaxed text-muted-foreground">
          {INTEGRATION_TARGETS.filter((target) => !queue.configured_targets[target]).length ===
            INTEGRATION_TARGETS.length
            ? "No target system has an endpoint configured on this deployment, so every posting is prepared here and completed by a person. That is the expected state, not a fault."
            : "Each transaction owes three postings, worked independently. A job waiting on a person is neither a success nor a failure."}
        </p>
      )}

      <div className="grid gap-3 rounded-lg border border-border bg-surface p-4 sm:grid-cols-2 xl:grid-cols-4">
        <div className="space-y-1.5">
          <Label htmlFor="job-target">Target system</Label>
          <Select
            id="job-target"
            value={filters.target}
            onChange={(event) => navigate({ target_system: event.target.value || null })}
          >
            <option value="">Any system</option>
            {INTEGRATION_TARGETS.map((target) => (
              <option key={target} value={target}>
                {INTEGRATION_TARGET_LABELS[target]}
              </option>
            ))}
          </Select>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="job-status">State</Label>
          <Select
            id="job-status"
            value={filters.status}
            onChange={(event) => navigate({ status: event.target.value || null })}
          >
            <option value="">Any state</option>
            {INTEGRATION_JOB_STATUSES.map((status) => (
              <option key={status} value={status}>
                {INTEGRATION_STATUS_LABELS[status]}
                {queue.counts_by_status[status] ? ` (${queue.counts_by_status[status]})` : ""}
              </option>
            ))}
          </Select>
        </div>

        {filters.target || filters.status ? (
          <div className="flex items-end">
            <Button variant="ghost" size="sm" onClick={() => router.push("/admin/integrations")}>
              Clear filters
            </Button>
          </div>
        ) : null}
      </div>

      {filters.transactionId ? (
        <div className="flex flex-wrap items-center gap-2 rounded-medium border-thin border-border bg-elevation-sunken px-4 py-2.5 text-sm">
          <span className="text-muted-foreground">
            Showing one transaction&apos;s jobs
            {queue.items[0]?.batch_number ? ` - ${queue.items[0].batch_number}` : ""}.
          </span>
          <Button variant="ghost" size="sm" onClick={() => navigate({ transaction_id: null })}>
            Show every job
          </Button>
        </div>
      ) : null}

      {queue.items.length === 0 ? (
        <EmptyState
          icon={PlugZap}
          title={
            filters.target || filters.status || filters.transactionId
              ? "Nothing matches those filters"
              : "No integration jobs yet"
          }
          description={
            filters.target || filters.status || filters.transactionId
              ? "Clear the filters to see every job."
              : "Three jobs appear here the moment a transaction is approved - one for the tracker, one for SAP and one for the document store."
          }
        />
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Batch</TableHead>
              <TableHead>System</TableHead>
              <TableHead>State</TableHead>
              <TableHead>Reference</TableHead>
              <TableHead>Attempts</TableHead>
              <TableHead>Last attempt</TableHead>
              <TableHead className="text-right">Action</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {queue.items.map((job) => (
              <TableRow key={job.id} className="align-top">
                <TableCell>
                  {job.batch_number ? (
                    <Link
                      href={`/transactions/purchase/${job.transaction_id}`}
                      className="inline-flex items-center gap-1 font-mono text-sm text-secondary underline-offset-4 hover:underline"
                    >
                      {job.batch_number}
                      <ExternalLink className="h-3 w-3" aria-hidden="true" />
                    </Link>
                  ) : (
                    <span className="text-sm text-muted-foreground">-</span>
                  )}
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    {job.counterparty ?? "No counterparty recorded"}
                  </p>
                </TableCell>

                <TableCell className="text-sm text-foreground">
                  {job.target_label ??
                    INTEGRATION_TARGET_LABELS[job.target_system as IntegrationTarget] ??
                    job.target_system}
                  {job.target_configured ? null : (
                    <p className="mt-0.5 text-xs text-muted-foreground">Not configured here</p>
                  )}
                </TableCell>

                <TableCell>
                  <IntegrationStatusBadge
                    status={job.status}
                    completedManually={job.completed_manually}
                  />
                  {job.status === "failed" && job.failure_reason ? (
                    <p
                      role="alert"
                      className="mt-1.5 max-w-[22rem] rounded-md border border-pill-red-border bg-pill-red-bg px-2 py-1.5 text-xs text-signal-blocked"
                    >
                      <TriangleAlert
                        className="mr-1 inline h-3 w-3 align-[-2px]"
                        aria-hidden="true"
                      />
                      {job.failure_reason}
                    </p>
                  ) : null}
                  {job.status === "awaiting_manual_action" && job.manual_instruction ? (
                    <p className="mt-1.5 max-w-[22rem] text-xs text-muted-foreground">
                      {job.manual_instruction}
                    </p>
                  ) : null}
                </TableCell>

                <TableCell>
                  {job.external_reference ? (
                    <>
                      <span className="font-mono text-sm text-secondary">
                        {job.external_reference}
                      </span>
                      <p className="mt-0.5 text-xs text-muted-foreground">
                        {successProvenance(
                          job.completed_manually,
                          job.completed_manually_by_name,
                        )}
                      </p>
                      {job.manual_note ? (
                        <p className="mt-0.5 max-w-[20rem] text-xs italic text-muted-foreground">
                          “{job.manual_note}”
                        </p>
                      ) : null}
                    </>
                  ) : (
                    <span className="text-sm text-muted-foreground">-</span>
                  )}
                </TableCell>

                <TableCell>
                  <Badge variant={job.attempt_count > 0 ? "muted" : "outline"}>
                    {attemptLabel(job.attempt_count, job.max_attempts)}
                  </Badge>
                  {job.next_attempt_at ? (
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      Next {formatDateTime(job.next_attempt_at)}
                    </p>
                  ) : null}
                </TableCell>

                <TableCell className="whitespace-nowrap text-sm text-muted-foreground">
                  {job.last_attempted_at ? formatDateTime(job.last_attempted_at) : "Not yet"}
                </TableCell>

                <TableCell className="text-right">
                  {canRetry(job.status) ? (
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={working === job.id}
                      onClick={() => retry(job)}
                    >
                      <RefreshCw
                        className={cnSpin(working === job.id)}
                        aria-hidden="true"
                      />
                      Retry
                    </Button>
                  ) : canCompleteManually(job.status) ? (
                    <Button
                      size="sm"
                      variant="secondary"
                      disabled={working === job.id}
                      onClick={() => setConfirming(job)}
                    >
                      Confirm manual completion
                    </Button>
                  ) : (
                    <span className="text-xs text-muted-foreground">Nothing to do</span>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      <div className="flex items-center justify-between text-sm text-muted-foreground">
        <p>
          {total} job{total === 1 ? "" : "s"} · page {page} of {totalPages}
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

      <ManualCompletionDialog
        job={confirming}
        open={confirming !== null}
        onOpenChange={(open) => (open ? null : setConfirming(null))}
        saving={working !== null}
        onConfirm={confirmManual}
      />
    </div>
  );
}

function cnSpin(spinning: boolean): string {
  return spinning ? "mr-1.5 h-3.5 w-3.5 animate-spin" : "mr-1.5 h-3.5 w-3.5";
}

const TargetTab = forwardRef<
  HTMLButtonElement,
  {
    label: string;
    count: number;
    selected: boolean;
    title?: string;
    onSelect: () => void;
  } & Omit<ButtonHTMLAttributes<HTMLButtonElement>, "onSelect">
>(function TargetTab({ label, count, selected, title, onSelect, ...rest }, ref) {
  return (
    <button
      ref={ref}
      type="button"
      role="tab"
      aria-selected={selected}
      title={title}
      onClick={onSelect}
      {...rest}
      className={
        selected
          ? "inline-flex items-center gap-2 rounded-md bg-secondary/15 px-3 py-1.5 text-sm font-medium text-foreground"
          : "inline-flex items-center gap-2 rounded-md px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-surface hover:text-foreground"
      }
    >
      <span>{label}</span>
      <Badge variant={count > 0 ? "secondary" : "muted"} className="tabular-nums">
        {count}
      </Badge>
    </button>
  );
});
