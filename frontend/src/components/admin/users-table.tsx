"use client";

import { Users } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useSession } from "next-auth/react";
import { useState } from "react";
import toast from "react-hot-toast";

import { RoleEditDialog } from "@/components/admin/role-edit-dialog";
import { EmptyState } from "@/components/shared/empty-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ApiError, updateUserRoles, type AdminUser, type AdminUserList } from "@/lib/api-client";
import { ROLE_LABELS, type PlatformRole } from "@/lib/roles";
import { formatDateTime } from "@/lib/utils";

export interface UsersTableProps {
  data: AdminUserList;
  search: string;
}

/**
 * The account list mirrored from the identity provider, with the manual role override on each row.
 *
 * A refused override leaves the row exactly as it was. That is not a courtesy of this component:
 * the API calls Keycloak first and commits nothing locally unless Keycloak confirms, so there is
 * no local state to roll back. What this does is show the failure honestly and re-render from the
 * server rather than optimistically painting a change that did not happen.
 */
export function UsersTable({ data, search }: UsersTableProps) {
  const router = useRouter();
  const params = useSearchParams();
  const { data: session } = useSession();
  const [editing, setEditing] = useState<AdminUser | null>(null);
  const [saving, setSaving] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [term, setTerm] = useState(search);

  function submitSearch(value: string) {
    const next = new URLSearchParams(params.toString());
    if (value.trim()) next.set("search", value.trim());
    else next.delete("search");
    router.push(`/admin/users${next.toString() ? `?${next.toString()}` : ""}`);
  }

  async function save(roles: string[], reason: string) {
    const token = session?.accessToken;
    if (!token || !editing) {
      toast.error("Your session has expired. Sign in again to make this change.");
      return;
    }
    setSaving(true);
    setFailure(null);
    try {
      const result = await updateUserRoles(token, {
        user_id: editing.id,
        roles,
        change_reason: reason,
      });
      const summary = [
        result.roles_added.length ? `added ${result.roles_added.join(", ")}` : "",
        result.roles_removed.length ? `removed ${result.roles_removed.join(", ")}` : "",
      ]
        .filter(Boolean)
        .join(" and ");
      toast.success(
        `Keycloak accepted the change${summary ? `: ${summary}` : ""}. It takes effect on their next sign-in.`,
      );
      setEditing(null);
      router.refresh();
    } catch (error) {
      const message =
        error instanceof ApiError
          ? error.message
          : "The identity provider could not be reached.";
      setFailure(message);
      toast.error(message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-4">
      <p className="text-sm leading-relaxed text-muted-foreground">{data.provisioning_note}</p>

      {data.identity_provider_configured ? null : (
        <p
          role="status"
          className="rounded-md border border-pill-amber-border bg-pill-amber-bg px-3 py-2 text-sm text-signal-review"
        >
          This deployment has no Keycloak Admin API credential configured, so role assignment
          cannot be changed from here. Roles still arrive from the identity provider on every
          sign-in - the override is what is unavailable, not the roles themselves.
        </p>
      )}

      <form
        className="grid gap-3 rounded-lg border border-border bg-surface p-4 sm:grid-cols-[1fr_auto]"
        onSubmit={(event) => {
          event.preventDefault();
          submitSearch(term);
        }}
      >
        <div className="space-y-1.5">
          <Label htmlFor="user-search">Find an account</Label>
          <Input
            id="user-search"
            value={term}
            placeholder="Name or email"
            onChange={(event) => setTerm(event.target.value)}
          />
        </div>
        <div className="flex items-end gap-2">
          <Button type="submit" variant="outline" size="sm">
            Search
          </Button>
          {search ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => {
                setTerm("");
                submitSearch("");
              }}
            >
              Clear
            </Button>
          ) : null}
        </div>
      </form>

      {data.items.length === 0 ? (
        <EmptyState
          icon={Users}
          title={search ? "No account matches that" : "No accounts yet"}
          description={
            search
              ? "Clear the search to see every account."
              : "An account appears here the first time somebody signs in, mirrored from the identity provider."
          }
        />
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Account</TableHead>
              <TableHead>Roles</TableHead>
              <TableHead>State</TableHead>
              <TableHead>Last sign-in</TableHead>
              <TableHead className="text-right">Action</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.items.map((row) => (
              <TableRow key={row.id} className="align-top">
                <TableCell>
                  <span className="text-sm font-medium text-foreground">{row.display_name}</span>
                  <p className="mt-0.5 text-xs text-muted-foreground">{row.email}</p>
                </TableCell>

                <TableCell>
                  <div className="flex max-w-[20rem] flex-wrap gap-1">
                    {row.roles.length === 0 ? (
                      <span className="text-sm text-muted-foreground">No role</span>
                    ) : (
                      row.roles.map((role) => (
                        <Badge key={role} variant="muted">
                          {ROLE_LABELS[role as PlatformRole] ?? role}
                        </Badge>
                      ))
                    )}
                  </div>
                </TableCell>

                <TableCell>
                  <Badge variant={row.is_active ? "secondary" : "muted"}>
                    {row.is_active ? "Active" : "Disabled"}
                  </Badge>
                </TableCell>

                <TableCell className="whitespace-nowrap text-sm text-muted-foreground">
                  {row.last_login_at ? formatDateTime(row.last_login_at) : "Never"}
                </TableCell>

                <TableCell className="text-right">
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={!data.identity_provider_configured}
                    title={
                      data.identity_provider_configured
                        ? undefined
                        : "No Keycloak Admin API credential is configured on this deployment."
                    }
                    onClick={() => {
                      setFailure(null);
                      setEditing(row);
                    }}
                  >
                    Edit roles
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      <RoleEditDialog
        user={editing}
        open={editing !== null}
        onOpenChange={(open) => {
          if (!open) {
            setEditing(null);
            setFailure(null);
          }
        }}
        assignableRoles={data.assignable_roles}
        saving={saving}
        failure={failure}
        onSave={save}
      />
    </div>
  );
}
