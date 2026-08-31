"use client";

import { ExternalLink, PlugZap } from "lucide-react";
import Link from "next/link";

import { IntegrationStatusBadge } from "@/components/integrations/integration-status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { IntegrationJob } from "@/lib/api-client";
import {
  INTEGRATION_TARGET_LABELS,
  attemptLabel,
  successProvenance,
  type IntegrationTarget,
} from "@/lib/integrations";
import { formatDateTime } from "@/lib/utils";

export interface IntegrationPanelProps {
  jobs: IntegrationJob[];
  transactionId: string;
  /** True for the roles that may act on these jobs. Decided by the API, passed straight through. */
  canManage: boolean;
}

/**
 * Where this transaction stands with the three systems it has to reach.
 *
 * The second retrofit to the three already-shipped workspaces, after Step 6's shipment card, and
 * built the same way: it stands on its own, says nothing at all before an approval has raised any
 * job, and never implies a state the platform does not have.
 *
 * The preparing desk sees the plain facts - queued, in progress, posted, failed, or waiting on a
 * person - and the reference once there is one. Acting on a job is the integration-support
 * function's, so the only control here is a link through to the monitor.
 */
export function IntegrationPanel({ jobs, transactionId, canManage }: IntegrationPanelProps) {
  if (jobs.length === 0) {
    return null;
  }

  const outstanding = jobs.filter((job) => job.status !== "succeeded").length;

  return (
    <section
      className="space-y-3 rounded-medium border-thin border-border bg-elevation-default shadow-raised p-4"
      aria-label="Downstream integration"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <PlugZap className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
          <h2 className="text-sm font-semibold text-foreground">Downstream systems</h2>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant={outstanding === 0 ? "secondary" : "muted"}>
            {outstanding === 0
              ? "All three resolved"
              : `${outstanding} of ${jobs.length} outstanding`}
          </Badge>
          {canManage ? (
            <Button asChild size="sm" variant="outline">
              <Link href={`/admin/integrations?transaction_id=${transactionId}`}>
                Integration monitor
                <ExternalLink className="ml-1.5 h-3 w-3" aria-hidden="true" />
              </Link>
            </Button>
          ) : null}
        </div>
      </div>

      <ul className="grid gap-2 sm:grid-cols-3">
        {jobs.map((job) => (
          <li
            key={job.id}
            className="space-y-1.5 rounded-medium border-thin border-border bg-elevation-sunken px-3 py-2.5"
          >
            <p className="text-xs font-medium uppercase tracking-widest text-muted-foreground">
              {job.target_label ??
                INTEGRATION_TARGET_LABELS[job.target_system as IntegrationTarget] ??
                job.target_system}
            </p>
            <IntegrationStatusBadge
              status={job.status}
              completedManually={job.completed_manually}
            />
            {job.external_reference ? (
              <>
                <p className="break-all font-mono text-xs text-secondary">
                  {job.external_reference}
                </p>
                <p className="text-xs text-muted-foreground">
                  {successProvenance(job.completed_manually, job.completed_manually_by_name)}
                </p>
              </>
            ) : (
              <p className="text-xs text-muted-foreground">
                {job.status === "failed"
                  ? (job.failure_reason ??
                    "The posting was not accepted. Technical support owns it.")
                  : job.status === "awaiting_manual_action"
                    ? "Prepared in full; a person completes this posting."
                    : attemptLabel(job.attempt_count, job.max_attempts)}
              </p>
            )}
            {job.next_attempt_at ? (
              <p className="text-xs text-muted-foreground">
                Next attempt {formatDateTime(job.next_attempt_at)}
              </p>
            ) : null}
          </li>
        ))}
      </ul>

      <p className="text-xs leading-relaxed text-muted-foreground">
        This batch reaches <span className="font-medium text-foreground">Committed</span> once all
        three postings are resolved. A posting completed by a person counts, and always shows that
        it was.
      </p>
    </section>
  );
}
