import { cleanup, render, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ReportViewer } from "@/components/reports/report-viewer";
import type { ReportDetail } from "@/lib/api-client";

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

afterEach(cleanup);

/** A report shaped exactly as the API serialises one, figures and filters included. */
function report(overrides: Partial<ReportDetail> = {}): ReportDetail {
  return {
    id: "5f1c2a8e-0000-4000-8000-0000000000aa",
    report_type: "monthly",
    output_format: "pdf",
    template_key: "monthly_management",
    title: "Monthly management report",
    period_start: "2026-07-01T00:00:00Z",
    period_end: "2026-08-01T00:00:00Z",
    stream: "both",
    status_filter: null,
    generation_reference: "AGF-RPT-20260801-9F1C4B72",
    byte_size: 68_402,
    generated_at: "2026-08-01T07:00:00Z",
    generated_by_name: null,
    scheduled: true,
    ai_summary_error: null,
    parameters: { stream: "both", status_filter: null },
    audit_event_id: "11111111-2222-3333-4444-555555555555",
    download_url: "http://localhost:8000/internal/files/reports/x.pdf?expires=1&signature=ab",
    distribution_note:
      "This report was generated and stored in the platform. It has not been sent to any recipient or channel.",
    content: {
      title: "Monthly management report",
      description: "The month that has just ended.",
      report_type: "monthly",
      template_key: "monthly_management",
      generation_reference: "AGF-RPT-20260801-9F1C4B72",
      generated_at: "2026-08-01T07:00:00Z",
      generated_by: null,
      period: { start: "2026-07-01T00:00:00Z", end: "2026-08-01T00:00:00Z" },
      stream: "both",
      status_filter: null,
      disclosures: ["Extraction figures are non-override rates."],
      definitions: {},
      sections: [
        {
          key: "executive_summary",
          title: "Executive summary",
          kind: "ai_summary",
          description: null,
          text: "Throughput held steady across both streams.",
          unavailable_reason: null,
          ai_generated: true,
        },
        {
          key: "headline",
          title: "The month in figures",
          kind: "kpi_grid",
          description: null,
          figures: [
            {
              key: "open_exceptions",
              label: "Open exceptions",
              value: 11,
              unit: "count",
              target: "exceptions",
              filters: { status: "open" },
              note: null,
            },
            {
              key: "turnaround_mean",
              label: "Mean turnaround",
              value: 18.5,
              unit: "hours",
              target: null,
              filters: {},
              note: "Request received to approval decided.",
            },
          ],
        },
        {
          key: "transactions",
          title: "Transactions by status",
          kind: "breakdown",
          description: null,
          columns: [
            { key: "label", label: "Status" },
            { key: "count", label: "Transactions" },
          ],
          rows: [
            {
              label: "Committed",
              count: 12,
              target: "transactions",
              filters: { status: "committed", date_from: "2026-07-01T00:00:00Z" },
            },
          ],
        },
        {
          key: "detail",
          title: "Transactions in the period",
          kind: "table",
          description: null,
          columns: [
            { key: "batch_number", label: "Batch" },
            { key: "value", label: "Value" },
          ],
          rows: [
            {
              batch_number: "I2626-14",
              value: null,
              transaction_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            },
          ],
          truncated: false,
        },
      ],
    },
    ...overrides,
  } as ReportDetail;
}

describe("ReportViewer", () => {
  it("turns every navigable figure into a link that reproduces it", () => {
    // The behaviour the whole screen exists for: a number on a report is never a dead end.
    const { getByText, getAllByText } = render(<ReportViewer report={report()} />);

    const figure = getByText("Open exceptions").closest("div")!;
    const link = within(figure).getByText("View transactions").closest("a")!;
    expect(link).toHaveAttribute("href", "/exceptions?status=open");

    const row = getByText("Committed").closest("tr")!;
    expect(within(row).getByText("View transactions").closest("a")).toHaveAttribute(
      "href",
      "/transactions?status=committed&date_from=2026-07-01T00%3A00%3A00Z",
    );

    expect(getAllByText("View transactions").length).toBeGreaterThan(1);
  });

  it("renders a descriptive figure as text rather than as a link to nowhere", () => {
    const { getByText } = render(<ReportViewer report={report()} />);
    const mean = getByText("Mean turnaround").closest("div")!;

    expect(within(mean).queryByText("View transactions")).toBeNull();
    // And it carries its unit: a duration printed as a bare number is not a duration.
    expect(within(mean).getByText("18.5h")).toBeInTheDocument();
  });

  it("links a detail row to its own batch, and shows a missing figure as a gap", () => {
    const { getByText } = render(<ReportViewer report={report()} />);
    const row = getByText("I2626-14").closest("tr")!;

    expect(within(row).getByText("Open batch").closest("a")).toHaveAttribute(
      "href",
      "/transactions/purchase/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    );
    // No amount recorded is rendered as no amount, never as zero.
    expect(within(row).getByText("-")).toBeInTheDocument();
  });

  it("labels the AI paragraph as the model's work and nothing else as such", () => {
    const { getByText, getAllByText } = render(<ReportViewer report={report()} />);

    expect(getByText("Throughput held steady across both streams.")).toBeInTheDocument();
    expect(getAllByText(/AI-generated/i).length).toBeGreaterThan(0);
  });

  it("says plainly that a report with no summary is otherwise complete", () => {
    const missing = report();
    missing.content.sections[0] = {
      ...missing.content.sections[0],
      text: null,
      ai_generated: false,
      unavailable_reason:
        "The AI summary could not be produced for this report. Every figure below is computed by the platform and is unaffected.",
    };

    const { getByText, queryByText } = render(<ReportViewer report={missing} />);

    expect(getByText(/is unaffected/)).toBeInTheDocument();
    expect(queryByText(/AI-generated summary/)).toBeNull();
    // The deterministic sections are still there in full.
    expect(getByText("Committed")).toBeInTheDocument();
    expect(getByText("I2626-14")).toBeInTheDocument();
  });

  it("never claims the report was sent anywhere, and attributes a scheduled one to nobody", () => {
    const { getByText, container } = render(<ReportViewer report={report()} />);

    expect(getByText(/has not been sent to any recipient/)).toBeInTheDocument();
    expect(getByText("On schedule, by the platform")).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/emailed|distributed to|sent to approved/i);
  });

  it("shows the generation reference so a printed page resolves back to its query", () => {
    const { getAllByText } = render(<ReportViewer report={report()} />);
    expect(getAllByText("AGF-RPT-20260801-9F1C4B72").length).toBeGreaterThan(0);
  });
});
