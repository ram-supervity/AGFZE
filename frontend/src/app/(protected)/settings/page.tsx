import { UserCog } from "lucide-react";
import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { SettingsForm } from "@/components/settings/settings-form";
import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { ApiError, fetchCurrentUser, type UserProfile } from "@/lib/api-client";
import { getServerAuthSession } from "@/lib/auth";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Settings" };

/**
 * Your own settings, and structurally only your own.
 *
 * The profile is read from `GET /users/me` and written through `PATCH /users/me/preferences` —
 * the endpoint declared in  and deliberately left unbuilt until there was a page to pair it
 * with. Neither takes an account identifier, so there is nothing here that could address another
 * user even if a request tried to.
 */
export default async function SettingsPage() {
  const session = await getServerAuthSession();
  if (!session?.accessToken) redirect("/signin");

  let profile: UserProfile | null = null;
  let failure: string | null = null;

  try {
    profile = await fetchCurrentUser(session.accessToken);
  } catch (error) {
    failure = error instanceof ApiError ? error.message : "Your profile could not be loaded.";
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Settings"
        description="Your profile as the identity provider asserts it, and how you would like the platform to reach you."
      />

      {failure || !profile ? (
        <EmptyState
          icon={UserCog}
          title="Your settings could not be loaded"
          description={failure ?? "No profile came back from the API."}
        />
      ) : (
        <SettingsForm profile={profile} />
      )}
    </div>
  );
}
