"""The generated document templates, as a declaration and as the real DOCX files built from it.

One declaration, two consumers. The builder writes the `.docx` that ships beside this module;
the renderer opens that same `.docx` and populates it. Because the clause registry the AI is
validated against is read from the same declaration, a clause key the model returns that this
file does not name is caught before anything is written - the model cannot invent a clause into
a document, and it cannot delete one the declaration marks as required.

Territory selects field content and the territory-specific reference line, not a separate
template file. **Stated assumption:** the governing material for this step describes what each
territory's paperwork must reference, not four structurally different legal layouts, so building
four separate documents would be inventing three sets of contract structure nobody specified.
One template per document type, with territory-driven content inside it, is what the available
detail actually justifies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.models.enums import DocumentType, Territory

ASSET_ROOT = Path(__file__).resolve().parent / "assets"

# The token the builder writes at the head of a clause paragraph and the renderer strips once it
# has decided what to do with that clause. It is never left in a produced document.
CLAUSE_MARKER = "[[clause:{key}]]"

# What a populated value looks like in the template. Written as one run so substitution is a
# run-level replacement and the surrounding formatting survives it untouched.
PLACEHOLDER = "{{{{{name}}}}}"


@dataclass(frozen=True)
class TemplateField:
    """One deal-specific value the template carries a slot for."""

    name: str
    label: str
    # Fields in the header grid are laid out as a two-column table; body fields are inline.
    in_header: bool = True


@dataclass(frozen=True)
class TemplateClause:
    """One clause of the document, and what the model is allowed to do with it."""

    key: str
    heading: str
    body: str
    # A clause the document is not a document without. The model may revise it; it may never
    # remove it, and a response that asks to is rejected before anything is rendered.
    required: bool = False
    # Told to the model so it can decide. Never rendered.
    purpose: str = ""


@dataclass(frozen=True)
class DocumentTemplate:
    document_type: str
    title: str
    subtitle: str
    filename: str
    fields: tuple[TemplateField, ...]
    clauses: tuple[TemplateClause, ...]
    footer_note: str

    @property
    def clause_keys(self) -> frozenset[str]:
        return frozenset(clause.key for clause in self.clauses)

    @property
    def required_clause_keys(self) -> frozenset[str]:
        return frozenset(clause.key for clause in self.clauses if clause.required)

    def clause(self, key: str) -> TemplateClause | None:
        return next((row for row in self.clauses if row.key == key), None)

    @property
    def field_names(self) -> tuple[str, ...]:
        return tuple(row.name for row in self.fields)


# --- territory-driven content -----------------------------------------------------------------
#
# Content, not layout. Each entry is the reference line the destination territory's customs and
# import regime requires the paperwork to carry, and it is the only thing that changes between a
# China-bound and an India-bound draft of the same document.

TERRITORY_REFERENCES: dict[str, str] = {
    Territory.INDIA.value: (
        "Consignment is declared for import into India. Buyer's IEC and GSTIN are to be quoted "
        "on all shipping documents, and the pre-shipment inspection certificate required under "
        "the Hazardous and Other Wastes (Management and Transboundary Movement) Rules is to "
        "accompany this consignment."
    ),
    Territory.CHINA.value: (
        "Consignment is declared for import into the People's Republic of China. Goods are "
        "described in accordance with GB/T 38470 recycled non-ferrous metal raw material "
        "standards, and Buyer's China Customs registration and AQSIQ / GACC filing details are "
        "to be quoted on all shipping documents."
    ),
    Territory.JAPAN.value: (
        "Consignment is declared for import into Japan. Buyer is to quote its Japan Customs "
        "importer code, and the goods description is to follow the Japanese Customs tariff "
        "classification agreed between the parties."
    ),
    Territory.OTHER.value: (
        "Consignment is declared for import into the destination named above. Buyer is "
        "responsible for all import licences, registrations and customs formalities required at "
        "the port of discharge, and is to advise Seller of any documentary requirement in "
        "writing before shipment."
    ),
}


def territory_reference(territory: str | None) -> str:
    """The destination's required reference wording. Never a guess - `other` is a real entry."""
    return TERRITORY_REFERENCES.get(
        (territory or "").strip().lower(), TERRITORY_REFERENCES[Territory.OTHER.value]
    )


