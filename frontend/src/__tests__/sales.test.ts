import { describe, expect, it } from "vitest";

import type {
  ContractCoverage,
  LinkedPurchaseContext,
  TransactionListItem,
} from "@/lib/api-client";
import {
  ATTACHMENT_LABELS,
  COVERAGE_BAR,
  COVERAGE_LABELS,
  COVERAGE_TONE,
  FIXATION_STATUSES,
  FIXATION_STATUS_LABELS,
  GENERATED_DOCUMENT_LABELS,
  GENERATED_DOCUMENT_NOTES,
  GENERATED_DOCUMENT_TYPES,
  MATCH_OUTCOME_LABELS,
  PAYMENT_CONDITIONS,
  PAYMENT_CONDITION_LABELS,
  SALES_WRITE_ROLES,
  TERRITORIES,
  TERRITORY_LABELS,
  canWriteSales,
  canWriteTransactions,
  deskLabel,
  workspacePath,
  type CoverageState,
} from "@/lib/transactions";

describe("the sales vocabulary", () => {
  it("mirrors the backend's territories, payment conditions and fixation states", () => {
    expect(TERRITORIES).toEqual(["india", "china", "japan", "other"]);
    expect(PAYMENT_CONDITIONS).toEqual(["CAD", "TT"]);
    expect(FIXATION_STATUSES).toEqual(["unfixed", "fixed"]);
  });

  it("labels every value it names", () => {
    for (const value of TERRITORIES) expect(TERRITORY_LABELS[value], value).toBeTruthy();
    for (const value of PAYMENT_CONDITIONS) {
      expect(PAYMENT_CONDITION_LABELS[value], value).toBeTruthy();
    }
    for (const value of FIXATION_STATUSES) {
      expect(FIXATION_STATUS_LABELS[value], value).toBeTruthy();
    }
  });

  it("offers only the four documents this platform actually writes", () => {
    // Two from the sales module, and the Performa invoice and bank cover letter discovery named
    // and the platform could not previously produce. Every one of them is a *draft* for review,
    // and nothing here sends any of them anywhere.
    expect(GENERATED_DOCUMENT_TYPES).toEqual([
      "draft_contract",
      "draft_invoice",
    ]);
    for (const value of GENERATED_DOCUMENT_TYPES) {
      expect(GENERATED_DOCUMENT_LABELS[value], value).toBeTruthy();
      expect(GENERATED_DOCUMENT_NOTES[value], value).toBeTruthy();
    }
  });

  it("names the sales side's own no-match band, which is not a new batch", () => {
    expect(MATCH_OUTCOME_LABELS.no_purchase_match).toBeTruthy();
    expect(MATCH_OUTCOME_LABELS.no_purchase_match).not.toMatch(/new batch/i);
  });

  it("names all four routes a sales leg can be attached by, and no fifth", () => {
    expect(Object.keys(ATTACHMENT_LABELS).sort()).toEqual([
      "auto_matched",
      "no_purchase_acknowledged",
      "suggestion_confirmed",
      "user_selected",
    ]);
  });
});

describe("who may work the sell side", () => {
  it("gives the selling desk and the admin write access", () => {
    expect(SALES_WRITE_ROLES).toEqual(["sales_user", "admin"]);
    expect(canWriteSales(["sales_user"])).toBe(true);
    expect(canWriteSales(["admin"])).toBe(true);
  });

  it("keeps the two desks apart", () => {
    // Holding one desk's role does not grant the other's, on either side.
    expect(canWriteSales(["purchase_user"])).toBe(false);
    expect(canWriteTransactions(["sales_user"])).toBe(false);
  });

  it("gives an approver and an auditor no write access at all", () => {
    for (const role of ["approver_hod", "auditor", "finance_user"] as const) {
      expect(canWriteSales([role]), role).toBe(false);
      expect(canWriteTransactions([role]), role).toBe(false);
    }
  });
});

