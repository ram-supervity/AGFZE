"use client";

import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { MIN_CHANGE_REASON, reasonIsValid } from "@/lib/admin";

export interface ChangeReasonFieldProps {
  id: string;
  value: string;
  onChange: (value: string) => void;
  /** What this reason will be attached to, so the prompt is about the actual change. */
  subject: string;
  disabled?: boolean;
}

/**
 * The last field in every configuration dialog, and the one that gates Save.
 *
 * This friction is deliberate and is not a validation nicety. `rule_configurations` and
 * `document_type_schemas` have carried a mandatory `change_reason` since the migrations that
 * created them, precisely so that a threshold which moved can always be explained afterwards.
 * The API rejects a request without one, so this field is the courteous version of a refusal that
 * happens either way.
 */
export function ChangeReasonField({
  id,
  value,
  onChange,
  subject,
  disabled,
}: ChangeReasonFieldProps) {
  const short = value.trim().length > 0 && !reasonIsValid(value);

  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>Reason for this change</Label>
      <Textarea
        id={id}
        value={value}
        rows={3}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        placeholder={`Why ${subject} is changing, and who asked for it.`}
        aria-describedby={`${id}-help`}
        aria-invalid={short || undefined}
      />
      <p id={`${id}-help`} className="text-xs text-muted-foreground">
        Required, at least {MIN_CHANGE_REASON} characters. It is stored on the row and on the audit
        trail against your account. A threshold that moved without a stated reason is not a change
        anybody can audit later.
      </p>
      {short ? (
        <p role="alert" className="text-xs text-signal-blocked">
          A little more detail — at least {MIN_CHANGE_REASON} characters.
        </p>
      ) : null}
    </div>
  );
}