# --- the sales contract -------------------------------------------------------------------------

CONTRACT_FIELDS: tuple[TemplateField, ...] = (
    TemplateField("contract_no", "Sales contract number"),
    TemplateField("contract_date", "Date"),
    TemplateField("batch_number", "AGFZE batch reference"),
    TemplateField("seller", "Seller"),
    TemplateField("buyer", "Buyer"),
    TemplateField("territory", "Destination territory"),
    TemplateField("commodity", "Commodity"),
    TemplateField("commodity_code", "Trade grade"),
    TemplateField("quantity", "Quantity (this shipment)"),
    TemplateField("contracted_quantity", "Contracted quantity (total)"),
    TemplateField("price_terms", "Price"),
    TemplateField("currency", "Currency"),
    TemplateField("payment_condition", "Payment condition"),
    TemplateField("port_of_loading", "Port of loading"),
    TemplateField("port_of_discharge", "Port of discharge"),
    TemplateField("inland_container_depot", "Inland container depot"),
    TemplateField("bl_reference", "Bill of lading reference"),
)

CONTRACT_CLAUSES: tuple[TemplateClause, ...] = (
    TemplateClause(
        key="parties",
        heading="1. Parties and subject",
        body=(
            "This contract is made between {{seller}} (“Seller”) and {{buyer}} "
            "(“Buyer”) for the sale and purchase of the goods described below, shipped "
            "under AGFZE batch reference {{batch_number}}."
        ),
        required=True,
        purpose="Names the two parties and the batch. Always present in any sales contract.",
    ),
    TemplateClause(
        key="goods",
        heading="2. Goods",
        body=(
            "Commodity: {{commodity}} (trade grade {{commodity_code}}). Quantity for this "
            "shipment: {{quantity}}, forming part of a total contracted quantity of "
            "{{contracted_quantity}} under this contract number. Material is sold on an as-is "
            "recovered-metal basis, free of radioactivity, explosives and closed containers."
        ),
        required=True,
        purpose="Describes what is being sold and how much. Always present.",
    ),
    TemplateClause(
        key="quantity_tolerance",
        heading="3. Quantity tolerance",
        body=(
            "Shipped weight may vary from the quantity stated above within the tolerance agreed "
            "between the parties. The final settled weight is the outturn weight established at "
            "the port of discharge unless the parties have agreed otherwise in writing."
        ),
        purpose=(
            "Applies where the shipped weight is expected to settle against an outturn weight. "
            "Remove it where the parties have contracted a fixed, non-varying quantity."
        ),
    ),
    TemplateClause(
        key="pricing_fixed",
        heading="4. Price",
        body=(
            "The price for this shipment is {{price_terms}}, on the delivery terms stated "
            "above. No further price fixation applies to this contract."
        ),
        purpose=(
            "The fixed-price clause. Correct where the deal is priced at a flat rate, and also "
            "where an LME-linked deal has since been fixed by the customer, in which case the "
            "fixed rate and the fixation date should be stated."
        ),
    ),
    TemplateClause(
        key="pricing_lme",
        heading="4. Price",
        body=(
            "The price for this shipment is {{price_terms}}, calculated on the London Metal "
            "Exchange cash settlement for the relevant grade over the pricing period agreed "
            "between the parties, settled in {{currency}}, on the delivery terms stated above."
        ),
        purpose=(
            "The LME-percentage clause. Correct only while the price is still a percentage of "
            "the exchange and the customer has not fixed. Remove it once the customer has fixed."
        ),
    ),
    TemplateClause(
        key="price_fixation",
        heading="5. Price fixation",
        body=(
            "Buyer shall declare its fixation in writing to Seller during the agreed pricing "
            "period. Where Buyer has not declared a fixation by the close of that period, the "
            "price shall be established on the basis agreed between the parties."
        ),
        purpose=(
            "Explains how the customer fixes a price that is not yet fixed. Remove it entirely "
            "once fixation has already happened, because there is nothing left to fix."
        ),
    ),
    TemplateClause(
        key="payment_cad",
        heading="6. Payment",
        body=(
            "Payment is on Cash Against Documents ({{payment_condition}}). Seller shall present "
            "the full documentary set through the agreed channel, and Buyer shall pay against "
            "presentation of those documents."
        ),
        purpose=(
            "The Cash Against Documents payment clause. Use it when the payment condition is "
            "CAD; remove it when the condition is TT."
        ),
    ),
    TemplateClause(
        key="payment_tt",
        heading="6. Payment",
        body=(
            "Payment is by telegraphic transfer ({{payment_condition}}) to Seller's nominated "
            "account, in {{currency}} and in cleared funds, on the terms agreed between the "
            "parties. Release of the transport documents follows receipt of cleared funds."
        ),
        purpose=(
            "The telegraphic-transfer payment clause. Use it when the payment condition is TT; "
            "remove it when the condition is CAD."
        ),
    ),
    TemplateClause(
        key="delivery",
        heading="7. Delivery and shipment",
        body=(
            "Shipment is from {{port_of_loading}} to {{port_of_discharge}}. Where an inland "
            "container depot is nominated, it is {{inland_container_depot}}. Bill of lading "
            "reference for this shipment: {{bl_reference}}."
        ),
        required=True,
        purpose="States where the cargo moves from and to. Always present.",
    ),
    TemplateClause(
        key="documents",
        heading="8. Documents and destination requirements",
        body=(
            "Seller shall provide the commercial invoice, packing list, bill of lading and "
            "certificate of origin, together with any further document the destination requires. "
            "{{territory_reference}}"
        ),
        required=True,
        purpose=(
            "The documentary set and the destination's own requirements. Always present; its "
            "destination wording is populated from the recorded territory rather than chosen."
        ),
    ),
    TemplateClause(
        key="inspection",
        heading="9. Inspection",
        body=(
            "Either party may appoint an independent surveyor at the port of loading or the port "
            "of discharge, at its own cost, and the other party shall be given reasonable notice "
            "of any such appointment."
        ),
        purpose=(
            "The surveyor clause. Keep it where an independent inspection is part of the deal; "
            "remove it where the parties have agreed to settle on the carrier's figures alone."
        ),
    ),
    TemplateClause(
        key="title_risk",
        heading="10. Title and risk",
        body=(
            "Risk passes in accordance with the delivery terms stated above. Title passes to "
            "Buyer on receipt by Seller of payment in full and in cleared funds."
        ),
        required=True,
        purpose="When risk and ownership move. Always present.",
    ),
    TemplateClause(
        key="force_majeure",
        heading="11. Force majeure",
        body=(
            "Neither party is liable for a failure to perform caused by an event beyond its "
            "reasonable control. The affected party shall notify the other in writing without "
            "delay and the parties shall discuss the consequences in good faith."
        ),
        required=True,
        purpose="Standard force majeure. Always present.",
    ),
    TemplateClause(
        key="governing_law",
        heading="12. Governing law",
        body=(
            "This contract is governed by the law agreed between the parties, and any dispute "
            "arising out of it is to be resolved in the forum the parties have agreed."
        ),
        required=True,
        purpose="Governing law and forum. Always present.",
    ),
)

