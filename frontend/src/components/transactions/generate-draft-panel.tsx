"use client";

import { FileText, Info } from "lucide-react";
import { useMemo, useState } from "react";
import toast from "react-hot-toast";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Select } from "@/components/ui/select";
import {
  ApiError,
  fetchJobStatus,
  generateDraft,
  type GeneratedDraft,
  type JobStatus,
} from "@/lib/api-client";
import { formatBytes } from "@/lib/intake";
import {
  GENERATED_DOCUMENT_LABELS,
  GENERATED_DOCUMENT_NOTES,
  SALES_GENERATED_DOCUMENT_TYPES,
  type GeneratedDocumentType,
} from "@/lib/transactions";
import { cn, formatDateTime } from "@/lib/utils";

export interface GenerateDraftPanelProps {
  transactionId: string;
  drafts: GeneratedDraft[];
  canGenerate: boolean;
  blocker: string | null;
  accessToken: string | undefined;
  title?: string;
  description?: string;
  documentTypes?: readonly GeneratedDocumentType[];
  documentLabels?: Record<GeneratedDocumentType, string>;
  documentNotes?: Record<GeneratedDocumentType, string>;
  defaultDocumentType?: GeneratedDocumentType;
  /** Re-read the transaction so the finished draft appears in its document history. */
  onGenerated: () => Promise<void>;
  /** Opens the field editor so the user can change the deal before re-generating. */
  onRequestChanges: () => void;
}

const POLL_INTERVAL_MS = 800;
const MAX_POLLS = 90;

/**
 * Generate a draft, watch the job, and preview what came out.
 *
 * The progress is the platform's existing background-job pattern - the same `create_job` /
 * poll `/jobs/{id}/status` loop the intake pipeline uses - not a second mechanism that looks
 * like it.
 *
 * "Request changes" does not edit the document. It sends the user back to the fields, because a
 * draft's content comes from the transaction record: changing what the draft says means changing
 * what the deal says, and then generating again. Every generation produces a new draft beside
 * the last one, so nothing that was ever produced is lost.
 *
 * There is no send, email, share or sign action here, and there is not meant to be. A draft is
 * reviewed inside AGFZE and taken forward on paper.
 */
