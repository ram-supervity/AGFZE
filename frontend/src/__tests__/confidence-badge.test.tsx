import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ConfidenceBadge } from "@/components/shared/confidence-badge";

describe("ConfidenceBadge", () => {
  it("shows the score as text, so colour is never the only signal", () => {
    const { container } = render(<ConfidenceBadge label="Purchase" confidence={0.93} />);
    expect(container.textContent).toContain("Purchase");
    expect(container.textContent).toContain("93%");
  });

  it("tints itself from the traffic-light triad", () => {
    const confident = render(<ConfidenceBadge label="Invoice" confidence={0.95} />);
    expect(confident.container.innerHTML).toContain("signal-confident");

    const review = render(<ConfidenceBadge label="Invoice" confidence={0.78} />);
    expect(review.container.innerHTML).toContain("signal-review");

    const blocked = render(<ConfidenceBadge label="Invoice" confidence={0.4} />);
    expect(blocked.container.innerHTML).toContain("signal-blocked");
  });

  it("says there is no score rather than implying a low one", () => {
    const { container } = render(<ConfidenceBadge label="Unidentified" confidence={null} />);
    expect(container.textContent).toContain("No score");
  });
});
