import { describe, expect, it } from "vitest";

import {
  INVOICE_STATUSES,
  LOCKED_TRANSACTION_STATUSES,
  PRICE_BASES,
  TRANSACTION_STATUSES,
  TRANSACTION_STATUS_CHIP,
  TRANSACTION_STATUS_LABELS,
  canWriteTransactions,
  formatAge,
  formatMoney,
  formatQuantity,
  isAcknowledgeable,
  isBlocking,
  submitBlocker,
} from "@/lib/transactions";

describe("the transaction vocabulary", () => {
  it("mirrors the backend states and ends at committed", () => {
    expect(TRANSACTION_STATUSES).toEqual([
      "received",
      "classified",
      "extraction_pending",
      "extracted",
      "matched",
      "validation_pending",
      "approval_pending",
      "approved",
      "integration_pending",
      "committed",
    ]);
    // `closed` is declared by the backend and reachable by no code path at all, so naming it
    // here would put a state on the screen that no transaction can ever be in.
    expect(TRANSACTION_STATUSES).not.toContain("closed");
  });

  it("locks a transaction from the moment it leaves the preparing desk", () => {
    expect(LOCKED_TRANSACTION_STATUSES).toEqual([
      "approval_pending",
      "approved",
      "integration_pending",
      "committed",
    ]);
    for (const status of LOCKED_TRANSACTION_STATUSES) {
      expect(TRANSACTION_STATUSES).toContain(status);
    }
  });

  it("gives every status a label and a colour", () => {
    for (const status of TRANSACTION_STATUSES) {
      expect(TRANSACTION_STATUS_LABELS[status], status).toBeTruthy();
      expect(TRANSACTION_STATUS_CHIP[status], status).toBeTruthy();
    }
  });

  it("carries the invoice and pricing vocabularies exactly", () => {
    expect(INVOICE_STATUSES).toEqual(["provisional", "final"]);
    expect(PRICE_BASES).toEqual(["fixed", "lme_percent"]);
  });
});

describe("canWriteTransactions", () => {
  it("admits the purchase desk and an administrator", () => {
    expect(canWriteTransactions(["purchase_user"])).toBe(true);
    expect(canWriteTransactions(["admin"])).toBe(true);
  });

  it("keeps the approver, the auditor and the other desks out", () => {
    expect(canWriteTransactions(["approver_hod"])).toBe(false);
    expect(canWriteTransactions(["auditor"])).toBe(false);
    expect(canWriteTransactions(["sales_user"])).toBe(false);
    expect(canWriteTransactions([])).toBe(false);
  });
});

describe("rule presentation", () => {
  const hardFailure = { passed: false, severity: "hard" };
  const flagged = { passed: false, severity: "acknowledgeable" };
  const passing = { passed: true, severity: "acknowledgeable" };

  it("treats any failing rule as blocking", () => {
    expect(isBlocking(hardFailure)).toBe(true);
    expect(isBlocking(flagged)).toBe(true);
    expect(isBlocking(passing)).toBe(false);
  });

  it("offers the acknowledge action only on a failing, self-approvable rule", () => {
    expect(isAcknowledgeable(flagged)).toBe(true);
    // A hard failure is never self-approvable, whatever its size.
    expect(isAcknowledgeable(hardFailure)).toBe(false);
    expect(isAcknowledgeable(passing)).toBe(false);
  });
});

describe("submitBlocker", () => {
  const passingRule = {
    passed: true,
    rule_id: "BR-02",
    check_key: "reference_present",
    message: "References present.",
  };
  const failingRule = {
    passed: false,
    rule_id: "BR-05",
    check_key: "quantity_tolerance",
    message: "Invoiced quantity varies by 10.20%, outside the configured 5% tolerance.",
  };

  it("names the specific rule, check and reason", () => {
    expect(submitBlocker([passingRule, failingRule])).toBe(
      "BR-05 (quantity tolerance): Invoiced quantity varies by 10.20%, outside the configured 5% tolerance.",
    );
  });

  it("returns null once nothing is outstanding", () => {
    expect(submitBlocker([passingRule])).toBeNull();
  });

  it("returns null for a transaction with no evaluations at all", () => {
    expect(submitBlocker([])).toBeNull();
  });
});

describe("value formatting", () => {
  it("renders money to the cent with its currency", () => {
    expect(formatMoney("199062.50", "USD")).toBe("199,062.50 USD");
    expect(formatMoney(null)).toBe("—");
  });

  it("renders a quantity to three decimals in metric tons", () => {
    expect(formatQuantity("24.5")).toBe("24.500 MT");
    expect(formatQuantity(null)).toBe("—");
  });

  it("renders an age in whole days", () => {
    expect(formatAge(0)).toBe("Today");
    expect(formatAge(1)).toBe("1 day");
    expect(formatAge(9)).toBe("9 days");
  });
});
