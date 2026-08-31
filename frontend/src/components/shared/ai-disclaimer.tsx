import { TriangleAlert } from "lucide-react";

import { Alert } from "@/components/ui/alert";
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
    <Alert
      variant="warning"
      icon={TriangleAlert}
      role="note"
      aria-label="AI accuracy notice"
      className={cn(className)}
    >
      {AI_DISCLAIMER_TEXT}
    </Alert>
  );
}
