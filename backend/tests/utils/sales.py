"""Builders for the sales fixtures the  suite works against.

Everything goes in through the real services or straight into the database exactly as they would
leave it, so the tests exercise the actual attachment, the actual evaluators and the actual
generation rather than mocks that resemble them.
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import (
    DocumentType,
    FixationStatus,
    PaymentCondition,
    Territory,
)
from app.models.transactions import SalesLeg, TradeTransaction
from app.services.rules import engine as rule_engine
from tests.utils.transactions import (
    CONTRACT,
    SUPPLIER,
    contract_values,
    invoice_values,
    make_document,
    make_request,
    make_transaction,
)

# The rate every fixture prices at, so the invoice's amount, the transaction's quantity and the
# contract's terms agree exactly and BR-05 and BR-06 pass on their own merits. A fixture whose
# purchase side is failing would hide SL-01's own case behind it, because two rules that map to
# the same exception category share one case per transaction by 's design.
FIXTURE_RATE = Decimal("8125.00")

CUSTOMER = "Hindalco Industries Limited"
SALES_CONTRACT = "AGF-SC-2026-441"

# What a bill of lading reads back as. Deliberately quotes the batch, so the batch-first branch of
# the matching path is the one exercised unless a test removes it.
BL_VALUES: dict[str, str | None] = {
    "bl_number": "MAEU-2026-77812",
    "container_numbers": "MSKU7781234, MSKU7781235",
    "vessel": "MV Northern Trader / V.214W",
    "port_of_loading": "Jebel Ali",
    "port_of_discharge": "Nhava Sheva",
    "shipper": "AGFZE Metals FZE",
    "consignee": CUSTOMER,
    "contract_reference": CONTRACT,
    "batch_number": "I2626-1",
    "commodity_code": "CU",
    "quantity": "24.500 MT",
    "shipped_on_board_date": "2026-08-20",
}


def bl_values(**overrides: Any) -> dict[str, str | None]:
    values = dict(BL_VALUES)
    values.update(overrides)
    return values


async def make_bl_document(
    session: AsyncSession,
    *,
    values: dict[str, str | None] | None = None,
    document_type: str = DocumentType.BL.value,
    filename: str = "original-bill-of-lading.pdf",
    transaction_id: uuid.UUID | None = None,
    territory: str | None = Territory.INDIA.value,
    request=None,
):
    """A confirmed bill of lading, draft or original, ready to trigger the sales workflow."""
    request = request or await make_request(session, category="sales")
    return await make_document(
        session,
        request,
        values=values if values is not None else bl_values(),
        document_type=document_type,
        filename=filename,
        territory=territory,
        transaction_id=transaction_id,
    )


async def attach_sales_leg_row(
    session: AsyncSession,
    transaction: TradeTransaction,
    *,
    customer_name: str = CUSTOMER,
    territory: str = Territory.INDIA.value,
    sales_contract_no: str = SALES_CONTRACT,
    contracted_quantity: str | None = "100.000",
    payment_condition: str = PaymentCondition.CAD.value,
    bl_reference: str | None = "MAEU-2026-77812",
    sales_invoice_number: str | None = "SI-2026-0091",
    port_of_discharge: str | None = "Nhava Sheva",
    fixation_status: str = FixationStatus.UNFIXED.value,
    fixation_rate: str | None = None,
    extracted_commodity_value: str | None = None,
    validate: bool = True,
) -> SalesLeg:
    """A sales leg written directly, for the tests that are about what happens after attachment."""
    leg = SalesLeg(
        transaction_id=transaction.id,
        customer_name=customer_name,
        territory=territory,
        sales_contract_no=sales_contract_no,
        contracted_quantity_mt=(
            Decimal(contracted_quantity) if contracted_quantity is not None else None
        ),
        sales_invoice_number=sales_invoice_number,
        bl_reference=bl_reference,
        payment_condition=payment_condition,
        customer_fixation_status=fixation_status,
        fixation_rate=Decimal(fixation_rate) if fixation_rate else None,
        port_of_discharge=port_of_discharge,
        extracted_commodity_value=extracted_commodity_value,
    )
    session.add(leg)
    await session.flush()
    transaction.sales_leg = leg
    if validate:
        await rule_engine.run_validation(session, transaction)
    await session.commit()
    await session.refresh(transaction)
    return leg


async def sales_transaction(
    session: AsyncSession,
    *,
    batch_number: str = "I2626-1",
    quantity: str | None = "24.500",
    sales_contract_no: str = SALES_CONTRACT,
    contracted_quantity: str | None = "100.000",
    with_purchase_pack: bool = True,
    with_final_bl: bool = True,
    with_draft_bl: bool = False,
    fixation_status: str = FixationStatus.UNFIXED.value,
    fixation_rate: str | None = None,
    extracted_commodity_value: str | None = None,
    territory: str = Territory.INDIA.value,
    validate: bool = True,
) -> TradeTransaction:
    """A transaction carrying both legs, with a purchase pack that satisfies every purchase rule.

    The buy side is made clean on purpose. Two rules that route to the same exception category
    share one case per transaction - 's idempotency, and correct - so a fixture whose BR-05
    was failing would hide SL-01's own case behind it and prove nothing.
    """
    request = await make_request(session)
    amount = str(Decimal(quantity) * FIXTURE_RATE) if quantity is not None else None
    transaction = await make_transaction(
        session,
        request=request,
        batch_number=batch_number,
        quantity=quantity,
        rate=str(FIXTURE_RATE),
        amount=amount,
    )
    if with_purchase_pack and quantity is not None:
        await make_document(
            session,
            request,
            values=invoice_values(quantity=f"{quantity} MT", rate=str(FIXTURE_RATE), amount=amount),
            document_type=DocumentType.INVOICE.value,
            filename="supplier-invoice.pdf",
            transaction_id=transaction.id,
        )
        await make_document(
            session,
            request,
            values=contract_values(quantity=f"{quantity} MT", rate=str(FIXTURE_RATE)),
            document_type=DocumentType.CONTRACT.value,
            filename="purchase-contract.pdf",
            transaction_id=transaction.id,
        )
    if with_draft_bl:
        await make_bl_document(
            session,
            request=request,
            values=bl_values(batch_number=batch_number),
            document_type=DocumentType.BL_DRAFT.value,
            filename="draft-bill-of-lading.pdf",
            transaction_id=transaction.id,
            # Deliberately left off the document. The destination lives on the sales leg; putting
            # it on the B/L would pull in the territory's mandatory-document checklist and fail
            # BR-04 on a fixture that is not about BR-04.
            territory=None,
        )
    if with_final_bl:
        await make_bl_document(
            session,
            request=request,
            values=bl_values(batch_number=batch_number),
            document_type=DocumentType.BL.value,
            filename="original-bill-of-lading.pdf",
            transaction_id=transaction.id,
            territory=None,
        )
    await attach_sales_leg_row(
        session,
        transaction,
        sales_contract_no=sales_contract_no,
        contracted_quantity=contracted_quantity,
        fixation_status=fixation_status,
        fixation_rate=fixation_rate,
        extracted_commodity_value=extracted_commodity_value,
        territory=territory,
        validate=validate,
    )
    return transaction


def draft_plan_response(
    *,
    keep: list[str] | None = None,
    revise: dict[str, str] | None = None,
    remove: list[str] | None = None,
    notes: list[str] | None = None,
) -> str:
    """A synthetic, schema-valid clause plan. Written by the test, never by a live model."""
    clauses: list[dict[str, Any]] = []
    for key in keep or ():
        clauses.append({"key": key, "action": "keep"})
    for key, text in (revise or {}).items():
        clauses.append({"key": key, "action": "revise", "text": text})
    for key in remove or ():
        clauses.append({"key": key, "action": "remove"})
    return json.dumps({"clauses": clauses, "notes": notes or []})


# A plan that is valid for the sales-contract template: one pricing clause, one payment clause.
VALID_CONTRACT_PLAN = draft_plan_response(
    keep=[
        "parties",
        "goods",
        "quantity_tolerance",
        "pricing_lme",
        "price_fixation",
        "payment_cad",
        "delivery",
        "documents",
        "inspection",
        "title_risk",
        "force_majeure",
        "governing_law",
    ],
    remove=["pricing_fixed", "payment_tt"],
    notes=["Check the pricing period against the customer's confirmation."],
)

VALID_INVOICE_PLAN = draft_plan_response(
    keep=[
        "header",
        "goods_description",
        "pricing_provisional",
        "lme_reference",
        "payment_cad",
        "bank_details",
        "destination_declaration",
        "declaration",
    ],
    remove=["pricing_final", "payment_tt"],
)

SUPPLIER_NAME = SUPPLIER
