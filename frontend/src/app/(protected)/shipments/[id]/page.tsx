import type { Metadata } from "next";
import { notFound, redirect } from "next/navigation";

import { ShipmentWorkspace } from "@/components/shipments/shipment-workspace";
import {
  ApiError,
  fetchShipmentDetail,
  fetchTransactionDetail,
  type DocumentSummary,
} from "@/lib/api-client";
import { getServerAuthSession } from "@/lib/auth";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Shipment" };

export default async function ShipmentDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const session = await getServerAuthSession();
  if (!session?.accessToken) redirect("/signin");

  const { id } = await params;

  let shipment;
  try {
    shipment = await fetchShipmentDetail(session.accessToken, id);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  }

  // The linked transaction's documents, so an issue can name the survey report or the photographs
  // it was raised from. A shipment with no transaction, or an unreadable one, is a normal state.
  let documents: DocumentSummary[] = [];
  if (shipment.transaction) {
    try {
      const transaction = await fetchTransactionDetail(
        session.accessToken,
        shipment.transaction.id,
      );
      documents = transaction.documents;
    } catch {
      documents = [];
    }
  }

  return <ShipmentWorkspace initial={shipment} documents={documents} />;
}
