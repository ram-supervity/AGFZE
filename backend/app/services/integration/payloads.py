"""What gets sent, or handed to a person, for one approved transaction.

Every figure here is read off the transaction record. Nothing is derived, rounded, defaulted or
inferred on the way out, because a downstream system is the last place a quiet transformation
should first appear.

One thing is worth being explicit about, since it is the difference between this module being
honest and being a fabrication. The keys below are **this platform's own field names**, not SAP's
and not the DMS's. No confirmed object, BAPI, OData entity or metadata schema exists for either
system anywhere in this platform's material, so inventing plausible-looking names -
`ZTRADE_HEADER`, `MATNR`, `docType` - would produce a payload that looks authoritative and is
fiction. What a person gets instead is the complete, correctly-structured set of values the
posting needs, under names they can read, ready to be mapped the day the real contract is
confirmed. Where a deployment has configured a real endpoint, the same payload is what it posts;
mapping it onto that system's schema is a configuration exercise, not a guess made here.

`sap_posting_reference` is the one section that names SAP's own concepts rather than this
platform's, and it does so because discovery named them directly and unambiguously: the Assignment
field carries the invoice number, the Header Text carries the batch number, and postings are booked
under Business Area 1070. Those three are a stated mapping rather than a guess, so they are filled
in. What discovery named but did not map - Reference Key 1 and 2, and the House Bank - is
deliberately absent rather than guessed at, and is listed in `docs/KNOWN-GAPS.md` as needing
AGFZE's confirmation. See `_posting_reference` for the whole of that reasoning.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.enums import (
    DocumentPackType,
    FixationStatus,
    IntegrationJobStatus,
    IntegrationTargetSystem,
    InvoiceStatus,
)
from app.models.integration import DocumentPack, IntegrationJob
from app.models.transactions import TradeTransaction
from app.services.rules.values import format_decimal


def _clean(values: dict[str, Any]) -> dict[str, Any]:
    """Drop the keys the transaction genuinely has no value for.

    An absent field is left out rather than sent as an empty string: "we do not have a hedge
    date" and "the hedge date is blank" are different statements, and only one of them is true.
    """
    return {key: value for key, value in values.items() if value not in (None, "")}


def tracker_fields(transaction: TradeTransaction) -> dict[str, Any]:
    """The figures a tracker row carries, keyed by this platform's field names.

    Which of these actually reaches the workbook, and under which column heading, is decided
    entirely by the configured column mapping. Producing a value here for a field nobody has
    mapped costs nothing and writes nothing.
    """
    purchase = transaction.purchase_leg
    sales = transaction.sales_leg
    fa = getattr(transaction, "fa_leg", None)
    counterparty = (
        (purchase.supplier_name if purchase else None)
        or (sales.customer_name if sales else None)
        or (fa.counterparty_name if fa else None)
    )
    contract = (
        (purchase.contract_number if purchase else None)
        or (sales.sales_contract_no if sales else None)
        or (fa.fa_contract_reference if fa else None)
    )
    return _clean(
        {
            "batch_number": transaction.batch_number,
            "transaction_code": transaction.transaction_code,
            "stream": transaction.stream,
            "status": transaction.status,
            "counterparty": counterparty,
            "contract_number": contract,
            "commodity_code": transaction.commodity_code,
            "commodity_name": (
                transaction.commodity.display_name if transaction.commodity else None
            ),
            "quantity_mt": format_decimal(transaction.quantity_mt),
            "currency": transaction.currency,
            "price_basis": transaction.price_basis,
            "lme_percentage": format_decimal(transaction.lme_percentage),
            "rate": format_decimal(purchase.rate) if purchase else None,
            "amount": format_decimal(purchase.amount) if purchase else None,
            "invoice_status": purchase.invoice_status if purchase else None,
            "supplier_invoice_number": (purchase.supplier_invoice_number if purchase else None),
            "port_of_loading": purchase.port_of_loading if purchase else None,
            "port_of_discharge": sales.port_of_discharge if sales else None,
            "territory": sales.territory if sales else None,
            "hedge_date": (
                purchase.hedge_date.isoformat()
                if purchase is not None and purchase.hedge_date is not None
                else None
            ),
            "approved_at": (
                transaction.submitted_at.isoformat()
                if transaction.submitted_at is not None
                else None
            ),
        }
    )


async def dms_document_reference(
    session: AsyncSession, transaction: TradeTransaction
) -> str | None:
    """The DMS reference for this transaction, if the filing has already happened.

    Opportunistic and explicitly non-blocking. Discovery asked for the DMS document number to
    travel with the SAP posting for traceability, and this reads it where it exists - but the three
    integration jobs are dispatched independently by design, no target system waiting on another,
    and that is a load-bearing decision rather than an accident of ordering. So this never waits,
    never retries and never holds the SAP job back: if the DMS upload has not resolved by the time
    the SAP payload is built, the field is simply absent.

    The consequence is worth stating plainly rather than burying: a SAP posting made before its DMS
    filing completes will not carry the DMS reference, and nothing goes back to add it. Whether
    AGFZE's accounting process actually requires that link to be present on every posting is an
    open question in `docs/KNOWN-GAPS.md` - if it does, the two jobs have to be re-sequenced, which
    is a larger change than this field and should be decided deliberately.

    `completed_manually` counts as resolved, because a person who filed the pack by hand and
    recorded the reference has produced exactly the same fact as an automated upload would have.
    """
    job = await session.scalar(
        select(IntegrationJob).where(
            IntegrationJob.transaction_id == transaction.id,
            IntegrationJob.target_system == IntegrationTargetSystem.DMS.value,
        )
    )
    if job is None:
        return None
    resolved = job.status == IntegrationJobStatus.SUCCEEDED.value or job.completed_manually
    return job.external_reference if resolved else None


# Which SAP posting a transaction maps to, where the transaction's own data says so unambiguously.
#
# Discovery named four T-codes: MIRO for invoice verification, a goods-receipt posting, and F-53 /
# F-58 for payment clearing. Only the first is derivable from anything this platform actually
# holds - an invoice with a final price is an invoice-verification posting - and that mapping is
# named here rather than as a T-code, because a T-code is a screen somebody drives and this is a
# statement about what kind of document the payload describes.
#
# The other three are deliberately not derived:
#
# * a goods receipt is posted against physical receipt of the cargo, which this platform tracks as
#   shipment milestones rather than as a receipt event, and reading "the container arrived" as "the
#   goods were received into stock" is an accounting judgement, not a data transformation;
# * F-53 and F-58 clear a *payment*, and payment confirmation lives in SAP rather than here - the
#   platform does not know that a payment happened, which is the same reason the `Closed`
#   transaction state has no code path setting it.
#
# Guessing at any of the three would put a wrong posting type on a real accounting document, so
# where the pattern cannot be sourced the field is absent and a person decides.
_INVOICE_VERIFICATION = "invoice_verification"


def _posting_pattern(transaction: TradeTransaction) -> str | None:
    purchase = transaction.purchase_leg
    if purchase is None or not purchase.supplier_invoice_number:
        return None
    if purchase.invoice_status == InvoiceStatus.FINAL.value:
        return _INVOICE_VERIFICATION
    # A provisional invoice is priced again before it is final, so calling it a verification
    # posting would name a document that is going to be superseded.
    return None


def _posting_reference(
    transaction: TradeTransaction, *, dms_document_number: str | None
) -> dict[str, Any]:
    """The SAP-side fields discovery named a mapping for, and only those.

    Present because discovery stated the mapping outright: Assignment is the invoice number,
    Header Text is the batch number, and Business Area is 1070. Those are not inferences.

    Absent, and deliberately so: **Reference Key 1**, **Reference Key 2** and **House Bank**. All
    three were named as fields the posting carries, and none was mapped to anything - no source
    document anywhere says what value belongs in them. A plausible-looking guess in an accounting
    document is worse than a gap a person fills, because the gap is visible and the guess is not.
    They are listed in `docs/KNOWN-GAPS.md` for AGFZE to confirm.
    """
    purchase = transaction.purchase_leg
    return _clean(
        {
            "business_area": settings.SAP_BUSINESS_AREA.strip() or None,
            # SAP's Assignment field. The invoice number, per discovery.
            "assignment": purchase.supplier_invoice_number if purchase else None,
            # SAP's Header Text. The batch number, per discovery - which is what makes a posting
            # traceable back to this platform at all.
            "header_text": transaction.batch_number,
            "posting_pattern": _posting_pattern(transaction),
            # Only ever present when the DMS filing has already resolved. See
            # `dms_document_reference` for why this is opportunistic rather than awaited.
            "dms_document_number": dms_document_number,
        }
    )


def sap_payload(
    transaction: TradeTransaction, *, dms_document_number: str | None = None
) -> dict[str, Any]:
    """The trade-contract and deal-price record a person keys into SAP, or a call posts.

    Structured in the two parts the posting is actually made in - the contract that describes the
    deal and the pricing record that values it - so somebody reading it can key each part into the
    screen it belongs to rather than hunting through one flat blob.

    The company code is included only where a deployment has configured one. AGFZE routes between
    company codes (2000 UAE, 3010 Singapore) and nothing in this platform's material says which
    transaction belongs to which, so this never picks one.
    """
    purchase = transaction.purchase_leg
    sales = transaction.sales_leg
    fa = getattr(transaction, "fa_leg", None)

    contract: dict[str, Any] = _clean(
        {
            "batch_number": transaction.batch_number,
            "transaction_code": transaction.transaction_code,
            "business_stream": transaction.stream,
            "commodity_code": transaction.commodity_code,
            "commodity_name": (
                transaction.commodity.display_name if transaction.commodity else None
            ),
            "quantity_mt": format_decimal(transaction.quantity_mt),
            "currency": transaction.currency,
            "company_code": settings.SAP_COMPANY_CODE.strip() or None,
        }
    )
    if purchase is not None:
        contract["purchase"] = _clean(
            {
                "supplier_name": purchase.supplier_name,
                "supplier_invoice_number": purchase.supplier_invoice_number,
                "contract_number": purchase.contract_number,
                "invoice_status": purchase.invoice_status,
                "port_of_loading": purchase.port_of_loading,
                "advance_payment_percent": format_decimal(purchase.advance_payment_percent),
            }
        )
    if sales is not None:
        contract["sales"] = _clean(
            {
                "customer_name": sales.customer_name,
                "sales_contract_no": sales.sales_contract_no,
                "sales_invoice_number": sales.sales_invoice_number,
                "contracted_quantity_mt": format_decimal(sales.contracted_quantity_mt),
                "territory": sales.territory,
                "port_of_discharge": sales.port_of_discharge,
                "payment_condition": sales.payment_condition,
                "bl_reference": sales.bl_reference,
            }
        )
    if fa is not None:
        contract["fa"] = _clean(
            {
                "counterparty_name": fa.counterparty_name,
                "fa_contract_reference": fa.fa_contract_reference,
                "document_type": fa.document_type,
                # The configured extras, exactly as the FA desk recorded them. Passed through
                # rather than interpreted: this module does not know what an FA field means.
                "additional_fields": dict(fa.extra_fields or {}),
            }
        )

    price_record: dict[str, Any] = _clean(
        {
            "price_basis": transaction.price_basis,
            "lme_percentage": format_decimal(transaction.lme_percentage),
            "rate": format_decimal(purchase.rate) if purchase else None,
            "amount": format_decimal(purchase.amount) if purchase else None,
            "currency": transaction.currency,
            "hedge_date": (
                purchase.hedge_date.isoformat()
                if purchase is not None and purchase.hedge_date is not None
                else None
            ),
            "customer_fixation_status": (sales.customer_fixation_status if sales else None),
            "fixation_rate": format_decimal(sales.fixation_rate) if sales else None,
            "fixation_date": (
                sales.fixation_date.isoformat()
                if sales is not None and sales.fixation_date is not None
                else None
            ),
            "is_final": (
                sales is not None and sales.customer_fixation_status == FixationStatus.FIXED.value
            ),
        }
    )

    return {
        # Says in the payload itself what the keys are and are not, so nobody downstream mistakes
        # them for SAP's own field names. The one exception is `sap_posting_reference`, which
        # names SAP's own fields because discovery mapped them explicitly.
        "schema": "agfze.platform.v1",
        "trade_contract": contract,
        "deal_price_record": price_record,
        "sap_posting_reference": _posting_reference(
            transaction, dms_document_number=dms_document_number
        ),
    }


PACK_LABELS: dict[str, str] = {
    DocumentPackType.PURCHASE_FILE.value: "Purchase file",
    DocumentPackType.SALES_BANK_DOCS.value: "Sales bank documents",
}


def dms_metadata(transaction: TradeTransaction, pack: DocumentPack) -> dict[str, Any]:
    """The index values the pack is filed under. Again, this platform's names, not the DMS's."""
    purchase = transaction.purchase_leg
    sales = transaction.sales_leg
    fa = getattr(transaction, "fa_leg", None)
    return _clean(
        {
            "schema": "agfze.platform.v1",
            "repository": settings.DMS_REPOSITORY.strip() or None,
            "pack_type": pack.pack_type,
            "pack_label": PACK_LABELS.get(pack.pack_type, pack.pack_type),
            "filename": pack.filename,
            "batch_number": transaction.batch_number,
            "transaction_code": transaction.transaction_code,
            "business_stream": transaction.stream,
            "commodity_code": transaction.commodity_code,
            "quantity_mt": format_decimal(transaction.quantity_mt),
            "currency": transaction.currency,
            "counterparty": (
                (purchase.supplier_name if purchase else None)
                or (sales.customer_name if sales else None)
                or (fa.counterparty_name if fa else None)
            ),
            "contract_number": (
                (purchase.contract_number if purchase else None)
                or (sales.sales_contract_no if sales else None)
                or (fa.fa_contract_reference if fa else None)
            ),
            "document_count": len(pack.source_document_ids or []),
        }
    )
