import { describe, expect, it } from "vitest";

import { NAV_ITEMS, visibleNavChildren, visibleNavItems } from "@/lib/navigation";
import type { PlatformRole } from "@/lib/roles";

const allKeys = NAV_ITEMS.map((item) => item.key);
const keysFor = (roles: PlatformRole[]) => visibleNavItems(roles).map((item) => item.key);

describe("NAV_ITEMS", () => {
  it("declares the twelve modules in navigation order", () => {
    // Admin becomes a real section in Step 9, and Settings and Notifications join it as the last
    // two entries that had been "coming soon" since the very first step.
    expect(allKeys).toEqual([
      "dashboard",
      "inbox",
      "transactions",
      "documents",
      "exceptions",
      "approvals",
      "shipments",
      "analytics",
      "reports",
      "admin",
      "notifications",
      "settings",
    ]);
  });

  it("leaves nothing deferred, and gives no live module an arrival step", () => {
    // Step 9 is where the sidebar stops promising anything. Every module in it is a working
    // screen, so none of them carries an arrival step any more.
    expect(NAV_ITEMS.filter((item) => item.status !== "available")).toEqual([]);
    for (const item of NAV_ITEMS) {
      expect(item.availableFrom, item.key).toBeUndefined();
    }
  });

  it("gives every module a summary", () => {
    for (const item of NAV_ITEMS) {
      expect(item.summary.trim().length, item.key).toBeGreaterThan(0);
    }
  });

  it("derives every href from its key", () => {
    for (const item of NAV_ITEMS) {
      expect(item.href, item.key).toBe(`/${item.key}`);
    }
  });
});

describe("visibleNavItems", () => {
  it("shows an admin every module", () => {
    expect(keysFor(["admin"])).toEqual(allKeys);
  });

  it("shows an auditor the admin section too, for the audit trail inside it", () => {
    // The Auditor role exists for independent oversight of the trail, so the section that holds
    // the audit explorer has to be reachable. Which screens inside it they may open is a
    // narrower question `visibleNavChildren` answers, and the API answers again on every call.
    expect(keysFor(["auditor"])).toEqual(allKeys);
    expect(visibleNavChildren(NAV_ITEMS.find((item) => item.key === "admin")!, ["auditor"])).toEqual(
      [expect.objectContaining({ href: "/admin/audit" })],
    );
  });

  it("offers the approver the exception queue, because it owns a category of its own", () => {
    expect(keysFor(["approver_hod"])).toContain("exceptions");
    expect(keysFor(["approver_hod"])).toContain("approvals");
  });

  it("shows a logistics user only the modules that touch its work, plus its own two", () => {
    // Settings and Notifications are everybody's: your own preferences and your own messages are
    // not a desk's business, they are yours.
    expect(keysFor(["logistics_user"])).toEqual([
      "dashboard",
      "inbox",
      "documents",
      "exceptions",
      "approvals",
      "shipments",
      "notifications",
      "settings",
    ]);
  });

  it("gives the oversight roles and finance the analytics and reports screens", () => {
    for (const role of ["approver_hod", "finance_user", "admin", "auditor"] as const) {
      expect(keysFor([role]), role).toContain("analytics");
      expect(keysFor([role]), role).toContain("reports");
    }
    expect(keysFor(["purchase_user"])).not.toContain("analytics");
    expect(keysFor(["purchase_user"])).not.toContain("reports");
  });

  it("keeps the admin section away from every desk role", () => {
    for (const role of ["purchase_user", "sales_user", "fa_user", "logistics_user", "finance_user", "approver_hod"] as const) {
      expect(keysFor([role]), role).not.toContain("admin");
    }
  });

  it("offers the shipment board to every signed-in role, and writes to none of them", () => {
    for (const role of ["purchase_user", "sales_user", "fa_user", "finance_user"] as const) {
      expect(keysFor([role])).toContain("shipments");
    }
  });

  it("offers transactions to the desks that own a deal", () => {
    expect(keysFor(["purchase_user"])).toContain("transactions");
    expect(keysFor(["approver_hod"])).toContain("transactions");
    expect(keysFor(["auditor"])).toContain("transactions");
    expect(keysFor(["logistics_user"])).not.toContain("transactions");
  });

  it("offers the inbox and documents to every role, including the approver", () => {
    expect(keysFor(["approver_hod"])).toContain("inbox");
    expect(keysFor(["approver_hod"])).toContain("documents");
    expect(keysFor(["auditor"])).toContain("inbox");
  });

  it("shows an account with no role only the role-agnostic modules", () => {
    const roleAgnostic = NAV_ITEMS.filter((item) => item.roles.length === 0).map((item) => item.key);

    // Notifications and Settings join this list in Step 9: both are scoped to the caller by the
    // API on every read and every write, so there is no role that could be required for them.
    expect(roleAgnostic).toEqual([
      "dashboard",
      "inbox",
      "documents",
      "exceptions",
      "approvals",
      "shipments",
      "notifications",
      "settings",
    ]);
    expect(keysFor([])).toEqual(roleAgnostic);
  });
});

describe("visibleNavChildren", () => {
  const admin = NAV_ITEMS.find((item) => item.key === "admin")!;

  it("lists the administration screens that exist, and only those", () => {
    // Deliberately absent, and each for its own reason: the tracker/SAP/DMS endpoints are
    // infrastructure and stay environment-only, and the rule-to-exception-category mapping stays
    // seed data. The report-distribution and report-template screens exist and are reached from
    // the Admin landing page's own list rather than from the sidebar, which carries the five
    // screens somebody navigates to directly.
    expect(visibleNavChildren(admin, ["admin"]).map((child) => child.href)).toEqual([
      "/admin/users",
      "/admin/rules",
      "/admin/document-types",
      "/admin/audit",
      "/admin/integrations",
    ]);
    for (const href of ["/admin/integrations-config", "/admin/exception-mapping"]) {
      expect(visibleNavChildren(admin, ["admin"]).map((child) => child.href)).not.toContain(href);
    }
  });

  it("gives the auditor the trail and nothing else under Admin", () => {
    expect(visibleNavChildren(admin, ["auditor"]).map((child) => child.href)).toEqual([
      "/admin/audit",
    ]);
  });

  it("shows the administration screens to nobody but an administrator", () => {
    expect(visibleNavChildren(admin, ["purchase_user"])).toEqual([]);
    expect(visibleNavChildren(admin, [])).toEqual([]);
  });

  it("returns nothing for a module that has no live screens inside it", () => {
    const reports = NAV_ITEMS.find((item) => item.key === "reports")!;
    expect(visibleNavChildren(reports, ["admin"])).toEqual([]);
  });
});