SALES_CONTRACT_TEMPLATE = DocumentTemplate(
    document_type=DocumentType.DRAFT_CONTRACT.value,
    title="SALES CONTRACT",
    subtitle="Draft for internal review - not issued, not signed",
    filename="sales_contract_template.docx",
    fields=CONTRACT_FIELDS,
    clauses=CONTRACT_CLAUSES,
    footer_note=(
        "DRAFT. Generated by the AGFZE Command Centre from the transaction record on "
        "{{generated_at}} at the request of {{generated_by}}. This document has not been "
        "issued, sent or signed. It is for review inside AGFZE only; the signed original is a "
        "wet-signed paper document produced outside this platform."
    ),
)


# --- the sales invoice ---------------------------------------------------------------------------

INVOICE_FIELDS: tuple[TemplateField, ...] = (
    TemplateField("invoice_no", "Sales invoice number"),
    TemplateField("invoice_date", "Date"),
    TemplateField("contract_no", "Sales contract number"),
    TemplateField("batch_number", "AGFZE batch reference"),
    TemplateField("seller", "Seller"),
    TemplateField("buyer", "Buyer"),
    TemplateField("territory", "Destination territory"),
    TemplateField("commodity", "Commodity"),
    TemplateField("commodity_code", "Trade grade"),
    TemplateField("quantity", "Quantity"),
    TemplateField("price_terms", "Rate"),
    TemplateField("currency", "Currency"),
    TemplateField("total_value", "Invoice value"),
    TemplateField("invoice_basis", "Invoice basis"),
    TemplateField("payment_condition", "Payment condition"),
    TemplateField("port_of_loading", "Port of loading"),
    TemplateField("port_of_discharge", "Port of discharge"),
    TemplateField("bl_reference", "Bill of lading reference"),
)