export function GenerateDraftPanel({
  transactionId,
  drafts,
  canGenerate,
  blocker,
  accessToken,
  title = "Draft sales documents",
  description = "Populated from this transaction's own data into an approved template. For internal review only.",
  documentTypes = SALES_GENERATED_DOCUMENT_TYPES,
  documentLabels = GENERATED_DOCUMENT_LABELS,
  documentNotes = GENERATED_DOCUMENT_NOTES,
  defaultDocumentType,
  onGenerated,
  onRequestChanges,
}: GenerateDraftPanelProps) {
  const [documentType, setDocumentType] = useState<GeneratedDocumentType>(
    defaultDocumentType ?? documentTypes[0] ?? "draft_contract",
  );
  const [job, setJob] = useState<JobStatus | null>(null);
  const [running, setRunning] = useState(false);

  const relevantDrafts = useMemo(
    () =>
      drafts.filter((d) =>
        d.document_type ? (documentTypes as readonly string[]).includes(d.document_type) : false,
      ),
    [drafts, documentTypes],
  );
  const latest = relevantDrafts.length > 0 ? relevantDrafts[relevantDrafts.length - 1] : null;

  async function generate() {
    if (!accessToken) {
      toast.error("Your session has expired. Sign in again to generate a draft.");
      return;
    }
    setRunning(true);
    setJob(null);
    try {
      const accepted = await generateDraft(accessToken, transactionId, documentType);
      const finished = await poll(accessToken, accepted.job_id, setJob);
      if (finished.status === "failed") {
        // A failed generation produces no document at all, deliberately. Saying so plainly is
        // the whole point: a half-populated draft would be far worse than none.
        toast.error(
          finished.error_message ??
            "The draft could not be generated, so nothing was produced.",
        );
        return;
      }
      await onGenerated();
      toast.success(
        `${documentLabels[documentType] ?? GENERATED_DOCUMENT_LABELS[documentType]} generated for review. It has not been sent anywhere.`,
      );
    } catch (error) {
      toast.error(
        error instanceof ApiError ? error.message : "The draft could not be generated.",
      );
    } finally {
      setRunning(false);
    }
  }

  return (
    <section
      className="space-y-space-200 rounded-medium border-thin border-border bg-elevation-default p-space-200 shadow-raised"
      aria-label="Generate draft"
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold text-foreground">{title}</h2>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {description}
          </p>
        </div>
        {relevantDrafts.length > 0 ? (
          <Badge variant="muted">
            {relevantDrafts.length} draft{relevantDrafts.length === 1 ? "" : "s"} generated
          </Badge>
        ) : null}
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-[16rem] flex-1 space-y-1.5">
          <label
            htmlFor="draft-type"
            className="block text-xs font-medium uppercase tracking-widest text-muted-foreground"
          >
            Document
          </label>
          <Select
            id="draft-type"
            value={documentType}
            disabled={running}
            onChange={(event) =>
              setDocumentType(event.target.value as GeneratedDocumentType)
            }
          >
            {documentTypes.map((value) => (
              <option key={value} value={value}>
                {documentLabels[value] ?? value}
              </option>
            ))}
          </Select>
          <p className="text-xs leading-relaxed text-muted-foreground">
            {documentNotes[documentType]}
          </p>
        </div>
        {/* The one AI-forward action on this panel, and the only place the brand gradient
            appears here - the design system reserves the gradient-text treatment for exactly this. */}
        <Button variant="ai" onClick={generate} disabled={!canGenerate || running}>
          {running ? "Generating…" : relevantDrafts.length > 0 ? "Generate again" : "Generate draft"}
        </Button>
        {relevantDrafts.length > 0 ? (
          <Button variant="outline" onClick={onRequestChanges} disabled={running}>
            Request changes
          </Button>
        ) : null}
      </div>

      {!canGenerate && blocker ? (
        <p className="rounded-medium border-thin border-pill-amber-border bg-pill-amber-bg px-space-150 py-space-100 text-body-sm text-foreground">
          {blocker}
        </p>
      ) : null}

      {running || job ? (
        <div className="space-y-1.5">
          <Progress value={job?.progress ?? 5} label="Generating the draft" />
          <p className="text-xs text-muted-foreground">
            {job?.status === "failed"
              ? (job.error_message ?? "The generation failed. Nothing was produced.")
              : job?.status === "completed"
                ? "Done."
                : "Building the document from the transaction record…"}
          </p>
        </div>
      ) : null}

      {latest ? (
        <div className="space-y-2 rounded-medium border-thin border-border bg-elevation-sunken p-3">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="flex min-w-0 items-start gap-2.5">
              <FileText
                className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground"
                aria-hidden="true"
              />
              <div className="min-w-0">
                <p className="truncate font-mono text-sm text-foreground">{latest.filename}</p>
                <p className="text-xs text-muted-foreground">
                  {documentLabels[latest.document_type as GeneratedDocumentType]
                    ? `${documentLabels[latest.document_type as GeneratedDocumentType]} · `
                    : ""}
                  Version {latest.version} · {formatBytes(latest.byte_size)} ·{" "}
                  {formatDateTime(latest.created_at)}
                  {latest.generated_by_name ? ` · requested by ${latest.generated_by_name}` : ""}
                </p>
              </div>
            </div>
            {latest.download_url ? (
              <Button asChild size="sm" variant="outline">
                <a href={latest.download_url} target="_blank" rel="noreferrer">
                  Open draft
                </a>
              </Button>
            ) : null}
          </div>
          <p className="flex items-start gap-2 text-xs text-muted-foreground">
            <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            This draft has not been issued, sent or signed, and this platform has no way to send
            it. Review it, then take it forward outside the system.
          </p>
        </div>
      ) : null}

      {relevantDrafts.length > 1 ? (
        <div className="space-y-1.5">
          <h3 className="text-xs font-medium uppercase tracking-widest text-muted-foreground">
            Earlier drafts
          </h3>
          <ul className="space-y-1.5">
            {relevantDrafts
              .slice(0, -1)
              .reverse()
              .map((draft) => (
                <li
                  key={draft.id}
                  className={cn(
                    "flex flex-wrap items-center justify-between gap-2 rounded-control border-thin",
                    "border-border bg-elevation-default px-space-150 py-space-075 text-body-xs",
                  )}
                >
                  <span className="truncate font-mono text-foreground">
                    v{draft.version} · {draft.filename}
                  </span>
                  <span className="flex items-center gap-2">
                    <span className="text-muted-foreground">
                      {formatDateTime(draft.created_at)}
                    </span>
                    {draft.download_url ? (
                      <a
                        href={draft.download_url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-secondary underline-offset-4 hover:underline"
                      >
                        Open
                      </a>
                    ) : null}
                  </span>
                </li>
              ))}
          </ul>
          <p className="text-xs text-muted-foreground">
            Regenerating never replaces a draft. Every version stays on the record so what was
            produced, and when, is always recoverable.
          </p>
        </div>
      ) : null}
    </section>
  );
}

async function poll(
  accessToken: string,
  jobId: string,
  onTick: (job: JobStatus) => void,
): Promise<JobStatus> {
  for (let attempt = 0; attempt < MAX_POLLS; attempt += 1) {
    const status = await fetchJobStatus(accessToken, jobId);
    onTick(status);
    if (status.status === "completed" || status.status === "failed") return status;
    await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
  }
  throw new ApiError(
    504,
    "job_timeout",
    "The draft generation is taking longer than expected. Check the transaction's documents in a moment.",
  );
}
