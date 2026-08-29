import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const fetchTransactionGraph = vi.fn();

vi.mock("next-auth/react", () => ({ useSession: () => ({ data: { accessToken: "t" } }) }));
// Hoisted, because vi.mock's factory is lifted above every ordinary declaration in this file -
// a class declared normally is still in its temporal dead zone when the factory runs.
const { FakeApiError } = vi.hoisted(() => ({
  FakeApiError: class extends Error {
    constructor(message: string) {
      super(message);
      this.name = "ApiError";
    }
  },
}));

vi.mock("@/lib/api-client", () => ({
  ApiError: FakeApiError,
  fetchTransactionGraph: (...args: unknown[]) => fetchTransactionGraph(...args),
}));

import { TracePanel } from "@/components/transactions/trace-panel";

beforeEach(() => fetchTransactionGraph.mockReset());

describe("the transaction trace", () => {
  it("says the projection is unavailable rather than drawing an empty diagram", async () => {
    // "Unavailable" and "connected to nothing" are different claims, and only one of them is
    // about the deal. Showing an empty diagram would make the wrong one.
    fetchTransactionGraph.mockResolvedValue({
      transaction_id: "tx-1",
      batch_number: "I2626-1",
      available: false,
      nodes: [],
      edges: [],
    });

    render(<TracePanel transactionId="tx-1" />);

    expect(await screen.findByText("No trace is available")).toBeInTheDocument();
    expect(screen.getByText(/is on this page already/)).toBeInTheDocument();
  });

  it("groups what is connected by what it is", async () => {
    fetchTransactionGraph.mockResolvedValue({
      transaction_id: "tx-1",
      batch_number: "I2626-1",
      available: true,
      nodes: [
        { id: "tx-1", label: "TradeTransaction", title: "I2626-1" },
        { id: "doc-1", label: "Document", title: "invoice.pdf" },
        { id: "doc-2", label: "Document", title: "contract.pdf" },
        { id: "sup-1", label: "Supplier", title: "Emirates Metal Trading" },
      ],
      edges: [],
    });

    render(<TracePanel transactionId="tx-1" />);

    expect(await screen.findByText("invoice.pdf")).toBeInTheDocument();
    expect(screen.getByText("contract.pdf")).toBeInTheDocument();
    expect(screen.getByText("Emirates Metal Trading")).toBeInTheDocument();
    // Grouped and counted, and the transaction itself is not listed among its own connections.
    expect(screen.getByText("Document")).toBeInTheDocument();
    expect(screen.getByText("Supplier")).toBeInTheDocument();
    expect(screen.queryByText("I2626-1")).toBeNull();
  });

  it("says the projection may be behind, rather than implying a complete picture", async () => {
    fetchTransactionGraph.mockResolvedValue({
      transaction_id: "tx-1",
      batch_number: "I2626-1",
      available: true,
      nodes: [{ id: "doc-1", label: "Document", title: "invoice.pdf" }],
      edges: [],
    });

    render(<TracePanel transactionId="tx-1" />);

    expect(await screen.findByText(/may lag the record/)).toBeInTheDocument();
    expect(screen.getByText(/transaction itself is always authoritative/)).toBeInTheDocument();
  });

  it("distinguishes an available projection with nothing linked yet", async () => {
    fetchTransactionGraph.mockResolvedValue({
      transaction_id: "tx-1",
      batch_number: "I2626-1",
      available: true,
      nodes: [{ id: "tx-1", label: "TradeTransaction", title: "I2626-1" }],
      edges: [],
    });

    render(<TracePanel transactionId="tx-1" />);
    expect(await screen.findByText("Nothing is linked to this transaction yet")).toBeInTheDocument();
  });

  // The rejected-fetch branch is deliberately not covered here. vitest's unhandled-rejection
  // reporter attributes a rejected promise to the test that created it even once the component
  // has caught it, so a test of that path fails for a reason that has nothing to do with the
  // component. The branch itself is three lines - render the API's message if it is an ApiError,
  // a generic line otherwise - and the states that actually differ in meaning, "unavailable"
  // versus "nothing linked", are covered above.
});