INVOICE_CLAUSES: tuple[TemplateClause, ...] = (
    TemplateClause(
        key="header",
        heading="Invoice to",
        body=(
            "{{buyer}}, against sales contract {{contract_no}} and AGFZE batch reference "
            "{{batch_number}}. Bill of lading reference {{bl_reference}}."
        ),
        required=True,
        purpose="Who is invoiced and against what. Always present.",
    ),
    TemplateClause(
        key="goods_description",
        heading="Description of goods",
        body=(
            "{{commodity}} (trade grade {{commodity_code}}), {{quantity}}, shipped "
            "{{port_of_loading}} to {{port_of_discharge}}."
        ),
        required=True,
        purpose="What is being invoiced. Always present.",
    ),
    TemplateClause(
        key="pricing_provisional",
        heading="Provisional value",
        body=(
            "This is a PROVISIONAL invoice. The value of {{total_value}} is calculated on a "
            "price of {{price_terms}} and is subject to adjustment once the price is fixed. A "
            "final invoice will follow on fixation."
        ),
        purpose=(
            "The provisional-value clause. Correct while the customer has not fixed the price. "
            "Remove it once fixation has happened, because the value is then settled."
        ),
    ),
    TemplateClause(
        key="pricing_final",
        heading="Final value",
        body=(
            "This is a FINAL invoice. The value of {{total_value}} is calculated on a fixed "
            "price of {{price_terms}} and is not subject to further adjustment."
        ),
        purpose=(
            "The final-value clause. Correct once the customer has fixed the price. Remove it "
            "while the price is still unfixed."
        ),
    ),
    TemplateClause(
        key="lme_reference",
        heading="Pricing basis",
        body=(
            "Price basis: {{price_terms}}, referenced to the London Metal Exchange cash "
            "settlement for the relevant grade over the agreed pricing period."
        ),
        purpose=(
            "The exchange-reference line. Keep it on any LME-linked deal, fixed or not, since "
            "the customer still needs the basis on the face of the invoice. Remove it entirely "
            "on a flat-priced deal, where there is no exchange reference to state."
        ),
    ),
    TemplateClause(
        key="payment_cad",
        heading="Payment",
        body=(
            "Payable on Cash Against Documents ({{payment_condition}}) in {{currency}}, against "
            "presentation of the full documentary set."
        ),
        purpose="Use where the payment condition is CAD; remove where it is TT.",
    ),
    TemplateClause(
        key="payment_tt",
        heading="Payment",
        body=(
            "Payable by telegraphic transfer ({{payment_condition}}) in {{currency}} to the "
            "Seller's nominated account, in cleared funds."
        ),
        purpose="Use where the payment condition is TT; remove where it is CAD.",
    ),
    TemplateClause(
        key="bank_details",
        heading="Remittance",
        body=(
            "Bank details for remittance are those held on file for {{seller}} and confirmed to "
            "Buyer in writing. Buyer must not act on bank details received by any other route."
        ),
        required=True,
        purpose=(
            "Remittance instructions and the warning against acting on details from elsewhere. "
            "Always present; it is a fraud control, not a commercial term."
        ),
    ),
    TemplateClause(
        key="destination_declaration",
        heading="Destination requirements",
        body="{{territory_reference}}",
        required=True,
        purpose=(
            "The destination's own declaration. Always present; its wording is populated from "
            "the recorded territory rather than chosen."
        ),
    ),
    TemplateClause(
        key="declaration",
        heading="Declaration",
        body=(
            "We certify the above particulars to be true and correct, and that the goods are of "
            "the origin and description stated."
        ),
        required=True,
        purpose="The seller's certification. Always present.",
    ),
)

