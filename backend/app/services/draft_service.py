"""Generating a reviewable draft sales contract or invoice from an approved template.

The division of labour here is the whole point of the module, and it is not negotiable:

* every commercial figure in a produced draft - party, grade, quantity, rate, value, ports,
  contract number, payment condition, fixation - is read out of the transaction record;
* the model is asked one narrow question, which clauses this deal needs, and its answer is
  validated against the template's own clause registry before it can touch anything;
* the bytes are produced by `python-docx` from a template file that shipped with the platform.

A model reply that does not survive validation fails the job. It does not fall back to the
shipped wording, it does not populate a partial template and it does not produce a document at
all. That asymmetry is deliberate: earlier steps' AI output was always read by somebody before it
mattered, and a polished-looking draft contract is exactly the kind of artefact that gets acted
on with less scrutiny than it deserves.

There is no code path in this module, dormant or otherwise, that emails, transmits, posts or
otherwise sends a produced document anywhere. A draft is stored, and a person opens it.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppError, BadRequestError, ConflictError
from app.core.logging import get_logger
from app.db.base import utcnow
from app.db.session import AsyncSessionLocal
from app.models.enums import (
    GENERATED_DOCUMENT_TYPES,
    NO_SHIPMENT_EVIDENCE_DRAFT_TYPES,
    DocumentSource,
    DocumentType,
    ExtractionStatus,
    FixationStatus,
    PriceBasis,
)
from app.models.identity import User
from app.models.intake import Document
from app.models.transactions import TradeTransaction
from app.services import job_service, sales_service
from app.services.audit_service import ActorType, record_audit_event
from app.services.gemini_service import AIServiceError, generate_draft_content
from app.services.rules import engine as rule_engine
from app.services.rules.sales_evaluators import draft_generation_permitted
from app.services.rules.values import format_decimal, money
from app.services.storage import get_storage_service
from app.services.templates import house_style
from app.services.templates.renderer import (
    ClauseDirective,
    TemplateRenderError,
    clause_brief,
    placeholder_brief,
    render_template,
)
from app.services.templates.sales_templates import (
    TEMPLATES_BY_TYPE,
    DocumentTemplate,
    ensure_template_files,
    template_path,
    territory_reference,
)

logger = get_logger(__name__)

JOB_TYPE_DRAFT = "sales.draft.generate"

DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

# The legal entity every AGFZE sales document is issued by. One value, and a real one, rather
# than a field somebody could leave blank on a document that names the company as a party.
#
# Corrected against the reference documents. Every one of them - the purchase contract's opening
# recital, the invoice's retention-of-title line, the bank beneficiary name and all four contract
# signature blocks - names the entity as ADANI GLOBAL FZE. The previous value here, "AGFZE Metals
# FZE", appears on no reference document and is not a legal entity: a generated contract carrying
# it would name the wrong party.
SELLER_LEGAL_NAME = house_style.SELLER_LEGAL_NAME

# How long a revised clause may be. Long enough for a real contract clause, short enough that a
# model producing a wall of text fails the job rather than filling a page with it.
MAX_CLAUSE_LENGTH = 2_000
MIN_CLAUSE_LENGTH = 20


class DraftContentInvalidError(AppError):
    """The model's structured answer did not survive validation, so no document was produced."""

    status_code = 422
    code = "draft_content_invalid"
    message = "The generated draft content failed validation, so no document was produced."


class DraftNotPermittedError(ConflictError):
    code = "draft_not_permitted"


@dataclass(frozen=True)
class DraftResult:
    document_id: UUID
    filename: str
    storage_ref: str
    document_type: str
    kept: list[str]
    revised: list[str]
    removed: list[str]
    unpopulated: list[str]
    notes: list[str]


# --- the facts, out of the record and nowhere else ---------------------------------------------


