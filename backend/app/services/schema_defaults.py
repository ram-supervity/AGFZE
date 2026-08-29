"""Default `DocumentTypeSchema` rows shipped with the platform.

These are the seed values the Step 2 migration writes. They are data, not behaviour: the
extraction service reads whatever the table holds at call time, so editing a row (Step 9 adds
the screen) changes what is extracted with no code change at all.

`tolerance` is recorded against the field it belongs to. It is documentation of what the field
type will bear; the tolerance a transaction is actually judged against is the configured one in
`rule_configurations`, which the Step 3 rule engine reads per rule and per commodity.
"""

from __future__ import annotations

from typing import Any

from app.models.enums import DocumentType, Territory

SEED_CHANGE_REASON = "Initial platform default schema shipped with the intake module."

INVOICE_FIELDS: list[dict[str, Any]] = [
    {
        "name": "invoice_number",
        "label": "Invoice number",
        "type": "string",
        "required": True,
        "tolerance": None,
        "section": "Identification",
        "description": "The seller's own invoice reference, exactly as printed.",
    },
    {
        "name": "contract_reference",
        "label": "Contract / PO reference",
        "type": "string",
        "required": True,
        "tolerance": None,
        "section": "Identification",
        "description": "Contract or purchase order number the invoice is raised against.",
    },
    {
        "name": "batch_number",
        "label": "Batch number",
        "type": "string",
        "required": False,
        "tolerance": None,
        "section": "Identification",
        "description": "Supplier batch or lot reference for the material invoiced.",
    },
    {
        "name": "supplier_name",
        "label": "Supplier",
        "type": "string",
        "required": True,
        "tolerance": None,
        "section": "Parties",
        "description": "Registered name of the party raising the invoice.",
    },
    {
        "name": "invoice_status",
        "label": "Invoice status",
        "type": "string",
        "required": False,
        "tolerance": None,
        "section": "Identification",
        "description": "Whether the invoice is provisional (price not yet fixed) or final. "
        "Report exactly 'provisional' or 'final'.",
    },
    {
        "name": "commodity_code",
        "label": "Commodity code",
        "type": "string",
        "required": False,
        "tolerance": None,
        "section": "Goods",
        "description": "Trade grade or ISRI code for the scrap grade invoiced.",
    },
    {
        "name": "quantity",
        "label": "Quantity",
        "type": "quantity",
        "required": True,
        "tolerance": 0.02,
        "section": "Goods",
        "description": "Invoiced weight with its unit, for example '24.500 MT'.",
    },
    {
        "name": "rate",
        "label": "Rate",
        "type": "number",
        "required": True,
        "tolerance": 0.01,
        "section": "Commercials",
        "description": "Unit price applied to the invoiced quantity.",
    },
    {
        "name": "currency",
        "label": "Currency",
        "type": "string",
        "required": True,
        "tolerance": None,
        "section": "Commercials",
        "description": "ISO 4217 currency code of the invoice total.",
    },
    {
        "name": "amount",
        "label": "Invoice amount",
        "type": "number",
        "required": True,
        "tolerance": 0.01,
        "section": "Commercials",
        "description": "Total invoiced value before any separately stated tax.",
    },
    {
        "name": "container_or_bl_reference",
        "label": "Container / B-L reference",
        "type": "string",
        "required": False,
        "tolerance": None,
        "section": "Shipment",
        "description": "Container number or bill of lading number quoted on the invoice.",
    },
    {
        "name": "invoice_date",
        "label": "Invoice date",
        "type": "date",
        "required": True,
        "tolerance": None,
        "section": "Identification",
        "description": "Date of issue, normalised to YYYY-MM-DD.",
    },
]

CONTRACT_FIELDS: list[dict[str, Any]] = [
    {
        "name": "contract_number",
        "label": "Contract number",
        "type": "string",
        "required": True,
        "tolerance": None,
        "section": "Identification",
        "description": "The contract reference the parties will quote on every later document.",
    },
    {
        "name": "buyer",
        "label": "Buyer",
        "type": "string",
        "required": True,
        "tolerance": None,
        "section": "Parties",
        "description": "Registered name of the buying party.",
    },
    {
        "name": "seller",
        "label": "Seller",
        "type": "string",
        "required": True,
        "tolerance": None,
        "section": "Parties",
        "description": "Registered name of the selling party.",
    },
    {
        "name": "commodity",
        "label": "Commodity",
        "type": "string",
        "required": True,
        "tolerance": None,
        "section": "Goods",
        "description": "Contracted material description or trade grade.",
    },
    {
        "name": "quantity",
        "label": "Quantity",
        "type": "quantity",
        "required": True,
        "tolerance": 0.10,
        "section": "Goods",
        "description": "Contracted quantity with its unit.",
    },
    {
        "name": "quantity_tolerance",
        "label": "Quantity tolerance",
        "type": "string",
        "required": False,
        "tolerance": None,
        "section": "Goods",
        "description": "Tolerance the contract states on the quantity, for example '+/- 10%'.",
    },
    {
        "name": "price_basis",
        "label": "Price basis / LME percentage",
        "type": "string",
        "required": True,
        "tolerance": None,
        "section": "Commercials",
        "description": "Pricing formula, including the LME percentage where the price is a "
        "percentage of an exchange settlement.",
    },
    {
        "name": "incoterm",
        "label": "Incoterm",
        "type": "string",
        "required": True,
        "tolerance": None,
        "section": "Commercials",
        "description": "Delivery term such as CIF, FOB or CFR, with its named place.",
    },
    {
        "name": "port_of_loading",
        "label": "Port of loading",
        "type": "string",
        "required": False,
        "tolerance": None,
        "section": "Shipment",
        "description": "Named port or place of loading.",
    },
    {
        "name": "port_of_discharge",
        "label": "Port of discharge",
        "type": "string",
        "required": False,
        "tolerance": None,
        "section": "Shipment",
        "description": "Named port or place of discharge.",
    },
    {
        "name": "payment_terms",
        "label": "Payment terms",
        "type": "string",
        "required": True,
        "tolerance": None,
        "section": "Commercials",
        "description": "Agreed payment terms, for example 'LC at sight' or '30 days from BL'.",
    },
]

