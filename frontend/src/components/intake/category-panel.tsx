"use client";

import { useRouter } from "next/navigation";
import { useSession } from "next-auth/react";
import { useState } from "react";
import toast from "react-hot-toast";

import { ConfidenceBadge } from "@/components/shared/confidence-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, overrideRequestCategory, type RequestDetail } from "@/lib/api-client";
import {
  BUSINESS_STREAMS,
  CATEGORY_LABELS,
  DEAL_DIRECTION_LABELS,
  DEAL_DIRECTIONS,
  REQUEST_CATEGORIES,
  STREAM_LABELS,
  formatConfidence,
  labelFor,
} from "@/lib/intake";
import { formatDateTime } from "@/lib/utils";

const MIN_REASON = 5;

export interface CategoryPanelProps {
  detail: RequestDetail;
  canCorrect: boolean;
}

export function CategoryPanel({ detail, canCorrect }: CategoryPanelProps) {
  const router = useRouter();
  const { data: session } = useSession();
  // Low confidence is what opens the field for correction inline; a confident classification is
  // still correctable, just behind an explicit "Correct" action rather than open by default.
  const lowConfidence = detail.needs_review || detail.category === null;
  const [editing, setEditing] = useState(false);
  const [category, setCategory] = useState(detail.category ?? "purchase");
  const [stream, setStream] = useState(detail.stream ?? "");
  const [dealDirection, setDealDirection] = useState(detail.deal_direction ?? "");
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);

  const open = editing || (lowConfidence && canCorrect);
  const reasonTooShort = reason.trim().length < MIN_REASON;

  async function save() {
    if (!session?.accessToken) {
      toast.error("Your session has expired. Sign in again to save this correction.");
      return;
    }
    setSaving(true);
    try {
      await overrideRequestCategory(session.accessToken, detail.id, {
        category,
        stream: stream || null,
        deal_direction: dealDirection || null,
        reason: reason.trim(),
      });
      toast.success("Category corrected.");
      setEditing(false);
      setReason("");
      router.refresh();
    } catch (error) {
      toast.error(
        error instanceof ApiError ? error.message : "The correction could not be saved.",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>AI classification</CardTitle>
        <CardDescription>
          {detail.classification_error
            ? "The classifier could not complete for this request, so it needs a person to set the category."
            : lowConfidence
              ? "Confidence is below the configured threshold, so this needs a person to confirm or correct it."
              : "Assigned automatically and above the confidence threshold."}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          {detail.category ? (
            <ConfidenceBadge
              label={labelFor(CATEGORY_LABELS, detail.category)}
              confidence={detail.category_confidence}
            />
          ) : (
            <Badge variant="muted">Not classified</Badge>
          )}
          {detail.deal_direction && detail.deal_direction !== "not_trade" ? (
            <Badge
              variant="outline"
              className={
                detail.deal_direction === "sales"
                  ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                  : "border-blue-500/40 bg-blue-500/10 text-blue-600 dark:text-blue-400"
              }
            >
              {detail.deal_direction === "sales" ? "Sales deal" : "Purchase deal"}
            </Badge>
          ) : null}
          {detail.stream ? (
            <Badge variant="outline">{labelFor(STREAM_LABELS, detail.stream)}</Badge>
          ) : null}
          {detail.category_overridden ? <Badge variant="muted">Corrected by a person</Badge> : null}
        </div>

        {detail.category_rationale ? (
          <p className="rounded-medium border-thin border-border bg-elevation-sunken p-3 text-sm leading-relaxed text-muted-foreground">
            {detail.category_rationale}
          </p>
        ) : null}

        {detail.deal_direction_rationale && detail.deal_direction_rationale !== detail.category_rationale ? (
          <p className="rounded-medium border-thin border-border bg-elevation-sunken p-3 text-xs leading-relaxed text-muted-foreground">
            <span className="font-semibold text-foreground">Deal direction: </span>
            {detail.deal_direction_rationale}
          </p>
        ) : null}

        {detail.category_overridden ? (
          <dl className="space-y-1.5 rounded-medium border-thin border-border bg-elevation-sunken p-3 text-sm">
            <div className="flex justify-between gap-3">
              <dt className="text-muted-foreground">Original AI category</dt>
              <dd className="text-foreground">
                {labelFor(CATEGORY_LABELS, detail.original_category)} ·{" "}
                {formatConfidence(detail.category_confidence)}
              </dd>
            </div>
            {detail.category_override_reason ? (
              <div>
                <dt className="text-muted-foreground">Reason given</dt>
                <dd className="mt-0.5 break-words text-foreground">
                  {detail.category_override_reason}
                </dd>
              </div>
            ) : null}
            {detail.category_overridden_at ? (
              <div className="flex justify-between gap-3">
                <dt className="text-muted-foreground">Corrected</dt>
                <dd className="text-foreground">{formatDateTime(detail.category_overridden_at)}</dd>
              </div>
            ) : null}
          </dl>
        ) : null}

        {!canCorrect ? (
          <p className="text-sm text-muted-foreground">
            Your role has read access to this request. Corrections are made by the desk that owns
            the work.
          </p>
        ) : open ? (
          <div className="space-y-3 border-t border-border pt-4">
            <div className="space-y-1.5">
              <Label htmlFor="category">Category</Label>
              <Select
                id="category"
                value={category}
                onChange={(event) => setCategory(event.target.value)}
              >
                {REQUEST_CATEGORIES.map((value) => (
                  <option key={value} value={value}>
                    {CATEGORY_LABELS[value]}
                  </option>
                ))}
              </Select>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="deal-direction">Deal direction</Label>
              <Select
                id="deal-direction"
                value={dealDirection}
                onChange={(event) => setDealDirection(event.target.value)}
              >
                <option value="">Auto-detected from category</option>
                {DEAL_DIRECTIONS.map((value) => (
                  <option key={value} value={value}>
                    {DEAL_DIRECTION_LABELS[value]}
                  </option>
                ))}
              </Select>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="stream">Business stream</Label>
              <Select
                id="stream"
                value={stream}
                onChange={(event) => setStream(event.target.value)}
              >
                <option value="">Leave as it is</option>
                {BUSINESS_STREAMS.map((value) => (
                  <option key={value} value={value}>
                    {STREAM_LABELS[value]}
                  </option>
                ))}
              </Select>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="reason">Reason for the correction (required)</Label>
              <Textarea
                id="reason"
                value={reason}
                placeholder="Why is this the right category?"
                onChange={(event) => setReason(event.target.value)}
                aria-describedby="reason-help"
              />
              <p id="reason-help" className="text-xs text-muted-foreground">
                Recorded against the request in the audit trail. At least {MIN_REASON} characters.
              </p>
            </div>

            <div className="flex gap-2">
              <Button size="sm" onClick={save} disabled={saving || reasonTooShort}>
                {saving ? "Saving…" : "Save correction"}
              </Button>
              {editing ? (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setEditing(false);
                    setReason("");
                  }}
                  disabled={saving}
                >
                  Cancel
                </Button>
              ) : null}
            </div>
          </div>
        ) : (
          <Button size="sm" variant="outline" onClick={() => setEditing(true)}>
            Correct the category
          </Button>
        )}
      </CardContent>
    </Card>
  );
}