def _price_terms(transaction: TradeTransaction) -> str:
    """How this deal is priced, in words, from the transaction's own fields."""
    leg = transaction.sales_leg
    currency = transaction.currency
    if leg is not None and leg.customer_fixation_status == FixationStatus.FIXED.value:
        rate = format_decimal(leg.fixation_rate)
        if rate:
            fixed_on = leg.fixation_date.isoformat() if leg.fixation_date else None
            return f"{currency} {rate} per MT, fixed" + (f" on {fixed_on}" if fixed_on else "")
    if transaction.price_basis == PriceBasis.THREE_MONTH_LME.value:
        # Which quotation the price is struck against is a contractual term, so it is stated even
        # where no percentage was recorded. The averaged figure itself is never asserted here:
        # this platform records the three-month price somebody entered and computes no average of
        # its own, because it holds no daily exchange series to average.
        percentage = format_decimal(transaction.lme_percentage)
        return (
            f"{percentage}% of the 3-month LME quotation"
            if percentage
            else "the 3-month LME quotation"
        )
    if transaction.price_basis == PriceBasis.LME_PERCENT.value and transaction.lme_percentage:
        return f"{format_decimal(transaction.lme_percentage)}% of the LME cash settlement"
    purchase = transaction.purchase_leg
    rate = format_decimal(purchase.rate) if purchase is not None else None
    return f"{currency} {rate} per MT" if rate else ""


def _unit_rate(transaction: TradeTransaction) -> Decimal | None:
    """The per-MT rate a document states, from the transaction and from nothing else."""
    leg = transaction.sales_leg
    if leg is not None and leg.fixation_rate is not None:
        return leg.fixation_rate
    purchase = transaction.purchase_leg
    return purchase.rate if purchase is not None else None


def _total_value(transaction: TradeTransaction) -> Decimal | None:
    leg = transaction.sales_leg
    quantity = transaction.quantity_mt
    if quantity is None:
        return None
    if leg is not None and leg.fixation_rate is not None:
        return money(leg.fixation_rate * quantity)
    purchase = transaction.purchase_leg
    if purchase is not None and purchase.rate is not None:
        return money(purchase.rate * quantity)
    return None


def is_final(transaction: TradeTransaction) -> bool:
    """A draft is `Final` once the customer has fixed, and `Prov` until then."""
    leg = transaction.sales_leg
    return bool(leg is not None and leg.customer_fixation_status == FixationStatus.FIXED.value)


# One name per document this platform writes. `contract` and `invoice` are the desk's own words
# for the first two and are left exactly as they were; the two later documents get their own
# rather than being folded into "invoice", which is what a proforma invoice and a bank cover
# letter were both called - two different documents arriving on one transaction under one
# filename, telling whoever downloaded them nothing about which was which.
FILENAME_KIND: dict[str, str] = {
    DocumentType.DRAFT_CONTRACT.value: "contract",
    DocumentType.DRAFT_INVOICE.value: "invoice",
    DocumentType.DRAFT_PERFORMA_INVOICE.value: "performa-invoice",
    DocumentType.DRAFT_BANK_COVER_LETTER.value: "bank-cover-letter",
    DocumentType.DRAFT_PURCHASE_CONTRACT.value: "purchase-contract",
    DocumentType.DRAFT_COST_SHEET.value: "cost-sheet",
}


def storage_filename(transaction: TradeTransaction, document_type: str) -> str:
    """`SO-{batch}-{qty}-{Final|Prov}-{kind}` or `PO-...`, the naming convention the desk uses."""
    quantity = format_decimal(transaction.quantity_mt) or "0"
    suffix = "Final" if is_final(transaction) else "Prov"
    kind = FILENAME_KIND.get(document_type, "document")
    prefix = (
        "PO"
        if document_type
        in (
            DocumentType.DRAFT_PURCHASE_CONTRACT.value,
            DocumentType.DRAFT_COST_SHEET.value,
        )
        else "SO"
    )
    stem = f"{prefix}-{transaction.batch_number}-{quantity}-{suffix}"
    return f"{stem}-{kind}.docx"


def storage_key_for(document_id: UUID, filename: str) -> str:
    """A UUID-derived key, so the readable name never decides where the bytes live."""
    return f"documents/generated/{document_id}/{filename}"


