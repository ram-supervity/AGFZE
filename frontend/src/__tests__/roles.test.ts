import { describe, expect, it } from "vitest";

import {
  PLATFORM_ROLES,
  hasAnyRole,
  isPlatformRole,
  normaliseRoles,
  primaryRole,
} from "@/lib/roles";

describe("PLATFORM_ROLES", () => {
  it("is the eight-slug vocabulary shared with the backend and Keycloak", () => {
    expect(PLATFORM_ROLES).toEqual([
      "approver_hod",
      "purchase_user",
      "sales_user",
      "fa_user",
      "logistics_user",
      "finance_user",
      "admin",
      "auditor",
    ]);
  });
});

describe("isPlatformRole", () => {
  it("accepts every canonical slug", () => {
    for (const role of PLATFORM_ROLES) {
      expect(isPlatformRole(role), role).toBe(true);
    }
  });

  it("rejects anything outside the vocabulary", () => {
    expect(isPlatformRole("offline_access")).toBe(false);
    expect(isPlatformRole("uma_authorization")).toBe(false);
    expect(isPlatformRole("superuser")).toBe(false);
    expect(isPlatformRole("")).toBe(false);
  });
});

describe("normaliseRoles", () => {
  it("drops the composites Keycloak grants every account", () => {
    expect(
      normaliseRoles(["offline_access", "uma_authorization", "default-roles-agfze", "sales_user"]),
    ).toEqual(["sales_user"]);
  });

  it("de-duplicates and returns canonical order whatever order the token used", () => {
    expect(normaliseRoles(["auditor", "admin", "auditor", "approver_hod"])).toEqual([
      "approver_hod",
      "admin",
      "auditor",
    ]);
    expect(normaliseRoles([...PLATFORM_ROLES].reverse())).toEqual([...PLATFORM_ROLES]);
  });

  it("returns an empty list for a claim that is not an array", () => {
    for (const raw of [null, undefined, "admin", 7, { roles: ["admin"] }]) {
      expect(normaliseRoles(raw)).toEqual([]);
    }
  });
});

describe("primaryRole", () => {
  it("returns the canonically first role the account actually holds", () => {
    expect(primaryRole(["auditor", "purchase_user"])).toBe("purchase_user");
    expect(primaryRole(["auditor", "admin"])).toBe("admin");
    expect(primaryRole(["auditor"])).toBe("auditor");
  });

  it("returns null when the account carries no platform role", () => {
    expect(primaryRole([])).toBeNull();
  });
});

describe("hasAnyRole", () => {
  it("is true only where the two lists intersect", () => {
    expect(hasAnyRole(["sales_user", "admin"], ["admin", "auditor"])).toBe(true);
    expect(hasAnyRole(["sales_user"], ["admin", "auditor"])).toBe(false);
    expect(hasAnyRole([], ["admin"])).toBe(false);
    expect(hasAnyRole(["admin"], [])).toBe(false);
  });
});