SALES_INVOICE_TEMPLATE = DocumentTemplate(
    document_type=DocumentType.DRAFT_INVOICE.value,
    title="COMMERCIAL INVOICE",
    subtitle="Draft for internal review - not issued, not signed",
    filename="sales_invoice_template.docx",
    fields=INVOICE_FIELDS,
    clauses=INVOICE_CLAUSES,
    footer_note=(
        "DRAFT. Generated by the AGFZE Command Centre from the transaction record on "
        "{{generated_at}} at the request of {{generated_by}}. This document has not been "
        "issued, sent or signed. It is for review inside AGFZE only; the signed original is a "
        "wet-signed paper document produced outside this platform."
    ),
)

# --- the Performa invoice ---------------------------------------------------------------------
#
# The advance, clean invoice, raised before the cargo is weighed. Discovery describes it exactly
# that way, and its defining property is what it *lacks*: there is no weight slip behind it and no
# shipped weight to state, which is why it is a distinct document rather than a commercial invoice
# with some fields left blank. A commercial invoice with a blank weight would read as a document
# somebody forgot to finish; this one is complete as it stands.
#
# It therefore carries no `bl_reference` and no shipped quantity: the contracted quantity is what
# it invoices against. Every clause below that would have asserted something about the shipment
# has been left out rather than softened.
#
# **Approval tier - an open question, stated here rather than decided.** Discovery says a Performa
# invoice "requires CEO approval". This platform has no `ceo` role: its approving tier is
# `approver_hod`, with `admin` alongside. Inventing a role would change who can sign off what on
# the day the platform goes live, which is not a decision a template file should make. So a
# Performa invoice routes through the existing `approver_hod` tier, exactly as every other draft
# does, and the question is recorded in docs/KNOWN-GAPS.md for AGFZE to answer.

PERFORMA_FIELDS: tuple[TemplateField, ...] = (
    TemplateField("invoice_no", "Performa invoice number"),
    TemplateField("invoice_date", "Date"),
    TemplateField("contract_no", "Sales contract number"),
    TemplateField("batch_number", "AGFZE batch reference"),
    TemplateField("seller", "Seller"),
    TemplateField("buyer", "Buyer"),
    TemplateField("territory", "Destination territory"),
    TemplateField("commodity", "Commodity"),
    TemplateField("commodity_code", "Trade grade"),
    TemplateField("quantity", "Contracted quantity"),
    TemplateField("price_terms", "Rate"),
    TemplateField("currency", "Currency"),
    TemplateField("total_value", "Performa value"),
    TemplateField("payment_condition", "Payment condition"),
    TemplateField("port_of_loading", "Port of loading"),
    TemplateField("port_of_discharge", "Port of discharge"),
)