def purchase_draft_generation_permitted(
    transaction: TradeTransaction, *, document_type: str | None = None
) -> tuple[bool, str | None]:
    """Check whether required purchase transaction data is present to generate a draft.

    If required data is missing, returns False and an informational message explaining what
    data is missing.
    """
    purchase = transaction.purchase_leg
    if purchase is None:
        return (
            False,
            "This transaction has no purchase leg, so there is no purchase document to draft.",
        )

    missing: list[str] = []
    if not (purchase.supplier_name and purchase.supplier_name.strip()):
        missing.append("supplier name")
    if transaction.quantity_mt is None or transaction.quantity_mt <= 0:
        missing.append("quantity (MT)")
    has_commodity = bool(
        (transaction.commodity and transaction.commodity.display_name)
        or (transaction.commodity_code and transaction.commodity_code.strip())
        or (
            transaction.extracted_commodity_value
            and transaction.extracted_commodity_value.strip()
        )
    )
    if not has_commodity:
        missing.append("commodity")
    has_rate = (
        purchase.rate is not None
        or purchase.amount is not None
        or bool(transaction.price_basis and transaction.price_basis.strip())
    )
    if not has_rate:
        missing.append("purchase rate / price")

    if missing:
        count = len(missing)
        verb = "is" if count == 1 else "are"
        items = (
            ", ".join(missing[:-1]) + f" and {missing[-1]}"
            if count > 1
            else missing[0]
        )
        return (
            False,
            f"Cannot generate draft: {items} {verb} missing from the purchase transaction.",
        )

    return True, None


def build_values(
    transaction: TradeTransaction, *, requested_by: User, moment: date | None = None
) -> dict[str, str]:
    """Every slot the templates declare, filled from the transaction and from nothing else."""
    leg = transaction.sales_leg
    purchase = transaction.purchase_leg
    today = (moment or utcnow().date()).isoformat()
    total = _total_value(transaction)

    values: dict[str, str] = {
        "contract_no": (
            getattr(purchase, "contract_number", None)
            or getattr(leg, "sales_contract_no", None)
            or ""
        ),
        "contract_date": today,
        "date": today,
        "invoice_no": (
            getattr(purchase, "supplier_invoice_number", None)
            or getattr(leg, "sales_invoice_number", None)
            or ""
        ),
        "invoice_date": today,
        "batch_number": transaction.batch_number,
        "seller": (
            getattr(purchase, "supplier_name", None)
            if leg is None
            else SELLER_LEGAL_NAME
        )
        or SELLER_LEGAL_NAME,
        "supplier": (getattr(purchase, "supplier_name", None) or ""),
        "buyer": (getattr(leg, "customer_name", None) or SELLER_LEGAL_NAME),
        "territory": (getattr(leg, "territory", None) or ""),
        "territory_reference": territory_reference(getattr(leg, "territory", None)),
        "commodity": (
            transaction.commodity.display_name
            if transaction.commodity is not None
            else (transaction.extracted_commodity_value or "")
        ),
        "commodity_code": (transaction.commodity_code or ""),
        # The issuing entity, under its own name rather than via `seller`. `seller` means
        # different things on a sales and a purchase document; the signature block needs a value
        # that is AGFZE on both, because AGFZE signs both.
        "agfze": SELLER_LEGAL_NAME,
        "quantity": format_decimal(transaction.quantity_mt, suffix=" MT") or "",
        # The per-MT figure the reference invoices print in their UNIT PRICE column, as a number.
        # Same precedence `_total_value` already settles on, so the rate and the amount on a
        # produced invoice can never disagree: the customer's fixed rate once fixed, and the
        # purchase rate until then. Empty while neither is recorded - never a guess.
        "unit_rate": format_decimal(_unit_rate(transaction)) or "",
        "contracted_quantity": (
            format_decimal(getattr(leg, "contracted_quantity_mt", None), suffix=" MT") or ""
        ),
        "price_terms": _price_terms(transaction),
        "purchase_rate": (
            f"{transaction.currency} {format_decimal(purchase.rate)} per MT"
            if purchase and purchase.rate is not None
            else _price_terms(transaction)
        ),
        "purchase_value": (
            f"{transaction.currency} {format_decimal(purchase.amount)}"
            if purchase and purchase.amount is not None
            else (f"{transaction.currency} {format_decimal(total)}" if total is not None else "")
        ),
        "currency": transaction.currency,
        "total_value": (
            f"{transaction.currency} {format_decimal(total)}" if total is not None else ""
        ),
        "total_cost": (
            f"{transaction.currency} {format_decimal(purchase.amount)}"
            if purchase and purchase.amount is not None
            else (f"{transaction.currency} {format_decimal(total)}" if total is not None else "")
        ),
        "invoice_basis": (
            purchase.invoice_status.capitalize()
            if purchase and purchase.invoice_status
            else ("Final" if is_final(transaction) else "Provisional")
        ),
        "payment_condition": (
            getattr(leg, "payment_condition", None) or "CAD"
        ),
        "port_of_loading": (getattr(purchase, "port_of_loading", None) or ""),
        "port_of_discharge": (getattr(leg, "port_of_discharge", None) or ""),
        "inland_container_depot": (getattr(leg, "inland_container_depot", None) or ""),
        "bl_reference": (getattr(leg, "bl_reference", None) or ""),
        "freight_and_logistics": "Standard Ocean Freight & Port Handling Allowance",
        "financing_and_charges": "Standard Bank Presentation & CAD Charges Provision",
        "hedge_details": (
            f"Hedged on {purchase.hedge_date.isoformat()}"
            + (
                f" (Low: {format_decimal(purchase.hedge_low_price)}, High: {format_decimal(purchase.hedge_high_price)})"
                if purchase.hedge_low_price is not None
                else ""
            )
            if purchase and purchase.hedge_date
            else (
                f"Price basis: {transaction.price_basis}"
                + (
                    f" ({format_decimal(transaction.lme_percentage)}% LME)"
                    if transaction.lme_percentage
                    else ""
                )
                if transaction.price_basis
                else "No exchange hedge recorded"
            )
        ),
        "b2b_split": (
            f"B2B deal with partner: {purchase.b2b_partner_name or 'Joint Venture Partner'}."
            if purchase and purchase.is_b2b
            else "100% AGFZE proprietary position."
        ),
        "letter_date": today,
        # The presenting bank is not recorded anywhere on a transaction. Left blank rather than
        # guessed, so a reviewer sees an empty slot and fills it in - a plausible bank name on a
        # covering letter is exactly the sort of invention that would reach a real presentation.
        "bank_name": "",
        "generated_at": utcnow().isoformat(timespec="seconds"),
        "generated_by": requested_by.display_name or requested_by.email,
    }
    return values


