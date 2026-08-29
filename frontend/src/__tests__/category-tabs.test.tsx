import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi, beforeEach } from "vitest";

import { CategoryTabs } from "@/components/exceptions/category-tabs";
import type { ExceptionCategoryInfo } from "@/lib/api-client";

const push = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  useSearchParams: () => new URLSearchParams(),
}));

function category(name: string, label: string): ExceptionCategoryInfo {
  return {
    category: name,
    label,
    owner_role: "purchase_user",
    shared_with: [],
    triggerable: true,
    description: label,
    dormant_reason: null,
    open_count: 0,
  } as ExceptionCategoryInfo;
}

const CATEGORIES = [
  category("low_confidence", "Low confidence"),
  category("duplicate_document", "Duplicate document"),
];

function renderTabs(active = "") {
  return render(<CategoryTabs categories={CATEGORIES} active={active} total={3} />);
}

beforeEach(() => {
  push.mockClear();
});

describe("the exception category tabs", () => {
  it("puts exactly one tab in the page's tab order", () => {
    // Roving tabindex. Without it, reaching anything past the strip by keyboard means stepping
    // through every tab in it - which on the full ten-category queue is ten presses.
    renderTabs();
    const tabs = screen.getAllByRole("tab");

    expect(tabs).toHaveLength(3);
    expect(tabs.filter((tab) => tab.getAttribute("tabindex") === "0")).toHaveLength(1);
    expect(tabs[0]).toHaveAttribute("tabindex", "0");
    expect(tabs[1]).toHaveAttribute("tabindex", "-1");
  });

  it("moves the tab order with the selection", () => {
    renderTabs("low_confidence");
    const tabs = screen.getAllByRole("tab");

    expect(tabs[0]).toHaveAttribute("tabindex", "-1");
    expect(tabs[1]).toHaveAttribute("tabindex", "0");
    expect(tabs[1]).toHaveAttribute("aria-selected", "true");
  });

  it("moves right and left with the arrow keys", async () => {
    const user = userEvent.setup();
    renderTabs();
    const tabs = screen.getAllByRole("tab");

    tabs[0].focus();
    await user.keyboard("{ArrowRight}");
    expect(push).toHaveBeenCalledWith("/exceptions?exception_type=low_confidence");

    push.mockClear();
    await user.keyboard("{ArrowLeft}");
    // Selection follows focus, so moving back re-selects the first tab - which for this strip
    // is "all categories", and carries no filter.
    expect(push).toHaveBeenCalledWith("/exceptions?");
  });

  it("wraps around at both ends rather than stopping", async () => {
    const user = userEvent.setup();
    renderTabs();
    const tabs = screen.getAllByRole("tab");

    tabs[0].focus();
    await user.keyboard("{ArrowLeft}");
    expect(push).toHaveBeenCalledWith("/exceptions?exception_type=duplicate_document");
  });

  it("jumps to the first and last tab with Home and End", async () => {
    const user = userEvent.setup();
    renderTabs();
    const tabs = screen.getAllByRole("tab");

    tabs[0].focus();
    await user.keyboard("{End}");
    expect(push).toHaveBeenCalledWith("/exceptions?exception_type=duplicate_document");

    push.mockClear();
    await user.keyboard("{Home}");
    expect(push).toHaveBeenCalledWith("/exceptions?");
  });

  it("ignores keys that are not navigation", async () => {
    const user = userEvent.setup();
    renderTabs();
    screen.getAllByRole("tab")[0].focus();

    await user.keyboard("{ArrowDown}");
    // A horizontal strip does not answer to Up and Down, and must not swallow them either -
    // they scroll the page, which is what somebody pressing them from here expects.
    expect(push).not.toHaveBeenCalled();
  });

  it("keeps its roles and its appearance", () => {
    // The fix is keyboard behaviour only. Anything that changed the markup would change what a
    // screen reader announces, which was already correct.
    renderTabs();
    expect(screen.getByRole("tablist")).toHaveAttribute("aria-label", "Exception categories");
    expect(screen.getAllByRole("tab")[0]).toHaveAttribute("aria-selected", "true");
  });
});

describe("a tab strip with only one tab", () => {
  it("treats arrow keys as a no-op rather than an error", async () => {
    const user = userEvent.setup();
    render(<CategoryTabs categories={[]} active="" total={0} />);

    const only = screen.getByRole("tab");
    only.focus();
    await user.keyboard("{ArrowRight}{Home}{End}");

    expect(push).not.toHaveBeenCalled();
    expect(only).toHaveAttribute("tabindex", "0");
  });
});
