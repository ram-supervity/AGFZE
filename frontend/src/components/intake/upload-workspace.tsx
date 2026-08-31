"use client";

import { CheckCircle2, CircleAlert, FileText, Loader2, UploadCloud, X } from "lucide-react";
import Link from "next/link";
import { useSession } from "next-auth/react";
import { useCallback, useRef, useState } from "react";
import toast from "react-hot-toast";

import { AiDisclaimer } from "@/components/shared/ai-disclaimer";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { Select } from "@/components/ui/select";
import {
  ApiError,
  fetchJobStatus,
  uploadDocuments,
  type UploadAccepted,
} from "@/lib/api-client";
import {
  ACCEPTED_EXTENSIONS,
  BUSINESS_STREAMS,
  DOCUMENT_TYPES,
  DOCUMENT_TYPE_LABELS,
  STREAM_LABELS,
  formatBytes,
  validateFileClientSide,
} from "@/lib/intake";
import { cn } from "@/lib/utils";

type FileState = "ready" | "rejected" | "uploading" | "queued" | "failed";

interface Staged {
  key: string;
  file: File;
  state: FileState;
  message: string | null;
}

const ACCEPT = ACCEPTED_EXTENSIONS.join(",");
const POLL_INTERVAL_MS = 2500;
const POLL_LIMIT = 80;

let counter = 0;
const nextKey = () => `staged-${(counter += 1)}`;

