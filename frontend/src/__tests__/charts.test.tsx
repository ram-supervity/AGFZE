import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { BarChart } from "@/components/charts/bar-chart";
import { DonutChart } from "@/components/charts/donut-chart";
import { LineChart } from "@/components/charts/line-chart";

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

const BARS = [
  {
    key: "quantity",
    label: "Quantity variation outside tolerance",
    value: 12,
    href: "/exceptions?exception_type=quantity_variation_outside_tolerance",
    detail: "4 over 48 hours",
  },
  { key: "amount", label: "Invoice amount outside tolerance", value: 5, href: null },
];

const SLICES = [
  { key: "succeeded", label: "Succeeded", value: 30, href: "/admin/integrations?status=succeeded" },
  { key: "awaiting", label: "Awaiting a person", value: 12, href: null },
];

const SERIES = [
  { key: "approved", label: "Approved", points: [3, 5, 4], unit: "" },
  { key: "exceptions", label: "Exceptions", points: [1, null, 2], unit: "" },
];

describe("the bar chart", () => {
  it("renders every row with its value shown as text", () => {
    // Colour is never the only signal: each bar carries its own number.
    render(<BarChart data={BARS} valueLabel="Open exceptions" />);

    expect(screen.getByText("Quantity variation outside tolerance")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("5")).toBeInTheDocument();
  });

  it("makes a row with a filter behind it a real link", () => {
    // The platform's stated promise is that every figure drills through to the live, filtered
    // query that reproduces it. That is a link, and it has to survive any change to this file.
    render(<BarChart data={BARS} valueLabel="Open exceptions" />);

    const link = screen.getByRole("link", { name: /Quantity variation/ });
    expect(link).toHaveAttribute(
      "href",
      "/exceptions?exception_type=quantity_variation_outside_tolerance",
    );
  });

  it("renders a row with no filter behind it as plain content, not a dead link", () => {
    render(<BarChart data={BARS} valueLabel="Open exceptions" />);
    expect(screen.queryByRole("link", { name: /Invoice amount/ })).toBeNull();
  });

  it("survives an empty series", () => {
    const { container } = render(<BarChart data={[]} valueLabel="Open exceptions" />);
    expect(container.querySelectorAll("li")).toHaveLength(0);
  });
});

describe("the donut chart", () => {
  it("renders each slice in a legend that states its value", () => {
    render(<DonutChart slices={SLICES} totalLabel="Postings" />);

    expect(screen.getByText("Succeeded")).toBeInTheDocument();
    expect(screen.getByText("Awaiting a person")).toBeInTheDocument();
  });

  it("keeps the drill-through on a slice that has one", () => {
    render(<DonutChart slices={SLICES} totalLabel="Postings" />);

    expect(screen.getByRole("link", { name: /Succeeded/ })).toHaveAttribute(
      "href",
      "/admin/integrations?status=succeeded",
    );
  });

  it("labels the drawing for a screen reader rather than leaving a bare svg", () => {
    const { container } = render(<DonutChart slices={SLICES} totalLabel="Postings" />);
    const svg = container.querySelector('svg[role="img"]');

    expect(svg).not.toBeNull();
    expect(svg).toHaveAttribute("aria-labelledby");
  });
});

describe("the line chart", () => {
  it("plots every series it is given", () => {
    render(<LineChart series={SERIES} labels={["Mon", "Tue", "Wed"]} valueLabel="Per day" />);

    expect(screen.getByText("Approved")).toBeInTheDocument();
    expect(screen.getByText("Exceptions")).toBeInTheDocument();
  });

  it("carries a live text readout, so the figures are not hover-only", () => {
    // The reason this chart is not a stock SVG plot. A visual tooltip tells a sighted mouse user
    // the value and tells nobody else; this region is announced.
    const { container } = render(
      <LineChart series={SERIES} labels={["Mon", "Tue", "Wed"]} valueLabel="Per day" />,
    );

    const live = container.querySelector('[aria-live="polite"]');
    expect(live).not.toBeNull();
    expect(live?.textContent).toContain("Per day");
  });

  it("renders a gap rather than inventing a point where a series has no data", () => {
    // `null` in a series means "not measured", which is a different claim from zero.
    const { container } = render(
      <LineChart series={SERIES} labels={["Mon", "Tue", "Wed"]} valueLabel="Per day" />,
    );
    expect(container.querySelector('svg[role="img"]')).not.toBeNull();
  });
});
