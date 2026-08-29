import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const push = vi.fn();
const fetchTransactionList = vi.fn();
const fetchDocumentList = vi.fn();
const fetchShipmentList = vi.fn();

vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("next-auth/react", () => ({ useSession: () => ({ data: { accessToken: "t" } }) }));
vi.mock("@/lib/api-client", () => ({
  fetchTransactionList: (...args: unknown[]) => fetchTransactionList(...args),
  fetchDocumentList: (...args: unknown[]) => fetchDocumentList(...args),
  fetchShipmentList: (...args: unknown[]) => fetchShipmentList(...args),
}));

import { CommandPalette } from "@/components/layout/command-palette";

beforeEach(() => {
  push.mockClear();
  fetchTransactionList.mockResolvedValue({
    items: [
      {
        id: "tx-1",
        batch_number: "I2626-42",
        counterparty: "Emirates Metal Trading",
        contract_number: "AGF-CT-118",
        has_purchase_leg: true,
        has_sales_leg: false,
      },
    ],
  });
  fetchDocumentList.mockResolvedValue({
    items: [{ id: "doc-1", filename: "invoice.pdf", document_type: "invoice" }],
  });
  fetchShipmentList.mockResolvedValue({
    items: [
      {
        id: "shp-1",
        container_number: "MSKU1234567",
        bl_number: null,
        batch_number: "I2626-42",
        carrier: "Test Line",
        port_of_discharge: "Nhava Sheva",
      },
    ],
  });
});

async function openPalette(user: ReturnType<typeof userEvent.setup>) {
  render(<CommandPalette />);
  await user.keyboard("{Control>}k{/Control}");
  return screen.findByPlaceholderText(/Search batches/);
}

describe("the command palette", () => {
  it("opens on the keyboard shortcut and closes on it again", async () => {
    const user = userEvent.setup();
    const input = await openPalette(user);
    expect(input).toBeInTheDocument();

    await user.keyboard("{Control>}k{/Control}");
    await waitFor(() => expect(screen.queryByPlaceholderText(/Search batches/)).toBeNull());
  });

  it("closes on Escape", async () => {
    const user = userEvent.setup();
    await openPalette(user);

    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByPlaceholderText(/Search batches/)).toBeNull());
  });

  it("searches nothing until the query is worth a request", async () => {
    // Three endpoints per keystroke would be three requests for a single letter that matches
    // most of the estate.
    const user = userEvent.setup();
    const input = await openPalette(user);

    await user.type(input, "I");
    await waitFor(() => expect(screen.getByText(/at least 2 characters/)).toBeInTheDocument());
    expect(fetchTransactionList).not.toHaveBeenCalled();
  });

  it("returns results across all three entity types, labelled by type", async () => {
    const user = userEvent.setup();
    const input = await openPalette(user);

    await user.type(input, "I2626");

    expect(await screen.findByText("I2626-42")).toBeInTheDocument();
    expect(await screen.findByText("invoice.pdf")).toBeInTheDocument();
    expect(await screen.findByText("MSKU1234567")).toBeInTheDocument();
    // A batch number and a container number look alike; the headings are what tell them apart.
    expect(screen.getByText("Transactions")).toBeInTheDocument();
    expect(screen.getByText("Documents")).toBeInTheDocument();
    expect(screen.getByText("Shipments")).toBeInTheDocument();
  });

  it("asks all three endpoints with the same search term", async () => {
    const user = userEvent.setup();
    const input = await openPalette(user);

    await user.type(input, "I2626");
    await waitFor(() => expect(fetchTransactionList).toHaveBeenCalled());

    for (const call of [fetchTransactionList, fetchDocumentList, fetchShipmentList]) {
      expect(call).toHaveBeenCalledWith("t", expect.objectContaining({ search: "I2626" }));
    }
  });

  it("navigates to the selected result and closes", async () => {
    const user = userEvent.setup();
    const input = await openPalette(user);

    await user.type(input, "I2626");
    await user.click(await screen.findByText("I2626-42"));

    expect(push).toHaveBeenCalledWith("/transactions/purchase/tx-1");
    await waitFor(() => expect(screen.queryByPlaceholderText(/Search batches/)).toBeNull());
  });

  it("says so plainly when nothing matches", async () => {
    fetchTransactionList.mockResolvedValue({ items: [] });
    fetchDocumentList.mockResolvedValue({ items: [] });
    fetchShipmentList.mockResolvedValue({ items: [] });

    const user = userEvent.setup();
    const input = await openPalette(user);
    await user.type(input, "nothing-like-this");

    expect(await screen.findByText("Nothing matches that.")).toBeInTheDocument();
  });

  it("survives one endpoint failing without losing the other two", async () => {
    // A palette that showed nothing because the shipment list was briefly down would be worse
    // than one that shows what it could reach.
    fetchShipmentList.mockRejectedValue(new Error("shipments are down"));

    const user = userEvent.setup();
    const input = await openPalette(user);
    await user.type(input, "I2626");

    expect(await screen.findByText("I2626-42")).toBeInTheDocument();
    expect(await screen.findByText("invoice.pdf")).toBeInTheDocument();
    expect(screen.queryByText("MSKU1234567")).toBeNull();
  });

  it("carries an accessible name without drawing a heading over its own input", async () => {
    const user = userEvent.setup();
    await openPalette(user);

    expect(screen.getByRole("dialog", { name: "Search the platform" })).toBeInTheDocument();
  });
});