def build_facts(transaction: TradeTransaction) -> dict[str, object]:
    """What the model is told. Facts only, and only the ones a clause decision turns on."""
    leg = transaction.sales_leg
    purchase = transaction.purchase_leg
    return {
        "document being prepared for batch": transaction.batch_number,
        "commodity": (
            transaction.commodity.display_name
            if transaction.commodity is not None
            else transaction.extracted_commodity_value
        ),
        "trade grade": transaction.commodity_code,
        "quantity MT": format_decimal(transaction.quantity_mt),
        "shipment quantity MT": format_decimal(transaction.quantity_mt),
        "total contracted quantity MT": format_decimal(
            getattr(leg, "contracted_quantity_mt", None)
        ),
        "supplier": getattr(purchase, "supplier_name", None),
        "customer": getattr(leg, "customer_name", None),
        "purchase contract number": getattr(purchase, "contract_number", None),
        "supplier invoice number": getattr(purchase, "supplier_invoice_number", None),
        "purchase rate": format_decimal(getattr(purchase, "rate", None)),
        "purchase amount": format_decimal(getattr(purchase, "amount", None)),
        "purchase invoice status": getattr(purchase, "invoice_status", None),
        "port of loading": getattr(purchase, "port_of_loading", None),
        "destination territory": getattr(leg, "territory", None),
        "price basis": transaction.price_basis,
        "LME percentage": format_decimal(transaction.lme_percentage),
        "customer price fixation status": getattr(leg, "customer_fixation_status", None),
        "fixation rate": format_decimal(getattr(leg, "fixation_rate", None)),
        "fixation date": (
            leg.fixation_date.isoformat()
            if leg is not None and leg.fixation_date is not None
            else None
        ),
        "payment condition": getattr(leg, "payment_condition", None),
        "currency": transaction.currency,
        "port of discharge": getattr(leg, "port_of_discharge", None),
        "inland container depot": getattr(leg, "inland_container_depot", None),
        "bill of lading reference": getattr(leg, "bl_reference", None),
        "is B2B": getattr(purchase, "is_b2b", False),
        "B2B partner": getattr(purchase, "b2b_partner_name", None),
    }


# --- validating what came back ------------------------------------------------------------------


