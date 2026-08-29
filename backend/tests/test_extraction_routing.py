"""The file-type router, the schema selection and the multi-page consolidation.

The routing decision is what is asserted here - which reader a set of real bytes is sent to -
not the model's output, which cannot be deterministically asserted and is not the router's job.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.enums import DocumentType, Territory
from app.services import extraction_service
from app.services.extraction_service import ExtractedValue, SchemaField, consolidate
from app.services.file_intake import DOCX, IMAGE, PDF, SPREADSHEET, detect_type
from app.services.schema_defaults import (
    CHINA_MANDATORY_DOCUMENTS,
    INDIA_MANDATORY_DOCUMENTS,
    INVOICE_FIELDS,
)
from app.services.text_extraction import ExtractionRoute, normalise_text, read_document
from tests.utils.fixtures import (
    PNG_1PX,
    csv_bytes,
    docx_bytes,
    scanned_pdf,
    text_layer_pdf,
    xlsx_bytes,
)


def test_a_digital_pdf_is_read_through_the_text_layer_not_a_vision_call() -> None:
    data = text_layer_pdf()
    content_type, family = detect_type(data, "invoice.pdf")
    assert (content_type, family) == ("application/pdf", PDF)

    content = read_document(data, family=family, content_type=content_type)

    assert content.route is ExtractionRoute.TEXT_LAYER
    assert "INV-2026-0451" in content.full_text
    # A text-layer page is not rasterised for the model; nothing is sent as an image.
    assert all(page.image is None for page in content.pages)
    assert content.pages[0].blocks


def test_a_scanned_pdf_is_rasterised_and_sent_down_the_multimodal_path() -> None:
    data = scanned_pdf()
    content_type, family = detect_type(data, "scan.pdf")
    assert family == PDF

    content = read_document(data, family=family, content_type=content_type)

    assert content.route is ExtractionRoute.MULTIMODAL
    assert content.pages[0].image is not None
    assert content.pages[0].image.startswith(b"\x89PNG")


def test_a_photograph_is_one_multimodal_page() -> None:
    content_type, family = detect_type(PNG_1PX, "whatsapp-photo.png")
    assert (content_type, family) == ("image/png", IMAGE)

    content = read_document(PNG_1PX, family=family, content_type=content_type)

    assert content.route is ExtractionRoute.MULTIMODAL
    assert content.page_count == 1
    assert content.pages[0].image == PNG_1PX


def test_a_word_document_is_parsed_for_paragraphs_and_tables() -> None:
    data = docx_bytes(["Sale Contract AGF-CT-2026-118", "Incoterm: CIF Nhava Sheva"])
    content_type, family = detect_type(data, "contract.docx")
    assert family == DOCX

    content = read_document(data, family=family, content_type=content_type)

    assert content.route is ExtractionRoute.OFFICE
    assert "AGF-CT-2026-118" in content.full_text
    assert content.pages[0].image is None


@pytest.mark.parametrize(
    ("payload", "filename"),
    [(xlsx_bytes(), "tracker.xlsx"), (csv_bytes(), "tracker.csv")],
)
def test_a_tracker_export_is_read_past_its_title_banner(payload: bytes, filename: str) -> None:
    content_type, family = detect_type(payload, filename)
    assert family == SPREADSHEET

    content = read_document(payload, family=family, content_type=content_type)

    assert content.route is ExtractionRoute.TABULAR
    # The header row is found below the banner rows rather than assumed to be row one.
    assert "Batch | Container | Commodity | Quantity" in content.full_text
    assert "MSKU7781234" in content.full_text


def _fullwidth(text: str) -> str:
    """Re-render ASCII in the full-width forms a CJK document actually prints.

    Built from code points rather than pasted as literals so the intent stays readable and the
    source carries no ambiguous glyphs of its own.
    """
    mapping = {" ": "\u3000", ".": "\uff0e", "-": "\uff0d"}
    return "".join(
        mapping.get(
            character, chr(ord(character) + 0xFEE0) if "!" <= character <= "~" else character
        )
        for character in text
    )


def test_full_width_source_text_is_normalised_to_a_comparable_form() -> None:
    assert normalise_text(_fullwidth("AGF-CT-2026-118")) == "AGF-CT-2026-118"
    assert normalise_text(_fullwidth("24.500 MT")) == "24.500 MT"


async def test_the_seeded_invoice_and_contract_schemas_round_trip(
    db_session: AsyncSession,
) -> None:
    invoice = await extraction_service.select_schema(
        db_session, document_type=DocumentType.INVOICE.value, territory=None
    )
    contract = await extraction_service.select_schema(
        db_session, document_type=DocumentType.CONTRACT.value, territory=None
    )

    assert [field.name for field in invoice.fields] == [field["name"] for field in INVOICE_FIELDS]
    assert invoice.field("quantity").type == "quantity"
    assert invoice.field("invoice_date").type == "date"
    assert {field.name for field in contract.fields} >= {
        "contract_number",
        "buyer",
        "seller",
        "commodity",
        "quantity",
        "price_basis",
        "incoterm",
        "payment_terms",
    }
    # The tolerance the contract states on its quantity survives the round trip for Step 3.
    assert contract.field("quantity").tolerance == pytest.approx(0.10)

    # The response schema handed to the model is built from the row, never written in code.
    response_schema = extraction_service.response_schema_for(invoice)
    names = response_schema["properties"]["fields"]["items"]["properties"]["name"]["enum"]
    assert names == [field.name for field in invoice.fields]


async def test_the_territory_row_wins_over_the_territory_agnostic_one(
    db_session: AsyncSession,
) -> None:
    india = await extraction_service.select_schema(
        db_session, document_type=DocumentType.INVOICE.value, territory=Territory.INDIA.value
    )
    china = await extraction_service.select_schema(
        db_session, document_type=DocumentType.INVOICE.value, territory=Territory.CHINA.value
    )
    japan = await extraction_service.select_schema(
        db_session, document_type=DocumentType.INVOICE.value, territory=Territory.JAPAN.value
    )

    assert india.territory == Territory.INDIA.value
    assert list(india.mandatory_documents) == INDIA_MANDATORY_DOCUMENTS
    assert list(china.mandatory_documents) == CHINA_MANDATORY_DOCUMENTS
    # Japan has no row of its own, so it falls back to the territory-agnostic default.
    assert japan.territory is None


async def test_an_unconfigured_document_type_is_refused_not_improvised(
    db_session: AsyncSession,
) -> None:
    """A type with no seeded schema is refused rather than extracted against a guessed field list.

    The bill of lading used to be the example here; the sales module seeded it, because the sales
    workflow triggers off that document and a type with no schema cannot be read at all. The
    tracker is now the unconfigured one, and the behaviour under test is unchanged.
    """
    with pytest.raises(extraction_service.SchemaNotConfiguredError):
        await extraction_service.select_schema(
            db_session, document_type=DocumentType.TRACKER.value, territory=None
        )


async def test_the_bill_of_lading_schema_is_seeded_for_the_sales_workflow(
    db_session: AsyncSession,
) -> None:
    schema = await extraction_service.select_schema(
        db_session, document_type=DocumentType.BL.value, territory=None
    )
    names = {item.name for item in schema.fields}

    assert {
        "bl_number",
        "container_numbers",
        "vessel",
        "port_of_loading",
        "port_of_discharge",
        "shipper",
        "consignee",
    } <= names

    # A draft bill of lading reads exactly the same fields as the original it will become.
    draft = await extraction_service.select_schema(
        db_session, document_type=DocumentType.BL_DRAFT.value, territory=None
    )
    assert {item.name for item in draft.fields} == names


def _schema(*names: str) -> extraction_service.ResolvedSchema:
    return extraction_service.ResolvedSchema(
        document_type="invoice",
        territory=None,
        fields=tuple(
            SchemaField(
                name=name,
                label=name,
                type="string",
                required=False,
                tolerance=None,
                section="Test",
                description="",
            )
            for name in names
        ),
        mandatory_documents=(),
    )


def test_the_highest_confidence_reading_of_a_repeated_value_wins() -> None:
    schema = _schema("invoice_number")
    consolidated = consolidate(
        schema,
        [
            ExtractedValue(name="invoice_number", value="INV-2026-045l", confidence=0.55, page=1),
            ExtractedValue(name="invoice_number", value="INV-2026-0451", confidence=0.97, page=2),
        ],
    )

    assert consolidated[0].value == "INV-2026-0451"
    assert consolidated[0].page == 2
    assert consolidated[0].has_conflict is False


def test_two_confident_readings_that_disagree_are_flagged_not_silently_picked() -> None:
    schema = _schema("quantity")
    above = settings.CONFIDENCE_THRESHOLD_DEFAULT + 0.1
    consolidated = consolidate(
        schema,
        [
            ExtractedValue(name="quantity", value="24.500 MT", confidence=above, page=1),
            ExtractedValue(name="quantity", value="25.100 MT", confidence=above - 0.01, page=3),
        ],
    )

    assert consolidated[0].has_conflict is True
    assert set(consolidated[0].conflicting_values) == {"24.500 MT", "25.100 MT"}
    # Neither reading is discarded and neither is quietly promoted: the surviving score is the
    # weaker of the two, and the conflict flag is what carries the value to a person.
    assert consolidated[0].confidence == pytest.approx(above - 0.01)
    assert consolidated[0].value == "24.500 MT"


def test_a_field_the_source_never_states_comes_back_empty() -> None:
    schema = _schema("batch_number")
    consolidated = consolidate(
        schema, [ExtractedValue(name="batch_number", value=None, confidence=0.1, page=1)]
    )

    assert consolidated[0].value is None
    assert consolidated[0].confidence == pytest.approx(0.1)
