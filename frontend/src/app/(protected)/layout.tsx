import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import { AppShell } from "@/components/layout/app-shell";
import { fetchCurrentUser } from "@/lib/api-client";
import { getServerAuthSession } from "@/lib/auth";
import { normaliseRoles } from "@/lib/roles";

export default async function ProtectedLayout({ children }: { children: ReactNode }) {
  const session = await getServerAuthSession();

  if (!session) redirect("/signin");
  if (session.error === "RefreshAccessTokenError") redirect("/signin?error=SessionExpired");

  const roles = normaliseRoles(session.user.roles);
  if (roles.length === 0) redirect("/unprovisioned");

  // Treated as already seen if the profile cannot be read. A failed lookup must not put a
  // walkthrough in front of somebody who finished it months ago.
  const onboardingCompleted = session.accessToken
    ? await fetchCurrentUser(session.accessToken)
        .then((profile) => profile.has_completed_onboarding)
        .catch(() => true)
    : true;

  return (
    <AppShell
      roles={roles}
      userName={session.user.name ?? session.user.email ?? "Signed-in user"}
      userEmail={session.user.email ?? ""}
      onboardingCompleted={onboardingCompleted}
    >
      {children}
    </AppShell>
  );
}
