import { describe, expect, it } from "vitest";

import {
  actorLabel,
  auditQueryString,
  canReadAuditTrail,
  entityTypeLabel,
  eventTypeLabel,
  metadataSummary,
} from "@/lib/audit";

describe("canReadAuditTrail", () => {
  it("opens the trail to admin and auditor, and to nobody else", () => {
    expect(canReadAuditTrail(["admin"])).toBe(true);
    expect(canReadAuditTrail(["auditor"])).toBe(true);
    expect(canReadAuditTrail(["approver_hod"])).toBe(false);
    expect(canReadAuditTrail([])).toBe(false);
  });
});

describe("eventTypeLabel", () => {
  it("renders an event type from any step without a lookup table", () => {
    // Deliberately derived rather than enumerated: ten steps have contributed to this vocabulary
    // and an eleventh will contribute more, so a hardcoded map would go stale on the day a new
    // event is first recorded.
    expect(eventTypeLabel("document.extraction_confirmed")).toBe(
      "Document - extraction confirmed",
    );
    expect(eventTypeLabel("integration.job.awaiting_manual_action")).toBe(
      "Integration - job awaiting manual action",
    );
    expect(eventTypeLabel("admin.rule_configuration.updated")).toBe(
      "Admin - rule configuration updated",
    );
    expect(eventTypeLabel("report.generated")).toBe("Report - generated");
  });

  it("handles a bare event type with no namespace", () => {
    expect(eventTypeLabel("heartbeat")).toBe("Heartbeat");
  });
});

describe("entityTypeLabel", () => {
  it("reads back the entity kinds every step writes against", () => {
    expect(entityTypeLabel("trade_transaction")).toBe("Trade transaction");
    expect(entityTypeLabel("exception_case")).toBe("Exception case");
    expect(entityTypeLabel("integration_job")).toBe("Integration job");
  });
});

describe("actorLabel", () => {
  it("names the person where there is one", () => {
    expect(actorLabel("user", "Marco Bellini", "marco@agfze.ae")).toBe(
      "Marco Bellini (marco@agfze.ae)",
    );
    expect(actorLabel("user", "Marco Bellini", null)).toBe("Marco Bellini");
  });

  it("names the platform as a real actor rather than as a missing one", () => {
    expect(actorLabel("system", null, null)).toBe("Platform");
    expect(actorLabel("agent", null, null)).toBe("AI agent");
  });
});

describe("metadataSummary", () => {
  it("renders the identifiers and counts an audit payload actually carries", () => {
    expect(
      metadataSummary({ batch_number: "26-CU-0001", decision: "approved", bulk: false }),
    ).toBe("batch number: 26-CU-0001 · decision: approved · bulk: false");
  });

  it("caps what it renders and says how much more there is", () => {
    const summary = metadataSummary({ a: 1, b: 2, c: 3, d: 4, e: 5, f: 6 }, 4);
    expect(summary).toContain("+2 more");
  });

  it("says so plainly when a row carries nothing further", () => {
    expect(metadataSummary({})).toBe("No further detail recorded.");
    expect(metadataSummary({ empty: "", missing: null })).toBe("No further detail recorded.");
  });
});

describe("auditQueryString", () => {
  it("carries only the filters that were set", () => {
    expect(auditQueryString({ event_type: "approval.decided", search: "" })).toBe(
      "?event_type=approval.decided",
    );
    expect(auditQueryString({})).toBe("");
  });
});
