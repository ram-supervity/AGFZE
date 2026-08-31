import { cleanup, render, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DashboardView } from "@/components/dashboard/dashboard-view";
import type { DashboardSummary } from "@/lib/api-client";

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

afterEach(cleanup);

/** A payload shaped exactly as `GET /dashboards/summary` serialises one. */
function summary(overrides: Partial<DashboardSummary> = {}): DashboardSummary {
  return {
    generated_at: "2026-08-28T09:00:00Z",
    period: { start: "2026-07-29T09:00:00Z", end: "2026-08-28T09:00:00Z" },
    emphasis: "shipments",
    streams: ["fa", "scrap"],
    scope_note: "Computed over fa, scrap and the 3 exception categories your roles work.",
    cache_age_seconds: 0,
    cache_ttl_seconds: 45,
    definitions: { automation_rate: "The percentage of transactions approved with no exception." },
    tiles: [
      {
        key: "tile.open_exceptions",
        label: "Open exceptions",
        value: 2,
        unit: "count",
        target: "exceptions",
        filters: { status: "open" },
        note: "1 of them open for more than 72 hours.",
      },
      {
        key: "tile.integration_failed",
        label: "Integration failures",
        value: 1,
        unit: "count",
        target: "integrations",
        filters: { status: "failed" },
        note: null,
      },
      {
        key: "tile.integration_awaiting_manual",
        label: "Postings awaiting a person",
        value: 3,
        unit: "count",
        target: "integrations",
        filters: { status: "awaiting_manual_action" },
        note: "Not a failure.",
      },
      {
        key: "tile.automation_rate",
        label: "Approved without an exception",
        value: 0,
        unit: "percent",
        target: null,
        filters: {},
        note: null,
      },
      {
        key: "tile.extraction_non_override",
        label: "Fields not overridden",
        value: 92.5,
        unit: "percent",
        target: "documents",
        filters: {},
        note: "The share of extracted fields a person did not override. A stated proxy for extraction quality, not a verified-correctness measurement.",
      },
    ],
    transactions_by_status: [
      { key: "transactions.matched", label: "Matched", value: 3, unit: "count", target: "transactions", filters: { status: "matched" }, note: null },
      { key: "transactions.committed", label: "Committed", value: 7, unit: "count", target: "transactions", filters: { status: "committed" }, note: null },
    ],
    exceptions: {
      categories: [
        {
          category: "shipment_status_unavailable",
          label: "Shipment status unavailable",
          open_count: 2,
          escalated_count: 0,
          ageing: { under_24h: 1, "24_to_72h": 0, over_72h: 1 },
          oldest_age_hours: 100,
          target: "exceptions",
          filters: { exception_type: "shipment_status_unavailable", status: "open" },
        },
      ],
      total_open: 2,
      over_72h: 1,
      bands: [],
      computed_at: "2026-08-28T09:00:00Z",
    },
    approvals: { pending: 1, oldest_waiting_hours: 8, target: "approvals", filters: { decision: "pending" } },
    integrations: {
      by_status: { queued: 0, processing: 0, succeeded: 2, failed: 1, awaiting_manual_action: 3 },
      failed: 1,
      awaiting_manual_action: 3,
      succeeded: 2,
      in_flight: 0,
      completed_manually: 1,
      separation_note: "A posting waiting on a person is not a failure.",
    },
    shipments: {
      by_status: [
        { status: "on_schedule", label: "On schedule", count: 4, target: "shipments", filters: { status: "on_schedule" } },
        { status: "delayed", label: "Delayed", count: 0, target: "shipments", filters: { status: "delayed" } },
      ],
      total: 4,
      stale_count: 1,
      stale_threshold_hours: 48,
      stale_target: "shipments",
      stale_filters: { stale_only: true },
    },
    extraction: {
      field_count: 120,
      overridden_count: 9,
      non_override_rate: 92.5,
      by_document_type: [],
      measure: "non_override_rate",
      disclosure: "A stated proxy for extraction quality, not a verified-correctness measurement.",
    },
    turnaround: {
      sample_size: 4,
      mean_hours: 21.5,
      median_hours: 16,
      fastest_hours: 5,
      slowest_hours: 52,
      definition: "Request created to approval decided.",
    },
    automation: {
      approved_count: 4,
      exception_free_count: 3,
      intervened_count: 1,
      automation_rate: 75,
      definition: "Approved with no exception ever opened.",
    },
    turnaround_trend: [
      { bucket_start: "2026-08-26T00:00:00Z", bucket_end: "2026-08-27T00:00:00Z", approved_count: 0, mean_hours: null, median_hours: null, exception_free_count: 0, intervened_count: 0, automation_rate: null },
      { bucket_start: "2026-08-27T00:00:00Z", bucket_end: "2026-08-28T00:00:00Z", approved_count: 2, mean_hours: 12, median_hours: 12, exception_free_count: 2, intervened_count: 0, automation_rate: 100 },
    ],
    ...overrides,
  } as DashboardSummary;
}