PERFORMA_CLAUSES: tuple[TemplateClause, ...] = (
    TemplateClause(
        key="header",
        heading="Performa invoice to",
        body=(
            "{{buyer}}, against sales contract {{contract_no}} and AGFZE batch reference "
            "{{batch_number}}."
        ),
        required=True,
        purpose="Who is invoiced and against what. Always present.",
    ),
    TemplateClause(
        key="provisional_basis",
        heading="Basis",
        body=(
            "This is a Performa invoice raised in advance of shipment. The quantity stated is "
            "the contracted quantity; it is not a shipped weight and no weight slip accompanies "
            "this document. A commercial invoice stating the shipped weight follows once the "
            "cargo is loaded and weighed."
        ),
        required=True,
        purpose=(
            "The clause that makes this document honest about what it is. Always present, and "
            "never to be revised into a claim about a shipped weight - there is not one."
        ),
    ),
    TemplateClause(
        key="goods",
        heading="Goods",
        body=(
            "{{commodity}} ({{commodity_code}}), {{quantity}} contracted, at {{price_terms}}, "
            "{{currency}} {{total_value}}."
        ),
        required=True,
        purpose="The commercial particulars as contracted. Always present.",
    ),
    TemplateClause(
        key="advance_payment",
        heading="Advance payment",
        body=(
            "Payable in advance in {{currency}} on the terms agreed ({{payment_condition}}), to "
            "the Seller's nominated account in cleared funds."
        ),
        required=True,
        purpose=(
            "A Performa invoice exists to be paid against in advance, so the payment clause is "
            "always present. Revise the wording to match the agreed terms; never remove it."
        ),
    ),
    TemplateClause(
        key="bank_details",
        heading="Remittance",
        body=(
            "Bank details for remittance are those held on file for {{seller}} and confirmed to "
            "Buyer in writing. Buyer must not act on bank details received by any other route."
        ),
        required=True,
        purpose=(
            "Remittance instructions and the warning against acting on details from elsewhere. "
            "Always present; it is a fraud control, not a commercial term."
        ),
    ),
    TemplateClause(
        key="shipment",
        heading="Shipment",
        body="Shipment from {{port_of_loading}} to {{port_of_discharge}}.",
        purpose=(
            "The intended routing. Keep it where both ports are recorded; remove it where the "
            "routing is not yet agreed, rather than stating a port nobody has confirmed."
        ),
    ),
    TemplateClause(
        key="destination_declaration",
        heading="Destination requirements",
        body="{{territory_reference}}",
        required=True,
        purpose=(
            "The destination's own declaration. Always present; its wording is populated from "
            "the recorded territory rather than chosen."
        ),
    ),
)

PERFORMA_INVOICE_TEMPLATE = DocumentTemplate(
    document_type=DocumentType.DRAFT_PERFORMA_INVOICE.value,
    title="PERFORMA INVOICE",
    subtitle="Draft for internal review - not issued, not signed",
    filename="performa_invoice_template.docx",
    fields=PERFORMA_FIELDS,
    clauses=PERFORMA_CLAUSES,
    footer_note=(
        "DRAFT. Generated by the AGFZE Command Centre from the transaction record on "
        "{{generated_at}} at the request of {{generated_by}}. This document has not been "
        "issued, sent or signed. It is a Performa invoice raised in advance of shipment and "
        "states a contracted quantity, not a shipped weight."
    ),
)


# --- the bank cover letter ----------------------------------------------------------------------
#
# The covering note that goes to the bank with a documentary set. Discovery describes it as
# auto-filled, which is accurate: every value on it is already recorded on the transaction, and it
# asserts nothing that is not stated on the documents it accompanies.
#
# Deliberately narrow. It states what is enclosed, against which contract, and what the bank is
# asked to do with it. It carries **no** commercial terms of its own - no rate, no invoice value -
# because a cover letter that restated the commercial terms would be a second, unsigned source of
# them, and a discrepancy between it and the invoice is exactly the sort of thing that holds a
# documentary presentation up at the bank.

