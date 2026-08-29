"use client";

import { useRouter } from "next/navigation";
import { useSession } from "next-auth/react";
import { useState } from "react";
import toast from "react-hot-toast";

import { ReportTemplateDialog } from "@/components/admin/report-template-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { reportTypeLabel, sectionSourceLabel } from "@/lib/admin";
import {
  ApiError,
  updateReportTemplate,
  type ReportTemplateBody,
  type ReportTemplateList,
  type ReportTemplateRow,
} from "@/lib/api-client";
import { formatDateTime } from "@/lib/utils";

export interface ReportTemplatesTableProps {
  data: ReportTemplateList;
}

/**
 * The three report structures in one table, with no branch on which report a row is.
 *
 * That there is no special case for the monthly report — the only one that carries an AI
 * paragraph and the only one that lists transactions under its summary — is the point. Those are
 * columns on the row, not code here, which is what makes a fourth report a configuration change
 * rather than a release.
 */
export function ReportTemplatesTable({ data }: ReportTemplatesTableProps) {
  const router = useRouter();
  const { data: session } = useSession();
  const [editing, setEditing] = useState<ReportTemplateRow | null>(null);
  const [saving, setSaving] = useState(false);

  async function save(body: ReportTemplateBody) {
    const token = session?.accessToken;
    if (!token || !editing) {
      toast.error("Your session has expired. Sign in again to make this change.");
      return;
    }
    setSaving(true);
    try {
      await updateReportTemplate(token, editing.id, body);
      toast.success(
        `The ${reportTypeLabel(editing.report_type).toLowerCase()} report takes its new shape from the next generation.`,
      );
      setEditing(null);
      router.refresh();
    } catch (error) {
      toast.error(
        error instanceof ApiError ? error.message : "The template could not be changed.",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-4">
      <p className="rounded-md border border-border bg-surface px-4 py-3 text-sm leading-relaxed text-muted-foreground">
        Structure only. No figure is reachable from this screen: every number a report prints is
        computed from the governed transaction, exception, approval, shipment and posting tables at
        the moment the report is generated, and each one still carries the filtered query that
        reproduces it.
      </p>

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Report</TableHead>
            <TableHead>Sections</TableHead>
            <TableHead>Carries</TableHead>
            <TableHead>Last changed</TableHead>
            <TableHead className="text-right">Action</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {data.items.map((row) => (
            <TableRow key={row.id} className="align-top">
              <TableCell>
                <span className="text-sm font-medium text-foreground">{row.title}</span>
                <p className="mt-0.5 font-mono text-xs text-muted-foreground">
                  {row.template_key}
                </p>
              </TableCell>

              <TableCell className="text-sm text-muted-foreground">
                <span className="text-foreground">{row.section_count}</span>
                <p className="mt-0.5 max-w-[22rem] text-xs">
                  {row.sections.map((section) => sectionSourceLabel(section.source)).join(" · ")}
                </p>
              </TableCell>

              <TableCell className="space-x-1.5 whitespace-nowrap">
                {row.wants_ai_summary ? (
                  <Badge variant="secondary">AI summary</Badge>
                ) : null}
                {row.include_detail_rows ? <Badge variant="muted">Transaction list</Badge> : null}
              </TableCell>

              <TableCell className="text-sm text-muted-foreground">
                {formatDateTime(row.changed_at)}
                <p className="mt-0.5 text-xs">
                  {row.changed_by_name ?? "Seeded with the platform"}
                </p>
                <p className="mt-0.5 max-w-[20rem] text-xs italic" title={row.change_reason}>
                  “{row.change_reason}”
                </p>
              </TableCell>

              <TableCell className="text-right">
                <Button size="sm" variant="outline" onClick={() => setEditing(row)}>
                  Edit
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      <ReportTemplateDialog
        row={editing}
        vocabularies={data}
        open={editing !== null}
        onOpenChange={(open) => (open ? null : setEditing(null))}
        saving={saving}
        onSave={save}
      />
    </div>
  );
}
