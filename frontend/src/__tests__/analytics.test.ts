import { describe, expect, it } from "vitest";

import {
  LIFECYCLE_PHASES,
  canGenerateReports,
  drillThroughHref,
  formatFigure,
  formatHours,
  freshnessNote,
  orderedPanels,
  phaseSlices,
  toCsv,
} from "@/lib/analytics";
import { TRANSACTION_STATUSES } from "@/lib/transactions";

describe("drillThroughHref", () => {
  it("turns a figure's declared target and filters into the filtered queue's URL", () => {
    expect(
      drillThroughHref({ target: "exceptions", filters: { exception_type: "low_confidence", status: "open" } }),
    ).toBe("/exceptions?exception_type=low_confidence&status=open");
  });

  it("returns null for a figure that declares no target, so nothing renders a dead link", () => {
    expect(drillThroughHref({ target: null, filters: { status: "approved" } })).toBeNull();
    expect(drillThroughHref({ target: "not_a_screen", filters: {} })).toBeNull();
  });

  it("drops empty filters rather than sending an empty query parameter", () => {
    expect(drillThroughHref({ target: "transactions", filters: { status: "", stream: null } })).toBe(
      "/transactions",
    );
  });

  it("sends the integration drill-through to the monitor, not to the transaction list", () => {
    // Failed and awaiting-a-person are separate states of separate jobs, and each one opens the
    // queue filtered to itself. Neither ever links to a merged view of both.
    expect(drillThroughHref({ target: "integrations", filters: { status: "failed" } })).toBe(
      "/admin/integrations?status=failed",
    );
    expect(
      drillThroughHref({ target: "integrations", filters: { status: "awaiting_manual_action" } }),
    ).toBe("/admin/integrations?status=awaiting_manual_action");
  });
});

describe("phaseSlices", () => {
  const figures = TRANSACTION_STATUSES.map((status, index) => ({
    key: `transactions.${status}`,
    label: status,
    value: index + 1,
    target: "transactions",
    filters: { status },
  }));

  it("covers every reachable status exactly once across the five phases", () => {
    const covered = LIFECYCLE_PHASES.flatMap((phase) => phase.statuses);
    expect([...covered].sort()).toEqual([...TRANSACTION_STATUSES].sort());
    expect(new Set(covered).size).toBe(covered.length);
  });

  it("sums each phase from the statuses inside it", () => {
    const slices = phaseSlices(figures);
    // received 1 + classified 2 + extraction_pending 3 + extracted 4
    expect(slices[0].value).toBe(10);
    // matched 5 + validation_pending 6
    expect(slices[1].value).toBe(11);
    expect(slices.reduce((total, slice) => total + slice.value, 0)).toBe(
      figures.reduce((total, figure) => total + figure.value, 0),
    );
  });

  it("reports a real zero for a phase nothing is in", () => {
    const slices = phaseSlices([{ key: "transactions.matched", label: "Matched", value: 3 }]);
    expect(slices.find((slice) => slice.key === "committed")?.value).toBe(0);
    expect(slices).toHaveLength(LIFECYCLE_PHASES.length);
  });

  it("names the statuses inside every phase, so the grouping hides nothing", () => {
    for (const slice of phaseSlices(figures)) {
      expect(slice.statuses.length).toBeGreaterThan(0);
      for (const status of slice.statuses) {
        expect(typeof status.value).toBe("number");
      }
    }
  });
});

describe("orderedPanels", () => {
  it("leads with the panel the account's desk emphasises and keeps every other one", () => {
    expect(orderedPanels("shipments")[0]).toBe("shipments");
    expect(orderedPanels("shipments")).toContain("exceptions");
    expect(orderedPanels("shipments")).toHaveLength(orderedPanels("transactions").length);
  });

  it("falls back to the default order for an emphasis it does not recognise", () => {
    expect(orderedPanels("automation")).toEqual(orderedPanels("transactions"));
  });
});

describe("formatting", () => {
  it("renders a percentage, an hour count and a plain count in their own units", () => {
    expect(formatFigure(72.5, "percent")).toBe("72.5%");
    expect(formatFigure(18.25, "hours")).toBe("18.3h");
    expect(formatFigure(1204)).toBe("1,204");
  });

  it("renders a missing figure as a gap rather than as a zero", () => {
    // "No approval was decided, so there is no turnaround" and "turnaround was zero" are
    // different statements, and only one of them is true.
    expect(formatFigure(null, "percent")).toBe("—");
    expect(formatHours(null)).toBe("—");
  });

  it("switches to days once an hour count stops being readable", () => {
    expect(formatHours(6)).toBe("6h");
    expect(formatHours(96)).toBe("4d");
  });

  it("says how old a cached figure is rather than implying it is live", () => {
    expect(freshnessNote(0, 45)).toContain("just now");
    expect(freshnessNote(12, 45)).toContain("12 seconds ago");
  });
});

describe("canGenerateReports", () => {
  it("offers generation to an administrator and the HOD only", () => {
    expect(canGenerateReports(["admin"])).toBe(true);
    expect(canGenerateReports(["approver_hod"])).toBe(true);
    expect(canGenerateReports(["finance_user"])).toBe(false);
    expect(canGenerateReports(["auditor"])).toBe(false);
    expect(canGenerateReports([])).toBe(false);
  });
});

describe("toCsv", () => {
  it("writes a header row and quotes anything that would break the format", () => {
    const csv = toCsv(
      [
        { key: "day", label: "Day" },
        { key: "note", label: "Note" },
      ],
      [{ day: "2026-08-01", note: 'Contains, a comma and a "quote"' }],
    );
    expect(csv.split("\n")[0]).toBe("Day,Note");
    expect(csv).toContain('"Contains, a comma and a ""quote"""');
  });

  it("renders a missing value as empty rather than as the word undefined", () => {
    expect(toCsv([{ key: "value", label: "Value" }], [{}])).toBe("Value\n");
  });
});