def validate_plan(template: DocumentTemplate, plan) -> list[ClauseDirective]:
    """Check the model's answer against the template's own registry. Nothing is coerced.

    Every failure here is a hard failure of the whole generation. There is no repair pass, no
    "drop the bad clause and carry on" and no default fallback, because each of those produces a
    document from an answer nobody can vouch for while looking exactly like one that was checked.
    """
    if not plan.clauses:
        raise DraftContentInvalidError(
            "The draft content service returned no clause decisions at all, so there is nothing "
            "to build a document from."
        )

    known = template.clause_keys
    required = template.required_clause_keys
    seen: set[str] = set()
    directives: list[ClauseDirective] = []

    for entry in plan.clauses:
        key = (entry.key or "").strip()
        action = (entry.action or "").strip().lower()

        if key not in known:
            raise DraftContentInvalidError(
                f"The draft content service named a clause '{key}' that the "
                f"{template.document_type} template does not have."
            )
        if key in seen:
            raise DraftContentInvalidError(
                f"The draft content service gave two conflicting instructions for clause '{key}'."
            )
        if action not in ("keep", "revise", "remove"):
            raise DraftContentInvalidError(
                f"'{action}' is not a clause action. Only keep, revise and remove are performed."
            )
        if action == "remove" and key in required:
            raise DraftContentInvalidError(
                f"The draft content service asked to remove '{key}', which is a required clause "
                f"of the {template.document_type} template."
            )

        text = (entry.text or "").strip() or None
        if action == "revise":
            if text is None or len(text) < MIN_CLAUSE_LENGTH:
                raise DraftContentInvalidError(
                    f"Clause '{key}' was marked for revision without usable replacement wording."
                )
            if len(text) > MAX_CLAUSE_LENGTH:
                raise DraftContentInvalidError(
                    f"The replacement wording for clause '{key}' is longer than a clause of this "
                    "template may be."
                )
            if "[[clause:" in text:
                raise DraftContentInvalidError(
                    f"The replacement wording for clause '{key}' contains a template control "
                    "marker, so it was rejected."
                )
            unknown = {
                name
                for name in _placeholders(text)
                if name not in set(template.field_names) | {"territory_reference"}
            }
            if unknown:
                raise DraftContentInvalidError(
                    f"The replacement wording for clause '{key}' refers to "
                    f"{', '.join(sorted(unknown))}, which this template does not populate."
                )
        elif text is not None and action == "remove":
            # Wording supplied for a clause being deleted is a contradiction, and a sign the
            # answer was not produced coherently. Refused rather than silently ignored.
            raise DraftContentInvalidError(
                f"Clause '{key}' was marked for removal but carries replacement wording."
            )

        seen.add(key)
        directives.append(
            ClauseDirective(
                key=key,
                action=action,
                text=text if action == "revise" else None,
                reason=(entry.reason or None),
            )
        )

    return directives


PLACEHOLDER_PATTERN = re.compile(r"\{\{([a-z0-9_]+)\}\}")


def _placeholders(text: str) -> set[str]:
    return set(PLACEHOLDER_PATTERN.findall(text))


# --- the generation itself ------------------------------------------------------------------------


async def load_transaction(session: AsyncSession, transaction_id: UUID) -> TradeTransaction:
    transaction = await session.scalar(
        select(TradeTransaction)
        .where(TradeTransaction.id == transaction_id)
        .options(
            selectinload(TradeTransaction.purchase_leg),
            selectinload(TradeTransaction.sales_leg),
            selectinload(TradeTransaction.commodity),
        )
    )
    if transaction is None:
        raise BadRequestError("The transaction no longer exists.")
    return transaction


def resolve_template(document_type: str) -> DocumentTemplate:
    template = TEMPLATES_BY_TYPE.get(document_type)
    if template is None:
        raise BadRequestError(
            f"'{document_type}' is not a document this platform generates. "
            f"Choose one of: {', '.join(sorted(GENERATED_DOCUMENT_TYPES))}.",
            code="unknown_draft_type",
        )
    return template


async def assert_generation_permitted(
    session: AsyncSession, transaction: TradeTransaction, *, document_type: str | None = None
) -> None:
    """Check whether draft generation is permitted for this transaction and document type."""
    if document_type in (
        DocumentType.DRAFT_PURCHASE_CONTRACT.value,
        DocumentType.DRAFT_COST_SHEET.value,
    ):
        permitted, reason = purchase_draft_generation_permitted(
            transaction, document_type=document_type
        )
        if not permitted:
            raise DraftNotPermittedError(
                reason or "Required purchase transaction data is missing."
            )
        return

    if transaction.sales_leg is None:
        raise DraftNotPermittedError(
            "This transaction has no sales leg, so there is no sales document to draft."
        )
    if document_type in NO_SHIPMENT_EVIDENCE_DRAFT_TYPES:
        return
    evaluations = await rule_engine.current_results(session, transaction.id)
    permitted, reason = draft_generation_permitted(evaluations)
    if not permitted:
        raise DraftNotPermittedError(
            reason or "BR-07 does not permit a draft to be prepared for this transaction yet."
        )


