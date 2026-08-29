import { TriangleAlert } from "lucide-react";
import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { CategoryTabs } from "@/components/exceptions/category-tabs";
import { ExceptionFilters } from "@/components/exceptions/exception-filters";
import { ExceptionTable } from "@/components/exceptions/exception-table";
import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { ApiError, fetchExceptionQueue, type ExceptionQueue } from "@/lib/api-client";
import { getServerAuthSession } from "@/lib/auth";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Exceptions" };

interface SearchParams {
  page?: string;
  exception_type?: string;
  owner_role?: string;
  status?: string;
  min_age_hours?: string;
}

export default async function ExceptionsPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const session = await getServerAuthSession();
  if (!session?.accessToken) redirect("/signin");

  const params = await searchParams;
  const page = Math.max(1, Number.parseInt(params.page ?? "1", 10) || 1);
  const status = params.status ?? "open";
  const category = params.exception_type ?? "";

  let queue: ExceptionQueue | null = null;
  let failure: string | null = null;

  try {
    queue = await fetchExceptionQueue(session.accessToken, {
      page,
      page_size: 25,
      exception_type: category,
      owner_role: params.owner_role,
      status,
      min_age_hours: params.min_age_hours,
    });
  } catch (error) {
    failure =
      error instanceof ApiError ? error.message : "The exception queue could not be loaded.";
  }

  const selected = queue?.categories.find((row) => row.category === category) ?? null;
  const filtered = Boolean(params.owner_role || params.min_age_hours || status !== "open");

  return (
    <div className="space-y-6">
      <PageHeader
        title="Exceptions"
        description="Everything the platform could not settle on its own, owned by the desk that has to act on it and ageing until somebody does."
      />

      {failure || !queue ? (
        <EmptyState
          icon={TriangleAlert}
          title="The queue could not be loaded"
          description={failure ?? "No exception data came back from the API."}
        />
      ) : (
        <>
          <CategoryTabs
            categories={queue.categories}
            active={category}
            total={queue.categories.reduce((sum, row) => sum + row.open_count, 0)}
          />

          {selected ? (
            <p className="text-sm leading-relaxed text-muted-foreground">
              {selected.description}
            </p>
          ) : null}

          <ExceptionFilters
            ownerRole={params.owner_role ?? ""}
            status={status}
            minAgeHours={params.min_age_hours ?? ""}
            thresholdHours={queue.ageing_threshold_hours}
          />

          {queue.items.length > 0 ? (
            <ExceptionTable queue={queue} />
          ) : (
            <EmptyState
              icon={TriangleAlert}
              title={filtered ? "Nothing matches those filters" : "No exceptions here — nice work"}
              description={
                filtered
                  ? "No case matches the filters you have applied. Clear them to see everything open."
                  : selected
                    ? // The same wording either way, on purpose: a category that is genuinely
                      // empty and one that nothing can fill yet both mean "there is no work
                      // here", and dressing either of them up would be a claim about the other.
                      `Nothing is outstanding under ${selected.label.toLowerCase()}. ${selected.dormant_reason ?? ""}`.trim()
                    : "Nothing is outstanding across any category. A case appears here the moment a check hard-fails or a document is read below the confidence threshold."
              }
            />
          )}
        </>
      )}
    </div>
  );
}
