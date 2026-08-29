import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";

import { UploadWorkspace } from "@/components/intake/upload-workspace";
import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { Button } from "@/components/ui/button";
import { getServerAuthSession } from "@/lib/auth";
import { canCorrect } from "@/lib/intake";
import { normaliseRoles } from "@/lib/roles";
import { ShieldOff } from "lucide-react";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Upload documents" };

export default async function UploadPage() {
  const session = await getServerAuthSession();
  if (!session) redirect("/signin");

  const roles = normaliseRoles(session.user.roles);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Upload documents"
        description="Bring documents in by hand when they did not arrive through the approved mailbox."
        actions={
          <Button asChild variant="outline" size="sm">
            <Link href="/inbox">Back to inbox</Link>
          </Button>
        }
      />

      {canCorrect(roles) ? (
        <UploadWorkspace />
      ) : (
        <EmptyState
          icon={ShieldOff}
          title="Uploading is not part of your role"
          description="Documents are brought in by the purchase, sales, FA, logistics and admin desks. Your role reads the inbox and the documents already captured."
          action={
            <Button asChild size="sm" variant="outline">
              <Link href="/inbox">Go to the inbox</Link>
            </Button>
          }
        />
      )}
    </div>
  );
}
