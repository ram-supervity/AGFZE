import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { IntegrationMonitor } from "@/components/integrations/integration-monitor";
import type { IntegrationJobQueue } from "@/lib/api-client";

const push = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("next-auth/react", () => ({
  useSession: () => ({ data: { accessToken: "token" } }),
}));

const QUEUE: IntegrationJobQueue = {
  items: [],
  page: { page: 1, page_size: 25, total: 0, total_pages: 1 },
  counts_by_target: { tracker: 2, sap: 1, dms: 0 },
  counts_by_status: {},
  configured_targets: { tracker: false, sap: false, dms: false },
  max_attempts: 3,
};

function renderMonitor(target = "") {
  return render(
    <IntegrationMonitor
      queue={QUEUE}
      filters={{ target, status: "", transactionId: "" }}
    />,
  );
}

beforeEach(() => {
  push.mockClear();
});

describe("the integration monitor's target tabs", () => {
  it("puts exactly one tab in the page's tab order", () => {
    renderMonitor();
    const tabs = screen.getAllByRole("tab");

    expect(tabs).toHaveLength(4);
    expect(tabs.filter((tab) => tab.getAttribute("tabindex") === "0")).toHaveLength(1);
    expect(tabs[0]).toHaveAttribute("tabindex", "0");
    expect(tabs[1]).toHaveAttribute("tabindex", "-1");
  });

  it("moves the tab order with the selection", () => {
    renderMonitor("sap");
    const tabs = screen.getAllByRole("tab");

    expect(tabs[0]).toHaveAttribute("tabindex", "-1");
    expect(tabs[2]).toHaveAttribute("tabindex", "0");
    expect(tabs[2]).toHaveAttribute("aria-selected", "true");
  });

  it("moves right and left with the arrow keys", async () => {
    const user = userEvent.setup();
    renderMonitor();

    screen.getAllByRole("tab")[0].focus();
    await user.keyboard("{ArrowRight}");
    expect(push).toHaveBeenCalledWith("/admin/integrations?target_system=tracker");

    push.mockClear();
    await user.keyboard("{ArrowLeft}");
    // Selection follows focus, so moving back re-selects "All systems", which carries no filter.
    expect(push).toHaveBeenCalledWith("/admin/integrations?");
  });

  it("wraps around at both ends rather than stopping", async () => {
    const user = userEvent.setup();
    renderMonitor();

    screen.getAllByRole("tab")[0].focus();
    await user.keyboard("{ArrowLeft}");
    expect(push).toHaveBeenCalledWith("/admin/integrations?target_system=dms");
  });

  it("jumps to the first and last target with Home and End", async () => {
    const user = userEvent.setup();
    renderMonitor();

    screen.getAllByRole("tab")[0].focus();
    await user.keyboard("{End}");
    expect(push).toHaveBeenCalledWith("/admin/integrations?target_system=dms");

    push.mockClear();
    await user.keyboard("{Home}");
    expect(push).toHaveBeenCalledWith("/admin/integrations?");
  });

  it("ignores keys that are not navigation", async () => {
    const user = userEvent.setup();
    renderMonitor();

    screen.getAllByRole("tab")[0].focus();
    await user.keyboard("{ArrowDown}");
    expect(push).not.toHaveBeenCalled();
  });

  it("keeps its roles and its label", () => {
    renderMonitor();
    expect(screen.getByRole("tablist")).toHaveAttribute("aria-label", "Target systems");
    expect(screen.getAllByRole("tab")[0]).toHaveAttribute("aria-selected", "true");
  });
});