# The shipping-document schema, added with the sales module. Step 2 seeded only the invoice and
# the contract, because those were the two documents the purchase pipeline read; the sales
# workflow triggers off a bill of lading, and a document type with no schema behind it cannot be
# extracted at all.
#
# One field list serves the draft and the original bill of lading alike. They differ in what they
# prove, not in what they say - a draft B/L carries the same fields as the original it will
# become - so seeding two identical schemas would be duplication that then drifts apart.
BILL_OF_LADING_FIELDS: list[dict[str, Any]] = [
    {
        "name": "bl_number",
        "label": "B/L number",
        "type": "string",
        "required": True,
        "tolerance": None,
        "section": "Identification",
        "description": "The carrier's bill of lading number, exactly as printed.",
    },
    {
        "name": "container_numbers",
        "label": "Container number(s)",
        "type": "string",
        "required": False,
        "tolerance": None,
        "section": "Shipment",
        "description": "Every container number listed, comma separated in the order printed.",
    },
    {
        "name": "vessel",
        "label": "Vessel",
        "type": "string",
        "required": False,
        "tolerance": None,
        "section": "Shipment",
        "description": "Vessel name, with the voyage number where one is printed beside it.",
    },
    {
        "name": "port_of_loading",
        "label": "Port of loading",
        "type": "string",
        "required": True,
        "tolerance": None,
        "section": "Shipment",
        "description": "Named port or place of loading.",
    },
    {
        "name": "port_of_discharge",
        "label": "Port of discharge",
        "type": "string",
        "required": True,
        "tolerance": None,
        "section": "Shipment",
        "description": "Named port or place of discharge.",
    },
    {
        "name": "shipper",
        "label": "Shipper",
        "type": "string",
        "required": True,
        "tolerance": None,
        "section": "Parties",
        "description": "Registered name of the shipper as consigned on the document.",
    },
    {
        "name": "consignee",
        "label": "Consignee",
        "type": "string",
        "required": True,
        "tolerance": None,
        "section": "Parties",
        "description": "Registered name of the consignee, or 'to order' where it is negotiable.",
    },
    {
        "name": "contract_reference",
        "label": "Contract reference",
        "type": "string",
        "required": False,
        "tolerance": None,
        "section": "Identification",
        "description": "Sales or purchase contract number quoted on the document, if any.",
    },
    {
        "name": "batch_number",
        "label": "Batch number",
        "type": "string",
        "required": False,
        "tolerance": None,
        "section": "Identification",
        "description": "Batch or lot reference for the material shipped, if quoted.",
    },
    {
        "name": "commodity_code",
        "label": "Commodity",
        "type": "string",
        "required": False,
        "tolerance": None,
        "section": "Goods",
        "description": "Trade grade or description of the goods, exactly as described.",
    },
    {
        "name": "quantity",
        "label": "Quantity",
        "type": "quantity",
        "required": False,
        "tolerance": 0.02,
        "section": "Goods",
        "description": "Shipped weight with its unit, for example '24.500 MT'.",
    },
    {
        "name": "shipped_on_board_date",
        "label": "Shipped on board date",
        "type": "date",
        "required": False,
        "tolerance": None,
        "section": "Identification",
        "description": "Date the cargo was shipped on board, normalised to YYYY-MM-DD.",
    },
]