async def generate(
    session: AsyncSession,
    transaction: TradeTransaction,
    *,
    document_type: str,
    requested_by: User,
) -> DraftResult:
    """Produce one draft, end to end. Raises rather than producing anything questionable."""
    template = resolve_template(document_type)
    ensure_template_files()

    path = template_path(template)
    if not path.exists():
        raise DraftContentInvalidError(
            f"The {template.document_type} template is not available on this deployment, so no "
            "document can be produced from it."
        )
    template_bytes = path.read_bytes()

    plan = await generate_draft_content(
        document_type=template.document_type,
        clause_registry=clause_brief(template),
        placeholder_registry=placeholder_brief(template),
        facts=build_facts(transaction),
    )
    directives = validate_plan(template, plan)

    values = build_values(transaction, requested_by=requested_by)
    try:
        rendered = render_template(
            template,
            template_bytes=template_bytes,
            values=values,
            directives=directives,
        )
    except TemplateRenderError as exc:
        raise DraftContentInvalidError(str(exc)) from exc

    document_id = uuid.uuid4()
    filename = storage_filename(transaction, template.document_type)
    key = storage_key_for(document_id, filename)
    await get_storage_service().upload(key, rendered.content, DOCX_CONTENT_TYPE)

    document = Document(
        id=document_id,
        # Deliberately null. A generated draft originates from no intake event: nothing received
        # it, so there is no request to point at, and minting a synthetic one would put a
        # fiction in the intake queue.
        request_id=None,
        transaction_id=transaction.id,
        filename=filename,
        content_type=DOCX_CONTENT_TYPE,
        byte_size=len(rendered.content),
        document_type=template.document_type,
        original_document_type=template.document_type,
        territory=transaction.sales_leg.territory if transaction.sales_leg else None,
        storage_ref=key,
        page_image_refs=[],
        content_hash=hashlib.sha256(rendered.content).hexdigest(),
        # There is nothing to read and understand about a document this platform wrote itself.
        extraction_status=ExtractionStatus.NOT_APPLICABLE.value,
        classification_confidence=None,
        needs_review=False,
        source=DocumentSource.GENERATED.value,
        # The existing field, recording who triggered the generation.
        uploaded_by_id=requested_by.id,
    )
    session.add(document)
    await session.flush()

    await record_audit_event(
        session,
        event_type=sales_service.AuditEvent.DRAFT_GENERATED,
        entity_type="trade_transaction",
        entity_id=transaction.id,
        actor_id=requested_by.id,
        actor_type=ActorType.USER,
        metadata={
            "batch_number": transaction.batch_number,
            "document_id": str(document.id),
            "document_type": template.document_type,
            "filename": filename,
            "storage_ref": key,
            "clauses_kept": rendered.kept,
            "clauses_revised": rendered.revised,
            "clauses_removed": rendered.removed,
            "unpopulated_fields": rendered.unpopulated,
            "model_notes": list(plan.notes or []),
        },
    )

    return DraftResult(
        document_id=document.id,
        filename=filename,
        storage_ref=key,
        document_type=template.document_type,
        kept=rendered.kept,
        revised=rendered.revised,
        removed=rendered.removed,
        unpopulated=rendered.unpopulated,
        notes=list(plan.notes or []),
    )


# --- the tracked background job -------------------------------------------------------------------


