import { FileSpreadsheet } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";

import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { TransactionFilters } from "@/components/transactions/transaction-filters";
import { TransactionTable } from "@/components/transactions/transaction-table";
import { Button } from "@/components/ui/button";
import { ApiError, fetchTransactionList, type TransactionList } from "@/lib/api-client";
import { getServerAuthSession } from "@/lib/auth";
import { normaliseRoles } from "@/lib/roles";
import { canWriteTransactions } from "@/lib/transactions";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Transactions" };

interface SearchParams {
  page?: string;
  search?: string;
  stream?: string;
  status?: string;
  deal_type?: string;
  date_from?: string;
  date_to?: string;
  sort_by?: string;
  sort_dir?: string;
}

export default async function TransactionsPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const session = await getServerAuthSession();
  if (!session?.accessToken) redirect("/signin");

  const params = await searchParams;
  const page = Math.max(1, Number.parseInt(params.page ?? "1", 10) || 1);
  const sortBy = params.sort_by ?? "created_at";
  const sortDir = params.sort_dir === "asc" ? "asc" : "desc";
  const canCreate = canWriteTransactions(normaliseRoles(session.user.roles));

  let list: TransactionList | null = null;
  let failure: string | null = null;

  try {
    list = await fetchTransactionList(session.accessToken, {
      page,
      page_size: 25,
      search: params.search,
      stream: params.stream,
      status: params.status,
      deal_type: params.deal_type,
      // The API takes ISO timestamps; a date input gives a day, so the day is widened to cover it.
      date_from: params.date_from ? `${params.date_from}T00:00:00Z` : undefined,
      date_to: params.date_to ? `${params.date_to}T23:59:59Z` : undefined,
      sort_by: sortBy,
      sort_dir: sortDir,
    });
  } catch (error) {
    failure =
      error instanceof ApiError ? error.message : "The transaction list could not be loaded.";
  }

  const filtered = Boolean(
    params.search ||
      params.stream ||
      params.status ||
      params.deal_type ||
      params.date_from ||
      params.date_to,
  );

  return (
    <div className="space-y-6">
      <PageHeader
        title="Transactions"
        description="Every deal the platform is holding, with the batch it belongs to, the checks it has passed and how long it has been open."
        actions={
          canCreate ? (
            <Button asChild size="sm">
              <Link href="/transactions/new">New transaction</Link>
            </Button>
          ) : undefined
        }
      />

      <TransactionFilters
        search={params.search ?? ""}
        stream={params.stream ?? ""}
        status={params.status ?? ""}
        dealType={params.deal_type ?? ""}
        dateFrom={params.date_from ?? ""}
        dateTo={params.date_to ?? ""}
      />

      {failure ? (
        <EmptyState
          icon={FileSpreadsheet}
          title="The list could not be loaded"
          description={failure}
        />
      ) : list && list.items.length > 0 ? (
        <TransactionTable list={list} sortBy={sortBy} sortDir={sortDir} />
      ) : (
        <EmptyState
          icon={FileSpreadsheet}
          title={filtered ? "Nothing matches those filters" : "No transactions yet"}
          description={
            filtered
              ? "No transaction matches the filters you have applied. Clear them to see everything open."
              : "A transaction appears here as soon as a confirmed purchase document is matched to a batch, or when one is registered by hand."
          }
          action={
            canCreate && !filtered ? (
              <Button asChild size="sm" variant="outline">
                <Link href="/transactions/new">Register a transaction</Link>
              </Button>
            ) : undefined
          }
        />
      )}
    </div>
  );
}
