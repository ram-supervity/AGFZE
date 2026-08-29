import { FileStack } from "lucide-react";
import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { DocumentTypesTable } from "@/components/admin/document-types-table";
import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import {
  ApiError,
  fetchDocumentTypeSchemas,
  type DocumentTypeSchemaList,
} from "@/lib/api-client";
import { getServerAuthSession } from "@/lib/auth";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Document types" };

interface SearchParams {
  document_type?: string;
}

/**
 * The field list every extraction is built from, and each territory's mandatory-document pack.
 *
 * No service in this platform carries a hardcoded field list. Adding a field, or a whole document
 * type's worth of them, has always been a row change rather than a code change; this is where
 * that row change is finally made by a person rather than by a migration.
 */
export default async function DocumentTypesPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const session = await getServerAuthSession();
  if (!session?.accessToken) redirect("/signin");

  const params = await searchParams;

  let data: DocumentTypeSchemaList | null = null;
  let failure: string | null = null;
  let forbidden = false;

  try {
    data = await fetchDocumentTypeSchemas(session.accessToken, {
      document_type: params.document_type,
    });
  } catch (error) {
    forbidden = error instanceof ApiError && error.status === 403;
    failure = error instanceof ApiError ? error.message : "The schemas could not be loaded.";
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Document types"
        description="What the extraction reads out of each kind of document, and what each territory's pack must contain. Documents already extracted keep whatever they were read with."
      />

      {failure || !data ? (
        <EmptyState
          icon={FileStack}
          title={forbidden ? "This screen is for administrators" : "The schemas could not be loaded"}
          description={
            forbidden
              ? "Document schemas are maintained by an administrator. The fields read from a particular document are shown on its own review screen."
              : (failure ?? "No schemas came back from the API.")
          }
        />
      ) : (
        <DocumentTypesTable data={data} />
      )}
    </div>
  );
}
