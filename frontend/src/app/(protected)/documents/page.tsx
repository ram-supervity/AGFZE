import { FileText } from "lucide-react";
import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { DocumentFilters } from "@/components/intake/document-filters";
import { DocumentTable } from "@/components/intake/document-table";
import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { ApiError, fetchDocumentList, type DocumentList } from "@/lib/api-client";
import { getServerAuthSession } from "@/lib/auth";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Documents" };

interface SearchParams {
  page?: string;
  search?: string;
  document_type?: string;
  status?: string;
  date_from?: string;
  date_to?: string;
}

export default async function DocumentsPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const session = await getServerAuthSession();
  if (!session?.accessToken) redirect("/signin");

  const params = await searchParams;
  const page = Math.max(1, Number.parseInt(params.page ?? "1", 10) || 1);

  let list: DocumentList | null = null;
  let failure: string | null = null;

  try {
    list = await fetchDocumentList(session.accessToken, {
      page,
      page_size: 25,
      search: params.search,
      document_type: params.document_type,
      status: params.status,
      // The API takes ISO timestamps; a date input gives a day, so the day is widened to cover it.
      date_from: params.date_from ? `${params.date_from}T00:00:00Z` : undefined,
      date_to: params.date_to ? `${params.date_to}T23:59:59Z` : undefined,
    });
  } catch (error) {
    failure =
      error instanceof ApiError ? error.message : "The document index could not be loaded.";
  }

  const filtered = Boolean(
    params.search || params.document_type || params.status || params.date_from || params.date_to,
  );

  return (
    <div className="space-y-6">
      <PageHeader
        title="Documents"
        description="Every document captured so far, with the type it was classified as and how far extraction has got."
      />

      <DocumentFilters
        search={params.search ?? ""}
        documentType={params.document_type ?? ""}
        status={params.status ?? ""}
        dateFrom={params.date_from ?? ""}
        dateTo={params.date_to ?? ""}
      />

      {failure ? (
        <EmptyState icon={FileText} title="The index could not be loaded" description={failure} />
      ) : list && list.items.length > 0 ? (
        <DocumentTable list={list} />
      ) : (
        <EmptyState
          icon={FileText}
          title={filtered ? "Nothing matches those filters" : "No documents yet"}
          description={
            filtered
              ? "No document matches the filters you have applied. Clear them to see everything captured."
              : "Documents appear here as soon as they arrive on an email or are uploaded through the portal."
          }
        />
      )}
    </div>
  );
}
