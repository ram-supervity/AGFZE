"""Builders for the transaction fixtures the  suite works against.

Everything here is written directly into the database, exactly as the services would leave it,
so the tests exercise the real matching and validation code against real rows rather than
against mocks of themselves.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utcnow
from app.models.enums import (
    DocumentType,
    ExtractionStatus,
    InvoiceStatus,
    MatchMethod,
    PriceBasis,
    RequestCategory,
    RequestSource,
    RequestStatus,
    TransactionStatus,
)
from app.models.intake import Document, ExtractedField, Request
from app.models.transactions import PurchaseLeg, TradeTransaction

SUPPLIER = "Emirates Metal Trading LLC"
CONTRACT = "AGF-CT-2026-118"

# A pack that satisfies every rule this  evaluates for real: the amount is exactly rate
# multiplied by quantity, the quantity matches the contract, and the price matches the contract's rate.
CLEAN_INVOICE_VALUES: dict[str, str | None] = {
    "invoice_number": "INV-2026-0451",
    "contract_reference": CONTRACT,
    "batch_number": None,
    "supplier_name": SUPPLIER,
    "invoice_status": "provisional",
    "commodity_code": "CU",
    "quantity": "24.500 MT",
    "rate": "8125.00",
    "currency": "USD",
    "amount": "199062.50",
    "container_or_bl_reference": "MSKU7781234",
    # Relative to the day the suite runs, not a fixed date. IV-01 judges an invoice against the
    # current date, so a literal here would quietly turn into a backdating flag once enough
    # calendar time had passed and every clean-pack test would start failing for a reason that
    # had nothing to do with what it was testing.
    "invoice_date": (utcnow().date() - timedelta(days=14)).isoformat(),
}

CLEAN_CONTRACT_VALUES: dict[str, str | None] = {
    "contract_number": CONTRACT,
    "buyer": "AGFZE Metals FZE",
    "seller": SUPPLIER,
    "commodity": "Copper",
    "quantity": "24.500 MT",
    "rate": "8125.00",
    "price_basis": "Fixed at USD 8125.00 per MT",
    "incoterm": "CIF Nhava Sheva",
    "port_of_loading": "Jebel Ali",
    "port_of_discharge": "Nhava Sheva",
    "payment_terms": "LC at sight",
}


async def make_request(
    session: AsyncSession,
    *,
    code: str | None = None,
    category: str = RequestCategory.PURCHASE.value,
    stream: str = "scrap",
) -> Request:
    request = Request(
        request_code=code or f"REQ-TEST-{uuid.uuid4().hex[:8]}",
        source=RequestSource.PORTAL.value,
        category=category,
        original_category=category,
        stream=stream,
        original_stream=stream,
        status=RequestStatus.EXTRACTED.value,
    )
    session.add(request)
    await session.flush()
    return request


async def make_document(
    session: AsyncSession,
    request: Request,
    *,
    values: dict[str, str | None],
    document_type: str = DocumentType.INVOICE.value,
    filename: str = "invoice.pdf",
    territory: str | None = None,
    content_hash: str | None = None,
    transaction_id: uuid.UUID | None = None,
    confidences: dict[str, float] | None = None,
    default_confidence: float = 0.95,
) -> Document:
    document = Document(
        request_id=request.id,
        transaction_id=transaction_id,
        filename=filename,
        content_type="application/pdf",
        byte_size=4096,
        storage_ref=f"documents/source/{uuid.uuid4().hex}.pdf",
        content_hash=content_hash or uuid.uuid4().hex * 2,
        document_type=document_type,
        territory=territory,
        page_count=1,
        extraction_status=ExtractionStatus.COMPLETED.value,
        classification_confidence=0.96,
    )
    session.add(document)
    await session.flush()

    scores = confidences or {}
    for name, value in values.items():
        confidence = scores.get(name, default_confidence)
        session.add(
            ExtractedField(
                document_id=document.id,
                field_name=name,
                field_value=value,
                confidence=confidence,
                original_ai_value=value,
                original_confidence=confidence,
            )
        )
    await session.flush()
    await session.refresh(document)
    return document


async def make_transaction(
    session: AsyncSession,
    *,
    request: Request | None = None,
    batch_number: str = "I2626-1",
    supplier_name: str | None = SUPPLIER,
    contract_number: str | None = CONTRACT,
    invoice_number: str | None = "INV-2026-0451",
    invoice_status: str = InvoiceStatus.PROVISIONAL.value,
    commodity_code: str | None = "CU",
    quantity: str | None = "24.500",
    rate: str | None = "8125.00",
    amount: str | None = "199062.50",
    status: str = TransactionStatus.MATCHED.value,
    price_basis: str = PriceBasis.FIXED.value,
    lme_percentage: str | None = None,
    hedge_date: date | None = None,
) -> TradeTransaction:
    request = request or await make_request(session)
    transaction = TradeTransaction(
        transaction_code=batch_number,
        batch_number=batch_number,
        stream="scrap",
        status=status,
        commodity_code=commodity_code,
        quantity_mt=Decimal(quantity) if quantity else None,
        price_basis=price_basis,
        lme_percentage=Decimal(lme_percentage) if lme_percentage else None,
        currency="USD",
        request_id=request.id,
        match_method=MatchMethod.MANUAL.value,
        field_overrides={},
    )
    session.add(transaction)
    await session.flush()

    leg = PurchaseLeg(
        transaction_id=transaction.id,
        supplier_name=supplier_name,
        supplier_invoice_number=invoice_number,
        contract_number=contract_number,
        invoice_status=invoice_status,
        amount=Decimal(amount) if amount else None,
        rate=Decimal(rate) if rate else None,
        hedge_date=hedge_date,
    )
    session.add(leg)
    await session.flush()
    await session.refresh(transaction)
    return transaction


def invoice_values(**overrides: Any) -> dict[str, str | None]:
    values = dict(CLEAN_INVOICE_VALUES)
    values.update(overrides)
    return values


def contract_values(**overrides: Any) -> dict[str, str | None]:
    values = dict(CLEAN_CONTRACT_VALUES)
    values.update(overrides)
    return values