# The FA document schema, seeded in Step 6.
#
# Exactly seven fields, and every one of them is named in AGFZE's own material: a counterparty, a
# reference, a quantity, a rate, an amount, a currency and the document's own type. Nothing has
# been added to "round it out" - AGFZE's material states that FA's fields and document types are
# not finalised and explicitly instructs against inventing them, so this is the whole list until
# the business confirms more. When it does, the extra fields are rows added here or through the
# Step 9 admin screen; they land in `fa_legs.extra_fields` and render on the workspace with no
# code change on either side of the wire.
#
# `required` is False on every field for the same reason. A required field is an assertion about
# what an FA document must contain, and nobody has made that assertion yet.
FA_DOCUMENT_FIELDS: list[dict[str, Any]] = [
    {
        "name": "counterparty",
        "label": "Counterparty",
        "type": "string",
        "required": False,
        "tolerance": None,
        "section": "Parties",
        "description": "Registered name of the counterparty to this FA transaction.",
    },
    {
        "name": "transaction_reference",
        "label": "Transaction / contract / batch reference",
        "type": "string",
        "required": False,
        "tolerance": None,
        "section": "Identification",
        "description": "The reference the document is raised against, exactly as printed.",
    },
    {
        "name": "quantity",
        "label": "Quantity",
        "type": "quantity",
        "required": False,
        "tolerance": None,
        "section": "Goods",
        "description": "Quantity with its unit, exactly as stated.",
    },
    {
        "name": "rate",
        "label": "Rate",
        "type": "number",
        "required": False,
        "tolerance": None,
        "section": "Commercials",
        "description": "Unit price applied to the quantity.",
    },
    {
        "name": "amount",
        "label": "Amount",
        "type": "number",
        "required": False,
        "tolerance": None,
        "section": "Commercials",
        "description": "Total value of the transaction as stated on the document.",
    },
    {
        "name": "currency",
        "label": "Currency",
        "type": "string",
        "required": False,
        "tolerance": None,
        "section": "Commercials",
        "description": "ISO 4217 currency code of the stated amount.",
    },
    {
        "name": "document_type",
        "label": "Document type",
        "type": "string",
        "required": False,
        "tolerance": None,
        "section": "Identification",
        "description": "What this document is, in the counterparty's own words.",
    },
]

# Completeness checklists for the territory document packs. Stored against the invoice, which is
# the anchor document every pack is assembled around. Step 3 is the step that enforces them.
INDIA_MANDATORY_DOCUMENTS: list[str] = [
    "invoice",
    "packing_list",
    "certificate_of_origin",
    "freight_certificate",
    "form_6",
    "form_9",
    "mill_test_certificate",
    "chemical_analysis_certificate",
]

CHINA_MANDATORY_DOCUMENTS: list[str] = [
    "invoice",
    "packing_list",
    "certificate_of_origin",
    "chemical_analysis_certificate",
    "mill_test_certificate",
]


def fa_schema_rows() -> list[dict[str, Any]]:
    """The one row the FA module seeds, kept apart from the earlier steps' lists for the reason
    they are kept apart from each other: each migration has to keep writing exactly what it
    wrote, and the unique constraint on (document_type, territory) would reject a second insert.

    `mandatory_documents` is empty and stays empty. A mandatory-document list is a business rule,
    and no FA one exists to seed.
    """
    return [
        {
            "document_type": DocumentType.FA_DOCUMENT.value,
            "territory": None,
            "field_schema": {"fields": FA_DOCUMENT_FIELDS},
            "mandatory_documents": [],
        },
    ]


def sales_schema_rows() -> list[dict[str, Any]]:
    """The rows the sales module seeds. Separate from `default_schema_rows` on purpose.

    That function is what the Step 2 migration writes and has to keep writing unchanged; the
    unique constraint on (document_type, territory) would reject a second insert of the same row.
    """
    return [
        {
            "document_type": DocumentType.BL.value,
            "territory": None,
            "field_schema": {"fields": BILL_OF_LADING_FIELDS},
            "mandatory_documents": [],
        },
        {
            "document_type": DocumentType.BL_DRAFT.value,
            "territory": None,
            "field_schema": {"fields": BILL_OF_LADING_FIELDS},
            "mandatory_documents": [],
        },
        {
            "document_type": DocumentType.SHIPPING_DOCUMENT.value,
            "territory": None,
            "field_schema": {"fields": BILL_OF_LADING_FIELDS},
            "mandatory_documents": [],
        },
    ]


def default_schema_rows() -> list[dict[str, Any]]:
    """The seed rows, in insertion order. Consumed by the migration and by the tests."""
    return [
        {
            "document_type": DocumentType.INVOICE.value,
            "territory": None,
            "field_schema": {"fields": INVOICE_FIELDS},
            "mandatory_documents": [],
        },
        {
            "document_type": DocumentType.CONTRACT.value,
            "territory": None,
            "field_schema": {"fields": CONTRACT_FIELDS},
            "mandatory_documents": [],
        },
        {
            "document_type": DocumentType.INVOICE.value,
            "territory": Territory.INDIA.value,
            "field_schema": {"fields": INVOICE_FIELDS},
            "mandatory_documents": INDIA_MANDATORY_DOCUMENTS,
        },
        {
            "document_type": DocumentType.INVOICE.value,
            "territory": Territory.CHINA.value,
            "field_schema": {"fields": INVOICE_FIELDS},
            "mandatory_documents": CHINA_MANDATORY_DOCUMENTS,
        },
    ]
