import { SlidersHorizontal } from "lucide-react";
import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { RulesTable } from "@/components/admin/rules-table";
import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { ApiError, fetchRuleConfigurations, type RuleConfigurationList } from "@/lib/api-client";
import { getServerAuthSession } from "@/lib/auth";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Rules & thresholds" };

interface SearchParams {
  rule_id?: string;
  stream?: string;
}

/**
 * Every configurable threshold in the platform, editable with a stated reason.
 *
 * Not one tolerance or limit is written in application code: every evaluator asks
 * `rule_configurations` for the value it compares against. This is the screen that finally makes
 * that promise usable - a tolerance moves here, with a reason on the audit trail, and no release.
 */
export default async function RulesPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const session = await getServerAuthSession();
  if (!session?.accessToken) redirect("/signin");

  const params = await searchParams;

  let data: RuleConfigurationList | null = null;
  let failure: string | null = null;
  let forbidden = false;

  try {
    data = await fetchRuleConfigurations(session.accessToken, {
      rule_id: params.rule_id,
      stream: params.stream,
    });
  } catch (error) {
    forbidden = error instanceof ApiError && error.status === 403;
    failure = error instanceof ApiError ? error.message : "The thresholds could not be loaded.";
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Rules & thresholds"
        description="Every tolerance, limit and threshold the rule engine compares against, whichever module first seeded it. A change takes effect on the next evaluation; decisions already made keep the value that was live at the time."
      />

      {failure || !data ? (
        <EmptyState
          icon={SlidersHorizontal}
          title={forbidden ? "This screen is for administrators" : "The thresholds could not be loaded"}
          description={
            forbidden
              ? "Business configuration is changed by an administrator. The value a rule applied to your transaction is shown on its own validation panel."
              : (failure ?? "No configuration came back from the API.")
          }
        />
      ) : (
        <RulesTable
          data={data}
          filters={{ ruleId: params.rule_id ?? "", stream: params.stream ?? "" }}
        />
      )}
    </div>
  );
}