export function UploadWorkspace() {
  const { data: session } = useSession();
  const inputRef = useRef<HTMLInputElement>(null);
  const [staged, setStaged] = useState<Staged[]>([]);
  const [stream, setStream] = useState<string>("scrap");
  const [hint, setHint] = useState<string>("");
  const [dragging, setDragging] = useState(false);
  const [progress, setProgress] = useState(0);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<UploadAccepted | null>(null);
  const [classifying, setClassifying] = useState(false);

  const stage = useCallback((incoming: FileList | File[]) => {
    const additions = Array.from(incoming).map<Staged>((file) => {
      // Rejected here before a byte leaves the browser. The server re-decides from the file's
      // real leading bytes regardless, and its answer is the one that counts.
      const problem = validateFileClientSide(file);
      return {
        key: nextKey(),
        file,
        state: problem ? "rejected" : "ready",
        message: problem,
      };
    });
    setStaged((current) => [...current, ...additions]);
    setResult(null);
  }, []);

  const acceptable = staged.filter((item) => item.state === "ready");

  async function submit() {
    if (!session?.accessToken) {
      toast.error("Your session has expired. Sign in again to upload.");
      return;
    }
    if (acceptable.length === 0) return;

    setBusy(true);
    setProgress(0);
    setStaged((current) =>
      current.map((item) => (item.state === "ready" ? { ...item, state: "uploading" } : item)),
    );

    const form = new FormData();
    for (const item of acceptable) form.append("files", item.file, item.file.name);
    form.append("stream", stream);
    if (hint) form.append("document_type_hint", hint);

    try {
      const accepted = await uploadDocuments(session.accessToken, form, setProgress);
      const rejectedNames = new Set(accepted.rejected.map((entry) => entry.filename));
      setStaged((current) =>
        current.map((item) => {
          if (item.state !== "uploading") return item;
          const rejection = accepted.rejected.find((entry) => entry.filename === item.file.name);
          return rejectedNames.has(item.file.name)
            ? { ...item, state: "failed", message: rejection?.reason ?? "Rejected by the server." }
            : { ...item, state: "queued", message: null };
        }),
      );
      setResult(accepted);
      toast.success(`Accepted as ${accepted.request_code}.`);
      void trackClassification(session.accessToken, accepted.job_id);
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "The upload could not be completed.";
      setStaged((current) =>
        current.map((item) =>
          item.state === "uploading" ? { ...item, state: "failed", message } : item,
        ),
      );
      toast.error(message);
    } finally {
      setBusy(false);
    }
  }

  async function trackClassification(accessToken: string, jobId: string) {
    setClassifying(true);
    for (let attempt = 0; attempt < POLL_LIMIT; attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
      try {
        const job = await fetchJobStatus(accessToken, jobId);
        if (job.status === "completed" || job.status === "failed") {
          setClassifying(false);
          if (job.status === "failed") {
            toast.error("Classification did not complete. The request is flagged for review.");
          }
          return;
        }
      } catch {
        // A transient polling failure is not the upload failing; the request is already saved.
        setClassifying(false);
        return;
      }
    }
    setClassifying(false);
  }

  return (
    <div className="space-y-6">
      <AiDisclaimer />

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <div
            onDragOver={(event) => {
              event.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(event) => {
              event.preventDefault();
              setDragging(false);
              if (event.dataTransfer.files.length > 0) stage(event.dataTransfer.files);
            }}
            className={cn(
              "flex flex-col items-center justify-center rounded-medium border-2 border-dashed px-space-300 py-space-600 text-center transition-colors",
              dragging ? "border-secondary bg-secondary/5" : "border-border bg-elevation-sunken",
            )}
          >
            <UploadCloud className="mb-3 h-8 w-8 text-muted-foreground" aria-hidden="true" />
            <p className="text-sm font-medium text-foreground">
              Drag documents here, or choose them from your machine
            </p>
            <p className="mt-1.5 max-w-md text-sm text-muted-foreground">
              PDF, Word, Excel, CSV, JPEG and PNG. Up to 25 MB each.
            </p>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="mt-5"
              onClick={() => inputRef.current?.click()}
              disabled={busy}
            >
              Choose files
            </Button>
            <input
              ref={inputRef}
              type="file"
              multiple
              accept={ACCEPT}
              className="sr-only"
              onChange={(event) => {
                if (event.target.files) stage(event.target.files);
                event.target.value = "";
              }}
            />
          </div>

          {staged.length > 0 ? (
            <ul className="mt-4 space-y-2">
              {staged.map((item) => (
                <li
                  key={item.key}
                  className="flex items-start gap-space-150 rounded-control border-thin border-border bg-elevation-default p-space-150 shadow-raised"
                >
                  <StatusIcon state={item.state} />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-foreground">
                      {item.file.name}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {formatBytes(item.file.size)} · {describe(item.state)}
                    </p>
                    {item.message ? (
                      <p className="mt-1 text-xs text-signal-blocked">{item.message}</p>
                    ) : null}
                    {item.state === "uploading" ? (
                      <Progress
                        value={progress}
                        label={`Uploading ${item.file.name}`}
                        className="mt-2"
                      />
                    ) : null}
                  </div>
                  {!busy ? (
                    <button
                      type="button"
                      aria-label={`Remove ${item.file.name}`}
                      onClick={() =>
                        setStaged((current) => current.filter((entry) => entry.key !== item.key))
                      }
                      className="rounded-control p-space-050 text-muted-foreground transition-colors hover:bg-elevation-hovered hover:text-foreground focus-visible:outline-none focus-visible:ring-thick focus-visible:ring-ring"
                    >
                      <X className="h-4 w-4" aria-hidden="true" />
                    </button>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : null}
        </div>

        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Where does this belong?</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-1.5">
                <Label htmlFor="upload-stream">Business stream (required)</Label>
                <Select
                  id="upload-stream"
                  value={stream}
                  onChange={(event) => setStream(event.target.value)}
                  disabled={busy}
                >
                  {BUSINESS_STREAMS.map((value) => (
                    <option key={value} value={value}>
                      {STREAM_LABELS[value]}
                    </option>
                  ))}
                </Select>
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="upload-hint">Document type (optional)</Label>
                <Select
                  id="upload-hint"
                  value={hint}
                  onChange={(event) => setHint(event.target.value)}
                  disabled={busy}
                >
                  <option value="">Let the classifier decide</option>
                  {DOCUMENT_TYPES.filter((value) => value !== "unknown").map((value) => (
                    <option key={value} value={value}>
                      {DOCUMENT_TYPE_LABELS[value]}
                    </option>
                  ))}
                </Select>
                <p className="text-xs text-muted-foreground">
                  Used only when the classifier is unsure of the type on its own.
                </p>
              </div>

              <Button
                className="w-full"
                onClick={submit}
                disabled={busy || acceptable.length === 0}
              >
                {busy
                  ? "Uploading…"
                  : `Upload ${acceptable.length || ""} file${acceptable.length === 1 ? "" : "s"}`.trim()}
              </Button>
            </CardContent>
          </Card>

          {result ? (
            <Card>
              <CardHeader>
                <CardTitle>{result.request_code}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 text-sm">
                <p className="text-muted-foreground">
                  {classifying
                    ? "Classification and extraction are running. This page does not need to stay open."
                    : "Classification has finished. Open the request to review what was found."}
                </p>
                <Button asChild size="sm" variant="outline" className="w-full">
                  <Link href={`/inbox/${result.request_id}`}>Open the request</Link>
                </Button>
              </CardContent>
            </Card>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function describe(state: FileState): string {
  switch (state) {
    case "ready":
      return "Ready to upload";
    case "rejected":
      return "Rejected before upload";
    case "uploading":
      return "Uploading";
    case "queued":
      return "Accepted and queued for extraction";
    case "failed":
      return "Not accepted";
  }
}

function StatusIcon({ state }: { state: FileState }) {
  const className = "mt-0.5 h-4 w-4 shrink-0";
  if (state === "queued") {
    return <CheckCircle2 className={cn(className, "text-signal-confident")} aria-hidden="true" />;
  }
  if (state === "rejected" || state === "failed") {
    return <CircleAlert className={cn(className, "text-signal-blocked")} aria-hidden="true" />;
  }
  if (state === "uploading") {
    return (
      <Loader2 className={cn(className, "animate-spin text-secondary")} aria-hidden="true" />
    );
  }
  return <FileText className={cn(className, "text-muted-foreground")} aria-hidden="true" />;
}
