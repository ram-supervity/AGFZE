import type { Metadata } from "next";
import { notFound, redirect } from "next/navigation";

import { SalesWorkspace } from "@/components/transactions/sales-workspace";
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
import { canWriteSales } from "@/lib/transactions";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Sales transaction" };

export default async function SalesTransactionPage({
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

  // A transaction with no sales leg has no sell side to work, so it belongs in the purchase
  // workspace rather than in an empty version of this one.
  if (!detail.sales_leg) redirect(`/transactions/purchase/${id}`);

  // The first linked source document, so the viewer has real pages on the first paint. A
  // generated draft is skipped here: it is a Word file with no page images, and it is opened
  // from the draft panel instead.
  let firstDocument: DocumentDetail | null = null;
  const viewable = detail.documents.find(
    (row) => row.document_type !== "draft_contract" && row.document_type !== "draft_invoice",
  );
  if (viewable) {
    try {
      firstDocument = await fetchDocumentDetail(session.accessToken, viewable.id);
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
    <SalesWorkspace
      initial={detail}
      initialDocument={firstDocument}
      commodities={commodities}
      canEdit={canWriteSales(normaliseRoles(session.user.roles))}
    />
  );
}
