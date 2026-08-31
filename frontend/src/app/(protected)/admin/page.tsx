import { ArrowRight } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";

import { PageHeader } from "@/components/shared/page-header";
import { ADMIN_AREAS } from "@/lib/admin";
import { getServerAuthSession } from "@/lib/auth";
import { hasAnyRole, normaliseRoles } from "@/lib/roles";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Admin" };

/**
 * The administration landing page.
 *
 * It lists exactly the areas that exist. Two other things this platform stores are configuration
 * in the technical sense and deliberately have no screen anywhere: the tracker/SAP/DMS endpoints
 * stay environment-only because changing where an approved deal is posted should require a
 * deployment, and the rule-to-exception-category mapping stays seed data. Neither appears here.
 */
export default async function AdminPage() {
  const session = await getServerAuthSession();
  if (!session?.accessToken) redirect("/signin");

  const roles = normaliseRoles(session.user.roles);
  const isAdmin = hasAnyRole(roles, ["admin"]);
  // An Auditor reaches this section for the trail and nothing else, which is the whole of what
  // independent oversight needs and the whole of what the API will give them.
  const areas = ADMIN_AREAS.filter((area) => isAdmin || area.key === "audit");

  return (
    <div className="space-y-6">
      <PageHeader
        title="Admin"
        description="Role assignment, the thresholds the rule engine reads, the document schemas extraction is built from, and the append-only audit trail. Everything here was migration-only until now."
      />

      <ul className="grid gap-3 sm:grid-cols-2">
        {areas.map((area) => (
          <li key={area.key}>
            <Link
              href={area.href}
              className="flex h-full flex-col rounded-medium border-thin border-border bg-elevation-default p-space-200 shadow-raised transition-colors hover:border-secondary/45 focus-visible:outline-none focus-visible:ring-thick focus-visible:ring-ring"
            >
              <span className="flex items-center gap-2 text-sm font-semibold text-foreground">
                {area.label}
                <ArrowRight className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
              </span>
              <span className="mt-1.5 text-sm leading-relaxed text-muted-foreground">
                {area.summary}
              </span>
            </Link>
          </li>
        ))}
      </ul>

      <p className="rounded-medium border-thin border-border bg-elevation-sunken px-4 py-3 text-sm leading-relaxed text-muted-foreground">
        The tracker, SAP and document-store endpoints are not edited here. They are infrastructure
        configuration, set per deployment through the environment, so changing where an approved
        transaction is posted goes through a release rather than a form.
      </p>
    </div>
  );
}
