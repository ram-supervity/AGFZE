"use client";

import { FileText, Ship, Wallet } from "lucide-react";
import { useRouter } from "next/navigation";
import { useSession } from "next-auth/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  fetchDocumentList,
  fetchShipmentList,
  fetchTransactionList,
} from "@/lib/api-client";
import { workspacePath } from "@/lib/transactions";

interface Hit {
  id: string;
  kind: "transaction" | "document" | "shipment";
  title: string;
  detail: string;
  href: string;
}

const PER_KIND = 5;
// Long enough that a keystroke does not become a request, short enough that the list does not
// feel like it is lagging behind the typing.
const DEBOUNCE_MS = 220;
// Below this a search matches most of the estate and the three requests cost more than the answer.
const MIN_QUERY = 2;

const GROUPS = [
  { kind: "transaction" as const, label: "Transactions", icon: Wallet },
  { kind: "document" as const, label: "Documents", icon: FileText },
  { kind: "shipment" as const, label: "Shipments", icon: Ship },
];

/**
 * The global ⌘K / Ctrl+K palette, searching the three things somebody looks for by name.
 *
 * It runs the three existing list endpoints in parallel with their `search` parameter, rather than
 * adding a search backend. That has a real consequence worth knowing: each endpoint applies its own
 * role and stream scoping, so the palette can only ever surface what the person could already reach
 * by navigating. There is no path here that widens visibility.
 *
 * Filtering is left entirely to the server (`shouldFilter={false}` on the Command). cmdk's built-in
 * fuzzy filter would re-filter the server's results against the same string and silently drop rows
 * the API considered a match - a batch number found by its contract reference, say, whose label
 * contains none of what was typed.
 */
export function CommandPalette() {
  const router = useRouter();
  const { data: session } = useSession();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<Hit[]>([]);
  const [loading, setLoading] = useState(false);
  // Guards against a slow early response landing after a faster later one and overwriting it.
  const latest = useRef(0);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key.toLowerCase() !== "k" || !(event.metaKey || event.ctrlKey)) return;
      event.preventDefault();
      setOpen((current) => !current);
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const search = useCallback(
    async (term: string, token: string, run: number) => {
      const params = { search: term, page: 1, page_size: PER_KIND };
      // Three requests at once rather than in sequence: they are independent, and awaiting them
      // one after another would make the palette feel three times slower than it is.
      const [transactions, documents, shipments] = await Promise.all([
        fetchTransactionList(token, params).catch(() => null),
        fetchDocumentList(token, params).catch(() => null),
        fetchShipmentList(token, params).catch(() => null),
      ]);
      if (latest.current !== run) return;

      const found: Hit[] = [];
      for (const row of transactions?.items ?? []) {
        found.push({
          id: row.id,
          kind: "transaction",
          title: row.batch_number,
          detail: [row.counterparty, row.contract_number].filter(Boolean).join(" · "),
          href: workspacePath(row),
        });
      }
      for (const row of documents?.items ?? []) {
        found.push({
          id: row.id,
          kind: "document",
          title: row.filename,
          detail: row.document_type ?? "Unclassified",
          href: `/documents/${row.id}`,
        });
      }
      for (const row of shipments?.items ?? []) {
        found.push({
          id: row.id,
          kind: "shipment",
          title: row.container_number ?? row.bl_number ?? row.batch_number ?? "Shipment",
          detail: [row.carrier, row.port_of_discharge].filter(Boolean).join(" · "),
          href: `/shipments/${row.id}`,
        });
      }
      setHits(found);
    },
    [],
  );

  useEffect(() => {
    const token = session?.accessToken;
    const term = query.trim();
    if (!open || !token || term.length < MIN_QUERY) {
      setHits([]);
      setLoading(false);
      return;
    }

    const run = ++latest.current;
    setLoading(true);
    const timer = setTimeout(() => {
      search(term, token, run).finally(() => {
        if (latest.current === run) setLoading(false);
      });
    }, DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [open, query, session?.accessToken, search]);

  const grouped = useMemo(
    () => GROUPS.map((group) => ({ ...group, rows: hits.filter((h) => h.kind === group.kind) })),
    [hits],
  );

  function go(href: string) {
    setOpen(false);
    setQuery("");
    router.push(href);
  }

  return (
    <CommandDialog open={open} onOpenChange={setOpen} label="Search the platform">
      <CommandInput
        value={query}
        onValueChange={setQuery}
        placeholder="Search batches, documents and shipments…"
      />
      <CommandList>
        {query.trim().length < MIN_QUERY ? (
          <CommandEmpty>Type at least {MIN_QUERY} characters.</CommandEmpty>
        ) : loading ? (
          <CommandEmpty>Searching…</CommandEmpty>
        ) : hits.length === 0 ? (
          <CommandEmpty>Nothing matches that.</CommandEmpty>
        ) : null}

        {grouped.map((group) =>
          group.rows.length > 0 ? (
            // Labelled by type, because a batch number and a container number look alike and
            // opening the wrong one wastes a click.
            <CommandGroup key={group.kind} heading={group.label}>
              {group.rows.map((hit) => (
                <CommandItem
                  key={`${hit.kind}-${hit.id}`}
                  value={`${hit.kind}-${hit.id}`}
                  onSelect={() => go(hit.href)}
                >
                  <group.icon className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                  <span className="min-w-0 flex-1 truncate">{hit.title}</span>
                  {hit.detail ? (
                    <span className="shrink-0 truncate text-xs text-muted-foreground">
                      {hit.detail}
                    </span>
                  ) : null}
                </CommandItem>
              ))}
            </CommandGroup>
          ) : null,
        )}
      </CommandList>
    </CommandDialog>
  );
}
