"use client";

import { Check, Search, TriangleAlert } from "lucide-react";
import { useRouter } from "next/navigation";
import { useSession } from "next-auth/react";
import { useState } from "react";
import toast from "react-hot-toast";

import { AiDisclaimer } from "@/components/shared/ai-disclaimer";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  ApiError,
  attachSalesLeg,
  fetchTransactionList,
  type SalesLegCreate,
  type TransactionListItem,
} from "@/lib/api-client";
import {
  PAYMENT_CONDITIONS,
  PAYMENT_CONDITION_LABELS,
  TERRITORIES,
  TERRITORY_LABELS,
  deskLabel,
  formatQuantity,
} from "@/lib/transactions";
import { cn } from "@/lib/utils";

interface FormState {
  customer_name: string;
  territory: string;
  sales_contract_no: string;
  contracted_quantity_mt: string;
  sales_invoice_number: string;
  payment_condition: string;
  bl_reference: string;
  port_of_discharge: string;
  inland_container_depot: string;
}

const EMPTY: FormState = {
  customer_name: "",
  territory: "india",
  sales_contract_no: "",
  contracted_quantity_mt: "",
  sales_invoice_number: "",
  payment_condition: "CAD",
  bl_reference: "",
  port_of_discharge: "",
  inland_container_depot: "",
};

function trimmed(value: string): string | null {
  const cleaned = value.trim();
  return cleaned === "" ? null : cleaned;
}

/**
 * Attach the sell side of a deal to the batch it belongs to.
 *
 * The batch comes first, and it is not optional. A sale is almost always of cargo AGFZE has
 * already bought, so this screen makes the user search for and select that purchase transaction
 * before it will take a single commercial term. Nothing on this page can create a transaction:
 * the sales leg is attached to one that already exists, which is what keeps the platform free of
 * two records for one physical cargo and therefore free of any need to merge them.
 *
 * A batch with no purchase leg can still be chosen - that genuine exceptional case is real - but
 * only behind the explicit acknowledgement below, which goes to the server and onto the audit
 * trail. There is no silent default.
 */
