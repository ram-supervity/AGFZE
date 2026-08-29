"use client";

import { FileStack } from "lucide-react";
import { useRouter } from "next/navigation";
import { useSession } from "next-auth/react";
import { useState } from "react";
import toast from "react-hot-toast";

import { DocumentTypeDialog } from "@/components/admin/document-type-dialog";
import { EmptyState } from "@/components/shared/empty-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { documentTypeLabel, territoryLabel } from "@/lib/admin";
import {
  ApiError,
  updateDocumentTypeSchema,
  type DocumentSchemaField,
  type DocumentTypeSchemaList,
  type DocumentTypeSchemaRow,
} from "@/lib/api-client";
import { formatDateTime } from "@/lib/utils";

export interface DocumentTypesTableProps {
  data: DocumentTypeSchemaList;
}

/**
 * Every document type's schema, whichever step first seeded it.
 *
 * The invoice and contract schemas shipped with intake, the bill of lading came with the sales
 * module and `fa_document` with the FA module. All three render and edit identically here, with
 * nothing in this component that knows which is which.
 */
export function DocumentTypesTable({ data }: DocumentTypesTableProps) {
  const router = useRouter();
  const { data: session } = useSession();
  const [editing, setEditing] = useState<DocumentTypeSchemaRow | null>(null);
  const [saving, setSaving] = useState(false);

  async function save(body: {
    change_reason: string;
    field_schema: { fields: DocumentSchemaField[] };
    mandatory_documents: string[];
  }) {
    const token = session?.accessToken;
    if (!token || !editing) {
      toast.error("Your session has expired. Sign in again to make this change.");
      return;
    }
    setSaving(true);
    try {
      await updateDocumentTypeSchema(token, editing.id, body);
      toast.success(`The ${documentTypeLabel(editing.document_type).toLowerCase()} schema is updated.`);
      setEditing(null);
      router.refresh();
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "The schema could not be changed.");
    } finally {
      setSaving(false);
    }
  }

  if (data.items.length === 0) {
    return (
      <EmptyState
        icon={FileStack}
        title="No document schemas yet"
        description="Every document type this platform reads is configured here, seeded by the migrations that introduced it."
      />
    );
  }

  return (
    <div className="space-y-4">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Document type</TableHead>
            <TableHead>Territory</TableHead>
            <TableHead className="text-right">Fields</TableHead>
            <TableHead>Mandatory pack</TableHead>
            <TableHead>Last changed</TableHead>
            <TableHead className="text-right">Action</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {data.items.map((row) => (
            <TableRow key={row.id} className="align-top">
              <TableCell className="text-sm font-medium text-foreground">
                {documentTypeLabel(row.document_type)}
              </TableCell>

              <TableCell className="text-sm text-muted-foreground">
                {territoryLabel(row.territory)}
              </TableCell>

              <TableCell className="whitespace-nowrap text-right text-sm text-foreground">
                {row.field_count}
                <p className="mt-0.5 text-xs text-muted-foreground">
                  {row.required_field_count} required
                </p>
              </TableCell>

              <TableCell>
                {row.mandatory_documents.length === 0 ? (
                  <span className="text-sm text-muted-foreground">Nothing required</span>
                ) : (
                  <div className="flex max-w-[18rem] flex-wrap gap-1">
                    {row.mandatory_documents.map((type) => (
                      <Badge key={type} variant="muted">
                        {documentTypeLabel(type)}
                      </Badge>
                    ))}
                  </div>
                )}
              </TableCell>

              <TableCell className="text-sm text-muted-foreground">
                {formatDateTime(row.changed_at)}
                <p className="mt-0.5 text-xs">
                  {row.changed_by_name ?? "Seeded with the platform"}
                </p>
                <p className="mt-0.5 max-w-[20rem] text-xs italic" title={row.change_reason}>
                  “{row.change_reason}”
                </p>
              </TableCell>

              <TableCell className="text-right">
                <Button size="sm" variant="outline" onClick={() => setEditing(row)}>
                  Edit
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      <DocumentTypeDialog
        row={editing}
        open={editing !== null}
        onOpenChange={(open) => (open ? null : setEditing(null))}
        documentTypes={data.document_types}
        saving={saving}
        onSave={save}
      />
    </div>
  );
}
