"use client";

import { Check, UploadCloud } from "lucide-react";
import { useRouter } from "next/navigation";
import { useSession } from "next-auth/react";
import { useCallback, useRef, useState } from "react";
import toast from "react-hot-toast";

import { AiDisclaimer } from "@/components/shared/ai-disclaimer";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { Select } from "@/components/ui/select";
import {
  ApiError,
  createTransaction,
  uploadDocuments,
  type CommodityCode,
  type PurchaseTransactionCreate,
} from "@/lib/api-client";
import {
  ACCEPTED_EXTENSIONS,
  formatBytes,
  validateFileClientSide,
} from "@/lib/intake";
import {
  INVOICE_STATUSES,
  INVOICE_STATUS_LABELS,
  PRICE_BASES,
  PRICE_BASIS_LABELS,
} from "@/lib/transactions";
import { cn } from "@/lib/utils";

const STEPS = [
  { key: "context", title: "Business context", hint: "Which desk and which stream." },
  { key: "counterparty", title: "Counterparty and contract", hint: "Who, and against what." },
  { key: "documents", title: "Documents", hint: "Optional. Attach them now or later." },
] as const;

type StepKey = (typeof STEPS)[number]["key"];

interface FormState {
  supplier_name: string;
  batch_number: string;
  contract_number: string;
  supplier_invoice_number: string;
  invoice_status: string;
  commodity_code: string;
  quantity_mt: string;
  price_basis: string;
  lme_percentage: string;
  currency: string;
  rate: string;
  amount: string;
  advance_payment_percent: string;
  hedge_date: string;
  hedge_low_price: string;
  hedge_high_price: string;
  port_of_loading: string;
}

const EMPTY: FormState = {
  supplier_name: "",
  batch_number: "",
  contract_number: "",
  supplier_invoice_number: "",
  invoice_status: "provisional",
  commodity_code: "",
  quantity_mt: "",
  price_basis: "fixed",
  lme_percentage: "",
  currency: "USD",
  rate: "",
  amount: "",
  advance_payment_percent: "",
  hedge_date: "",
  hedge_low_price: "",
  hedge_high_price: "",
  port_of_loading: "",
};

function trimmed(value: string): string | null {
  const cleaned = value.trim();
  return cleaned === "" ? null : cleaned;
}

