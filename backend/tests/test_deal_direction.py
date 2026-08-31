"""Tests for automatic AI deal-direction detection and workspace routing across intake paths."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.roles import PlatformRole
from app.models.enums import (
    DealDirection,
    DocumentType,
    ExtractionStatus,
    RequestCategory,
    RequestSource,
    TransactionStatus,
)
from app.models.intake import Document, ExtractedField, Request
from app.models.transactions import PurchaseLeg, SalesLeg, TradeTransaction
from app.services import classification_service, sales_service

# The three routing tests below sign in over the API, so the JWKS the token is verified against
# has to be the patched one. The classification tests above touch no endpoint and are unaffected.
pytestmark = pytest.mark.usefixtures("patched_jwks")


# --- 1. AI Classification Unit Tests -----------------------------------------------------------


@pytest.mark.asyncio
async def test_classification_detects_purchase_direction() -> None:
    mock_response = classification_service.DocumentClassification(
        document_type=DocumentType.INVOICE.value,
        confidence=0.95,
        rationale="Supplier invoice issued to AGFZE as buyer.",
        territory="india",
        deal_direction=DealDirection.PURCHASE.value,
        deal_direction_confidence=0.98,
        deal_direction_rationale="AGFZE is the buyer paying the counterparty.",
        document_kinds=[],
    )
    with patch("app.services.classification_service.generate_structured", new=AsyncMock(return_value=mock_response)):
        outcome = await classification_service.classify_document(
            filename="supplier_inv_123.pdf",
            text="PROVISIONAL INVOICE \nBuyer: AGFZE \nSeller: Global Metal Supplier \nAmount: $50,000",
        )
        assert outcome.document_type == DocumentType.INVOICE.value
        assert outcome.deal_direction == DealDirection.PURCHASE.value
        assert outcome.deal_direction_confidence == 0.98
        assert outcome.needs_review is False


@pytest.mark.asyncio
async def test_classification_detects_sales_direction() -> None:
    mock_response = classification_service.DocumentClassification(
        document_type=DocumentType.CONTRACT.value,
        confidence=0.94,
        rationale="Sales contract issued by AGFZE to customer.",
        territory="china",
        deal_direction=DealDirection.SALES.value,
        deal_direction_confidence=0.96,
        deal_direction_rationale="AGFZE is the seller billing the customer.",
        document_kinds=[],
    )
    with patch("app.services.classification_service.generate_structured", new=AsyncMock(return_value=mock_response)):
        outcome = await classification_service.classify_document(
            filename="sales_contract_sc99.pdf",
            text="SALES CONFIRMATION \nSeller: AGFZE \nBuyer: Oriental Foundry Ltd \nQuantity: 100 MT",
        )
        assert outcome.document_type == DocumentType.CONTRACT.value
        assert outcome.deal_direction == DealDirection.SALES.value
        assert outcome.deal_direction_confidence == 0.96
        assert outcome.needs_review is False


@pytest.mark.asyncio
async def test_classification_shipping_paperwork_direction() -> None:
    mock_response = classification_service.DocumentClassification(
        document_type=DocumentType.BL.value,
        confidence=0.91,
        rationale="Bill of lading for export cargo sold by AGFZE.",
        territory="china",
        deal_direction=DealDirection.SALES.value,
        deal_direction_confidence=0.90,
        deal_direction_rationale="Shipper is AGFZE exporting goods to customer consignee.",
        document_kinds=["bill_of_lading"],
    )
    with patch("app.services.classification_service.generate_structured", new=AsyncMock(return_value=mock_response)):
        outcome = await classification_service.classify_document(
            filename="ocean_bl_654321.pdf",
            text="BILL OF LADING \nShipper: AGFZE \nConsignee: Ningbo Metals \nPort of Discharge: Ningbo",
        )
        assert outcome.document_type == DocumentType.BL.value
        assert outcome.deal_direction == DealDirection.SALES.value
        assert "bill_of_lading" in outcome.kinds


@pytest.mark.asyncio
async def test_classification_low_confidence_flags_needs_review() -> None:
    mock_response = classification_service.DocumentClassification(
        document_type=DocumentType.INVOICE.value,
        confidence=0.90,
        rationale="Invoice found but direction ambiguous.",
        territory=None,
        deal_direction=DealDirection.PURCHASE.value,
        deal_direction_confidence=0.60,  # Below threshold (0.75)
        deal_direction_rationale="Unclear who is buyer.",
        document_kinds=[],
    )
    with patch("app.services.classification_service.generate_structured", new=AsyncMock(return_value=mock_response)):
        outcome = await classification_service.classify_document(
            filename="ambiguous.pdf",
            text="INVOICE \nParty A and Party B",
        )
        assert outcome.needs_review is True
        assert outcome.deal_direction_confidence == 0.60


# --- 2. Pipeline Reconciliation & Standalone Sales Transaction Tests -------------------------


@pytest.mark.asyncio
async def test_sales_document_creates_standalone_sales_transaction_when_no_match(
    client: AsyncClient,
    db_session: AsyncSession,
    signed_in,
) -> None:
    _user, sales_auth_headers = await signed_in(
        str(uuid4()), "sales.user@agfze.local", "Sales User", [PlatformRole.SALES_USER.value]
    )

    # 1. Create a portal request with a sales document
    req = Request(
        request_code="REQ-TEST-SALES-001",
        source=RequestSource.PORTAL.value,
        category=RequestCategory.SALES.value,
        deal_direction=DealDirection.SALES.value,
        stream="scrap",
    )
    db_session.add(req)
    await db_session.flush()

    doc = Document(
        request_id=req.id,
        filename="sales_contract_sc555.pdf",
        content_type="application/pdf",
        byte_size=1024,
        document_type=DocumentType.CONTRACT.value,
        deal_direction=DealDirection.SALES.value,
        deal_direction_confidence=0.95,
        deal_direction_rationale="AGFZE selling scrap to customer.",
        content_hash="test_hash_sales_001",
        storage_ref="test/sales_contract.pdf",
        extraction_status=ExtractionStatus.COMPLETED.value,
    )
    db_session.add(doc)
    await db_session.flush()

    db_session.add_all([
        ExtractedField(
            document_id=doc.id,
            field_name="customer_name",
            field_value="Atlas Foundry Ltd",
            confidence=0.95,
        ),
        ExtractedField(
            document_id=doc.id,
            field_name="contracted_quantity",
            field_value="55.5",
            confidence=0.92,
        ),
        ExtractedField(
            document_id=doc.id,
            field_name="sales_contract_no",
            field_value="SC-2026-555",
            confidence=0.98,
        ),
        ExtractedField(
            document_id=doc.id,
            field_name="commodity_code",
            field_value="TENSE",
            confidence=0.95,
        ),
    ])
    await db_session.commit()

    # 2. Confirm extraction as sales user
    response = await client.post(f"/api/v1/documents/{doc.id}/confirm", headers=sales_auth_headers)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["matching"]["outcome"] == "new_transaction"
    created_txn_id = data["matching"]["transaction_id"]
    assert created_txn_id is not None

    # 3. Verify transaction carries SalesLeg and no PurchaseLeg
    txn = await db_session.scalar(
        select(TradeTransaction)
        .where(TradeTransaction.id == created_txn_id)
        .options(selectinload(TradeTransaction.sales_leg), selectinload(TradeTransaction.purchase_leg))
    )
    assert txn is not None
    assert txn.purchase_leg is None
    assert txn.sales_leg is not None
    assert txn.sales_leg.customer_name == "Atlas Foundry Ltd"
    assert txn.sales_leg.sales_contract_no == "SC-2026-555"

    # 4. Verify transaction list and detail show sales deal
    txn_res = await client.get(f"/api/v1/transactions/{created_txn_id}", headers=sales_auth_headers)
    assert txn_res.status_code == 200
    txn_data = txn_res.json()["data"]
    assert txn_data["has_sales_leg"] is True
    assert txn_data["has_purchase_leg"] is False
    assert txn_data["deal_direction"] == "sales"

    # 5. Verify request API includes transaction id and leg type
    req_res = await client.get(f"/api/v1/requests/{req.id}", headers=sales_auth_headers)
    assert req_res.status_code == 200
    req_data = req_res.json()["data"]
    assert req_data["deal_direction"] == "sales"
    assert req_data["transaction_id"] == str(created_txn_id)
    assert req_data["transaction_leg_type"] == "sales"


@pytest.mark.asyncio
async def test_sales_document_attaches_to_matching_purchase_batch(
    client: AsyncClient,
    db_session: AsyncSession,
    signed_in,
) -> None:
    _user, sales_auth_headers = await signed_in(
        str(uuid4()), "sales.user2@agfze.local", "Sales User 2", [PlatformRole.SALES_USER.value]
    )

    # 1. Create open purchase transaction
    purchase_txn = TradeTransaction(
        transaction_code="B-2026-9001",
        batch_number="B-2026-9001",
        batch_number_source="allocated",
        stream="scrap",
        status=TransactionStatus.MATCHED.value,
        commodity_code="TENSE",
        quantity_mt=Decimal("50.0"),
    )
    db_session.add(purchase_txn)
    await db_session.flush()

    p_leg = PurchaseLeg(
        transaction_id=purchase_txn.id,
        supplier_name="Global Scrap Exporters",
        contract_number="PUR-9001",
    )
    db_session.add(p_leg)
    await db_session.flush()

    # 2. Ingest sales document explicitly referencing this batch
    req = Request(
        request_code="REQ-TEST-SALES-ATTACH",
        source=RequestSource.PORTAL.value,
        category=RequestCategory.SALES.value,
        deal_direction=DealDirection.SALES.value,
        stream="scrap",
    )
    db_session.add(req)
    await db_session.flush()

    doc = Document(
        request_id=req.id,
        filename="bl_for_batch_9001.pdf",
        content_type="application/pdf",
        byte_size=1024,
        document_type=DocumentType.BL.value,
        deal_direction=DealDirection.SALES.value,
        deal_direction_confidence=0.98,
        content_hash="test_hash_sales_attach",
        storage_ref="test/bl_9001.pdf",
        extraction_status=ExtractionStatus.COMPLETED.value,
    )
    db_session.add(doc)
    await db_session.flush()

    db_session.add_all([
        ExtractedField(
            document_id=doc.id,
            field_name="batch_number",
            field_value="B-2026-9001",
            confidence=0.99,
        ),
        ExtractedField(
            document_id=doc.id,
            field_name="customer_name",
            field_value="Pacific Alloys Ltd",
            confidence=0.95,
        ),
        ExtractedField(
            document_id=doc.id,
            field_name="contracted_quantity",
            field_value="50.0",
            confidence=0.95,
        ),
        ExtractedField(
            document_id=doc.id,
            field_name="sales_contract_no",
            field_value="SC-PACIFIC-9001",
            confidence=0.95,
        ),
    ])
    await db_session.commit()

    # 3. Confirm extraction
    response = await client.post(f"/api/v1/documents/{doc.id}/confirm", headers=sales_auth_headers)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["matching"]["outcome"] == "auto_linked"
    assert data["matching"]["batch_number"] == "B-2026-9001"

    # 4. Verify transaction now carries both PurchaseLeg and SalesLeg
    txn = await db_session.scalar(
        select(TradeTransaction)
        .where(TradeTransaction.id == purchase_txn.id)
        .options(selectinload(TradeTransaction.sales_leg), selectinload(TradeTransaction.purchase_leg))
    )
    assert txn is not None
    assert txn.purchase_leg is not None
    assert txn.sales_leg is not None
    assert txn.sales_leg.customer_name == "Pacific Alloys Ltd"


@pytest.mark.asyncio
async def test_direction_override_reroutes_request_and_documents(
    client: AsyncClient,
    db_session: AsyncSession,
    signed_in,
) -> None:
    _user, admin_auth_headers = await signed_in(
        str(uuid4()), "admin@agfze.local", "Admin User", [PlatformRole.ADMIN.value]
    )

    req = Request(
        request_code="REQ-TEST-OVERRIDE-01",
        source=RequestSource.EMAIL.value,
        category=RequestCategory.PURCHASE.value,
        deal_direction=DealDirection.PURCHASE.value,
        stream="scrap",
        category_confidence=0.80,
    )
    db_session.add(req)
    await db_session.flush()

    doc = Document(
        request_id=req.id,
        filename="misclassified_deal.pdf",
        content_type="application/pdf",
        byte_size=1024,
        document_type=DocumentType.CONTRACT.value,
        deal_direction=DealDirection.PURCHASE.value,
        content_hash="test_hash_override_01",
        storage_ref="test/override.pdf",
        extraction_status=ExtractionStatus.COMPLETED.value,
    )
    db_session.add(doc)
    await db_session.commit()

    # Override category to sales with deal_direction sales
    res = await client.patch(
        f"/api/v1/requests/{req.id}/category",
        headers=admin_auth_headers,
        json={
            "category": "sales",
            "deal_direction": "sales",
            "reason": "This is an export sales contract confirmed with buyer.",
        },
    )
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert data["category"] == "sales"
    assert data["deal_direction"] == "sales"
    assert data["category_overridden"] is True

    # Re-fetch document from DB to check deal_direction was updated
    refreshed_doc = await db_session.get(Document, doc.id)
    assert refreshed_doc is not None
    assert refreshed_doc.deal_direction == "sales"
