"use client";

import { Send } from "lucide-react";
import { useRouter } from "next/navigation";
import { useSession } from "next-auth/react";
import { useState } from "react";
import toast from "react-hot-toast";

import { DistributionEditDialog } from "@/components/admin/distribution-edit-dialog";
import { EmptyState } from "@/components/shared/empty-state";
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
import { reportTypeLabel } from "@/lib/admin";
import {
  ApiError,
  createReportDistributionRule,
  updateReportDistributionRule,
  type ReportDistributionRuleBody,
  type ReportDistributionRuleList,
  type ReportDistributionRuleRow,
} from "@/lib/api-client";
import { ROLE_LABELS, type PlatformRole } from "@/lib/roles";
import { formatDateTime } from "@/lib/utils";

export interface DistributionTableProps {
  data: ReportDistributionRuleList;
}

const CHANNEL_LABELS: Record<string, string> = {
  in_app: "In-app only",
  email: "Email",
  both: "Both",
};

/**
 * Every distribution rule, active and inactive.
 *
 * The inactive ones are shown deliberately. "We used to send the monthly report to the finance
 * desk and stopped in March, because …" is exactly what somebody signing this platform off needs
 * to be able to read on the screen rather than reconstruct from the audit trail.
 */
export function DistributionTable({ data }: DistributionTableProps) {
  const router = useRouter();
  const { data: session } = useSession();
  const [editing, setEditing] = useState<ReportDistributionRuleRow | null>(null);
  const [adding, setAdding] = useState(false);
  const [saving, setSaving] = useState(false);

  async function save(body: ReportDistributionRuleBody) {
    const token = session?.accessToken;
    if (!token) {
      toast.error("Your session has expired. Sign in again to make this change.");
      return;
    }
    setSaving(true);
    try {
      if (editing) await updateReportDistributionRule(token, editing.id, body);
      else await createReportDistributionRule(token, body);
      toast.success(
        editing
          ? "The distribution rule is saved."
          : `The ${reportTypeLabel(body.report_type)} report will be distributed from its next scheduled generation.`,
      );
      setEditing(null);
      setAdding(false);
      router.refresh();
    } catch (error) {
      toast.error(
        error instanceof ApiError ? error.message : "The rule could not be saved.",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Button onClick={() => setAdding(true)}>Add a rule</Button>
      </div>

      {data.items.length === 0 ? (
        <EmptyState
          icon={Send}
          title="No report is distributed to anybody"
          description="Scheduled reports are generated, stored and readable in the platform, and reach nobody until a rule here says who should receive them. That is the shipped state, not a fault."
        />
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Report</TableHead>
              <TableHead>Recipients</TableHead>
              <TableHead>Reaches today</TableHead>
              <TableHead>Channel</TableHead>
              <TableHead>State</TableHead>
              <TableHead>Last changed</TableHead>
              <TableHead className="sr-only">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.items.map((row) => (
              <TableRow key={row.id}>
                <TableCell className="font-medium text-foreground">
                  {reportTypeLabel(row.report_type)}
                </TableCell>
                <TableCell className="text-sm text-muted-foreground">
                  {row.recipient_roles.length > 0
                    ? row.recipient_roles
                      .map((role) => ROLE_LABELS[role as PlatformRole] ?? role)
                      .join(", ")
                    : "-"}
                  {row.recipient_user_ids.length > 0
                    ? ` · ${row.recipient_user_ids.length} named ${row.recipient_user_ids.length === 1 ? "person" : "people"}`
                    : ""}
                </TableCell>
                <TableCell className="text-sm text-muted-foreground">
                  {row.recipient_names.length > 0
                    ? `${row.recipient_names.length} ${row.recipient_names.length === 1 ? "person" : "people"}`
                    : "Nobody currently holds these roles"}
                </TableCell>
                <TableCell>
                  <Badge variant="muted">{CHANNEL_LABELS[row.channel] ?? row.channel}</Badge>
                </TableCell>
                <TableCell>
                  <Badge variant={row.is_active ? "secondary" : "muted"}>
                    {row.is_active ? "Active" : "Inactive"}
                  </Badge>
                </TableCell>
                <TableCell className="text-sm text-muted-foreground">
                  {formatDateTime(row.changed_at)}
                  {row.changed_by_name ? ` · ${row.changed_by_name}` : ""}
                </TableCell>
                <TableCell className="text-right">
                  <Button variant="ghost" size="sm" onClick={() => setEditing(row)}>
                    Edit
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      <DistributionEditDialog
        row={editing}
        open={Boolean(editing) || adding}
        reportTypes={data.report_types}
        channels={data.channels}
        roles={data.roles}
        saving={saving}
        onOpenChange={(open) => {
          if (open) return;
          setEditing(null);
          setAdding(false);
        }}
        onSave={save}
      />
    </div>
  );
}
