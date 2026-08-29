import { Users } from "lucide-react";
import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { UsersTable } from "@/components/admin/users-table";
import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { ApiError, fetchAdminUsers, type AdminUserList } from "@/lib/api-client";
import { getServerAuthSession } from "@/lib/auth";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Users & roles" };

interface SearchParams {
  search?: string;
}

/**
 * The account list, and the manual exception to group-based role mapping.
 *
 * Roles normally arrive with the token, mapped from Entra ID groups, and that is how they should
 * arrive. The override here is for the case AGFZE actually asked for: somebody whose group
 * membership is wrong, or has not propagated, who needs their role corrected today.
 */
export default async function UsersPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const session = await getServerAuthSession();
  if (!session?.accessToken) redirect("/signin");

  const params = await searchParams;

  let data: AdminUserList | null = null;
  let failure: string | null = null;
  let forbidden = false;

  try {
    data = await fetchAdminUsers(session.accessToken, { search: params.search });
  } catch (error) {
    forbidden = error instanceof ApiError && error.status === 403;
    failure = error instanceof ApiError ? error.message : "The account list could not be loaded.";
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Users & roles"
        description="Every account mirrored from the identity provider, and the roles it holds. A role change is written to Keycloak first and mirrored here only once Keycloak confirms it."
      />

      {failure || !data ? (
        <EmptyState
          icon={Users}
          title={forbidden ? "This screen is for administrators" : "The account list could not be loaded"}
          description={
            forbidden
              ? "Role assignment is an administrator's. Your own roles are shown on your settings page."
              : (failure ?? "No accounts came back from the API.")
          }
        />
      ) : (
        <UsersTable data={data} search={params.search ?? ""} />
      )}
    </div>
  );
}
