import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const completeOnboarding = vi.fn();

vi.mock("next-auth/react", () => ({ useSession: () => ({ data: { accessToken: "t" } }) }));
vi.mock("@/lib/api-client", () => ({
  completeOnboarding: (...args: unknown[]) => completeOnboarding(...args),
}));

import { OnboardingWalkthrough } from "@/components/shared/onboarding-walkthrough";

beforeEach(() => {
  completeOnboarding.mockReset();
  completeOnboarding.mockResolvedValue({});
});

describe("the first-login walkthrough", () => {
  it("appears for an account that has not seen it", () => {
    render(<OnboardingWalkthrough roles={["purchase_user"]} completed={false} />);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Everything arrives here")).toBeInTheDocument();
  });

  it("does not appear for an account that already has", () => {
    // Server-owned, so it cannot reappear on a second device or after a cleared cache.
    render(<OnboardingWalkthrough roles={["purchase_user"]} completed={true} />);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("skips the approval  for somebody with no approval rights", async () => {
    // A walkthrough that describes a screen the reader cannot open teaches them that this
    // platform's guidance is approximate.
    const user = userEvent.setup();
    render(<OnboardingWalkthrough roles={["purchase_user"]} completed={false} />);

    expect(screen.getByText(/1 of 2/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByText(/2 of 2/)).toBeInTheDocument();
    expect(screen.queryByText(/Nothing is committed without a decision/)).toBeNull();
  });

  it("shows the approval  to an approver", async () => {
    const user = userEvent.setup();
    render(<OnboardingWalkthrough roles={["approver_hod"]} completed={false} />);

    expect(screen.getByText(/1 of 3/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.click(screen.getByRole("button", { name: "Next" }));
    // Awaited: the  text cross-fades, so the incoming copy mounts after the outgoing one
    // has finished leaving.
    expect(
      await screen.findByText("Nothing is committed without a decision"),
    ).toBeInTheDocument();
  });

  it(" backwards as well as forwards", async () => {
    const user = userEvent.setup();
    render(<OnboardingWalkthrough roles={["approver_hod"]} completed={false} />);

    // No Back on the first  - there is nowhere to go.
    expect(screen.queryByRole("button", { name: "Back" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByText(/1 of 3/)).toBeInTheDocument();
  });

  it("records completion once the last  is acknowledged", async () => {
    const user = userEvent.setup();
    render(<OnboardingWalkthrough roles={["purchase_user"]} completed={false} />);

    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.click(screen.getByRole("button", { name: "Got it" }));

    await waitFor(() => expect(completeOnboarding).toHaveBeenCalledWith("t"));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("treats skipping as the same fact as finishing", async () => {
    // Somebody who dismissed the tour meant it. Showing it again next login would be the
    // platform arguing with them.
    const user = userEvent.setup();
    render(<OnboardingWalkthrough roles={["purchase_user"]} completed={false} />);

    await user.click(screen.getByRole("button", { name: "Skip" }));

    await waitFor(() => expect(completeOnboarding).toHaveBeenCalledWith("t"));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("closes on Escape and records that too", async () => {
    const user = userEvent.setup();
    render(<OnboardingWalkthrough roles={["purchase_user"]} completed={false} />);

    await user.keyboard("{Escape}");

    await waitFor(() => expect(completeOnboarding).toHaveBeenCalled());
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("stays closed even if recording the completion fails", async () => {
    // Worst case is the tour appearing once more. Showing somebody an error about a tooltip,
    // or holding them behind a spinner, would both be worse than that.
    completeOnboarding.mockRejectedValue(new Error("offline"));
    const user = userEvent.setup();
    render(<OnboardingWalkthrough roles={["purchase_user"]} completed={false} />);

    await user.click(screen.getByRole("button", { name: "Skip" }));

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByText(/error/i)).toBeNull();
  });

  it("names itself for a screen reader", () => {
    render(<OnboardingWalkthrough roles={["purchase_user"]} completed={false} />);
    const dialog = screen.getByRole("dialog");

    expect(dialog).toHaveAttribute("aria-labelledby", "onboarding-title");
    expect(dialog).toHaveAttribute("aria-describedby", "onboarding-body");
    // Not modal: it sits beside the work rather than blocking it, so somebody can start using
    // the screen the tour is describing while it is open.
    expect(dialog).toHaveAttribute("aria-modal", "false");
  });
});
