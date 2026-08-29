import { cleanup, render } from "@testing-library/react";
import { Rocket } from "lucide-react";
import { afterEach, describe, expect, it } from "vitest";

import { ModuleStatusCard } from "@/components/shared/module-status-card";
import { NAV_ITEMS, type NavItem } from "@/lib/navigation";

// Every module in the sidebar is live from  - Admin, Settings and Notifications were the
// last three still to come - so there is no longer a real planned item to render this against.
// The card is still the platform's way of presenting a module that does not exist yet, so it is
// exercised against a synthetic one rather than deleted along with the last real "coming soon".
const planned: NavItem = {
  key: "synthetic",
  label: "Offline mode",
  href: "/synthetic",
  icon: Rocket,
  roles: [],
  status: "planned",
  availableFrom: "",
  summary: "A module that has not been built yet, used here to exercise the card.",
};

const textOf = (container: HTMLElement) => (container.textContent ?? "").replace(/\s+/g, " ").trim();

afterEach(cleanup);

describe("ModuleStatusCard", () => {
  it("renders the module's own copy and the  it arrives in", () => {
    const { container, getByText } = render(<ModuleStatusCard item={planned} />);

    expect(getByText(planned.label)).toBeInTheDocument();
    expect(getByText(planned.summary)).toBeInTheDocument();
    expect(textOf(container)).toMatch(/coming soon/i);
    expect(textOf(container)).toMatch(/Arrives in\s*/);
  });

  it("stays inert so it cannot be mistaken for a working module", () => {
    const { container } = render(<ModuleStatusCard item={planned} />);

    expect(container.querySelector("a")).toBeNull();
    expect(container.querySelector("button")).toBeNull();
  });

  it("shows no number other than the arrival ", () => {
    const { container } = render(<ModuleStatusCard item={planned} />);
    const numbers = textOf(container).match(/\d+/g) ?? [];

    expect(numbers).toEqual(["10"]);
  });

  it("has no live module left to render, which is the point of ", () => {
    // The last three deferred sections - Admin, Settings and Notifications - became real here.
    expect(NAV_ITEMS.filter((item) => item.status === "planned")).toEqual([]);
  });
});
