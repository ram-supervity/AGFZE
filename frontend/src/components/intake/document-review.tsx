"use client";

import Link from "next/link";
import { useSession } from "next-auth/react";
import { useCallback, useMemo, useState } from "react";
import toast from "react-hot-toast";

import { FieldEditor } from "@/components/intake/field-editor";
import { PageViewer } from "@/components/intake/page-viewer";
import { ReclassifyDialog } from "@/components/intake/reclassify-dialog";
import { AiDisclaimer } from "@/components/shared/ai-disclaimer";
import { ConfidenceBadge } from "@/components/shared/confidence-badge";
import { PageHeader } from "@/components/shared/page-header";
import { MatchOutcomeCard } from "@/components/transactions/match-outcome-card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import {
  ApiError,
  confirmDocumentExtraction,
  correctDocumentFields,
  fetchDocumentDetail,
  fetchDocumentMatch,
  fetchJobStatus,
  type DocumentDetail,
  type ExtractedField,
  type MatchOutcome,
} from "@/lib/api-client";
import {
  DOCUMENT_TYPE_LABELS,
  EXTRACTION_STATUS_LABELS,
  TERRITORY_LABELS,
  labelFor,
} from "@/lib/intake";
import { formatDateTime } from "@/lib/utils";

const POLL_INTERVAL_MS = 2000;
const POLL_LIMIT = 90;

export interface DocumentReviewProps {
  initial: DocumentDetail;
  canCorrect: boolean;
  /** Whether this account may resolve an ambiguous match, which the purchase desk owns. */
  canMatch: boolean;
  /** The matching position as the server sees it now, for a document already confirmed. */
  initialMatch: MatchOutcome | null;
}

