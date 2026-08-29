import { describe, expect, it } from "vitest";

import {
  APPROVAL_DECISIONS,
  DECISIONS_NEEDING_REASON,
  EXCEPTION_CATEGORIES,
  ageBand,
  canDecideApprovals,
  canWorkExceptions,
  formatAgeHours,
  ownerLabel,
} from "@/lib/governance";

describe("EXCEPTION_CATEGORIES", () => {
  it("carries all ten categories of the matrix, including the three nothing can raise yet", () => {
    expect(EXCEPTION_CATEGORIES).toHaveLength(10);
    for (const dormant of [
      "mismatched_container_number",
      "shipment_status_unavailable",
      "integration_failure",
    ] as const) {
      expect(EXCEPTION_CATEGORIES).toContain(dormant);
    }
  });
});

describe("ageBand", () => {
  it("moves with the configured threshold rather than a fixed number of hours", () => {
    expect(ageBand(4, 48)).toBe("fresh");
    expect(ageBand(30, 48)).toBe("warm");
    expect(ageBand(48, 48)).toBe("breached");

    // The same age against a tighter threshold is a different band, which is the whole point.
    expect(ageBand(30, 12)).toBe("breached");
  });

  it("never claims a breach when nothing is configured", () => {
    expect(ageBand(1000, 0)).toBe("fresh");
  });
});

describe("formatAgeHours", () => {
  it("reads in hours below a day and days above it", () => {
    expect(formatAgeHours(0.4)).toBe("Under an hour");
    expect(formatAgeHours(1)).toBe("1 hour");
    expect(formatAgeHours(5.9)).toBe("5 hours");
    expect(formatAgeHours(24)).toBe("1 day");
    expect(formatAgeHours(73)).toBe("3 days");
  });
});

describe("decisions", () => {
  it("asks for a reason on exactly the two that send a transaction back", () => {
    expect(DECISIONS_NEEDING_REASON).toEqual(["rejected", "changes_requested"]);
    expect(DECISIONS_NEEDING_REASON).not.toContain("approved");
  });

  it("knows no decision beyond approve, reject and request changes", () => {
    // Nothing resembling "posted", "synced" or "committed" exists as an outcome.
    expect([...APPROVAL_DECISIONS]).toEqual([
      "pending",
      "approved",
      "rejected",
      "changes_requested",
    ]);
  });
});

describe("role helpers", () => {
  it("lets only the approver and the admin decide", () => {
    expect(canDecideApprovals(["approver_hod"])).toBe(true);
    expect(canDecideApprovals(["admin"])).toBe(true);
    expect(canDecideApprovals(["purchase_user"])).toBe(false);
    expect(canDecideApprovals(["auditor"])).toBe(false);
  });

  it("lets the desks work exceptions and keeps the approver and auditor out of the resolve path", () => {
    expect(canWorkExceptions(["purchase_user"])).toBe(true);
    expect(canWorkExceptions(["finance_user"])).toBe(true);
    expect(canWorkExceptions(["approver_hod"])).toBe(false);
    expect(canWorkExceptions(["auditor"])).toBe(false);
  });
});

describe("ownerLabel", () => {
  it("reads a role identifier back as the desk it names", () => {
    expect(ownerLabel("purchase_user")).toBe("Purchase User");
    expect(ownerLabel("approver_hod")).toBe("Approver HOD");
  });
});