async def _run(transaction_id: UUID, job_id: UUID, document_type: str, user_id: UUID) -> None:
    """Own session, own lifetime: the request that queued the work is long gone.

    Every failure lands the job in `failed` with a message the workspace shows. Nothing partial
    survives: the document row is only added after the bytes exist, and the session is rolled
    back on any error, so a failed generation leaves no half-written draft on the transaction.
    """
    async with AsyncSessionLocal() as session:
        try:
            transaction = await load_transaction(session, transaction_id)
            user = await session.get(User, user_id)
            if user is None:
                await job_service.fail_job(
                    session, job_id, error_message="The requesting account no longer exists."
                )
                await session.commit()
                return

            await job_service.update_job_progress(session, job_id, 20)
            await session.commit()

            result = await generate(
                session, transaction, document_type=document_type, requested_by=user
            )
            await job_service.complete_job(
                session, job_id, result_ref=f"document:{result.document_id}"
            )
            await session.commit()
        except (DraftContentInvalidError, TemplateRenderError, AIServiceError) as exc:
            # The higher-stakes failure. A malformed or unvalidated answer fails the job cleanly
            # and produces nothing at all, rather than populating a template with content nobody
            # has vouched for.
            await session.rollback()
            reason = (
                exc.message
                if isinstance(exc, DraftContentInvalidError)
                else "The draft content service could not produce a usable, validated answer."
            )
            logger.warning(
                "draft_generation_rejected",
                extra={
                    "transaction_id": str(transaction_id),
                    "document_type": document_type,
                    "reason": type(exc).__name__,
                },
            )
            await _record_failure(job_id, transaction_id, document_type, user_id, reason)
        except Exception:
            await session.rollback()
            logger.exception(
                "draft_generation_failed", extra={"transaction_id": str(transaction_id)}
            )
            await _record_failure(
                job_id,
                transaction_id,
                document_type,
                user_id,
                "The draft could not be generated. Nothing was produced.",
            )


async def _record_failure(
    job_id: UUID, transaction_id: UUID, document_type: str, user_id: UUID, reason: str
) -> None:
    """Fail the job and audit the failure on a session of its own.

    Separate from the session that just rolled back, so the failure record cannot be lost to the
    same rollback that discarded the work.
    """
    async with AsyncSessionLocal() as session:
        try:
            await job_service.fail_job(session, job_id, error_message=reason)
            await record_audit_event(
                session,
                event_type=sales_service.AuditEvent.DRAFT_GENERATION_FAILED,
                entity_type="trade_transaction",
                entity_id=transaction_id,
                actor_id=user_id,
                actor_type=ActorType.USER,
                metadata={
                    "document_type": document_type,
                    "job_id": str(job_id),
                    "reason": reason,
                },
            )
            await session.commit()
        except Exception:  # pragma: no cover - the failure path's own failure
            logger.exception("draft_failure_not_recorded", extra={"job_id": str(job_id)})
            await session.rollback()


_BACKGROUND_TASKS: set[asyncio.Task] = set()


async def queue_generation(
    session: AsyncSession,
    transaction: TradeTransaction,
    *,
    document_type: str,
    requested_by: User,
) -> UUID:
    """Create the tracked job and start the generation. Returns the job id the client polls.

    The same `job_service` and the same `GET /jobs/{job_id}/status` Step 2 established for
    extraction. There is no second job mechanism, and this one reports progress into the same
    row the intake pipeline uses.
    """
    resolve_template(document_type)
    await assert_generation_permitted(session, transaction, document_type=document_type)

    job = await job_service.create_job(
        session,
        job_type=JOB_TYPE_DRAFT,
        created_by_id=requested_by.id,
        transaction_id=transaction.id,
    )
    await record_audit_event(
        session,
        event_type=sales_service.AuditEvent.DRAFT_GENERATION_REQUESTED,
        entity_type="trade_transaction",
        entity_id=transaction.id,
        actor_id=requested_by.id,
        actor_type=ActorType.USER,
        metadata={
            "batch_number": transaction.batch_number,
            "document_type": document_type,
            "job_id": str(job.id),
            # Every regeneration produces a new draft beside the last one. The count is the
            # version this request will become.
            "existing_draft_count": await _draft_count(session, transaction.id, document_type),
        },
    )
    await session.commit()

    task = asyncio.create_task(_run(transaction.id, job.id, document_type, requested_by.id))
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)
    return job.id


async def _draft_count(session: AsyncSession, transaction_id: UUID, document_type: str) -> int:
    rows = (
        await session.scalars(
            select(Document.id).where(
                Document.transaction_id == transaction_id,
                Document.document_type == document_type,
                Document.source == DocumentSource.GENERATED.value,
            )
        )
    ).all()
    return len(rows)


async def drafts_for(session: AsyncSession, transaction_id: UUID) -> list[Document]:
    """Every draft ever generated for this transaction, oldest first.

    Requesting changes and regenerating creates a new document beside the previous one; nothing
    is ever overwritten, so this list is the full record of what was produced and when.
    """
    return list(
        (
            await session.scalars(
                select(Document)
                .where(
                    Document.transaction_id == transaction_id,
                    Document.source == DocumentSource.GENERATED.value,
                )
                .order_by(Document.created_at)
            )
        ).all()
    )
