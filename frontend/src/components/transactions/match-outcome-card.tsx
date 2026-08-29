"use client";

import { ArrowRight, CircleAlert, CircleCheck, Copy, GitMerge, Layers } from "lucide-react";
import Link from "next/link";
import { useSession } from "next-auth/react";
import { useState } from "react";
import toast from "react-hot-toast";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  ApiError,
  resolveDocumentMatch,
  type MatchOutcome,
} from "@/lib/api-client";
import { MATCH_OUTCOME_LABELS } from "@/lib/transactions";
import { cn } from "@/lib/utils";

export interface MatchOutcomeCardProps {
  documentId: string;
  outcome: MatchOutcome;
  canResolve: boolean;
  onResolved?: (outcome: MatchOutcome) => void;
  className?: string;
}

const TONE: Record<string, string> = {
  auto_linked: "border-signal-confident/35 bg-signal-confident/10",
  superseded: "border-signal-confident/35 bg-signal-confident/10",
  new_transaction: "border-border bg-surface",
  already_linked: "border-border bg-surface",
  duplicate_linked: "border-signal-review/35 bg-signal-review/10",
  suggested: "border-signal-review/35 bg-signal-review/10",
  no_reference: "border-signal-blocked/35 bg-signal-blocked/10",
  not_applicable: "border-border bg-surface",
};

function OutcomeIcon({ outcome }: { outcome: string }) {
  const className = "mt-0.5 h-4 w-4 shrink-0";
  if (outcome === "suggested") return <GitMerge className={className} aria-hidden="true" />;
  if (outcome === "duplicate_linked") return <Copy className={className} aria-hidden="true" />;
  if (outcome === "no_reference")
    return <CircleAlert className={className} aria-hidden="true" />;
  if (outcome === "new_transaction") return <Layers className={className} aria-hidden="true" />;
  return <CircleCheck className={className} aria-hidden="true" />;
}

/**
 * The real matching result for one confirmed document, shown inline wherever that document is.
 *
 * A suggestion is the only outcome that asks anything of the reader, and it asks before anything
 * has been created: there is no merge later, so the decision has to be made here.
 */
export function MatchOutcomeCard({
  documentId,
  outcome,
  canResolve,
  onResolved,
  className,
}: MatchOutcomeCardProps) {
  const { data: session } = useSession();
  const [busy, setBusy] = useState<string | null>(null);
  const [current, setCurrent] = useState(outcome);

  if (current.outcome === "not_applicable") return null;

  async function resolve(decision: "confirm" | "reject", transactionId?: string) {
    if (!session?.accessToken) {
      toast.error("Your session has expired. Sign in again to resolve this match.");
      return;
    }
    setBusy(transactionId ?? decision);
    try {
      const resolved = await resolveDocumentMatch(session.accessToken, documentId, {
        decision,
        transaction_id: transactionId ?? null,
      });
      setCurrent(resolved);
      onResolved?.(resolved);
      toast.success(resolved.message);
    } catch (error) {
      toast.error(
        error instanceof ApiError ? error.message : "The match could not be resolved.",
      );
    } finally {
      setBusy(null);
    }
  }

  return (
    <div
      className={cn(
        "space-y-3 rounded-md border px-4 py-3",
        TONE[current.outcome] ?? "border-border bg-surface",
        className,
      )}
    >
      <div className="flex items-start gap-3">
        <OutcomeIcon outcome={current.outcome} />
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-medium text-foreground">
              {MATCH_OUTCOME_LABELS[current.outcome] ?? current.outcome}
            </p>
            {current.batch_number ? (
              <Badge variant="muted" className="font-mono text-[11px]">
                {current.batch_number}
              </Badge>
            ) : null}
            {current.score !== null ? (
              <Badge variant="outline" className="tabular-nums text-[11px]">
                score {Math.round(current.score)}
              </Badge>
            ) : null}
          </div>
          <p className="text-sm leading-relaxed text-muted-foreground">{current.message}</p>
        </div>
      </div>

      {current.transaction_id && !current.needs_user_decision ? (
        <Button asChild size="sm" variant="outline">
          <Link href={`/transactions/purchase/${current.transaction_id}`}>
            Open the transaction workspace
            <ArrowRight aria-hidden="true" />
          </Link>
        </Button>
      ) : null}

      {current.needs_user_decision ? (
        canResolve ? (
          <div className="space-y-2">
            <ul className="space-y-2">
              {current.candidates.map((candidate) => (
                <li
                  key={candidate.transaction_id}
                  className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-border bg-card px-3 py-2"
                >
                  <div className="min-w-0">
                    <p className="font-mono text-sm text-foreground">
                      {candidate.batch_number}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {candidate.supplier_name ?? "No supplier recorded"}
                      {candidate.contract_number ? ` · ${candidate.contract_number}` : ""} ·{" "}
                      {candidate.rationale}
                    </p>
                  </div>
                  <Button
                    size="sm"
                    disabled={busy !== null}
                    onClick={() => resolve("confirm", candidate.transaction_id)}
                  >
                    {busy === candidate.transaction_id ? "Linking…" : "This is the same deal"}
                  </Button>
                </li>
              ))}
            </ul>
            <Button
              size="sm"
              variant="outline"
              disabled={busy !== null}
              onClick={() => resolve("reject")}
            >
              {busy === "reject" ? "Opening…" : "None of these - open a new batch"}
            </Button>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            The purchase desk decides whether this is the same deal. Nothing is created until
            they do.
          </p>
        )
      ) : null}
    </div>
  );
}
