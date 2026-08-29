import { Ship } from "lucide-react";
import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { ShipmentDashboard } from "@/components/shipments/shipment-dashboard";
import { ApiError, fetchShipmentList, type ShipmentList } from "@/lib/api-client";
import { getServerAuthSession } from "@/lib/auth";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Shipments" };

interface SearchParams {
  page?: string;
  search?: string;
  status?: string;
  carrier?: string;
  port_of_discharge?: string;
  stale_only?: string;
}

export default async function ShipmentsPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const session = await getServerAuthSession();
  if (!session?.accessToken) redirect("/signin");

  const params = await searchParams;
  const page = Math.max(1, Number.parseInt(params.page ?? "1", 10) || 1);
  const staleOnly = params.stale_only === "true";

  let list: ShipmentList | null = null;
  let failure: string | null = null;

  try {
    list = await fetchShipmentList(session.accessToken, {
      page,
      page_size: 25,
      search: params.search,
      status: params.status,
      carrier: params.carrier,
      port_of_discharge: params.port_of_discharge,
      stale_only: staleOnly || undefined,
    });
  } catch (error) {
    failure = error instanceof ApiError ? error.message : "The shipment board could not be loaded.";
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Shipments"
        description="Where each batch's cargo physically is, and when anybody last established that - whether a carrier reported it or somebody typed it in."
      />

      {failure || !list ? (
        <EmptyState
          icon={Ship}
          title="The shipment board could not be loaded"
          description={failure ?? "The shipment board could not be loaded."}
        />
      ) : (
        <ShipmentDashboard
          list={list}
          filters={{
            search: params.search ?? "",
            status: params.status ?? "",
            carrier: params.carrier ?? "",
            portOfDischarge: params.port_of_discharge ?? "",
            staleOnly,
          }}
        />
      )}
    </div>
  );
}
