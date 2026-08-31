"use client";

import { CircleCheck, CircleX, TriangleAlert } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import type { RuleEvaluation } from "@/lib/api-client";
import { isAcknowledgeable } from "@/lib/transactions";
import { cn, formatDateTime } from "@/lib/utils";

const MIN_REASON = 10;

export interface ValidationPanelProps {
  rules: RuleEvaluation[];
  canAcknowledge: boolean;
  acknowledging: string | null;
  onAcknowledge: (rule: RuleEvaluation, reason: string) => Promise<void>;
}

function tone(rule: RuleEvaluation): string {
  if (rule.passed) {
    return rule.acknowledged
      ? "border-pill-amber-border bg-pill-amber-bg"
      : "border-pill-green-border bg-pill-green-bg";
  }
  return rule.severity === "acknowledgeable"
    ? "border-pill-amber-border bg-pill-amber-bg"
    : "border-pill-red-border bg-pill-red-bg";
}

function Icon({ rule }: { rule: RuleEvaluation }) {
  const className = "mt-0.5 h-4 w-4 shrink-0";
  if (rule.passed) {
    return rule.acknowledged ? (
      <TriangleAlert className={cn(className, "text-signal-review")} aria-hidden="true" />
    ) : (
      <CircleCheck className={cn(className, "text-signal-confident")} aria-hidden="true" />
    );
  }
  return rule.severity === "acknowledgeable" ? (
    <TriangleAlert className={cn(className, "text-signal-review")} aria-hidden="true" />
  ) : (
    <CircleX className={cn(className, "text-signal-blocked")} aria-hidden="true" />
  );
}

/**
 * Every rule that has actually been evaluated, as a labelled pass or fail naming its field, the
 * threshold it was judged against and the value that was found. Never a bare "invalid".
 *
 * A rule that is registered but not yet evaluable never reaches this list at all - the server
 * does not write one, because a row reading "BR-03: not applicable" would be noise rather than
 * information about this transaction.
 */
export function ValidationPanel({
  rules,
  canAcknowledge,
  acknowledging,
  onAcknowledge,
}: ValidationPanelProps) {
  const [reasons, setReasons] = useState<Record<string, string>>({});

  if (rules.length === 0) {
    return (
      <p className="rounded-medium border-thin border-dashed border-border bg-elevation-sunken px-space-200 py-space-400 text-center text-body-sm text-muted-foreground">
        No rule has been evaluated against this transaction yet. Validation runs as soon as a
        document is matched to it or a field is corrected.
      </p>
    );
  }

  return (
    <ul className="space-y-2">
      {rules.map((rule) => {
        const key = `${rule.rule_id}:${rule.check_key ?? ""}`;
        const reason = reasons[key] ?? "";
        const offerAcknowledge = canAcknowledge && isAcknowledgeable(rule);

        return (
          <li key={rule.id} className={cn("space-y-space-100 rounded-control border-thin px-space-150 py-space-100", tone(rule))}>
            <div className="flex items-start gap-2.5">
              <Icon rule={rule} />
              <div className="min-w-0 flex-1 space-y-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-xs font-semibold text-foreground">
                    {rule.rule_id}
                  </span>
                  <span className="text-sm font-medium text-foreground">
                    {rule.title ?? rule.check_key?.replace(/_/g, " ") ?? "Check"}
                  </span>
                  {rule.check_key ? (
                    <Badge variant="muted" className="text-body-xs uppercase tracking-wider">
                      {rule.check_key.replace(/_/g, " ")}
                    </Badge>
                  ) : null}
                  {rule.acknowledged ? (
                    <Badge
                      variant="outline"
                      className="border-pill-amber-border bg-pill-amber-bg text-pill-amber-text"
                    >
                      Acknowledged
                    </Badge>
                  ) : null}
                </div>

                <p className="text-sm leading-relaxed text-muted-foreground">{rule.message}</p>

                {rule.field_name || rule.expected_value || rule.actual_value ? (
                  <dl className="grid gap-x-4 gap-y-0.5 text-xs sm:grid-cols-3">
                    {rule.field_name ? (
                      <div className="flex gap-1.5">
                        <dt className="text-muted-foreground">Field</dt>
                        <dd className="text-foreground">{rule.field_name}</dd>
                      </div>
                    ) : null}
                    {rule.expected_value ? (
                      <div className="flex gap-1.5">
                        <dt className="text-muted-foreground">Expected</dt>
                        <dd className="break-words text-foreground">{rule.expected_value}</dd>
                      </div>
                    ) : null}
                    {rule.actual_value ? (
                      <div className="flex gap-1.5">
                        <dt className="text-muted-foreground">Found</dt>
                        <dd className="break-words text-foreground">{rule.actual_value}</dd>
                      </div>
                    ) : null}
                  </dl>
                ) : null}

                {rule.acknowledged && rule.acknowledgement_reason ? (
                  <p className="text-xs text-muted-foreground">
                    {rule.acknowledged_by_name ?? "A platform user"} accepted this
                    {rule.acknowledged_at ? ` on ${formatDateTime(rule.acknowledged_at)}` : ""}:{" "}
                    {rule.acknowledgement_reason}
                  </p>
                ) : null}
              </div>
            </div>

            {offerAcknowledge ? (
              <div className="space-y-2 border-t border-border/60 pt-2">
                <label
                  htmlFor={`ack-${rule.id}`}
                  className="block text-xs font-medium text-foreground"
                >
                  Acknowledging this records your name against the difference. Say why it is
                  acceptable.
                </label>
                <Textarea
                  id={`ack-${rule.id}`}
                  rows={2}
                  value={reason}
                  placeholder="For example: the supplier rounded the line total; the rate and quantity are correct."
                  onChange={(event) =>
                    setReasons((current) => ({ ...current, [key]: event.target.value }))
                  }
                />
                <Button
                  size="sm"
                  variant="outline"
                  disabled={acknowledging !== null || reason.trim().length < MIN_REASON}
                  onClick={() => onAcknowledge(rule, reason.trim())}
                >
                  {acknowledging === rule.id ? "Recording…" : "Acknowledge this difference"}
                </Button>
              </div>
            ) : null}

            {!rule.passed && rule.severity === "hard" ? (
              <p className="border-t border-border/60 pt-2 text-xs text-signal-blocked">
                This has to be corrected. It cannot be self-approved.
              </p>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}
