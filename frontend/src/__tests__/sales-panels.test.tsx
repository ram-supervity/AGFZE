import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { LinkedPurchaseCard } from "@/components/transactions/linked-purchase-card";
import { QuantityMeter } from "@/components/transactions/quantity-meter";
import type {
  ContractCoverage,
  LinkedPurchaseContext,
  TransactionDetail,
} from "@/lib/api-client";

const DETAIL = { currency: "USD" } as TransactionDetail;

function linked(overrides: Partial<LinkedPurchaseContext> = {}): LinkedPurchaseContext {
  return {
    present: true,
    supplier_name: "Emirates Metal Trading LLC",
    contract_number: "AGF-CT-2026-118",
    supplier_invoice_number: "INV-2026-0451",
    invoice_status: "provisional",
    port_of_loading: "Jebel Ali",
    amount: "199062.50",
    rate: "8125.00",
    commodity_code: "CU",
    sales_document_commodity_value: "CU",
    commodity_code_mismatch: false,
    // The server's own wording, verbatim, so the assertion below tests what a user actually sees.
    message:
      "The sales document's grade resolves to CU, which is the batch's own grade. The " +
      "description wording on the two sides may legitimately differ; the code agrees.",
    ...overrides,
  };
}

function coverage(overrides: Partial<ContractCoverage> = {}): ContractCoverage {
  return {
    sales_contract_no: "AGF-SC-2026-441",
    contracted_quantity_mt: "100.000",
    invoiced_quantity_mt: "60.000",
    remaining_quantity_mt: "40.000",
    shipment_count: 2,
    state: "partial",
    ratio: 0.6,
    message: "Part-shipped, with further shipments expected against this contract.",
    ...overrides,
  };
}

describe("the linked purchase leg card", () => {
  it("shows the supplier context beside the shared commodity code", () => {
    render(
      <LinkedPurchaseCard
        detail={DETAIL}
        // The grade as a destination's paperwork words it, which is what the server stores.
        linked={linked({ sales_document_commodity_value: "Copper Millberry 99.9%" })}
      />,
    );

    expect(screen.getByText("Emirates Metal Trading LLC")).toBeInTheDocument();
    expect(screen.getByText("AGF-CT-2026-118")).toBeInTheDocument();
    expect(screen.getByText("Codes agree")).toBeInTheDocument();
    expect(screen.queryByText(/mismatch/i)).not.toBeInTheDocument();
  });

  it("shouts about a genuine code disagreement", () => {
    render(
      <LinkedPurchaseCard
        detail={DETAIL}
        linked={linked({
          sales_document_commodity_value: "AL",
          commodity_code_mismatch: true,
          message: "The sales document's grade disagrees with this batch's.",
        })}
      />,
    );

    expect(screen.getByText("Commodity code mismatch")).toBeInTheDocument();
    expect(screen.getByText(/disagrees with this batch/i)).toBeInTheDocument();
  });

  it("says plainly that wording differences are expected and are not flagged", () => {
    // The card's own copy is what stops a user reading a differently-worded description as a
    // problem. A China-bound shipment legitimately describes the same grade differently.
    render(<LinkedPurchaseCard detail={DETAIL} linked={linked()} />);

    expect(
      screen.getByText(/description wording on the two sides may legitimately differ/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/the code agrees/i)).toBeInTheDocument();
  });

  it("says so when the batch has no purchase leg at all", () => {
    render(<LinkedPurchaseCard detail={DETAIL} linked={linked({ present: false })} />);

    expect(screen.getByText(/no purchase leg/i)).toBeInTheDocument();
  });
});

describe("the quantity meter", () => {
  it("reports the summed position across every shipment on the contract", () => {
    render(<QuantityMeter coverage={coverage()} />);

    expect(screen.getByText("AGF-SC-2026-441")).toBeInTheDocument();
    expect(screen.getByText(/60\.000 MT invoiced/)).toBeInTheDocument();
    expect(screen.getByText(/100\.000 MT contracted/)).toBeInTheDocument();
    // The whole point: it is a fact about the contract, not about this shipment. The contract
    // number sits in its own element, so the sentence around it is matched on its own node.
    expect(screen.getByText(/Summed across every shipment on sales contract/i))
      .toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "60");
  });

  it("reads part-shipped as a normal state rather than an outstanding one", () => {
    render(<QuantityMeter coverage={coverage()} />);

    expect(screen.getByText("Part-shipped")).toBeInTheDocument();
    expect(screen.getByText("Still to ship")).toBeInTheDocument();
    expect(screen.getByText(/further shipments expected/i)).toBeInTheDocument();
  });

  it("reads an over-invoiced contract as a breach and states the overspill", () => {
    render(
      <QuantityMeter
        coverage={coverage({
          invoiced_quantity_mt: "130.000",
          remaining_quantity_mt: "-30.000",
          state: "exceeded",
          ratio: 1.3,
          message: "More has been invoiced against this contract than the contract covers.",
        })}
      />,
    );

    expect(screen.getByText("Over-invoiced")).toBeInTheDocument();
    expect(screen.getByText("Over by")).toBeInTheDocument();
    // The figure appears both as the overspill and inside the message; either is the point.
    expect(screen.getAllByText(/30\.000 MT/).length).toBeGreaterThan(0);
    expect(screen.getByText(/than the contract covers/i)).toBeInTheDocument();
  });

  it("says nothing it cannot know when no contracted total is recorded", () => {
    render(
      <QuantityMeter
        coverage={coverage({
          contracted_quantity_mt: null,
          remaining_quantity_mt: null,
          state: "unknown",
          ratio: 0,
          message: "No contracted total is recorded for this sales contract.",
        })}
      />,
    );

    // Said in the chip and again on the meter's own track, rather than a figure being invented
    // to fill the gap.
    expect(screen.getAllByText(/^no contracted total recorded$/i)).toHaveLength(2);
    expect(
      screen.getByText(/No contracted total is recorded for this sales contract/i),
    ).toBeInTheDocument();
  });
});
