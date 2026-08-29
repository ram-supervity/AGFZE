"use client";

import { useEffect, useState } from "react";

import { ChangeReasonField } from "@/components/admin/change-reason-field";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { channelNote, reasonIsValid, reportTypeLabel } from "@/lib/admin";
import { ROLE_LABELS, type PlatformRole } from "@/lib/roles";
import type { ReportDistributionRuleBody, ReportDistributionRuleRow } from "@/lib/api-client";

export interface DistributionEditDialogProps {
  row: ReportDistributionRuleRow | null;
  /** Null row plus open means "add a rule"; a row means "edit this one". */
  open: boolean;
  reportTypes: string[];
  channels: string[];
  roles: string[];
  onOpenChange: (open: boolean) => void;
  saving: boolean;
  onSave: (body: ReportDistributionRuleBody) => Promise<void>;
}

/**
 * Configure who receives a scheduled report.
 *
 * Two things this dialog will not let somebody do, both because the server will not either. An
 * active rule that names nobody cannot be saved - it would read on the table as distribution that
 * works while reaching no one, and stopping a report is what deactivating is for. And an ad-hoc
 * report cannot be chosen at all: its requester is already watching it generate.
 *
 * Recipients are named by role rather than only by person on purpose. A rule that names the
 * finance desk stays correct as people join and leave it; a rule listing three names quietly stops
 * being correct the first time somebody moves on.
 */
export function DistributionEditDialog({
  row,
  open,
  reportTypes,
  channels,
  roles,
  onOpenChange,
  saving,
  onSave,
}: DistributionEditDialogProps) {
  const [reportType, setReportType] = useState("daily");
  const [selectedRoles, setSelectedRoles] = useState<string[]>([]);
  const [channel, setChannel] = useState("in_app");
  const [active, setActive] = useState(true);
  const [reason, setReason] = useState("");

  useEffect(() => {
    if (!open) return;
    setReportType(row?.report_type ?? reportTypes[0] ?? "daily");
    setSelectedRoles(row?.recipient_roles ?? []);
    setChannel(row?.channel ?? "in_app");
    setActive(row?.is_active ?? true);
    setReason("");
  }, [row, open, reportTypes]);

  function toggleRole(role: string) {
    setSelectedRoles((current) =>
      current.includes(role) ? current.filter((item) => item !== role) : [...current, role],
    );
  }

  const namesNobody = selectedRoles.length === 0 && (row?.recipient_user_ids.length ?? 0) === 0;
  const ready = reasonIsValid(reason) && (!active || !namesNobody);

  async function submit() {
    if (!ready) return;
    await onSave({
      change_reason: reason.trim(),
      report_type: reportType,
      recipient_roles: selectedRoles,
      // Individually-named recipients are preserved as they are. This dialog edits by role, which
      // is the shape an administrator maintains; a named individual is added through the API and
      // must not be silently dropped by an edit that never offered to change them.
      recipient_user_ids: row?.recipient_user_ids ?? [],
      channel,
      is_active: active,
    });
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <div className="space-y-1.5">
          <DialogTitle>{row ? "Edit distribution rule" : "Add a distribution rule"}</DialogTitle>
          <DialogDescription>
            Recipients are notified with a link to the report in the platform. The file itself is
            never attached to an email and never leaves the platform on its own.
          </DialogDescription>
        </div>

        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="distribution-report-type">Report</Label>
            <Select
              id="distribution-report-type"
              value={reportType}
              onChange={(event) => setReportType(event.target.value)}
            >
              {reportTypes.map((value) => (
                <option key={value} value={value}>
                  {reportTypeLabel(value)}
                </option>
              ))}
            </Select>
            <p className="text-xs text-muted-foreground">
              Only the scheduled reports can be distributed. An ad-hoc report&apos;s requester is
              already watching it generate, so it is not offered here.
            </p>
          </div>

          <fieldset className="space-y-1.5">
            <legend className="text-sm font-medium text-foreground">Recipients</legend>
            <p className="text-xs text-muted-foreground">
              Named by role, and resolved to whoever holds that role on the day the report is
              produced.
            </p>
            <div className="grid gap-1.5 sm:grid-cols-2">
              {roles.map((role) => (
                <label key={role} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    className="h-4 w-4 rounded border-input"
                    checked={selectedRoles.includes(role)}
                    onChange={() => toggleRole(role)}
                  />
                  <span>{ROLE_LABELS[role as PlatformRole] ?? role}</span>
                </label>
              ))}
            </div>
            {active && namesNobody ? (
              <p role="alert" className="text-xs text-signal-blocked">
                An active rule has to reach somebody. To stop this report being distributed,
                uncheck Active rather than emptying the list.
              </p>
            ) : null}
          </fieldset>

          <div className="space-y-1.5">
            <Label htmlFor="distribution-channel">Channel</Label>
            <Select
              id="distribution-channel"
              value={channel}
              onChange={(event) => setChannel(event.target.value)}
            >
              {channels.map((value) => (
                <option key={value} value={value}>
                  {value === "in_app" ? "In-app only" : value === "email" ? "Email" : "Both"}
                </option>
              ))}
            </Select>
            <p className="text-xs text-muted-foreground">{channelNote(channel)}</p>
          </div>

          <label className="flex items-start gap-2.5 text-sm">
            <input
              type="checkbox"
              className="mt-0.5 h-4 w-4 rounded border-input"
              checked={active}
              onChange={(event) => setActive(event.target.checked)}
            />
            <span>
              <span className="font-medium text-foreground">Active</span>
              <span className="mt-0.5 block text-xs text-muted-foreground">
                An inactive rule sends nothing and stays listed, so the decision to stop remains
                readable later.
              </span>
            </span>
          </label>

          <ChangeReasonField
            id="distribution-reason"
            value={reason}
            onChange={setReason}
            subject="this distribution rule"
            disabled={saving}
          />
        </div>

        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={saving}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={!ready || saving}>
            {saving ? "Saving…" : "Save rule"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
