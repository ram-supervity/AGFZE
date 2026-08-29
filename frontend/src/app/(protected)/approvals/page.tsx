import { ShieldCheck } from "lucide-react";
import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { ApprovalTable } from "@/components/approvals/approval-table";
import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { ApiError, fetchApprovalQueue, type ApprovalQueue } from "@/lib/api-client";
import { getServerAuthSession } from "@/lib/auth";
import { canDecideApprovals } from "@/lib/governance";
import { normaliseRoles } from "@/lib/roles";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Approvals" };

interface SearchParams {
  page?: string;
  rank_by?: string;
  decision?: string;
}

export default async function ApprovalsPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const session = await getServerAuthSession();
  if (!session?.accessToken) redirect("/signin");

  const params = await searchParams;
  const page = Math.max(1, Number.parseInt(params.page ?? "1", 10) || 1);
  const rankBy = ["age", "value", "risk"].includes(params.rank_by ?? "")
    ? (params.rank_by as string)
    : "age";
  const decision = params.decision ?? "pending";

  let queue: ApprovalQueue | null = null;
  let failure: string | null = null;

  try {
    queue = await fetchApprovalQueue(session.accessToken, {
      page,
      page_size: 25,
      rank_by: rankBy,
      decision,
    });
  } catch (error) {
    failure =
      error instanceof ApiError ? error.message : "The approval queue could not be loaded.";
  }

  // The server also decides this, and refuses the write regardless; this only chooses what the
  // screen bothers to render.
  const canDecide = canDecideApprovals(normaliseRoles(session.user.roles));

  return (
    <div className="space-y-6">
      <PageHeader
        title="Approvals"
        description="Every transaction that has passed its checks and is now waiting on a departmental decision."
      />

      {failure || !queue ? (
        <EmptyState
          icon={ShieldCheck}
          title="The queue could not be loaded"
          description={failure ?? "No approval data came back from the API."}
        />
      ) : queue.items.length > 0 ? (
        <ApprovalTable queue={queue} canDecide={canDecide && queue.can_decide} />
      ) : (
        <EmptyState
          icon={ShieldCheck}
          title="Nothing is waiting on a decision"
          description="A transaction appears here the moment the desk that raised it submits it with every applicable check passing."
        />
      )}
    </div>
  );
}
