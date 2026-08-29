"use client";

import { useEffect, useState } from "react";

import { ChangeReasonField } from "@/components/admin/change-reason-field";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { reasonIsValid } from "@/lib/admin";
import type { AdminUser } from "@/lib/api-client";
import { ROLE_DESCRIPTIONS, ROLE_LABELS, type PlatformRole } from "@/lib/roles";

export interface RoleEditDialogProps {
  user: AdminUser | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  assignableRoles: string[];
  saving: boolean;
  /** The error the identity provider produced, if the last attempt was refused. */
  failure: string | null;
  onSave: (roles: string[], reason: string) => Promise<void>;
}

/**
 * The manual role override, and it says out loud that that is what it is.
 *
 * Roles normally arrive with the token on every sign-in, mapped from Entra ID groups. This is the
 * documented exception for the case where that mapping is wrong or has not propagated, so the
 * dialog states where the change is written (Keycloak first), what happens if that call fails
 * (nothing at all changes), and when it takes effect (the account's next sign-in).
 */
export function RoleEditDialog({
  user,
  open,
  onOpenChange,
  assignableRoles,
  saving,
  failure,
  onSave,
}: RoleEditDialogProps) {
  const [roles, setRoles] = useState<string[]>([]);
  const [reason, setReason] = useState("");

  useEffect(() => {
    if (!user) return;
    setRoles([...user.roles]);
    setReason("");
  }, [user]);

  if (!user) return null;

  const changed =
    roles.length !== user.roles.length || roles.some((role) => !user.roles.includes(role));
  const ready = roles.length > 0 && changed && reasonIsValid(reason);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <div className="space-y-1.5">
          <DialogTitle>Override {user.display_name}&apos;s roles</DialogTitle>
          <DialogDescription>
            {user.email}. This is written to Keycloak first and mirrored here only once Keycloak
            confirms it. If that call fails, nothing changes on either side. The new roles reach
            this platform on their next sign-in, when a new token is issued.
          </DialogDescription>
        </div>

        {failure ? (
          <p
            role="alert"
            className="rounded-md border border-signal-blocked/45 bg-signal-blocked/10 px-3 py-2 text-sm text-signal-blocked"
          >
            {failure} Nothing was changed - this account still holds{" "}
            {user.roles.map((role) => ROLE_LABELS[role as PlatformRole] ?? role).join(", ")}.
          </p>
        ) : null}

        <div className="space-y-2">
          <Label>Roles</Label>
          <ul className="max-h-[38vh] space-y-1.5 overflow-y-auto pr-1">
            {assignableRoles.map((role) => (
              <li key={role}>
                <label className="flex items-start gap-2.5 rounded-md border border-border px-3 py-2 text-sm">
                  <input
                    type="checkbox"
                    className="mt-0.5 h-4 w-4 rounded border-input"
                    checked={roles.includes(role)}
                    onChange={(event) =>
                      setRoles((held) =>
                        event.target.checked
                          ? [...held, role]
                          : held.filter((value) => value !== role),
                      )
                    }
                  />
                  <span>
                    <span className="font-medium text-foreground">
                      {ROLE_LABELS[role as PlatformRole] ?? role}
                    </span>
                    <span className="mt-0.5 block text-xs text-muted-foreground">
                      {ROLE_DESCRIPTIONS[role as PlatformRole] ?? ""}
                    </span>
                  </span>
                </label>
              </li>
            ))}
          </ul>
          {roles.length === 0 ? (
            <p role="alert" className="text-xs text-signal-blocked">
              An account needs at least one role. Removing every role would leave somebody signed
              in with nothing they may open.
            </p>
          ) : null}
        </div>

        <ChangeReasonField
          id="role-reason"
          value={reason}
          onChange={setReason}
          subject={`${user.display_name}'s role assignment`}
          disabled={saving}
        />

        <div className="flex justify-end gap-2 pt-2">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
            Cancel
          </Button>
          <Button onClick={() => onSave(roles, reason.trim())} disabled={!ready || saving}>
            {saving ? "Writing to Keycloak…" : "Save change"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
