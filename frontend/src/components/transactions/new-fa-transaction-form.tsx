"use client";

import { useRouter } from "next/navigation";
import { useSession } from "next-auth/react";
import { useState } from "react";
import toast from "react-hot-toast";

import { AiDisclaimer } from "@/components/shared/ai-disclaimer";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  ApiError,
  createFaTransaction,
  type FaFieldSchema,
  type FaTransactionCreate,
} from "@/lib/api-client";

export interface NewFaTransactionFormProps {
  /**
   * The configured FA fields with no named column of their own. Rendered from the schema,
   * exactly as the workspace's panel is, so this form grows with the configuration too.
   */
  extraFields: FaFieldSchema[];
}

interface FormState {
  counterparty_name: string;
  fa_contract_reference: string;
  document_type: string;
  batch_number: string;
  quantity_mt: string;
  currency: string;
}

const EMPTY: FormState = {
  counterparty_name: "",
  fa_contract_reference: "",
  document_type: "",
  batch_number: "",
  quantity_mt: "",
  currency: "USD",
};

function trimmed(value: string): string | null {
  const cleaned = value.trim();
  return cleaned === "" ? null : cleaned;
}

/**
 * Registering an FA transaction by hand.
 *
 * Purchase's standalone pattern rather than sales' attach-to-an-existing-batch one. That
 * asymmetry is deliberate and is the same one the tab strip explains: a sale is the sell side of
 * cargo AGFZE already bought and belongs on that cargo's record, whereas FA is a structurally
 * separate business line with nothing to attach to.
 *
 * The named fields are the three AGFZE's material actually specifies. Everything else comes from
 * the configured schema below them, so this form has no FA field list of its own either.
 */
export function NewFaTransactionForm({ extraFields }: NewFaTransactionFormProps) {
  const router = useRouter();
  const { data: session } = useSession();
  const [form, setForm] = useState<FormState>(EMPTY);
  const [extras, setExtras] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);

  const ready = form.counterparty_name.trim().length >= 2;

  function set<K extends keyof FormState>(key: K, value: string) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  async function submit() {
    if (!session?.accessToken) {
      toast.error("Your session has expired. Sign in again to register this transaction.");
      return;
    }
    if (!ready) {
      toast.error("The counterparty name is required.");
      return;
    }

    setSaving(true);
    try {
      const body: FaTransactionCreate = {
        counterparty_name: form.counterparty_name.trim(),
        fa_contract_reference: trimmed(form.fa_contract_reference),
        document_type: trimmed(form.document_type),
        batch_number: trimmed(form.batch_number),
        quantity_mt: trimmed(form.quantity_mt),
        currency: form.currency.trim().toUpperCase() || "USD",
        extra_fields: Object.fromEntries(
          Object.entries(extras).filter(([, value]) => value.trim() !== ""),
        ),
      };
      const created = await createFaTransaction(session.accessToken, body);
      toast.success(`FA transaction ${created.batch_number} registered.`);
      router.push(`/transactions/fa/${created.id}`);
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

      <Card>
        <CardHeader>
          <CardTitle>FA transaction</CardTitle>
          <CardDescription>
            AGFZE&apos;s second business line. It opens its own record rather than attaching to a
            scrap batch, because it is a separate line of business and not the other side of one.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5 sm:col-span-2">
            <Label htmlFor="fa-counterparty">Counterparty (required)</Label>
            <Input
              id="fa-counterparty"
              value={form.counterparty_name}
              disabled={saving}
              onChange={(event) => set("counterparty_name", event.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="fa-reference">Transaction / contract reference</Label>
            <Input
              id="fa-reference"
              value={form.fa_contract_reference}
              disabled={saving}
              onChange={(event) => set("fa_contract_reference", event.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="fa-document-type">Document type</Label>
            <Input
              id="fa-document-type"
              value={form.document_type}
              disabled={saving}
              placeholder="As the counterparty names it"
              onChange={(event) => set("document_type", event.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              Free text. No FA document-type vocabulary has been agreed, so the platform does not
              invent one.
            </p>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="fa-quantity">Quantity</Label>
            <Input
              id="fa-quantity"
              inputMode="decimal"
              value={form.quantity_mt}
              disabled={saving}
              onChange={(event) => set("quantity_mt", event.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="fa-currency">Currency</Label>
            <Input
              id="fa-currency"
              maxLength={3}
              value={form.currency}
              disabled={saving}
              onChange={(event) => set("currency", event.target.value.toUpperCase())}
            />
          </div>
          <div className="space-y-1.5 sm:col-span-2">
            <Label htmlFor="fa-batch">Reference number (optional)</Label>
            <Input
              id="fa-batch"
              value={form.batch_number}
              disabled={saving}
              placeholder="Leave blank and the next one is proposed"
              onChange={(event) => set("batch_number", event.target.value)}
            />
          </div>
        </CardContent>
      </Card>

      {extraFields.length > 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>Additional FA fields</CardTitle>
            <CardDescription>
              Drawn from the configured FA document schema. Adding a field to that schema adds it
              here and to the workspace, with no change to either screen.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2">
            {extraFields.map((definition) => (
              <div key={definition.name} className="space-y-1.5">
                <Label htmlFor={`fa-extra-${definition.name}`}>{definition.label}</Label>
                <Input
                  id={`fa-extra-${definition.name}`}
                  type={definition.type === "date" ? "date" : "text"}
                  inputMode={
                    ["number", "currency", "quantity"].includes(definition.type)
                      ? "decimal"
                      : undefined
                  }
                  value={extras[definition.name] ?? ""}
                  disabled={saving}
                  onChange={(event) =>
                    setExtras((current) => ({
                      ...current,
                      [definition.name]: event.target.value,
                    }))
                  }
                />
                {definition.description ? (
                  <p className="text-xs text-muted-foreground">{definition.description}</p>
                ) : null}
              </div>
            ))}
          </CardContent>
        </Card>
      ) : null}

      <div className="flex justify-end border-t border-border pt-4">
        <Button onClick={submit} disabled={saving || !ready}>
          {saving ? "Registering…" : "Register FA transaction"}
        </Button>
      </div>
    </div>
  );
}
