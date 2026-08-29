import { describe, expect, it } from "vitest";

import {
  BILL_OF_LADING_TYPES,
  BILL_OF_LADING_TYPE_LABELS,
  SHIPMENT_ISSUE_TYPES,
  SHIPMENT_ISSUE_TYPE_LABELS,
  SHIPMENT_MILESTONES,
  SHIPMENT_MILESTONE_LABELS,
  SHIPMENT_STATUSES,
  SHIPMENT_STATUS_CHIP,
  SHIPMENT_STATUS_LABELS,
  canManageShipments,
  formatDate,
  formatDateTime,
  sourceLabel,
  stalenessLabel,
  stalenessTone,
  trackingModeNote,
} from "@/lib/shipments";
import { deskLabel, workspacePath } from "@/lib/transactions";

describe("shipment vocabularies", () => {
  it("mirrors the backend's four statuses and labels every one", () => {
    expect(SHIPMENT_STATUSES).toEqual(["on_schedule", "delayed", "arrived", "exception"]);
    for (const status of SHIPMENT_STATUSES) {
      expect(SHIPMENT_STATUS_LABELS[status]).toBeTruthy();
      expect(SHIPMENT_STATUS_CHIP[status]).toBeTruthy();
    }
  });

  it("has no status meaning 'tracked by hand'", () => {
    // The whole design turns on this: how a status was established is provenance, not a state.
    // A vocabulary that could express "manually tracked" would invite the screen to branch on it.
    for (const status of SHIPMENT_STATUSES) {
      expect(status).not.toMatch(/manual|auto/);
    }
  });

  it("labels every milestone, including the honest unknown", () => {
    for (const milestone of SHIPMENT_MILESTONES) {
      expect(SHIPMENT_MILESTONE_LABELS[milestone]).toBeTruthy();
    }
    expect(SHIPMENT_MILESTONE_LABELS.unknown).toBe("Not yet reported");
  });

  it("labels every bill-of-lading type and issue type", () => {
    for (const type of BILL_OF_LADING_TYPES) {
      expect(BILL_OF_LADING_TYPE_LABELS[type]).toBeTruthy();
    }
    for (const type of SHIPMENT_ISSUE_TYPES) {
      expect(SHIPMENT_ISSUE_TYPE_LABELS[type]).toBeTruthy();
    }
  });
});

describe("canManageShipments", () => {
  it("offers the write actions to the logistics desk and to admin, and to nobody else", () => {
    expect(canManageShipments(["logistics_user"])).toBe(true);
    expect(canManageShipments(["admin"])).toBe(true);
    expect(canManageShipments(["sales_user"])).toBe(false);
    expect(canManageShipments(["purchase_user", "auditor"])).toBe(false);
    expect(canManageShipments([])).toBe(false);
  });
});

describe("stalenessLabel", () => {
  it("says plainly when nobody has ever checked", () => {
    expect(stalenessLabel(400, null)).toBe("Never checked");
  });

  it("reads at a glance across the whole range", () => {
    expect(stalenessLabel(0.2, "2026-08-28T09:00:00Z")).toBe("Checked just now");
    expect(stalenessLabel(6, "2026-08-28T09:00:00Z")).toBe("Checked 6h ago");
    expect(stalenessLabel(30, "2026-08-27T09:00:00Z")).toBe("Checked 1 day ago");
    expect(stalenessLabel(80, "2026-08-25T09:00:00Z")).toBe("Checked 3 days ago");
  });

  it("tints a never-checked shipment the same as a stale one", () => {
    // Both mean the same thing to the desk: nobody knows where this cargo is.
    expect(stalenessTone(false, null)).toBe(stalenessTone(true, "2026-08-25T09:00:00Z"));
  });
});

describe("sourceLabel", () => {
  it("names the source as provenance without dressing either up", () => {
    expect(sourceLabel(null)).toBe("Not yet checked");
    expect(sourceLabel("manual")).toBe("Entered by hand");
    expect(sourceLabel("some-carrier")).toBe("Reported by some-carrier");
  });
});

describe("trackingModeNote", () => {
  it("says plainly that nothing is connected, rather than leaving a user guessing", () => {
    const note = trackingModeNote(0);
    expect(note).toMatch(/no carrier tracking source is connected/i);
    expect(note).toMatch(/by hand/i);
    // And it says the manual path is equivalent, not a lesser one.
    expect(note).toMatch(/same fields/i);
  });

  it("still says the manual path covers whatever an adapter does not", () => {
    expect(trackingModeNote(2)).toMatch(/kept current by hand/i);
  });
});

describe("formatDate", () => {
  it("renders an em dash for an absent date rather than a misleading today", () => {
    expect(formatDate(null)).toBe("-");
    expect(formatDate(undefined)).toBe("-");
  });

  it("reads the same instant wherever the reader is", () => {
    // Server-rendered and rendered again during hydration. Left to the runtime's own zone the
    // two disagree - the Node server is UTC and the browser is not - and React throws away the
    // server's markup for the subtree. Both of these are late enough in a UTC day that any
    // eastward zone would roll them to the next one.
    expect(formatDate("2026-03-31T23:30:00Z")).toBe("31 Mar 2026");
    expect(formatDateTime("2026-03-31T23:30:00Z")).toBe("31 Mar 2026, 23:30 UTC");
  });

  it("says which zone the time is in, so nobody reads it as their own", () => {
    expect(formatDateTime("2026-03-31T23:30:00Z")).toContain("UTC");
  });
});

describe("workspacePath", () => {
  it("sends an FA transaction to the FA workspace", () => {
    expect(workspacePath({ id: "abc", has_fa_leg: true })).toBe("/transactions/fa/abc");
  });

  it("still sends the two scrap-side legs where they always went", () => {
    expect(workspacePath({ id: "abc", has_sales_leg: true })).toBe("/transactions/sales/abc");
    expect(workspacePath({ id: "abc" })).toBe("/transactions/purchase/abc");
  });

  it("never routes an FA transaction to a scrap workspace, whatever else is set", () => {
    // An FA transaction cannot carry another leg, so there is no ambiguity to resolve - but if
    // one somehow arrived, the FA workspace is still the only one that can render it.
    expect(workspacePath({ id: "abc", has_fa_leg: true, has_sales_leg: true })).toBe(
      "/transactions/fa/abc",
    );
  });
});

describe("deskLabel", () => {
  it("names the FA desk", () => {
    expect(deskLabel({ has_fa_leg: true })).toBe("FA");
  });

  it("leaves the existing labels alone", () => {
    expect(deskLabel({ has_purchase_leg: true, has_sales_leg: true })).toBe("Purchase + Sales");
    expect(deskLabel({ has_purchase_leg: true })).toBe("Purchase");
    expect(deskLabel({})).toBe("No leg");
  });
});
