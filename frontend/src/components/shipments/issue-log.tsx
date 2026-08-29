"use client";

import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import type { DocumentSummary, ShipmentIssue } from "@/lib/api-client";
import { labelFor } from "@/lib/intake";
import { SHIPMENT_ISSUE_TYPE_LABELS, formatDateTime } from "@/lib/shipments";

const MIN_DESCRIPTION = 10;

export interface IssueLogProps {
  issues: ShipmentIssue[];
  issueTypes: string[];
  documents: DocumentSummary[];
  canLog: boolean;
  saving: boolean;
  onLog: (issue: {
    issue_type: string;
    description: string;
    document_id: string | null;
  }) => Promise<void>;
}

/** Post-delivery issues: what went wrong with the cargo after it left, and who said so. */
export function IssueLog({
  issues,
  issueTypes,
  documents,
  canLog,
  saving,
  onLog,
}: IssueLogProps) {
  const [issueType, setIssueType] = useState(issueTypes[0] ?? "other");
  const [description, setDescription] = useState("");
  const [documentId, setDocumentId] = useState("");

  const tooShort = description.trim().length < MIN_DESCRIPTION;

  async function submit() {
    await onLog({
      issue_type: issueType,
      description: description.trim(),
      document_id: documentId || null,
    });
    setDescription("");
    setDocumentId("");
  }

  return (
    <div className="space-y-5">
      {issues.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No issue has been logged against this shipment.
        </p>
      ) : (
        <ul className="space-y-3">
          {issues.map((issue) => (
            <li
              key={issue.id}
              className="space-y-1.5 rounded-md border border-border bg-surface px-3 py-2.5"
            >
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="muted">
                  {labelFor(SHIPMENT_ISSUE_TYPE_LABELS, issue.issue_type)}
                </Badge>
                <span className="text-xs text-muted-foreground">
                  {formatDateTime(issue.logged_at)}
                  {issue.logged_by_name ? ` · ${issue.logged_by_name}` : ""}
                </span>
                {issue.resolved_at ? (
                  <Badge
                    variant="outline"
                    className="border-signal-confident/35 bg-signal-confident/10 text-signal-confident"
                  >
                    Resolved
                  </Badge>
                ) : null}
              </div>
              <p className="text-sm leading-relaxed text-foreground">{issue.description}</p>
            </li>
          ))}
        </ul>
      )}

      {canLog ? (
        <div className="space-y-4 border-t border-border pt-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="issue-type">Issue type</Label>
              <Select
                id="issue-type"
                value={issueType}
                disabled={saving}
                onChange={(event) => setIssueType(event.target.value)}
              >
                {issueTypes.map((value) => (
                  <option key={value} value={value}>
                    {labelFor(SHIPMENT_ISSUE_TYPE_LABELS, value)}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="issue-document">Supporting document (optional)</Label>
              <Select
                id="issue-document"
                value={documentId}
                disabled={saving || documents.length === 0}
                onChange={(event) => setDocumentId(event.target.value)}
              >
                <option value="">None</option>
                {documents.map((document) => (
                  <option key={document.id} value={document.id}>
                    {document.filename}
                  </option>
                ))}
              </Select>
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="issue-description">What happened</Label>
            <Textarea
              id="issue-description"
              rows={3}
              value={description}
              disabled={saving}
              placeholder="Two bales water-damaged on arrival at the ICD; photographs taken by the surveyor."
              onChange={(event) => setDescription(event.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              At least {MIN_DESCRIPTION} characters. This goes on the record against the shipment.
            </p>
          </div>

          <div className="flex justify-end">
            <Button onClick={submit} disabled={saving || tooShort}>
              {saving ? "Logging…" : "Log this issue"}
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
