"use client";

import { useSession } from "next-auth/react";
import { useCallback, useEffect, useState } from "react";

import { MatchOutcomeCard } from "@/components/transactions/match-outcome-card";
import { fetchDocumentMatch, type MatchOutcome } from "@/lib/api-client";

export interface DocumentMatchPanelProps {
  documentId: string;
  /** Nothing is fetched until the extraction has actually been confirmed. */
  confirmed: boolean;
  canResolve: boolean;
  /** Seeded from a confirm response so the outcome is on screen without a second round trip. */
  initial?: MatchOutcome | null;
}

/**
 * Reads the live matching position for one document.
 *
 * Scoring is deterministic, so this asks the server what it would do rather than replaying a
 * stored answer: a reload, a second reviewer or a later visit all see the same thing, and there
 * is no half-resolved suggestion sitting anywhere going stale.
 */
export function DocumentMatchPanel({
  documentId,
  confirmed,
  canResolve,
  initial = null,
}: DocumentMatchPanelProps) {
  const { data: session } = useSession();
  const [outcome, setOutcome] = useState<MatchOutcome | null>(initial);
  const token = session?.accessToken;

  const load = useCallback(async () => {
    if (!token || !confirmed) return;
    try {
      setOutcome(await fetchDocumentMatch(token, documentId));
    } catch {
      // A matching position that cannot be read is not worth replacing the page with an error;
      // the panel simply stays quiet until the next load.
    }
  }, [token, confirmed, documentId]);

  useEffect(() => {
    if (initial === null) void load();
  }, [initial, load]);

  if (!confirmed || outcome === null) return null;

  return (
    <MatchOutcomeCard
      documentId={documentId}
      outcome={outcome}
      canResolve={canResolve}
      onResolved={setOutcome}
    />
  );
}
