export const PLATFORM_ROLES = [
  "approver_hod",
  "purchase_user",
  "sales_user",
  "fa_user",
  "logistics_user",
  "finance_user",
  "admin",
  "auditor",
] as const;

export type PlatformRole = (typeof PLATFORM_ROLES)[number];

export const ROLE_LABELS: Record<PlatformRole, string> = {
  approver_hod: "Approver / HOD",
  purchase_user: "Purchase User",
  sales_user: "Sales User",
  fa_user: "FA User",
  logistics_user: "Logistics User",
  finance_user: "Finance User",
  admin: "Admin",
  auditor: "Auditor",
};

export const ROLE_DESCRIPTIONS: Record<PlatformRole, string> = {
  approver_hod:
    "Department head who signs off the transactions that exceed the raising desk's own authority.",
  purchase_user:
    "Buying desk: supplier enquiries, purchase orders and the correspondence behind them.",
  sales_user: "Selling desk: customer enquiries, quotations and sales orders.",
  fa_user:
    "Works the FA desk's own enquiries and document set alongside the purchase and sales desks.",
  logistics_user:
    "Arranges freight, customs and delivery for confirmed orders and owns the shipping paperwork.",
  finance_user: "Handles invoicing, payment status and the commercial ledger view of a deal.",
  admin: "Administers accounts, role assignment and platform configuration.",
  auditor:
    "Independent oversight: read access across the desks and the append-only audit trail.",
};

const ROLE_SET: ReadonlySet<string> = new Set(PLATFORM_ROLES);

export function isPlatformRole(value: string): value is PlatformRole {
  return ROLE_SET.has(value);
}

export function normaliseRoles(raw: unknown): PlatformRole[] {
  if (!Array.isArray(raw)) return [];
  const held = new Set(raw.filter((value): value is string => typeof value === "string"));
  return PLATFORM_ROLES.filter((role) => held.has(role));
}

export function primaryRole(roles: PlatformRole[]): PlatformRole | null {
  return PLATFORM_ROLES.find((role) => roles.includes(role)) ?? null;
}

export function hasAnyRole(roles: PlatformRole[], allowed: readonly PlatformRole[]): boolean {
  return roles.some((role) => allowed.includes(role));
}
