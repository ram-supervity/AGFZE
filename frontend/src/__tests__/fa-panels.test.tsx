import { readFileSync } from "node:fs";
import { join } from "node:path";

import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { FaFieldsPanel } from "@/components/transactions/fa-fields-panel";
import { LinkedShipmentCard } from "@/components/transactions/linked-shipment-card";
import type { FaFieldSchema, LinkedShipment, TransactionField } from "@/lib/api-client";

afterEach(cleanup);

/** The FA schema exactly as the platform currently seeds it, minus the named columns. */
const CURRENT_SCHEMA: FaFieldSchema[] = [
  {
    name: "rate",
    label: "Rate",
    type: "number",
    required: false,
    section: "Commercials",
    description: "Unit price applied to the quantity.",
  },
  {
    name: "amount",
    label: "Amount",
    type: "number",
    required: false,
    section: "Commercials",
    description: "Total value of the transaction as stated on the document.",
  },
];

/** The same schema after the business has agreed three more fields. Used only here. */
const LARGER_SCHEMA: FaFieldSchema[] = [
  ...CURRENT_SCHEMA,
  {
    name: "fa_service_period",
    label: "Service period",
    type: "date",
    required: true,
    section: "Engagement",
    description: "Period the fee covers.",
  },
  {
    name: "fa_engagement_note",
    label: "Engagement note",
    type: "text",
    required: false,
    section: "Engagement",
    description: "",
  },
  {
    name: "fa_regulator_reference",
    label: "Regulator reference",
    type: "string",
    required: false,
    section: "Engagement",
    description: "",
  },
];

function field(name: string, value: string | null): TransactionField {
  return {
    name,
    label: name,
    owner: "fa_extra",
    type: "string",
    value,
    section: "Additional FA fields",
    source_confidence: null,
    reason_required: false,
    is_overridden: false,
    original_ai_value: null,
    original_confidence: null,
    override_reason: null,
    overridden_by_name: null,
    overridden_at: null,
    options: [],
    editable: true,
  };
}

describe("FaFieldsPanel", () => {
  it("renders exactly the fields the configured schema carries", () => {
    const { getByLabelText, queryByLabelText } = render(
      <FaFieldsPanel
        schema={CURRENT_SCHEMA}
        fields={[field("rate", "1500.00"), field("amount", "18000.00")]}
        disabled={false}
        drafts={{}}
        onDraftChange={vi.fn()}
      />,
    );

    expect(getByLabelText("Rate")).toHaveValue("1500.00");
    expect(getByLabelText("Amount")).toHaveValue("18000.00");
    expect(queryByLabelText("Service period")).toBeNull();
  });

  it("grows to a larger schema with no change to the component", () => {
    // The concrete proof of the platform's "no frontend code change" promise. The same component,
    // handed a bigger schema, renders the bigger form - including a field type it has never seen
    // on an FA transaction before.
    const { getByLabelText } = render(
      <FaFieldsPanel
        schema={LARGER_SCHEMA}
        fields={[field("fa_service_period", "2026-09-01")]}
        disabled={false}
        drafts={{}}
        onDraftChange={vi.fn()}
      />,
    );

    expect(getByLabelText(/Service period/)).toHaveAttribute("type", "date");
    expect(getByLabelText("Regulator reference")).toHaveAttribute("type", "text");
    // A `text` field gets a textarea, from its configured type and from nothing else.
    expect(getByLabelText("Engagement note").tagName).toBe("TEXTAREA");
  });

  it("groups by the section each field declares, rather than by an order of its own", () => {
    const { getByText } = render(
      <FaFieldsPanel
        schema={LARGER_SCHEMA}
        fields={[]}
        disabled={false}
        drafts={{}}
        onDraftChange={vi.fn()}
      />,
    );

    expect(getByText("Commercials")).toBeInTheDocument();
    expect(getByText("Engagement")).toBeInTheDocument();
  });

  it("says something true when the schema configures nothing extra", () => {
    const { container } = render(
      <FaFieldsPanel
        schema={[]}
        fields={[]}
        disabled={false}
        drafts={{}}
        onDraftChange={vi.fn()}
      />,
    );

    expect(container.textContent).toMatch(/No additional FA fields are configured/);
    expect(container.querySelector("input")).toBeNull();
  });

  it("hardcodes no FA field name anywhere in its source", () => {
    // The prohibition, checked against the file rather than against the render. A panel that
    // named even one FA field would stop being schema-driven the moment the business agreed a
    // second one, and no rendering test would notice.
    const source = readFileSync(
      join(process.cwd(), "src/components/transactions/fa-fields-panel.tsx"),
      "utf8",
    );

    // `currency` and `quantity` are deliberately absent from this list. They are FA field names,
    // but they are also two of the platform's schema *types*, which the panel legitimately
    // switches on to choose a control. Asserting against them would fail on the type vocabulary
    // rather than on a hardcoded field, which is a different thing entirely.
    for (const name of [
      "counterparty",
      "transaction_reference",
      "rate",
      "amount",
      "document_type",
      "fa_contract_reference",
    ]) {
      expect(source, `the panel names the FA field '${name}'`).not.toContain(`"${name}"`);
    }

    // And what it does switch on is the schema's type vocabulary, which is shared by every
    // document type on the platform rather than being FA's.
    for (const type of ["number", "currency", "quantity", "date", "text"]) {
      expect(source).toContain(`case "${type}"`);
    }
  });
});

