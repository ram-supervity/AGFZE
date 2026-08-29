import type { Metadata } from "next";
import { notFound, redirect } from "next/navigation";

import { ExceptionWorkspace } from "@/components/exceptions/exception-workspace";
import {
  ApiError,
  fetchCommodityCodes,
  fetchExceptionCase,
  fetchTransactionDetail,
  type CommodityCode,
  type TransactionField,
} from "@/lib/api-client";
import { getServerAuthSession } from "@/lib/auth";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Exception" };

export default async function ExceptionDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const session = await getServerAuthSession();
  if (!session?.accessToken) redirect("/signin");

  const { id } = await params;

  let detail;
  try {
    detail = await fetchExceptionCase(session.accessToken, id);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  }

  // The transaction's own editable fields, so the inline correction offers exactly the fields the
  // purchase workspace does - and the same reason gate on each of them. A case with no
  // transaction behind it simply has nothing to correct here, which is a normal state.
  let fields: TransactionField[] = [];
  let commodities: CommodityCode[] = [];
  if (detail.transaction_id) {
    try {
      const transaction = await fetchTransactionDetail(session.accessToken, detail.transaction_id);
      fields = transaction.fields;
      commodities = await fetchCommodityCodes(session.accessToken);
    } catch {
      fields = [];
    }
  }

  return <ExceptionWorkspace initial={detail} fields={fields} commodities={commodities} />;
}