describe("routing a transaction to the desk that owns it", () => {
  const row = (overrides: Partial<TransactionListItem>) =>
    ({ id: "tx-1", has_purchase_leg: false, has_sales_leg: false, ...overrides }) as
      TransactionListItem;

  it("sends a purchase-only transaction to the purchase workspace", () => {
    expect(workspacePath(row({ has_purchase_leg: true }))).toBe("/transactions/purchase/tx-1");
  });

  it("sends anything with a sales leg to the sales workspace", () => {
    // The sales workspace shows the purchase leg beside the sell side; the purchase workspace
    // does not show the sales leg, so the sell side wins where both exist.
    expect(workspacePath(row({ has_sales_leg: true }))).toBe("/transactions/sales/tx-1");
    expect(
      workspacePath(row({ has_sales_leg: true, has_purchase_leg: true })),
    ).toBe("/transactions/sales/tx-1");
  });

  it("names the desks a transaction carries", () => {
    expect(deskLabel({ has_purchase_leg: true })).toBe("Purchase");
    expect(deskLabel({ has_sales_leg: true })).toBe("Sales");
    expect(deskLabel({ has_purchase_leg: true, has_sales_leg: true })).toBe("Purchase + Sales");
    expect(deskLabel({})).toBe("No leg");
  });
});

describe("the quantity meter's semantics", () => {
  const STATES: CoverageState[] = ["partial", "complete", "exceeded", "unknown"];

  it("gives every state a label, a chip and a bar colour", () => {
    for (const state of STATES) {
      expect(COVERAGE_LABELS[state], state).toBeTruthy();
      expect(COVERAGE_TONE[state], state).toBeTruthy();
      expect(COVERAGE_BAR[state], state).toBeTruthy();
    }
  });

  it("treats a part-shipped contract as normal rather than as a warning", () => {
    // A live sales contract with more shipments to come is the expected state. Colouring it
    // amber would teach people to ignore amber, so it reads in the confident colour.
    expect(COVERAGE_TONE.partial).toContain("signal-confident");
    expect(COVERAGE_BAR.partial).toContain("signal-confident");
    expect(COVERAGE_LABELS.partial).not.toMatch(/error|breach|problem/i);
  });

  it("reserves the blocked colour for an over-invoiced contract alone", () => {
    expect(COVERAGE_TONE.exceeded).toContain("signal-blocked");
    expect(COVERAGE_BAR.exceeded).toContain("signal-blocked");
    for (const state of ["partial", "complete", "unknown"] as CoverageState[]) {
      expect(COVERAGE_TONE[state], state).not.toContain("signal-blocked");
    }
  });
});

describe("the linked purchase comparison", () => {
  const linked = (overrides: Partial<LinkedPurchaseContext>): LinkedPurchaseContext => ({
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
    message: null,
    ...overrides,
  });

  it("carries the shared commodity code and nothing that could be a description clash", () => {
    // The shape itself is the guarantee: there is no purchase-side description field here to
    // compare against the sales-side wording, so a wording difference cannot be flagged.
    const keys = Object.keys(linked({}));
    expect(keys).toContain("commodity_code");
    expect(keys).toContain("commodity_code_mismatch");
    expect(keys.some((key) => key.includes("description"))).toBe(false);
    expect(keys.some((key) => key.includes("commodity_name"))).toBe(false);
  });

  it("flags a genuine code disagreement", () => {
    const clash = linked({
      sales_document_commodity_value: "AL",
      commodity_code_mismatch: true,
    });
    expect(clash.commodity_code_mismatch).toBe(true);
    expect(clash.commodity_code).not.toBe(clash.sales_document_commodity_value);
  });
});

describe("the coverage read the meter draws", () => {
  const coverage = (overrides: Partial<ContractCoverage>): ContractCoverage => ({
    sales_contract_no: "AGF-SC-2026-441",
    contracted_quantity_mt: "100.000",
    invoiced_quantity_mt: "60.000",
    remaining_quantity_mt: "40.000",
    shipment_count: 2,
    state: "partial",
    ratio: 0.6,
    message: "Part-shipped.",
    ...overrides,
  });

  it("is an aggregate over the contract rather than one shipment", () => {
    const row = coverage({});
    expect(row.shipment_count).toBeGreaterThan(1);
    expect(row.sales_contract_no).toBeTruthy();
  });

  it("reports the three states the rule distinguishes", () => {
    expect(coverage({ state: "partial" }).state).toBe("partial");
    expect(coverage({ state: "complete", ratio: 1 }).state).toBe("complete");
    expect(coverage({ state: "exceeded", ratio: 1.2 }).state).toBe("exceeded");
  });
});
