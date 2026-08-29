import type { Metadata } from "next";
import { notFound, redirect } from "next/navigation";

import { PurchaseWorkspace } from "@/components/transactions/purchase-workspace";
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
import { canWriteTransactions } from "@/lib/transactions";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Purchase transaction" };

export default async function PurchaseTransactionPage({
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

  // A transaction with no purchase leg has no buy side to work, so it belongs in the sales
  // workspace. This keeps every existing link into `/transactions/purchase/{id}` - from the
  // exception queue, the approval screen, the document index - correct without each of them
  // having to know which desk owns the transaction it is pointing at.
  if (!detail.purchase_leg && detail.sales_leg) redirect(`/transactions/sales/${id}`);

  // The first linked document is loaded here so the viewer has real pages on the first paint.
  // A transaction with none is a normal state, not a failure.
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
    <PurchaseWorkspace
      initial={detail}
      initialDocument={firstDocument}
      commodities={commodities}
      canEdit={canWriteTransactions(normaliseRoles(session.user.roles))}
    />
  );
}
