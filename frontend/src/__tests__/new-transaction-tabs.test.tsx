import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { NewTransactionTabs } from "@/components/transactions/new-transaction-tabs";

// The three forms behind the strip each reach for the session, the router and the API. None of
// that is what this file is about: the subject is the tab strip's keyboard behaviour, so the
// panels are stubbed down to a marker element apiece.
vi.mock("@/components/transactions/new-transaction-form", () => ({
  NewTransactionForm: () => <div data-testid="panel">purchase form</div>,
}));
vi.mock("@/components/transactions/new-sales-leg-form", () => ({
  NewSalesLegForm: () => <div data-testid="panel">sales form</div>,
}));
vi.mock("@/components/transactions/new-fa-transaction-form", () => ({
  NewFaTransactionForm: () => <div data-testid="panel">fa form</div>,
}));

function renderTabs(
  permissions: Partial<{
    canRegisterPurchase: boolean;
    canAttachSales: boolean;
    canRegisterFa: boolean;
  }> = {},
) {
  return render(
    <NewTransactionTabs
      commodities={[]}
      faFieldSchema={[]}
      canRegisterPurchase={permissions.canRegisterPurchase ?? true}
      canAttachSales={permissions.canAttachSales ?? true}
      canRegisterFa={permissions.canRegisterFa ?? true}
    />,
  );
}

describe("the registration-path tabs", () => {
  it("puts exactly one tab in the page's tab order", () => {
    renderTabs();
    const tabs = screen.getAllByRole("tab");

    expect(tabs).toHaveLength(3);
    expect(tabs.filter((tab) => tab.getAttribute("tabindex") === "0")).toHaveLength(1);
    expect(tabs[0]).toHaveAttribute("tabindex", "0");
    expect(tabs[1]).toHaveAttribute("tabindex", "-1");
  });

  it("moves right and left with the arrow keys, and the panel follows", async () => {
    const user = userEvent.setup();
    renderTabs();
    const tabs = screen.getAllByRole("tab");

    tabs[0].focus();
    await user.keyboard("{ArrowRight}");
    expect(screen.getByTestId("panel")).toHaveTextContent("sales form");
    expect(screen.getAllByRole("tab")[1]).toHaveAttribute("aria-selected", "true");

    await user.keyboard("{ArrowLeft}");
    expect(screen.getByTestId("panel")).toHaveTextContent("purchase form");
  });

  it("wraps around at both ends rather than stopping", async () => {
    const user = userEvent.setup();
    renderTabs();

    screen.getAllByRole("tab")[0].focus();
    await user.keyboard("{ArrowLeft}");
    expect(screen.getByTestId("panel")).toHaveTextContent("fa form");
  });

  it("jumps to the first and last path with Home and End", async () => {
    const user = userEvent.setup();
    renderTabs();

    screen.getAllByRole("tab")[0].focus();
    await user.keyboard("{End}");
    expect(screen.getByTestId("panel")).toHaveTextContent("fa form");

    await user.keyboard("{Home}");
    expect(screen.getByTestId("panel")).toHaveTextContent("purchase form");
  });

  it("ignores keys that are not navigation", async () => {
    const user = userEvent.setup();
    renderTabs();

    screen.getAllByRole("tab")[0].focus();
    await user.keyboard("{ArrowDown}");
    // Horizontal strip. Up and Down scroll the page, and must keep doing so from here.
    expect(screen.getByTestId("panel")).toHaveTextContent("purchase form");
  });

  it("keeps its roles and its label", () => {
    renderTabs();
    expect(screen.getByRole("tablist")).toHaveAttribute(
      "aria-label",
      "What are you registering",
    );
    expect(screen.getAllByRole("tab")[0]).toHaveAttribute("aria-selected", "true");
  });

  it("renders no strip at all when only one path is permitted", () => {
    renderTabs({ canAttachSales: false, canRegisterFa: false });
    expect(screen.queryByRole("tablist")).toBeNull();
    expect(screen.getByTestId("panel")).toHaveTextContent("purchase form");
  });
});
