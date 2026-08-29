import { ShieldOff } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";

import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { NewTransactionTabs } from "@/components/transactions/new-transaction-tabs";
import { Button } from "@/components/ui/button";
import {
  fetchCommodityCodes,
  fetchFaFieldSchema,
  type CommodityCode,
  type FaFieldSchema,
} from "@/lib/api-client";
import { getServerAuthSession } from "@/lib/auth";
import { normaliseRoles } from "@/lib/roles";
import { canWriteFa, canWriteSales, canWriteTransactions } from "@/lib/transactions";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "New transaction" };

export default async function NewTransactionPage() {
  const session = await getServerAuthSession();
  if (!session?.accessToken) redirect("/signin");

  const roles = normaliseRoles(session.user.roles);
  const canRegisterPurchase = canWriteTransactions(roles);
  const canAttachSales = canWriteSales(roles);
  const canRegisterFa = canWriteFa(roles);
  const allowed = canRegisterPurchase || canAttachSales || canRegisterFa;

  let commodities: CommodityCode[] = [];
  let faFieldSchema: FaFieldSchema[] = [];
  if (allowed) {
    try {
      commodities = await fetchCommodityCodes(session.accessToken);
    } catch {
      // The grade can be left unset and corrected in the workspace; an unreachable reference
      // list is not a reason to refuse the registration.
      commodities = [];
    }
  }
  if (canRegisterFa) {
    try {
      faFieldSchema = await fetchFaFieldSchema(session.accessToken);
    } catch {
      // The named fields are enough to open an FA transaction; the configured extras can be
      // filled in on the workspace afterwards.
      faFieldSchema = [];
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Register a transaction"
        description="For a deal that never arrived by email. A purchase opens a new batch, a sale attaches to the batch that cargo was already bought as, and an FA transaction opens its own record on the second business line."
        actions={
          <Button asChild variant="outline" size="sm">
            <Link href="/transactions">Back to transactions</Link>
          </Button>
        }
      />

      {allowed ? (
        <NewTransactionTabs
          commodities={commodities}
          faFieldSchema={faFieldSchema}
          canRegisterPurchase={canRegisterPurchase}
          canAttachSales={canAttachSales}
          canRegisterFa={canRegisterFa}
        />
      ) : (
        <EmptyState
          icon={ShieldOff}
          title="Registering a transaction is not part of your role"
          description="Deals are raised by the desk that owns them - purchase by the buying desk, sales by the selling desk, FA by the FA desk - and by an administrator. Your role reads the transactions the desks have opened."
          action={
            <Button asChild size="sm" variant="outline">
              <Link href="/transactions">Go to the transaction list</Link>
            </Button>
          }
        />
      )}
    </div>
  );
}
