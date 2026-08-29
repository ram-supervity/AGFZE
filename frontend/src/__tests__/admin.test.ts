import { describe, expect, it } from "vitest";

import {
  ADMIN_AREAS,
  MIN_CHANGE_REASON,
  canAdminister,
  canReadAudit,
  channelNote,
  documentTypeLabel,
  formatThreshold,
  reasonIsValid,
  reportTypeLabel,
  scopeLabel,
  territoryLabel,
} from "@/lib/admin";

describe("ADMIN_AREAS", () => {
  it("lists exactly the administration screens that exist", () => {
    expect(ADMIN_AREAS.map((area) => area.key)).toEqual([
      "users",
      "rules",
      "document-types",
      "audit",
      "report-distribution",
      "report-templates",
      "integrations",
    ]);
  });

  it("has no screen for anything deliberately left out of the admin module", () => {
    // Each exclusion is its own decision, not an oversight. The tracker/SAP/DMS endpoints are
    // infrastructure and change by deployment; the rule-to-exception-category mapping decides
    // which desk owns which failure and stays seed data.
    //
    // Two entries are deliberately not on this list any more. Report *distribution* is the one
    // piece of configuration whose effect is that a person is contacted, which is precisely why
    // it earns a screen with a mandatory reason and an audit trail. Report *templates* are here
    // because the governing material asks for the exact report structures to be confirmed with
    // AGFZE, and a conversation should not need a release - the screen edits structure only, and
    // no figure is reachable from it.
    const hrefs = ADMIN_AREAS.map((area) => area.href);
    for (const excluded of [
      "/admin/integration-config",
      "/admin/tracker",
      "/admin/sap",
      "/admin/dms",
      "/admin/exception-mapping",
      "/admin/rule-categories",
    ]) {
      expect(hrefs).not.toContain(excluded);
    }
  });

  it("gives every area a summary a reader can act on", () => {
    for (const area of ADMIN_AREAS) {
      expect(area.summary.trim().length, area.key).toBeGreaterThan(20);
      expect(area.href, area.key).toMatch(/^\/admin\//);
    }
  });
});

describe("role gates", () => {
  it("keeps the administration screens to the admin role", () => {
    expect(canAdminister(["admin"])).toBe(true);
    expect(canAdminister(["auditor"])).toBe(false);
    expect(canAdminister(["approver_hod"])).toBe(false);
    expect(canAdminister([])).toBe(false);
  });

  it("opens the audit trail to the auditor as well as the admin", () => {
    expect(canReadAudit(["admin"])).toBe(true);
    expect(canReadAudit(["auditor"])).toBe(true);
    expect(canReadAudit(["finance_user"])).toBe(false);
  });
});

describe("reasonIsValid", () => {
  it("refuses a blank, a whitespace-only and a token reason", () => {
    expect(reasonIsValid("")).toBe(false);
    expect(reasonIsValid("     ")).toBe(false);
    expect(reasonIsValid("ok")).toBe(false);
    expect(reasonIsValid("x".repeat(MIN_CHANGE_REASON - 1))).toBe(false);
  });

  it("accepts a reason at or above the floor the API enforces", () => {
    expect(reasonIsValid("x".repeat(MIN_CHANGE_REASON))).toBe(true);
    expect(reasonIsValid("Confirmed with the trading desk on 12 May.")).toBe(true);
  });
});

describe("scopeLabel", () => {
  const unscoped = {
    scope_commodity_code: null,
    scope_transaction_type: null,
    scope_stream: null,
  };

  it("says plainly that an unscoped row is the default for everything", () => {
    expect(scopeLabel(unscoped)).toBe("Applies to everything");
  });

  it("renders an FA-stream row seeded in Step 6 the same way as any other", () => {
    expect(scopeLabel({ ...unscoped, scope_stream: "fa" })).toBe("fa stream");
  });

  it("renders a commodity-scoped row narrowest-first", () => {
    expect(
      scopeLabel({
        scope_commodity_code: "CU",
        scope_transaction_type: "purchase",
        scope_stream: "scrap",
      }),
    ).toBe("CU · purchase · scrap stream");
  });
});

describe("formatThreshold", () => {
  it("renders a percentage as a percentage", () => {
    expect(formatThreshold("2.0000", "percent")).toBe("2%");
  });

  it("keeps a meaningful decimal", () => {
    expect(formatThreshold("0.7500", "percent")).toBe("0.75%");
  });

  it("names the unit where it is not a percentage", () => {
    expect(formatThreshold("50000.0000", "currency")).toBe("50000 currency");
    expect(formatThreshold("2.0000", "count")).toBe("2 count");
  });
});

describe("labels", () => {
  it("names every document type this platform recognises, including the generated ones", () => {
    expect(documentTypeLabel("bl_draft")).toBe("Draft bill of lading");
    expect(documentTypeLabel("fa_document")).toBe("FA document");
    expect(documentTypeLabel("draft_invoice")).toBe("Draft invoice (generated)");
  });

  it("falls back readably for a document type a later step adds", () => {
    expect(documentTypeLabel("customs_declaration")).toBe("customs declaration");
  });

  it("says a null territory applies everywhere rather than showing a blank", () => {
    expect(territoryLabel(null)).toBe("Every territory");
    expect(territoryLabel("india")).toBe("India");
  });
});


describe("report distribution", () => {
  it("names the two scheduled reports the way the business does", () => {
    expect(reportTypeLabel("daily")).toBe("Daily operations");
    expect(reportTypeLabel("monthly")).toBe("Monthly management");
  });

  it("falls back to a readable label for a report type it does not know", () => {
    expect(reportTypeLabel("quarterly_board")).toBe("quarterly board");
  });

  it("says plainly that in-app never emails, even somebody who asked to be emailed", () => {
    // The ceiling-not-floor behaviour is the part an administrator would otherwise get wrong, so
    // the screen has to state it rather than leave it to be inferred from the word "In-app".
    expect(channelNote("in_app")).toContain("No email is sent");
    expect(channelNote("in_app")).toContain("even to recipients who have asked to be emailed");
  });

  it("says plainly that choosing email still never emails somebody who did not ask", () => {
    for (const channel of ["email", "both"]) {
      expect(channelNote(channel)).toContain("never emails somebody who did not ask");
    }
  });

  it("gives report distribution a screen of its own", () => {
    const area = ADMIN_AREAS.find((item) => item.key === "report-distribution");
    expect(area?.href).toBe("/admin/report-distribution");
    // The summary has to say the empty state is deliberate, because an administrator opening an
    // empty screen should not conclude the feature is broken.
    expect(area?.summary).toContain("reaches nobody");
  });
});
