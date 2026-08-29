import type { Metadata } from "next";
import { notFound, redirect } from "next/navigation";

import { DocumentReview } from "@/components/intake/document-review";
import {
  ApiError,
  fetchDocumentDetail,
  fetchDocumentMatch,
  type MatchOutcome,
} from "@/lib/api-client";
import { getServerAuthSession } from "@/lib/auth";
import { canCorrect } from "@/lib/intake";
import { normaliseRoles } from "@/lib/roles";
import { canWriteTransactions } from "@/lib/transactions";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Document review" };

export default async function DocumentReviewPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const session = await getServerAuthSession();
  if (!session?.accessToken) redirect("/signin");

  const { id } = await params;

  let detail;
  try {
    detail = await fetchDocumentDetail(session.accessToken, id);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  }

  // The matching position is re-derived rather than stored, so a reload shows exactly what the
  // server would do. Only a confirmed document has one at all.
  let match: MatchOutcome | null = null;
  if (detail.confirmed_at) {
    try {
      match = await fetchDocumentMatch(session.accessToken, id);
    } catch {
      match = null;
    }
  }

  const roles = normaliseRoles(session.user.roles);

  return (
    <DocumentReview
      initial={detail}
      canCorrect={canCorrect(roles)}
      canMatch={canWriteTransactions(roles)}
      initialMatch={match}
    />
  );
}