export function NewSalesLegForm() {
  const router = useRouter();
  const { data: session } = useSession();

  const [query, setQuery] = useState("");
  const [results, setResults] = useState<TransactionListItem[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [selected, setSelected] = useState<TransactionListItem | null>(null);
  const [acknowledged, setAcknowledged] = useState(false);
  const [note, setNote] = useState("");
  const [form, setForm] = useState<FormState>(EMPTY);
  const [saving, setSaving] = useState(false);

  const needsAcknowledgement = Boolean(selected && !selected.has_purchase_leg);
  const ready =
    selected !== null &&
    form.customer_name.trim().length >= 2 &&
    form.sales_contract_no.trim().length > 0 &&
    (!needsAcknowledgement || acknowledged);

  function set(key: keyof FormState) {
    return (value: string) => setForm((current) => ({ ...current, [key]: value }));
  }

  async function search() {
    if (!session?.accessToken) {
      toast.error("Your session has expired. Sign in again to search for a batch.");
      return;
    }
    setSearching(true);
    try {
      const list = await fetchTransactionList(session.accessToken, {
        search: query.trim() || undefined,
        page_size: 15,
      });
      // A batch that already carries a sales leg has already been sold, so offering it would be
      // offering a conflict rather than a match.
      setResults(list.items.filter((row) => !row.has_sales_leg));
    } catch (error) {
      toast.error(
        error instanceof ApiError ? error.message : "The batch search could not be run.",
      );
    } finally {
      setSearching(false);
    }
  }

  async function submit() {
    if (!session?.accessToken || selected === null) return;

    setSaving(true);
    try {
      const body: SalesLegCreate = {
        customer_name: form.customer_name.trim(),
        territory: form.territory,
        sales_contract_no: form.sales_contract_no.trim(),
        payment_condition: form.payment_condition,
        contracted_quantity_mt: trimmed(form.contracted_quantity_mt),
        sales_invoice_number: trimmed(form.sales_invoice_number),
        bl_reference: trimmed(form.bl_reference),
        port_of_discharge: trimmed(form.port_of_discharge),
        inland_container_depot: trimmed(form.inland_container_depot),
        acknowledge_no_purchase_leg: needsAcknowledgement && acknowledged,
        acknowledgement_note: needsAcknowledgement ? trimmed(note) : null,
      };

      const result = await attachSalesLeg(session.accessToken, selected.id, body);
      if (result.commodity_code_mismatch) {
        toast.error(
          result.commodity_message ??
            "The commodity code does not agree with this batch. Check the match.",
        );
      } else {
        toast.success(`Sales leg attached to batch ${selected.batch_number}.`);
      }
      router.push(`/transactions/sales/${selected.id}`);
    } catch (error) {
      toast.error(
        error instanceof ApiError ? error.message : "The sales leg could not be attached.",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-6">
      <AiDisclaimer />

      <Card>
        <CardHeader>
          <CardTitle>1. Find the batch this cargo was bought as</CardTitle>
          <CardDescription>
            Search by batch number, purchase contract, supplier or supplier invoice. A sale is
            almost always of material AGFZE already holds, so the sell side attaches to that
            record rather than opening a second one for the same cargo.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-end gap-2">
            <div className="min-w-[18rem] flex-1 space-y-1.5">
              <Label htmlFor="sales-batch-search">Batch, contract, supplier or invoice</Label>
              <Input
                id="sales-batch-search"
                value={query}
                placeholder="I2626-1, AGF-CT-2026-118, Emirates Metal…"
                onChange={(event) => setQuery(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") search();
                }}
              />
            </div>
            <Button variant="outline" onClick={search} disabled={searching}>
              <Search className="mr-2 h-4 w-4" aria-hidden="true" />
              {searching ? "Searching…" : "Search"}
            </Button>
          </div>

          {results !== null ? (
            results.length === 0 ? (
              <p className="rounded-md border border-dashed border-border bg-surface px-3 py-6 text-center text-sm text-muted-foreground">
                Nothing open matched that. Widen the search, or select a batch with no purchase
                leg below and acknowledge the exception explicitly.
              </p>
            ) : (
              <ul className="space-y-2">
                {results.map((row) => {
                  const active = selected?.id === row.id;
                  return (
                    <li key={row.id}>
                      <button
                        type="button"
                        onClick={() => {
                          setSelected(row);
                          setAcknowledged(false);
                        }}
                        className={cn(
                          "flex w-full items-start gap-3 rounded-md border px-3 py-2.5 text-left transition-colors",
                          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                          active
                            ? "border-secondary bg-secondary/10"
                            : "border-border bg-surface hover:border-secondary/60",
                        )}
                        aria-pressed={active}
                      >
                        <span
                          className={cn(
                            "mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full border",
                            active
                              ? "border-secondary bg-secondary text-secondary-foreground"
                              : "border-border",
                          )}
                        >
                          {active ? <Check className="h-3 w-3" aria-hidden="true" /> : null}
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="block font-mono text-sm text-foreground">
                            {row.batch_number}
                          </span>
                          <span className="block text-xs text-muted-foreground">
                            {row.counterparty ?? "No counterparty recorded"} ·{" "}
                            {row.contract_number ?? "no contract reference"} ·{" "}
                            {formatQuantity(row.quantity_mt)}
                          </span>
                        </span>
                        <Badge
                          variant="outline"
                          className={cn(
                            "shrink-0",
                            row.has_purchase_leg
                              ? "border-pill-green-border bg-pill-green-bg text-pill-green-text"
                              : "border-pill-amber-border bg-pill-amber-bg text-pill-amber-text",
                          )}
                        >
                          {deskLabel(row)}
                        </Badge>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )
          ) : null}

          {needsAcknowledgement ? (
            <div className="space-y-2 rounded-md border border-pill-amber-border bg-pill-amber-bg p-3">
              <p className="flex items-start gap-2 text-sm font-medium text-foreground">
                <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                Batch {selected?.batch_number} has no purchase leg.
              </p>
              <p className="text-sm text-muted-foreground">
                A sale normally follows a purchase of the same cargo. Attaching a sales leg to a
                batch with no purchase counterpart is a real decision, and it goes on the audit
                trail with your name against it.
              </p>
              <label className="flex items-start gap-2 text-sm text-foreground">
                <input
                  type="checkbox"
                  checked={acknowledged}
                  onChange={(event) => setAcknowledged(event.target.checked)}
                  className="mt-1 h-4 w-4 rounded border-border"
                />
                <span>
                  I confirm no purchase counterpart exists for this cargo yet, and that this is
                  deliberate.
                </span>
              </label>
              {acknowledged ? (
                <div className="space-y-1.5">
                  <Label htmlFor="sales-ack-note">Why (optional, kept on the record)</Label>
                  <Textarea
                    id="sales-ack-note"
                    rows={2}
                    value={note}
                    placeholder="For example: back-to-back sale agreed before the purchase contract was signed."
                    onChange={(event) => setNote(event.target.value)}
                  />
                </div>
              ) : null}
            </div>
          ) : null}
        </CardContent>
      </Card>

      <Card className={cn(!selected && "opacity-60")}>
        <CardHeader>
          <CardTitle>2. The customer and the terms</CardTitle>
          <CardDescription>
            {selected
              ? `Attaching to batch ${selected.batch_number}.`
              : "Select a batch above before recording the sell side."}
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5 sm:col-span-2">
            <Label htmlFor="sales-customer">Customer (required)</Label>
            <Input
              id="sales-customer"
              disabled={!selected}
              value={form.customer_name}
              onChange={(event) => set("customer_name")(event.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="sales-contract">Sales contract number (required)</Label>
            <Input
              id="sales-contract"
              disabled={!selected}
              value={form.sales_contract_no}
              onChange={(event) => set("sales_contract_no")(event.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="sales-contracted-qty">Contracted quantity (MT, whole contract)</Label>
            <Input
              id="sales-contracted-qty"
              inputMode="decimal"
              disabled={!selected}
              value={form.contracted_quantity_mt}
              onChange={(event) => set("contracted_quantity_mt")(event.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              The total this contract covers, not this shipment. Every shipment quoting the same
              contract number is measured against it together.
            </p>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="sales-territory">Destination territory</Label>
            <Select
              id="sales-territory"
              disabled={!selected}
              value={form.territory}
              onChange={(event) => set("territory")(event.target.value)}
            >
              {TERRITORIES.map((value) => (
                <option key={value} value={value}>
                  {TERRITORY_LABELS[value]}
                </option>
              ))}
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="sales-payment">Payment condition</Label>
            <Select
              id="sales-payment"
              disabled={!selected}
              value={form.payment_condition}
              onChange={(event) => set("payment_condition")(event.target.value)}
            >
              {PAYMENT_CONDITIONS.map((value) => (
                <option key={value} value={value}>
                  {PAYMENT_CONDITION_LABELS[value]}
                </option>
              ))}
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="sales-invoice">Sales invoice number (optional)</Label>
            <Input
              id="sales-invoice"
              disabled={!selected}
              value={form.sales_invoice_number}
              onChange={(event) => set("sales_invoice_number")(event.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="sales-bl">Bill of lading reference (optional)</Label>
            <Input
              id="sales-bl"
              disabled={!selected}
              value={form.bl_reference}
              onChange={(event) => set("bl_reference")(event.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="sales-pod">Port of discharge</Label>
            <Input
              id="sales-pod"
              disabled={!selected}
              value={form.port_of_discharge}
              onChange={(event) => set("port_of_discharge")(event.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="sales-icd">Inland container depot (optional)</Label>
            <Input
              id="sales-icd"
              disabled={!selected}
              value={form.inland_container_depot}
              onChange={(event) => set("inland_container_depot")(event.target.value)}
            />
          </div>
        </CardContent>
      </Card>

      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4">
        <p className="min-w-0 flex-1 text-xs text-muted-foreground">
          {selected
            ? needsAcknowledgement && !acknowledged
              ? "Acknowledge the missing purchase leg above before this can be attached."
              : "The price fixation is recorded from the workspace once the customer fixes."
            : "Select the batch this cargo was bought as."}
        </p>
        <Button onClick={submit} disabled={!ready || saving}>
          {saving ? "Attaching…" : "Attach sales leg"}
        </Button>
      </div>
    </div>
  );
}
