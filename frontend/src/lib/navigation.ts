import {
  Bell,
  ChartLine,
  ClipboardList,
  FileSpreadsheet,
  FileText,
  Inbox,
  LayoutDashboard,
  Settings,
  Settings2,
  ShieldCheck,
  Ship,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";

import { hasAnyRole, type PlatformRole } from "@/lib/roles";

export type NavStatus = "available" | "planned";

/**
 * A live screen inside a section.
 *
 * The Admin section carried exactly one of these while the section itself was still to come - the
 * integration monitor. The section is real from , and its children are now what the
 * administration module actually consists of: users and roles, the rule thresholds, the document
 * schemas, the audit explorer, and the monitor that was already there.
 */
export interface NavChild {
  key: string;
  label: string;
  href: string;
  roles: readonly PlatformRole[];
  summary: string;
}

export interface NavItem {
  key: string;
  label: string;
  href: string;
  icon: LucideIcon;
  roles: readonly PlatformRole[];
  status: NavStatus;
  availableFrom?: string;
  summary: string;
  children?: readonly NavChild[];
}

export const NAV_ITEMS: readonly NavItem[] = [
  {
    key: "dashboard",
    label: "Dashboard",
    href: "/dashboard",
    icon: LayoutDashboard,
    roles: [],
    status: "available",
    summary:
      "Confirms the account you are signed in as, the roles it holds, and which modules are scheduled to come online.",
  },
  {
    key: "inbox",
    label: "Inbox",
    href: "/inbox",
    icon: Inbox,
    // Every signed-in role reads the queue. Only the desks that own the work may correct a
    // classification or upload a document, and the API enforces that regardless of this list.
    roles: [],
    status: "available",
    summary:
      "Gathers incoming trade email and its attachments into one triage queue, with the AI-assigned category and its confidence on every row.",
  },
  {
    key: "transactions",
    label: "Transactions",
    href: "/transactions",
    icon: FileSpreadsheet,
    roles: [
      "purchase_user",
      "sales_user",
      "fa_user",
      "finance_user",
      "approver_hod",
      "admin",
      "auditor",
    ],
    status: "available",
    summary:
      "Carries the record for each deal: its batch, pricing basis, counterparty, linked documents and the business rules it has been checked against.",
  },
  {
    key: "documents",
    label: "Documents",
    href: "/documents",
    icon: FileText,
    roles: [],
    status: "available",
    summary:
      "Every invoice, contract and certificate received so far, with its extracted fields shown beside the source page it was read from.",
  },
  {
    key: "exceptions",
    label: "Exceptions",
    href: "/exceptions",
    icon: TriangleAlert,
    // Open to every signed-in role, because every role owns at least one category of the matrix
    // and because a queue only some people can see is not a governed one. Who may resolve a
    // given case is a narrower question the API answers per case, per category.
    roles: [],
    status: "available",
    summary:
      "Queues the validations and extractions the system could not settle on its own, owned by the desk that has to act and ageing until somebody does.",
  },
  {
    key: "approvals",
    label: "Approvals",
    href: "/approvals",
    icon: ShieldCheck,
    // Also open to everyone: the decision is the approver's, but the queue is visible, which is
    // the whole point of moving sign-off off paper.
    roles: [],
    status: "available",
    summary:
      "Presents the transactions waiting on departmental sign-off, ranked by age, value or risk, and records who decided what.",
  },
  {
    key: "shipments",
    label: "Shipments",
    href: "/shipments",
    icon: Ship,
    // Open to every signed-in role, on the same principle as the inbox and the exception queue:
    // the point of moving this off one person's morning spreadsheet is that everybody can see
    // where the cargo is. Who may refresh, correct or log against a shipment is a narrower
    // question the API answers on every call.
    roles: [],
    status: "available",
    summary:
      "Follows containers, vessels and delivery milestones against the batches they carry, whether a carrier reported them or somebody typed them in.",
  },
  {
    key: "analytics",
    label: "Analytics",
    href: "/analytics",
    icon: ChartLine,
    roles: ["approver_hod", "finance_user", "admin", "auditor"],
    status: "available",
    summary:
      "Turnaround, automation share and extraction quality over a range you choose, computed from the transaction records and scoped to the desks your roles cover.",
  },
  {
    key: "reports",
    label: "Reports",
    href: "/reports",
    icon: ClipboardList,
    // Reading a report is open to the oversight roles and the finance desk; asking for a new one
    // is narrower still, and the API refuses any other role regardless of what was rendered.
    roles: ["approver_hod", "finance_user", "admin", "auditor"],
    status: "available",
    summary:
      "The daily and monthly reports the platform produces on schedule, plus anything asked for on demand. Generated and stored here; nothing is sent anywhere.",
  },
  {
    key: "admin",
    label: "Admin",
    href: "/admin",
    icon: Settings2,
    roles: ["admin", "auditor"],
    status: "available",
    summary:
      "Role assignment, the rule thresholds, the document schemas and the append-only audit trail — everything that was migration-only until now.",
    children: [
      {
        key: "users",
        label: "Users & roles",
        href: "/admin/users",
        roles: ["admin"],
        summary:
          "Every account mirrored from the identity provider, and the manual exception to group-based role mapping.",
      },
      {
        key: "rules",
        label: "Rules & thresholds",
        href: "/admin/rules",
        roles: ["admin"],
        summary:
          "Every tolerance and limit the rule engine reads, editable with a stated reason and no deployment.",
      },
      {
        key: "document-types",
        label: "Document types",
        href: "/admin/document-types",
        roles: ["admin"],
        summary:
          "The field list extraction reads for each document type, and each territory's mandatory-document checklist.",
      },
      {
        key: "audit",
        label: "Audit explorer",
        href: "/admin/audit",
        // The one screen under Admin the Auditor may open. Independent oversight of the trail is
        // the whole reason the role exists.
        roles: ["admin", "auditor"],
        summary:
          "Every governance event recorded since the platform's first day, filterable and exportable. Read-only, always.",
      },
      {
        key: "integrations",
        label: "Integration monitor",
        href: "/admin/integrations",
        roles: ["admin"],
        summary:
          "Every posting an approved transaction owes the tracker, SAP and the document store — what succeeded, what failed, and what is waiting on a person.",
      },
    ],
  },
  {
    key: "notifications",
    label: "Notifications",
    href: "/notifications",
    icon: Bell,
    // Everybody's own, and only their own. The API scopes every read and write to the caller.
    roles: [],
    status: "available",
    summary:
      "What the platform needs to tell you: an exception on your desk, a decision waiting on you, and the outcome of what you submitted.",
  },
  {
    key: "settings",
    label: "Settings",
    href: "/settings",
    icon: Settings,
    roles: [],
    status: "available",
    summary:
      "Your profile as the identity provider asserts it, and the notification channel you want. In-app is the only channel that exists today.",
  },
];

/** The live screens inside a section, filtered to the roles that may open them. */
export function visibleNavChildren(item: NavItem, roles: PlatformRole[]): NavChild[] {
  return (item.children ?? []).filter(
    (child) => child.roles.length === 0 || hasAnyRole(roles, child.roles),
  );
}

export function visibleNavItems(roles: PlatformRole[]): NavItem[] {
  return NAV_ITEMS.filter((item) => item.roles.length === 0 || hasAnyRole(roles, item.roles));
}
