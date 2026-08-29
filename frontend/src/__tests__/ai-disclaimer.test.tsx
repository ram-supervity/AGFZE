import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AI_DISCLAIMER_TEXT, AiDisclaimer } from "@/components/shared/ai-disclaimer";

const EXPECTED =
  "AI-extracted information may contain errors and must be verified against the source document " +
  "before approval. This platform does not replace the designated approver's review. For " +
  "transactions above configured value or risk thresholds, or where source documents conflict, " +
  "escalate to the approver before proceeding.";

describe("AiDisclaimer", () => {
  it("renders the governing wording exactly, with nothing added or dropped", () => {
    const { getByRole } = render(<AiDisclaimer />);
    const note = getByRole("note", { name: /ai accuracy notice/i });

    expect(AI_DISCLAIMER_TEXT).toBe(EXPECTED);
    expect(note.textContent).toBe(EXPECTED);
  });

  it("is announced as a note rather than passed off as decoration", () => {
    const { getByRole } = render(<AiDisclaimer />);
    expect(getByRole("note")).toHaveAttribute("aria-label", "AI accuracy notice");
  });
});