function shipment(overrides: Partial<LinkedShipment> = {}): LinkedShipment {
  return {
    id: "ship-1",
    container_number: "MSKU7781234",
    bl_number: "MAEU-2026-77812",
    carrier: "Sample Line",
    vessel: "MV Northern Trader",
    port_of_loading: "Jebel Ali",
    port_of_discharge: "Nhava Sheva",
    etd: "2026-08-20",
    eta: "2026-09-12",
    current_milestone: "departed",
    status: "on_schedule",
    last_checked_at: "2026-08-28T09:00:00Z",
    last_checked_source: "manual",
    hours_since_check: 2,
    is_stale: false,
    review_flagged: false,
    original_bl_received: false,
    ...overrides,
  };
}

describe("LinkedShipmentCard", () => {
  it("says nothing exists rather than implying a status the platform does not have", () => {
    const { container } = render(<LinkedShipmentCard shipments={[]} />);

    expect(container.textContent).toMatch(/No shipment record exists/);
    expect(container.textContent).not.toMatch(/on schedule/i);
  });

  it("shows the status, the milestone and when anybody last looked", () => {
    const { container } = render(<LinkedShipmentCard shipments={[shipment()]} />);
    const text = (container.textContent ?? "").replace(/\s+/g, " ");

    expect(text).toMatch(/MSKU7781234/);
    expect(text).toMatch(/On schedule/);
    expect(text).toMatch(/Departed/);
    expect(text).toMatch(/Checked 2h ago/);
    expect(text).toMatch(/Entered by hand/);
  });

  it("puts the field BR-07 blocks on in front of the desk that has to act on it", () => {
    const blocked = render(<LinkedShipmentCard shipments={[shipment()]} />);
    expect(blocked.container.textContent).toMatch(/Original B\/L not yet in hand/);
    cleanup();

    const cleared = render(
      <LinkedShipmentCard shipments={[shipment({ original_bl_received: true })]} />,
    );
    expect(cleared.container.textContent).toMatch(/Original B\/L received/);
  });

  it("renders a manually tracked shipment identically to an automatically tracked one", () => {
    // The claim the whole module rests on, checked on the screen. Only the provenance caption
    // differs; every other word on the card is the same.
    const manual = render(<LinkedShipmentCard shipments={[shipment()]} />);
    const manualText = (manual.container.textContent ?? "").replace(/\s+/g, " ");
    cleanup();

    const automated = render(
      <LinkedShipmentCard shipments={[shipment({ last_checked_source: "some-carrier" })]} />,
    );
    const automatedText = (automated.container.textContent ?? "").replace(/\s+/g, " ");

    expect(manualText.replace("Entered by hand", "")).toBe(
      automatedText.replace("Reported by some-carrier", ""),
    );
  });

  it("flags an implausible change without hiding the values it was saved with", () => {
    const { container } = render(
      <LinkedShipmentCard
        shipments={[shipment({ review_flagged: true, eta: "2026-08-30" })]}
      />,
    );

    expect(container.textContent).toMatch(/Needs a look/);
    // The change was saved, so the figure is still shown.
    expect(container.textContent).toMatch(/30 Aug 2026/);
  });
});
