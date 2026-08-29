import type { Metadata } from "next";
import { notFound, redirect } from "next/navigation";

import { ApprovalDecisionScreen } from "@/components/approvals/approval-decision";
import { ApiError, fetchApprovalDetail, fetchApprovalQueue } from "@/lib/api-client";
import { getServerAuthSession } from "@/lib/auth";
import { canDecideApprovals } from "@/lib/governance";
import { normaliseRoles } from "@/lib/roles";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Approval" };

export default async function ApprovalDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const session = await getServerAuthSession();
  if (!session?.accessToken) redirect("/signin");

  const { id } = await params;

  let detail;
  try {
    detail = await fetchApprovalDetail(session.accessToken, id);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  }

  // The configured overdue threshold, read from the queue rather than restated here, so the age
  // badge on this screen and the one in the queue mean the same thing.
  let overdueThresholdHours = 0;
  try {
    overdueThresholdHours = (
      await fetchApprovalQueue(session.accessToken, { page: 1, page_size: 1 })
    ).overdue_threshold_hours;
  } catch {
    overdueThresholdHours = 0;
  }

  return (
    <ApprovalDecisionScreen
      initial={detail}
      canDecide={canDecideApprovals(normaliseRoles(session.user.roles))}
      overdueThresholdHours={overdueThresholdHours}
    />
  );
}
