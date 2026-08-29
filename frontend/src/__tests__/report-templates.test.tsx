import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReportTemplatesTable } from "@/components/admin/report-templates-table";
import {
  headlineFigureLabel,
  sectionKindLabel,
  sectionSourceLabel,
} from "@/lib/admin";
import type { ReportTemplateList } from "@/lib/api-client";

const refresh = vi.fn();
const update = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh, push: vi.fn() }),
}));

vi.mock("next-auth/react", () => ({
  useSession: () => ({ data: { accessToken: "token" } }),
}));

vi.mock("@/lib/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api-client")>();
  return { ...actual, updateReportTemplate: (...args: unknown[]) => update(...args) };
});

const DATA: ReportTemplateList = {
  items: [
    {
      id: "11111111-1111-4111-8111-111111111111",
      template_key: "daily_operations",
      report_type: "daily",
      title: "Daily operations summary",
      description: "What moved yesterday and what is open this morning.",
      sections: [
        {
          key: "headline",
          title: "Where things stand",
          kind: "kpi_grid",
          source: "headline",
          description: null,
          figures: ["open_exceptions", "approval_queue"],
        },
        {
          key: "shipments",
          title: "Cargo",
          kind: "breakdown",
          source: "shipments",
          description: null,
          figures: [],
        },
      ],
      disclosures: ["This file is never sent by the platform."],
      wants_ai_summary: false,
      include_detail_rows: false,
      default_period_days: 1,
      change_reason: "Seeded with the platform.",
      changed_at: "2026-03-15T00:00:00Z",
      changed_by_name: null,
      section_count: 2,
    },
  ],
  report_types: ["daily", "monthly", "adhoc"],
  section_kinds: ["kpi_grid", "breakdown", "table", "ai_summary", "note"],
  section_sources: ["headline", "shipments", "transactions_by_status"],
  headline_figures: ["open_exceptions", "approval_queue", "automation_rate"],
};

beforeEach(() => {
  refresh.mockClear();
  update.mockClear();
  update.mockResolvedValue(DATA.items[0]);
});

describe("the report templates screen", () => {
  it("says plainly that no figure is reachable from it", () => {
    render(<ReportTemplatesTable data={DATA} />);
    // The one promise this screen has to keep: it edits what a report asks for, never what the
    // answer is. Every number is still computed from the governed tables at generation time.
    expect(screen.getByText(/Structure only/i)).toBeInTheDocument();
  });

  it("lists each template with its sections in printed order", () => {
    render(<ReportTemplatesTable data={DATA} />);
    expect(screen.getByText("Daily operations summary")).toBeInTheDocument();
    expect(screen.getByText("daily_operations")).toBeInTheDocument();
    expect(screen.getByText("Headline figures · Cargo")).toBeInTheDocument();
  });

  it("refuses to save without a reason, and refuses to save nothing", async () => {
    const user = userEvent.setup();
    render(<ReportTemplatesTable data={DATA} />);
    await user.click(screen.getByRole("button", { name: "Edit" }));

    const save = screen.getByRole("button", { name: "Save change" });
    // Nothing has changed yet, so there is nothing to save even with a reason typed.
    expect(save).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Move Cargo up" }));
    expect(save).toBeDisabled();

    await user.type(
      screen.getByLabelText("Reason for this change"),
      "Confirmed with the HOD in the March reporting review.",
    );
    expect(save).toBeEnabled();
    expect(update).not.toHaveBeenCalled();
  });

  it("sends the reordered structure and the reason, and nothing else", async () => {
    const user = userEvent.setup();
    render(<ReportTemplatesTable data={DATA} />);
    await user.click(screen.getByRole("button", { name: "Edit" }));
    await user.click(screen.getByRole("button", { name: "Move Cargo up" }));
    await user.type(
      screen.getByLabelText("Reason for this change"),
      "Cargo leads the morning read now, per the HOD.",
    );
    await user.click(screen.getByRole("button", { name: "Save change" }));

    expect(update).toHaveBeenCalledTimes(1);
    const [, id, body] = update.mock.calls[0];
    expect(id).toBe(DATA.items[0].id);
    expect(body.sections.map((section: { key: string }) => section.key)).toEqual([
      "shipments",
      "headline",
    ]);
    expect(body.change_reason).toContain("Cargo leads");
    // The row's identity is not on the wire at all.
    expect(body).not.toHaveProperty("report_type");
    expect(body).not.toHaveProperty("template_key");
  });

  it("removing every section leaves Save unreachable", async () => {
    const user = userEvent.setup();
    render(<ReportTemplatesTable data={DATA} />);
    await user.click(screen.getByRole("button", { name: "Edit" }));

    await user.click(screen.getByRole("button", { name: "Remove Where things stand" }));
    await user.click(screen.getByRole("button", { name: "Remove Cargo" }));
    await user.type(
      screen.getByLabelText("Reason for this change"),
      "A reason long enough to satisfy the floor.",
    );

    expect(screen.getByRole("button", { name: "Save change" })).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent(/at least one section/i);
  });

  it("offers a figure choice only where the block actually has figures to choose", async () => {
    const user = userEvent.setup();
    render(<ReportTemplatesTable data={DATA} />);
    await user.click(screen.getByRole("button", { name: "Edit" }));

    expect(screen.getByLabelText(headlineFigureLabel("automation_rate"))).toBeInTheDocument();
    // The cargo breakdown prints the whole block, so it offers no per-figure choice at all.
    expect(screen.getAllByText(/prints the whole block/i)).toHaveLength(1);
  });
});

describe("the screen's vocabularies", () => {
  it("reads a kind and a source as a person would say them", () => {
    expect(sectionKindLabel("kpi_grid")).toBe("Figure grid");
    expect(sectionSourceLabel("transactions_by_status")).toBe("Transactions by status");
    // A key the service adds later still reads as words rather than as an identifier.
    expect(sectionSourceLabel("something_new")).toBe("something new");
    expect(headlineFigureLabel("open_exceptions")).toBe("Open exceptions");
  });
});
