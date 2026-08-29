import { LayoutDashboard } from "lucide-react";
import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { DashboardView } from "@/components/dashboard/dashboard-view";
import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { Badge } from "@/components/ui/badge";
import {
  ApiError,
  fetchCurrentUser,
  fetchDashboardSummary,
  type DashboardSummary,
  type UserProfile,
} from "@/lib/api-client";
import { getServerAuthSession } from "@/lib/auth";
import { normaliseRoles, ROLE_LABELS } from "@/lib/roles";

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "Dashboard" };

interface SearchParams {
  stream?: string;
}

/**
 * The home screen, with real content for the first time.
 *
 * It has been a real, clickable route since the platform's first  and has shown no metric of
 * any kind until now, because until now there was nothing genuine to count. Everything on it is
 * queried from the transaction records, scoped to this account's roles inside those queries, and
 * clickable through to the rows behind it.
 */
export default async function DashboardPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const session = await getServerAuthSession();
  if (!session?.accessToken) redirect("/signin");

  const params = await searchParams;
  const stream = params.stream === "scrap" || params.stream === "fa" ? params.stream : "";

  let profile: UserProfile | null = null;
  let summary: DashboardSummary | null = null;
  let failure: string | null = null;

  try {
    [profile, summary] = await Promise.all([
      fetchCurrentUser(session.accessToken),
      fetchDashboardSummary(session.accessToken, { stream: stream || undefined }),
    ]);
  } catch (error) {
    failure =
      error instanceof ApiError ? error.message : "The dashboard figures could not be loaded.";
  }

  const roles = normaliseRoles(profile ? profile.roles : session.user.roles);
  const displayName = profile?.display_name ?? session.user.name ?? "Your account";

  return (
    <div className="space-y-6">
      <PageHeader
        title="Dashboard"
        description={`Where AGFZE's trading stands right now — what is open, what is stuck, and how much of it ran without anybody having to  in. Signed in as ${displayName}.`}
        actions={
          <div className="flex flex-wrap justify-end gap-1.5">
            {roles.map((role) => (
              <Badge key={role} variant="secondary">
                {ROLE_LABELS[role]}
              </Badge>
            ))}
          </div>
        }
      />

      {failure || !summary ? (
        <EmptyState
          icon={LayoutDashboard}
          title="The dashboard could not be loaded"
          description={
            failure ??
            "No figures came back from the API. Nothing is shown rather than a number nobody can vouch for."
          }
        />
      ) : (
        <DashboardView summary={summary} stream={stream} />
      )}
    </div>
  );
}