export function DocumentReview({
  initial,
  canCorrect,
  canMatch,
  initialMatch,
}: DocumentReviewProps) {
  const { data: session } = useSession();
  const [detail, setDetail] = useState(initial);
  const [savingField, setSavingField] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [jobProgress, setJobProgress] = useState<number | null>(null);
  const [match, setMatch] = useState<MatchOutcome | null>(initialMatch);

  const token = session?.accessToken;

  const refresh = useCallback(async () => {
    if (!token) return;
    try {
      setDetail(await fetchDocumentDetail(token, detail.id));
      if (detail.confirmed_at) setMatch(await fetchDocumentMatch(token, detail.id));
    } catch {
      // Leaving the last good view on screen beats replacing it with an error page.
    }
  }, [token, detail.id, detail.confirmed_at]);

  const sections = useMemo(() => groupBySection(detail.fields), [detail.fields]);
  const unresolved = detail.fields.filter((field) => field.has_conflict).length;
  const confirmed = Boolean(detail.confirmed_at);
  const ready = detail.extraction_status === "completed";

  async function saveField(field: ExtractedField, value: string | null, reason: string | null) {
    if (!token) {
      toast.error("Your session has expired. Sign in again to save this correction.");
      return;
    }
    setSavingField(field.field_name);
    try {
      setDetail(
        await correctDocumentFields(token, detail.id, [
          { field_name: field.field_name, value, reason: reason ?? undefined },
        ]),
      );
      toast.success(`${field.label ?? field.field_name} corrected.`);
    } catch (error) {
      toast.error(
        error instanceof ApiError ? error.message : "The correction could not be saved.",
      );
    } finally {
      setSavingField(null);
    }
  }

  async function confirm() {
    if (!token) {
      toast.error("Your session has expired. Sign in again to confirm.");
      return;
    }
    setConfirming(true);
    try {
      const result = await confirmDocumentExtraction(token, detail.id);
      // The real matching outcome, straight off the confirmation, rather than a second guess at
      // what the server decided.
      setMatch(result.matching);
      toast.success("Extraction confirmed.");
      await refresh();
    } catch (error) {
      toast.error(
        error instanceof ApiError ? error.message : "The extraction could not be confirmed.",
      );
    } finally {
      setConfirming(false);
    }
  }

  const trackJob = useCallback(
    async (jobId: string) => {
      if (!token) return;
      setJobProgress(0);
      for (let attempt = 0; attempt < POLL_LIMIT; attempt += 1) {
        await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
        try {
          const job = await fetchJobStatus(token, jobId);
          setJobProgress(job.progress);
          if (job.status === "completed" || job.status === "failed") {
            setJobProgress(null);
            if (job.status === "failed") {
              toast.error("Re-extraction did not complete. The document is flagged for review.");
            }
            await refresh();
            return;
          }
        } catch {
          setJobProgress(null);
          await refresh();
          return;
        }
      }
      setJobProgress(null);
      await refresh();
    },
    [token, refresh],
  );

  return (
    <div className="space-y-6">
      <PageHeader
        title={detail.filename}
        description={
          detail.classification_rationale ??
          "Extracted fields shown beside the pages they were read from."
        }
        actions={
          // A generated draft came from no request, so there is nowhere to go back to and the
          // button is simply not offered rather than pointing at an intake row that never existed.
          detail.request_id ? (
            <Button asChild variant="outline" size="sm">
              <Link href={`/inbox/${detail.request_id}`}>
                Back to {detail.request_code ?? "the request"}
              </Link>
            </Button>
          ) : null
        }
      />

      <AiDisclaimer />

      <div className="flex flex-wrap items-center gap-2">
        {detail.document_type ? (
          <ConfidenceBadge
            label={labelFor(DOCUMENT_TYPE_LABELS, detail.document_type)}
            confidence={detail.classification_confidence}
          />
        ) : (
          <Badge variant="muted">Not classified yet</Badge>
        )}
        {detail.territory ? (
          <Badge variant="outline">{labelFor(TERRITORY_LABELS, detail.territory)}</Badge>
        ) : null}
        <Badge variant="muted">
          {labelFor(EXTRACTION_STATUS_LABELS, detail.extraction_status)}
        </Badge>
        {confirmed ? (
          <Badge
            variant="outline"
            className="border-signal-confident/35 bg-signal-confident/10 text-signal-confident"
          >
            Confirmed {formatDateTime(detail.confirmed_at)}
            {detail.confirmed_by_name ? ` by ${detail.confirmed_by_name}` : ""}
          </Badge>
        ) : null}
        {unresolved > 0 ? (
          <Badge
            variant="outline"
            className="border-signal-review/35 bg-signal-review/10 text-signal-review"
          >
            {unresolved} conflicting field{unresolved === 1 ? "" : "s"}
          </Badge>
        ) : null}
      </div>

      {jobProgress !== null ? (
        <div className="space-y-1.5 rounded-md border border-border bg-surface p-4">
          <p className="text-sm text-foreground">
            Re-running extraction against the new document type&apos;s schema…
          </p>
          <Progress value={jobProgress} label="Re-extraction progress" />
        </div>
      ) : null}

      {match ? (
        <MatchOutcomeCard
          documentId={detail.id}
          outcome={match}
          canResolve={canMatch}
          onResolved={(resolved) => {
            setMatch(resolved);
            void refresh();
          }}
        />
      ) : null}

      {detail.extraction_error ? (
        <p className="rounded-md border border-signal-blocked/35 bg-signal-blocked/10 px-4 py-3 text-sm text-foreground">
          {detail.extraction_error}
        </p>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-2">
        <div className="lg:sticky lg:top-20 lg:h-[calc(100vh-9rem)]">
          <PageViewer
            filename={detail.filename}
            pageUrls={detail.page_image_urls}
            sourceUrl={detail.source_url}
            contentType={detail.content_type}
          />
        </div>

        <div className="space-y-6">
          {sections.length === 0 ? (
            <p className="rounded-md border border-dashed border-border bg-surface px-4 py-8 text-center text-sm text-muted-foreground">
              No fields have been extracted from this document yet.
            </p>
          ) : (
            sections.map(([section, fields]) => (
              <section key={section} className="space-y-3">
                <h2 className="text-sm font-semibold uppercase tracking-widest text-muted-foreground">
                  {section}
                </h2>
                <div className="space-y-3">
                  {fields.map((field) => (
                    <FieldEditor
                      key={field.id}
                      field={field}
                      editable={canCorrect && !confirmed}
                      saving={savingField === field.field_name}
                      onSave={(value, reason) => saveField(field, value, reason)}
                    />
                  ))}
                </div>
              </section>
            ))
          )}

          {canCorrect ? (
            <div className="flex flex-wrap gap-2 border-t border-border pt-4">
              <Button onClick={confirm} disabled={confirming || confirmed || !ready}>
                {confirmed
                  ? "Extraction confirmed"
                  : confirming
                    ? "Confirming…"
                    : "Confirm extraction"}
              </Button>
              <ReclassifyDialog
                documentId={detail.id}
                currentType={detail.document_type}
                currentTerritory={detail.territory}
                onQueued={trackJob}
              />
            </div>
          ) : (
            <p className="border-t border-border pt-4 text-sm text-muted-foreground">
              Your role has read access to this document. Corrections and confirmation are made by
              the desk that owns the work.
            </p>
          )}

          {detail.mandatory_documents.length > 0 ? (
            <section className="space-y-2 rounded-md border border-border bg-surface p-4">
              <h2 className="text-sm font-semibold text-foreground">
                Document pack for {labelFor(TERRITORY_LABELS, detail.territory)}
              </h2>
              <p className="text-sm text-muted-foreground">
                Configured checklist for this territory, recorded for reference. Completeness is
                not checked at this stage.
              </p>
              <ul className="flex flex-wrap gap-1.5">
                {detail.mandatory_documents.map((entry) => (
                  <li key={entry}>
                    <Badge variant="muted" className="font-normal">
                      {entry.replace(/_/g, " ")}
                    </Badge>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function groupBySection(fields: ExtractedField[]): [string, ExtractedField[]][] {
  const grouped = new Map<string, ExtractedField[]>();
  for (const field of fields) {
    const section = field.section || "Extracted fields";
    const bucket = grouped.get(section);
    if (bucket) bucket.push(field);
    else grouped.set(section, [field]);
  }
  return Array.from(grouped.entries());
}