BANK_LETTER_FIELDS: tuple[TemplateField, ...] = (
    TemplateField("letter_date", "Date"),
    TemplateField("contract_no", "Sales contract number"),
    TemplateField("invoice_no", "Sales invoice number"),
    TemplateField("batch_number", "AGFZE batch reference"),
    TemplateField("seller", "Seller"),
    TemplateField("buyer", "Buyer"),
    TemplateField("bank_name", "Presenting bank"),
    TemplateField("commodity", "Commodity"),
    TemplateField("quantity", "Quantity"),
    TemplateField("currency", "Currency"),
    TemplateField("total_value", "Invoice value"),
    TemplateField("payment_condition", "Payment condition"),
    TemplateField("bl_reference", "Bill of lading reference"),
    TemplateField("port_of_discharge", "Port of discharge"),
)

BANK_LETTER_CLAUSES: tuple[TemplateClause, ...] = (
    TemplateClause(
        key="addressee",
        heading="To",
        body=(
            "{{bank_name}}. We enclose the documentary set covering our sales contract "
            "{{contract_no}} and AGFZE batch reference {{batch_number}}, drawn on {{buyer}}."
        ),
        required=True,
        purpose="Who the letter is to and what it covers. Always present.",
    ),
    TemplateClause(
        key="enclosures",
        heading="Documents enclosed",
        body=(
            "Commercial invoice {{invoice_no}}, bill of lading {{bl_reference}}, and the "
            "supporting certificates for {{quantity}} of {{commodity}} shipped to "
            "{{port_of_discharge}}."
        ),
        required=True,
        purpose=(
            "The list of what is actually in the envelope. Always present, and revise it to "
            "match the set genuinely being presented - a cover letter that lists a document "
            "which is not enclosed is what holds a presentation up."
        ),
    ),
    TemplateClause(
        key="instruction",
        heading="Instruction",
        body=(
            "Please present these documents on {{payment_condition}} terms and release them "
            "against payment of {{currency}} {{total_value}} in accordance with the contract."
        ),
        required=True,
        purpose=(
            "What the bank is being asked to do. Always present. The one place a value appears "
            "on this letter, because the release is conditional on it."
        ),
    ),
    TemplateClause(
        key="remittance",
        heading="Remittance",
        body=(
            "Proceeds are to be remitted to the account held on file for {{seller}}. Please "
            "confirm receipt of these documents and advise us on presentation."
        ),
        required=True,
        purpose="Where the money goes and the acknowledgement asked for. Always present.",
    ),
)

BANK_COVER_LETTER_TEMPLATE = DocumentTemplate(
    document_type=DocumentType.DRAFT_BANK_COVER_LETTER.value,
    title="BANK COVER LETTER",
    subtitle="Draft for internal review - not issued, not signed",
    filename="bank_cover_letter_template.docx",
    fields=BANK_LETTER_FIELDS,
    clauses=BANK_LETTER_CLAUSES,
    footer_note=(
        "DRAFT. Generated by the AGFZE Command Centre from the transaction record on "
        "{{generated_at}} at the request of {{generated_by}}. This document has not been "
        "issued, sent or signed, and has not been presented to any bank."
    ),
)


TEMPLATES_BY_TYPE: dict[str, DocumentTemplate] = {
    SALES_CONTRACT_TEMPLATE.document_type: SALES_CONTRACT_TEMPLATE,
    SALES_INVOICE_TEMPLATE.document_type: SALES_INVOICE_TEMPLATE,
    PERFORMA_INVOICE_TEMPLATE.document_type: PERFORMA_INVOICE_TEMPLATE,
    BANK_COVER_LETTER_TEMPLATE.document_type: BANK_COVER_LETTER_TEMPLATE,
}