describe("DashboardView", () => {
  it("makes every navigable tile a link into the queue it counts", () => {
    const { getByText } = render(<DashboardView summary={summary()} stream="" />);

    expect(getByText("Open exceptions").closest("a")).toHaveAttribute(
      "href",
      "/exceptions?status=open",
    );
    expect(getByText("Postings awaiting a person").closest("a")).toHaveAttribute(
      "href",
      "/admin/integrations?status=awaiting_manual_action",
    );
  });

  it("keeps the failure count and the awaiting-a-person count apart", () => {
    // Two tiles, two numbers, two different destinations. They are never added together.
    const { getByText } = render(<DashboardView summary={summary()} stream="" />);

    const failures = getByText("Integration failures").closest("a")!;
    const waiting = getByText("Postings awaiting a person").closest("a")!;

    expect(within(failures).getByText("1")).toBeInTheDocument();
    expect(within(waiting).getByText("3")).toBeInTheDocument();
    expect(failures).toHaveAttribute("href", "/admin/integrations?status=failed");
    expect(waiting).not.toBe(failures);
  });

  it("renders a tile with no drill-through as plain text rather than a dead link", () => {
    const { getByText } = render(<DashboardView summary={summary()} stream="" />);
    expect(getByText("Approved without an exception").closest("a")).toBeNull();
  });

  it("shows a real zero rather than dropping the tile", () => {
    // An absent tile and an empty queue look identical, and only one of them means anything.
    const { getByText } = render(<DashboardView summary={summary()} stream="" />);
    const tile = getByText("Approved without an exception").closest("div.rounded-medium") as HTMLElement;
    expect(within(tile).getByText("0%")).toBeInTheDocument();
  });

  it("leads with the panel the account's desk emphasises", () => {
    const { container } = render(<DashboardView summary={summary()} stream="" />);
    const panels = Array.from(container.querySelectorAll("section[aria-label]")).map((node) =>
      node.getAttribute("aria-label"),
    );
    expect(panels[0]).toBe("Cargo");
    // Emphasis, not exclusion: everything else is still on the screen underneath it.
    expect(panels).toContain("Open exceptions by category");
    expect(panels).toContain("Where the deals are");
  });

  it("carries the extraction disclosure with the figure rather than leaving it off", () => {
    const { getByText } = render(<DashboardView summary={summary()} stream="" />);
    expect(getByText(/not a verified-correctness measurement/)).toBeInTheDocument();
  });

  it("says how fresh the figures are", () => {
    const { getByText } = render(<DashboardView summary={summary()} stream="" />);
    expect(getByText(/Computed just now/)).toBeInTheDocument();

    cleanup();
    const cached = render(
      <DashboardView summary={summary({ cache_age_seconds: 12 })} stream="" />,
    );
    expect(cached.getByText(/Computed 12 seconds ago/)).toBeInTheDocument();
  });

  it("groups the statuses into phases without losing one", () => {
    const { container, getByText } = render(<DashboardView summary={summary()} stream="" />);
    const donut = container.querySelector(
      "section[aria-label='Where the deals are']",
    ) as HTMLElement;

    // 3 matched + 7 committed, and the ring's centre carries the total of every phase.
    expect(within(donut).getByTitle(/10$/)).toBeInTheDocument();
    expect(getByText("In preparation")).toBeInTheDocument();
    expect(getByText("Committed")).toBeInTheDocument();
    // Every phase is listed, including the ones nothing is in.
    expect(getByText("Intake")).toBeInTheDocument();
    expect(getByText("Awaiting a decision")).toBeInTheDocument();
  });
});