export function NewTransactionForm({ commodities }: { commodities: CommodityCode[] }) {
  const router = useRouter();
  const { data: session } = useSession();
  const inputRef = useRef<HTMLInputElement>(null);
  const [step, setStep] = useState<StepKey>("context");
  const [form, setForm] = useState<FormState>(EMPTY);
  const [files, setFiles] = useState<File[]>([]);
  const [saving, setSaving] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);

  const set = useCallback(
    (key: keyof FormState) => (value: string) =>
      setForm((current) => ({ ...current, [key]: value })),
    [],
  );

  const index = STEPS.findIndex((entry) => entry.key === step);
  const counterpartyReady = form.supplier_name.trim().length >= 2;

  function stage(incoming: FileList | File[]) {
    const accepted: File[] = [];
    for (const file of Array.from(incoming)) {
      const problem = validateFileClientSide(file);
      if (problem) toast.error(`${file.name}: ${problem}`);
      else accepted.push(file);
    }
    setFiles((current) => [...current, ...accepted]);
  }

  async function submit() {
    if (!session?.accessToken) {
      toast.error("Your session has expired. Sign in again to register this transaction.");
      return;
    }
    if (!counterpartyReady) {
      toast.error("The supplier name is required.");
      setStep("counterparty");
      return;
    }

    setSaving(true);
    try {
      const body: PurchaseTransactionCreate = {
        // This form registers a purchase on the scrap stream. FA has its own tab beside it,
        // because it opens its own record rather than a batch of physical cargo.
        stream: "scrap",
        batch_number: trimmed(form.batch_number),
        supplier_name: form.supplier_name.trim(),
        contract_number: trimmed(form.contract_number),
        supplier_invoice_number: trimmed(form.supplier_invoice_number),
        invoice_status: form.invoice_status,
        commodity_code: trimmed(form.commodity_code),
        quantity_mt: trimmed(form.quantity_mt),
        price_basis: form.price_basis,
        lme_percentage:
          form.price_basis === "lme_percent" ? trimmed(form.lme_percentage) : null,
        currency: form.currency.trim().toUpperCase() || "USD",
        rate: trimmed(form.rate),
        amount: trimmed(form.amount),
        advance_payment_percent: trimmed(form.advance_payment_percent),
        hedge_date: trimmed(form.hedge_date),
        hedge_low_price: trimmed(form.hedge_low_price),
        hedge_high_price: trimmed(form.hedge_high_price),
        port_of_loading: trimmed(form.port_of_loading),
      };

      const created = await createTransaction(session.accessToken, body);
      toast.success(`Batch ${created.batch_number} registered.`);

      if (files.length > 0) {
        const data = new FormData();
        for (const file of files) data.append("files", file, file.name);
        data.append("stream", "scrap");
        data.append("transaction_id", created.id);
        setUploadProgress(0);
        try {
          await uploadDocuments(session.accessToken, data, setUploadProgress);
          toast.success("Documents attached. Extraction is running against them.");
        } catch (error) {
          // The transaction is real and saved; only the attachment failed, and saying so beats
          // pretending the whole registration did.
          toast.error(
            error instanceof ApiError
              ? `The transaction was created, but the documents were not attached: ${error.message}`
              : "The transaction was created, but the documents were not attached.",
          );
        } finally {
          setUploadProgress(null);
        }
      }

      router.push(`/transactions/purchase/${created.id}`);
    } catch (error) {
      toast.error(
        error instanceof ApiError ? error.message : "The transaction could not be registered.",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-6">
      <AiDisclaimer />

      <ol className="flex flex-wrap gap-2">
        {STEPS.map((entry, position) => {
          const done = position < index;
          const current = entry.key === step;
          return (
            <li key={entry.key}>
              <button
                type="button"
                onClick={() => setStep(entry.key)}
                className={cn(
                  "flex items-center gap-space-100 rounded-control border-thin px-space-150 py-space-100 text-left text-body-sm transition-colors focus-visible:outline-none focus-visible:ring-thick focus-visible:ring-ring",
                  current
                    ? "border-secondary bg-secondary/10 text-foreground"
                    : "border-border bg-elevation-default text-muted-foreground hover:text-foreground",
                )}
                aria-current={current ? "step" : undefined}
              >
                <span
                  className={cn(
                    "flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-body-xs font-medium",
                    done
                      ? "bg-pill-green-bg text-pill-green-text"
                      : "bg-muted text-muted-foreground",
                  )}
                >
                  {done ? <Check className="h-3 w-3" aria-hidden="true" /> : position + 1}
                </span>
                <span>
                  <span className="block font-medium">{entry.title}</span>
                  <span className="block text-xs">{entry.hint}</span>
                </span>
              </button>
            </li>
          );
        })}
      </ol>

      {step === "context" ? (
        <Card>
          <CardHeader>
            <CardTitle>Business context</CardTitle>
            <CardDescription>
              A purchase deal on the scrap stream. The sales and FA desks register their own work
              through the tabs above, because neither opens a batch the way a purchase does.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="new-stream">Business stream</Label>
              <Select id="new-stream" value="scrap" disabled>
                <option value="scrap">Scrap</option>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="new-batch">Batch number (optional)</Label>
              <Input
                id="new-batch"
                value={form.batch_number}
                placeholder="Leave blank and the next one is proposed"
                onChange={(event) => set("batch_number")(event.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                Left blank, the platform allocates the next sequential batch number for this
                financial year.
              </p>
            </div>
          </CardContent>
        </Card>
      ) : null}

      {step === "counterparty" ? (
        <Card>
          <CardHeader>
            <CardTitle>Counterparty and contract</CardTitle>
            <CardDescription>
              Everything the validation engine needs to check the deal against its paperwork.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5 sm:col-span-2">
              <Label htmlFor="new-supplier">Supplier (required)</Label>
              <Input
                id="new-supplier"
                value={form.supplier_name}
                onChange={(event) => set("supplier_name")(event.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="new-contract">Contract number (optional)</Label>
              <Input
                id="new-contract"
                value={form.contract_number}
                onChange={(event) => set("contract_number")(event.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="new-invoice">Supplier invoice number (optional)</Label>
              <Input
                id="new-invoice"
                value={form.supplier_invoice_number}
                onChange={(event) => set("supplier_invoice_number")(event.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="new-invoice-status">Invoice status</Label>
              <Select
                id="new-invoice-status"
                value={form.invoice_status}
                onChange={(event) => set("invoice_status")(event.target.value)}
              >
                {INVOICE_STATUSES.map((value) => (
                  <option key={value} value={value}>
                    {INVOICE_STATUS_LABELS[value]}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="new-commodity">Commodity</Label>
              <Select
                id="new-commodity"
                value={form.commodity_code}
                onChange={(event) => set("commodity_code")(event.target.value)}
              >
                <option value="">Not decided yet</option>
                {commodities.map((commodity) => (
                  <option key={commodity.code} value={commodity.code}>
                    {commodity.display_name} ({commodity.code})
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="new-quantity">Quantity (MT)</Label>
              <Input
                id="new-quantity"
                inputMode="decimal"
                value={form.quantity_mt}
                onChange={(event) => set("quantity_mt")(event.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="new-price-basis">Price basis</Label>
              <Select
                id="new-price-basis"
                value={form.price_basis}
                onChange={(event) => set("price_basis")(event.target.value)}
              >
                {PRICE_BASES.map((value) => (
                  <option key={value} value={value}>
                    {PRICE_BASIS_LABELS[value]}
                  </option>
                ))}
              </Select>
            </div>
            {form.price_basis === "lme_percent" ? (
              <div className="space-y-1.5">
                <Label htmlFor="new-lme">LME percentage</Label>
                <Input
                  id="new-lme"
                  inputMode="decimal"
                  value={form.lme_percentage}
                  onChange={(event) => set("lme_percentage")(event.target.value)}
                />
              </div>
            ) : null}
            <div className="space-y-1.5">
              <Label htmlFor="new-rate">Rate</Label>
              <Input
                id="new-rate"
                inputMode="decimal"
                value={form.rate}
                onChange={(event) => set("rate")(event.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="new-amount">Invoice amount</Label>
              <Input
                id="new-amount"
                inputMode="decimal"
                value={form.amount}
                onChange={(event) => set("amount")(event.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="new-currency">Currency</Label>
              <Input
                id="new-currency"
                maxLength={3}
                value={form.currency}
                onChange={(event) => set("currency")(event.target.value.toUpperCase())}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="new-advance">Advance payment %</Label>
              <Input
                id="new-advance"
                inputMode="decimal"
                value={form.advance_payment_percent}
                onChange={(event) => set("advance_payment_percent")(event.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="new-hedge">Hedge / fixation date</Label>
              <Input
                id="new-hedge"
                type="date"
                value={form.hedge_date}
                onChange={(event) => set("hedge_date")(event.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="new-hedge-low">Hedge day low (LLME)</Label>
              <Input
                id="new-hedge-low"
                inputMode="decimal"
                value={form.hedge_low_price}
                onChange={(event) => set("hedge_low_price")(event.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="new-hedge-high">Hedge day high</Label>
              <Input
                id="new-hedge-high"
                inputMode="decimal"
                value={form.hedge_high_price}
                onChange={(event) => set("hedge_high_price")(event.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="new-pol">Port of loading</Label>
              <Input
                id="new-pol"
                value={form.port_of_loading}
                onChange={(event) => set("port_of_loading")(event.target.value)}
              />
            </div>
          </CardContent>
        </Card>
      ) : null}

      {step === "documents" ? (
        <Card>
          <CardHeader>
            <CardTitle>Initial documents</CardTitle>
            <CardDescription>
              Optional. A transaction with no documents attached is a normal starting state; they
              can be added to the workspace at any time.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => {
                event.preventDefault();
                if (event.dataTransfer.files.length > 0) stage(event.dataTransfer.files);
              }}
              className="flex flex-col items-center justify-center rounded-medium border-2 border-dashed border-border bg-elevation-sunken px-space-300 py-space-500 text-center"
            >
              <UploadCloud
                className="mb-3 h-7 w-7 text-muted-foreground"
                aria-hidden="true"
              />
              <p className="text-sm text-muted-foreground">
                PDF, Word, Excel, CSV, JPEG and PNG. Up to 25 MB each.
              </p>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="mt-4"
                onClick={() => inputRef.current?.click()}
              >
                Choose files
              </Button>
              <input
                ref={inputRef}
                type="file"
                multiple
                accept={ACCEPTED_EXTENSIONS.join(",")}
                className="sr-only"
                onChange={(event) => {
                  if (event.target.files) stage(event.target.files);
                  event.target.value = "";
                }}
              />
            </div>

            {files.length > 0 ? (
              <ul className="space-y-2">
                {files.map((file) => (
                  <li
                    key={`${file.name}-${file.size}-${file.lastModified}`}
                    className="flex items-center justify-between gap-space-150 rounded-control border-thin border-border bg-elevation-default px-space-150 py-space-100 text-body-sm shadow-raised"
                  >
                    <span className="truncate text-foreground">{file.name}</span>
                    <span className="shrink-0 text-xs text-muted-foreground">
                      {formatBytes(file.size)}
                    </span>
                  </li>
                ))}
              </ul>
            ) : null}

            {uploadProgress !== null ? (
              <Progress value={uploadProgress} label="Attaching documents" />
            ) : null}
          </CardContent>
        </Card>
      ) : null}

      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4">
        <Button
          variant="ghost"
          disabled={index === 0 || saving}
          onClick={() => setStep(STEPS[Math.max(0, index - 1)].key)}
        >
          Back
        </Button>
        <div className="flex gap-2">
          {index < STEPS.length - 1 ? (
            <Button
              onClick={() => setStep(STEPS[index + 1].key)}
              disabled={step === "counterparty" && !counterpartyReady}
            >
              Continue
            </Button>
          ) : null}
          <Button variant={index === STEPS.length - 1 ? "default" : "outline"} onClick={submit} disabled={saving}>
            {saving ? "Registering…" : "Register transaction"}
          </Button>
        </div>
      </div>
    </div>
  );
}