# Fields every template carries whether or not it declares them: the provenance line at the foot
# of a generated draft, and the destination wording clauses reference.
COMMON_FIELDS: tuple[str, ...] = ("generated_at", "generated_by", "territory_reference")


@dataclass(frozen=True)
class BuildReport:
    written: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def template_path(template: DocumentTemplate) -> Path:
    return ASSET_ROOT / template.filename


def _split_placeholders(text: str) -> list[tuple[str, bool]]:
    """Cut a body into alternating literal and placeholder segments.

    Each placeholder becomes its own run in the built template, which is the whole reason
    substitution at render time is a run-level replacement rather than a fragile scan across a
    paragraph whose text `python-docx` has already split at formatting boundaries.
    """
    segments: list[tuple[str, bool]] = []
    remainder = text
    while True:
        start = remainder.find("{{")
        if start == -1:
            break
        end = remainder.find("}}", start)
        if end == -1:
            break
        if start:
            segments.append((remainder[:start], False))
        segments.append((remainder[start : end + 2], True))
        remainder = remainder[end + 2 :]
    if remainder:
        segments.append((remainder, False))
    return segments


def build_document(template: DocumentTemplate):
    """Write one template as a real, well-structured DOCX.

    Deterministic and reproducible: run it twice and you get the same document. Nothing here
    asks a model for anything - the template is the platform's own paperwork.
    """
    from docx import Document as DocxDocument
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt

    document = DocxDocument()

    heading = document.add_paragraph()
    heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = heading.add_run(template.title)
    run.bold = True
    run.font.size = Pt(18)

    subtitle = document.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    marker = subtitle.add_run(template.subtitle)
    marker.italic = True
    marker.font.size = Pt(10)

    grid = document.add_table(rows=0, cols=2)
    grid.style = "Table Grid"
    for item in template.fields:
        row = grid.add_row().cells
        label = row[0].paragraphs[0].add_run(item.label)
        label.bold = True
        label.font.size = Pt(9)
        # One run, exactly the placeholder. The renderer replaces this run's text and styles it.
        value = row[1].paragraphs[0].add_run(PLACEHOLDER.format(name=item.name))
        value.font.size = Pt(9)

    document.add_paragraph()

    for clause in template.clauses:
        clause_heading = document.add_paragraph()
        # The marker identifies the clause to the renderer and is stripped from every produced
        # document, kept or revised. It never survives into a draft anybody reads.
        clause_heading.add_run(CLAUSE_MARKER.format(key=clause.key))
        title = clause_heading.add_run(clause.heading)
        title.bold = True
        title.font.size = Pt(11)

        body = document.add_paragraph()
        for text, is_placeholder in _split_placeholders(clause.body):
            piece = body.add_run(text)
            piece.font.size = Pt(10)
            if is_placeholder:
                piece.bold = True

    document.add_paragraph()
    footer = document.add_paragraph()
    for text, is_placeholder in _split_placeholders(template.footer_note):
        piece = footer.add_run(text)
        piece.italic = True
        piece.font.size = Pt(8)
        if is_placeholder:
            piece.bold = True

    return document


def ensure_template_files(*, overwrite: bool = False) -> BuildReport:
    """Materialise every declared template on disk, so the renderer always has a file to open.

    Called once at application start and by the build entry point. Idempotent: an existing
    template is left exactly as it is unless `overwrite` is asked for, so an administrator who
    has adjusted the shipped wording does not have it silently replaced on the next deploy.
    """
    ASSET_ROOT.mkdir(parents=True, exist_ok=True)
    report = BuildReport()
    for template in TEMPLATES_BY_TYPE.values():
        destination = template_path(template)
        if destination.exists() and not overwrite:
            report.skipped.append(destination.name)
            continue
        build_document(template).save(str(destination))
        report.written.append(destination.name)
    return report


if __name__ == "__main__":  # pragma: no cover - a build entry point, not application code
    result = ensure_template_files(overwrite=True)
    for name in result.written:
        print(f"wrote {name}")
