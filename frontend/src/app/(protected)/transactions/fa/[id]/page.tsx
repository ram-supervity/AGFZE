import type { Metadata } from "next";
import { notFound, redirect } from "next/navigation";

import { FaWorkspace } from "@/components/transactions/fa-workspace";
import {
  ApiError,
  fetchCommodityCodes,
  fetchDocumentDetail,
  fetchTransactionDetail,
  type CommodityCode,
  type DocumentDetail,
} from "@/lib/api-client";
import { getServerAuthSession } from "@/lib/auth";
import { normaliseRoles } from "@/lib/roles";
import { canWriteFa } from "@/lib/transactions";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "FA transaction" };

export default async function FaTransactionPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const session = await getServerAuthSession();
  if (!session?.accessToken) redirect("/signin");

  const { id } = await params;

  let detail;
  try {
    detail = await fetchTransactionDetail(session.accessToken, id);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  }

  // A transaction with no FA leg has no FA side to work, so it belongs in the workspace of
  // whichever desk does carry it. This keeps every existing link into a transaction correct
  // without each of them having to know which stream it is on.
  if (!detail.fa_leg) {
    redirect(
      detail.sales_leg ? `/transactions/sales/${id}` : `/transactions/purchase/${id}`,
    );
  }

  let firstDocument: DocumentDetail | null = null;
  if (detail.documents.length > 0) {
    try {
      firstDocument = await fetchDocumentDetail(session.accessToken, detail.documents[0].id);
    } catch {
      firstDocument = null;
    }
  }

  let commodities: CommodityCode[] = [];
  try {
    commodities = await fetchCommodityCodes(session.accessToken);
  } catch {
    commodities = [];
  }

  return (
    <FaWorkspace
      initial={detail}
      initialDocument={firstDocument}
      commodities={commodities}
      canEdit={canWriteFa(normaliseRoles(session.user.roles))}
    />
  );
}
