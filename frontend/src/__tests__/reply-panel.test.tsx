import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReplyPanel } from "@/components/intake/reply-panel";
import type { ReplyDraftList } from "@/lib/api-client";

const refresh = vi.fn();
const compose = vi.fn();
const send = vi.fn();
const withdraw = vi.fn();

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh, push: vi.fn() }) }));
vi.mock("next-auth/react", () => ({ useSession: () => ({ data: { accessToken: "token" } }) }));

vi.mock("@/lib/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api-client")>();
  return {
    ...actual,
    composeRequestReply: (...args: unknown[]) => compose(...args),
    sendRequestReply: (...args: unknown[]) => send(...args),
    withdrawRequestReply: (...args: unknown[]) => withdraw(...args),
  };
});

const REQUEST_ID = "22222222-2222-4222-8222-222222222222";
const DRAFT_ID = "33333333-3333-4333-8333-333333333333";

const DRAFT = {
  id: DRAFT_ID,
  request_id: REQUEST_ID,
  status: "draft" as const,
  subject: "RE: Copper 125 MT",
  body_text: "Confirming 125 MT copper.\n\nOur reference: REQ-1\n\nAI-extracted information…",
  failure_reason: null,
  composed_at: "2026-04-01T09:00:00Z",
  composed_by_name: "Marco Bellini",
  sent_at: null,
  sent_by_name: null,
};

function list(overrides: Partial<ReplyDraftList> = {}): ReplyDraftList {
  return {
    items: [],
    recipient_address: "desk@broker.example",
    outbound_enabled: true,
    ...overrides,
  };
}

beforeEach(() => {
  refresh.mockClear();
  compose.mockClear().mockResolvedValue(DRAFT);
  send.mockClear().mockResolvedValue({ ...DRAFT, status: "sent" });
  withdraw.mockClear().mockResolvedValue({ ...DRAFT, status: "withdrawn" });
});

describe("the reply panel", () => {
  it("names who a reply would actually reach", () => {
    render(<ReplyPanel requestId={REQUEST_ID} replies={list()} canCompose />);
    expect(screen.getByText(/desk@broker\.example/)).toBeInTheDocument();
  });

  it("drafts without sending, and never both in one action", async () => {
    const user = userEvent.setup();
    render(<ReplyPanel requestId={REQUEST_ID} replies={list()} canCompose />);

    await user.type(
      screen.getByLabelText("What should the desk say?"),
      "Confirming 125 MT copper against your reference.",
    );
    await user.click(screen.getByRole("button", { name: "Draft a reply" }));

    expect(compose).toHaveBeenCalledTimes(1);
    // The whole point of two buttons: drafting reaches no mailbox.
    expect(send).not.toHaveBeenCalled();
  });

  it("will not draft a message too short to be one", async () => {
    const user = userEvent.setup();
    render(<ReplyPanel requestId={REQUEST_ID} replies={list()} canCompose />);

    await user.type(screen.getByLabelText("What should the desk say?"), "ok");
    expect(screen.getByRole("button", { name: "Draft a reply" })).toBeDisabled();
    expect(compose).not.toHaveBeenCalled();
  });

  it("sends only on its own explicit action", async () => {
    const user = userEvent.setup();
    render(
      <ReplyPanel requestId={REQUEST_ID} replies={list({ items: [DRAFT] })} canCompose />,
    );

    await user.click(screen.getByRole("button", { name: /Send this reply/ }));
    expect(send).toHaveBeenCalledWith("token", REQUEST_ID, DRAFT_ID);
    expect(compose).not.toHaveBeenCalled();
  });

  it("shows the body exactly as it was composed, disclaimer and all", () => {
    render(<ReplyPanel requestId={REQUEST_ID} replies={list({ items: [DRAFT] })} canCompose />);
    expect(screen.getByText(/AI-extracted information/)).toBeInTheDocument();
    expect(screen.getByText(/Our reference: REQ-1/)).toBeInTheDocument();
  });

  it("offers no send at all where the deployment cannot send", () => {
    render(
      <ReplyPanel
        requestId={REQUEST_ID}
        replies={list({ items: [DRAFT], outbound_enabled: false })}
        canCompose
      />,
    );
    // Said plainly rather than by a button that could only fail.
    expect(screen.getByRole("note")).toHaveTextContent(/not enabled on this deployment/i);
    expect(screen.getByRole("button", { name: /Send this reply/ })).toBeDisabled();
  });

  it("offers neither action to somebody who may only read", () => {
    render(
      <ReplyPanel
        requestId={REQUEST_ID}
        replies={list({ items: [DRAFT] })}
        canCompose={false}
      />,
    );
    expect(screen.queryByLabelText("What should the desk say?")).toBeNull();
    expect(screen.queryByRole("button", { name: /Send this reply/ })).toBeNull();
  });

  it("neither sends nor withdraws a reply that has already been sent", () => {
    render(
      <ReplyPanel
        requestId={REQUEST_ID}
        replies={list({
          items: [{ ...DRAFT, status: "sent", sent_at: "2026-04-01T10:00:00Z", sent_by_name: "Marco Bellini" }],
        })}
        canCompose
      />,
    );
    expect(screen.queryByRole("button", { name: /Send this reply/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Withdraw" })).toBeNull();
    expect(screen.getByText("Sent")).toBeInTheDocument();
  });

  it("says a refusal was a refusal, and that nothing was delivered", () => {
    render(
      <ReplyPanel
        requestId={REQUEST_ID}
        replies={list({ items: [{ ...DRAFT, status: "failed", failure_reason: "http_403" }] })}
        canCompose
      />,
    );
    expect(screen.getByText(/Nothing was delivered/)).toBeInTheDocument();
    expect(screen.getByText("Send failed")).toBeInTheDocument();
  });

  it("offers nothing at all on a request with no thread behind it", () => {
    render(
      <ReplyPanel
        requestId={REQUEST_ID}
        replies={list({ recipient_address: null })}
        canCompose
      />,
    );
    expect(screen.getByText(/no thread to reply on/i)).toBeInTheDocument();
    expect(screen.queryByLabelText("What should the desk say?")).toBeNull();
  });
});
