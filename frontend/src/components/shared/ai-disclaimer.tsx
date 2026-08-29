import { TriangleAlert } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * The exact governance wording, in one place. Every screen that shows AI-assigned or
 * AI-extracted content renders this component rather than restating the copy, so the text can
 * never drift between screens.
 */
export const AI_DISCLAIMER_TEXT =
  "AI-extracted information may contain errors and must be verified against the source document " +
  "before approval. This platform does not replace the designated approver's review. For " +
  "transactions above configured value or risk thresholds, or where source documents conflict, " +
  "escalate to the approver before proceeding.";

export function AiDisclaimer({ className }: { className?: string }) {
  return (
    <aside
      role="note"
      aria-label="AI accuracy notice"
      className={cn(
        "flex items-start gap-3 rounded-md border border-signal-review/35 bg-signal-review/10 px-4 py-3",
        className,
      )}
    >
      <TriangleAlert
        aria-hidden="true"
        className="mt-0.5 h-4 w-4 shrink-0 text-signal-review"
      />
      <p className="text-sm leading-relaxed text-foreground">{AI_DISCLAIMER_TEXT}</p>
    </aside>
  );
}
