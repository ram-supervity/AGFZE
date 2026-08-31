"""Attaching the sell side of a batch to the batch it belongs to, and keeping SL-01 honest.

Three concerns live here, and one deliberate absence.

**Attachment.** A sales-triggering document - an original bill of lading, a shipping
confirmation, or an approved draft B/L - is matched to the transaction the purchase side already
opened, using the very same scoring Step 3 built. Nothing here re-implements matching: it reads
`matching_service`'s thresholds, its candidate scorer and its bands, and differs from the
purchase path in exactly one respect, described below.

**Cross-contract consistency.** The transaction's commodity code is shared by construction
between the legs, so a genuine disagreement can only mean the sales document was matched to the
wrong batch. That is what is checked and flagged. The free-text commodity *description* on the
two sides is never compared: a China-bound shipment legitimately needs different customs wording
for the same underlying grade, and flagging that would produce a false positive on nearly every
export the desk makes.

**Aggregate consistency.** SL-01 is a fact about a sales contract, not about a transaction, so
an event on one shipment changes what SL-01 says about its siblings. `propagate_coverage` is what
keeps their recorded results from going stale, and it re-runs SL-01 alone - never a full
re-validation of every rule on every sibling.

The absence: there is no merge. Where the sales document does not confidently identify one
transaction, a person picks the right one or explicitly states that no purchase counterpart
exists, before anything is created. Two transactions that should have been one is a far harder
problem than one decision taken at the right time, and this platform does not create it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import BadRequestError, ConflictError, NotFoundError
from app.core.logging import get_logger
from app.db.base import utcnow
from app.models.configuration import RuleConfiguration
from app.models.enums import (
    DRAFT_BL_DOCUMENT_TYPES,
    FINAL_BL_DOCUMENT_TYPES,
    SALES_TRIGGER_DOCUMENT_KINDS,
    BatchNumberSource,
    DealDirection,
    DocumentType,
    FixationStatus,
    MatchMethod,
    PriceBasis,
    RequestCategory,
    TransactionStatus,
)
from app.models.intake import Document
from app.models.transactions import RuleEvaluation, SalesLeg, TradeTransaction
from app.services import matching_service, transaction_service
from app.services.audit_service import ActorType, record_audit_event
from app.services.governance import hooks as governance_hooks
from app.services.rules import engine as rule_engine
from app.services.rules.catalog import CheckKey, RuleId
from app.services.rules.registry import RuleConfigurationResolver
from app.services.rules.sales_evaluators import (
    ContractCoverage,
    contract_coverage,
    evaluate_coverage_for,
    sibling_transactions,
)

logger = get_logger(__name__)

# The document types that trigger the sales workflow. A draft B/L is on the list because AGFZE's
# process explicitly permits preparing sales paperwork from one; what a draft cannot do is get a
# transaction submitted, and that is BR-07's business rather than this list's.
SALES_TRIGGER_DOCUMENT_TYPES: frozenset[str] = frozenset(
    (*FINAL_BL_DOCUMENT_TYPES, *DRAFT_BL_DOCUMENT_TYPES)
)

# The one type in that set that is not, on its own, evidence of a shipment. `bl` and `bl_draft`
# say what they are; `shipping_document` is the family's catch-all and has to be read together
# with the document's kind before it is treated as a trigger.
SUPPORTING_PACK_TYPES: frozenset[str] = frozenset({DocumentType.SHIPPING_DOCUMENT.value})


class AuditEvent:
    SALES_LEG_ATTACHED = "transaction.sales_leg_attached"
    SALES_MATCH_UNRESOLVED = "transaction.sales_match_unresolved"
    SALES_COMMODITY_MISMATCH = "transaction.sales_commodity_mismatch"
    PRICE_FIXATION_RECORDED = "transaction.price_fixation_recorded"
    CONTRACT_COVERAGE_REEVALUATED = "transaction.contract_coverage_reevaluated"
    DRAFT_GENERATION_REQUESTED = "transaction.draft_requested"
    DRAFT_GENERATED = "transaction.draft_generated"
    DRAFT_GENERATION_FAILED = "transaction.draft_generation_failed"


class Attachment:
    """How a sales leg came to sit on the transaction it sits on."""

    AUTO_MATCHED = "auto_matched"
    SUGGESTION_CONFIRMED = "suggestion_confirmed"
    USER_SELECTED = "user_selected"
    NO_PURCHASE_ACKNOWLEDGED = "no_purchase_acknowledged"


# --- matching a sales document to the batch already bought ------------------------------------


def is_sales_document(document: Document) -> bool:
    """Whether this document is one the sales workflow triggers off."""
    if document.deal_direction == "sales":
        return True
    if document.deal_direction == "purchase":
        return False
    if document.document_type in SUPPORTING_PACK_TYPES:
        kinds = tuple(document.document_kinds or ())
        if kinds and not set(kinds).intersection(SALES_TRIGGER_DOCUMENT_KINDS):
            return False
    if document.document_type in SALES_TRIGGER_DOCUMENT_TYPES:
        return True
    request = document.request
    return bool(request is not None and request.category == RequestCategory.SALES.value)


@dataclass
class SalesMatch:
    """What the platform believes the sales document belongs to, and how sure it is."""

    outcome: str
    message: str
    transaction_id: UUID | None = None
    batch_number: str | None = None
    score: float | None = None
    method: str | None = None
    candidates: list[dict[str, object]] = field(default_factory=list)

    @property
    def needs_user_decision(self) -> bool:
        return self.outcome in (
            matching_service.Outcome.SUGGESTED,
            Outcome.NO_PURCHASE_MATCH,
        )


def sales_score(candidate: matching_service.Candidate) -> float:
    """The composite for a sales-side candidate, from the same scorer's own components.

    One deliberate difference from the purchase side, and the reason it is a difference rather
    than a second scorer. On the purchase path the composite is the *weaker* of the contract and
    counterparty comparisons, because both appear on the same supplier paperwork and a perfect
    contract reference cannot carry a name that plainly belongs to somebody else.

    A bill of lading names the carrier's parties - AGFZE as shipper, the customer as consignee -
    and never the supplier AGFZE bought the cargo from. A zero counterparty score is therefore
    the expected state of a genuine match, not evidence against one, and taking the minimum would
    reject every real sales document there is. The stronger of the two is taken instead, and the
    corroborating commodity and quantity penalties the scorer already computed still only ever
    subtract.
    """
    base = max(candidate.contract_score, candidate.supplier_score)
    if candidate.quantity_variance is not None:
        penalty = Decimal(str(matching_service.QUANTITY_PENALTY))
        base -= float(
            min(penalty, candidate.quantity_variance / matching_service.QUANTITY_SPREAD * penalty)
        )
    if (candidate.contract_score or candidate.supplier_score) and not candidate.commodity_match:
        base -= matching_service.COMMODITY_PENALTY
    return max(0.0, round(float(base), 2))


def classify_sales_candidate(score: float, thresholds: dict[str, Decimal]) -> str:
    """The same three bands, against the same configured thresholds, and no fourth."""
    if score >= float(thresholds["contract"]):
        return matching_service.Outcome.AUTO_LINKED
    if score >= float(thresholds["floor"]):
        return matching_service.Outcome.SUGGESTED
    return Outcome.NO_PURCHASE_MATCH


class Outcome(matching_service.Outcome):
    """Step 3's bands, plus the one the sales side needs and the purchase side does not.

    On the purchase path, nothing matching means a new batch is opened, and that is correct: a
    purchase is where a batch begins. On the sales path it is not. A sale is almost always of
    cargo AGFZE has already bought, so silently opening a second, purchase-less transaction would
    quietly split one physical cargo across two records. This band is what stops that: the Sales
    User names the transaction, or states on the record that there genuinely is no purchase
    counterpart yet.
    """

    NO_PURCHASE_MATCH = "no_purchase_match"


async def evaluate_attachment(session: AsyncSession, document: Document) -> SalesMatch:
    """Work out which transaction this sales document belongs to. Changes nothing.

    The batch number first, then Step 3's contract / counterparty / commodity scoring, against
    the same configured thresholds. Only the bottom band differs.
    """
    if not is_sales_document(document):
        return SalesMatch(
            outcome=matching_service.Outcome.NOT_APPLICABLE,
            message="This document does not trigger the sales workflow.",
        )

    values = matching_service.document_values(document)

    batch = (values.get("batch_number") or "").strip()
    if batch:
        exact = await session.scalar(
            select(TradeTransaction)
            .where(TradeTransaction.batch_number == batch)
            .options(
                selectinload(TradeTransaction.purchase_leg),
                selectinload(TradeTransaction.sales_leg),
            )
        )
        if exact is not None:
            return SalesMatch(
                outcome=matching_service.Outcome.AUTO_LINKED,
                message=(
                    f"The document quotes batch {batch}, which is an exact match to an existing "
                    "transaction."
                ),
                transaction_id=exact.id,
                batch_number=exact.batch_number,
                score=100.0,
                method=MatchMethod.BATCH_NUMBER.value,
            )

    # The same candidate scorer, the same thresholds. `find_candidates` already restricts itself
    # to transactions that carry a purchase leg, which is exactly what a sales document should be
    # looking for: the batch that was bought.
    candidates, thresholds = await matching_service.find_candidates(session, document, values)
    scored = sorted(
        (
            (candidate, sales_score(candidate))
            for candidate in candidates
            # A batch that already carries a sales leg has already been sold. Offering it would
            # be offering a conflict, not a match.
            if candidate.transaction.sales_leg is None
        ),
        key=lambda pair: pair[1],
        reverse=True,
    )
    best, best_score = scored[0] if scored else (None, 0.0)
    band = (
        classify_sales_candidate(best_score, thresholds)
        if best is not None
        else Outcome.NO_PURCHASE_MATCH
    )

    if best is not None and band == matching_service.Outcome.AUTO_LINKED:
        return SalesMatch(
            outcome=matching_service.Outcome.AUTO_LINKED,
            message=(
                f"Matched to batch {best.transaction.batch_number} at {best_score:.0f} "
                f"({best.rationale()})."
            ),
            transaction_id=best.transaction.id,
            batch_number=best.transaction.batch_number,
            score=best_score,
            method=MatchMethod.FUZZY_AUTO.value,
        )

    offered = [
        {
            "transaction_id": str(candidate.transaction.id),
            "batch_number": candidate.transaction.batch_number,
            "supplier_name": (
                candidate.transaction.purchase_leg.supplier_name
                if candidate.transaction.purchase_leg
                else None
            ),
            "contract_number": (
                candidate.transaction.purchase_leg.contract_number
                if candidate.transaction.purchase_leg
                else None
            ),
            "score": score,
            "rationale": candidate.rationale(),
        }
        for candidate, score in scored
        if score >= float(thresholds["floor"])
    ][:5]

    if best is not None and band == matching_service.Outcome.SUGGESTED:
        return SalesMatch(
            outcome=matching_service.Outcome.SUGGESTED,
            message=(
                f"Batch {best.transaction.batch_number} looks like the same cargo at "
                f"{best_score:.0f}, which is below the auto-link threshold. Confirm it before a "
                "sales leg is created against it."
            ),
            transaction_id=best.transaction.id,
            batch_number=best.transaction.batch_number,
            score=best_score,
            method=MatchMethod.SUGGESTION_CONFIRMED.value,
            candidates=offered,
        )

    return SalesMatch(
        outcome=Outcome.NO_PURCHASE_MATCH,
        message=(
            "No open purchase transaction resembles this shipment closely enough to attach to. "
            "Search for and select the correct batch, or record explicitly that no purchase "
            "counterpart exists yet - nothing is created until you do."
        ),
        score=best_score if best is not None else None,
        candidates=offered,
    )


# --- cross-contract consistency: the code, never the wording ----------------------------------


@dataclass(frozen=True)
class CommodityConsistency:
    """The result of the one comparison Section 9.5 asks for."""

    transaction_code: str | None
    document_code: str | None
    document_value: str | None
    mismatch: bool
    message: str


async def check_commodity_consistency(
    session: AsyncSession, transaction: TradeTransaction, raw_value: str | None
) -> CommodityConsistency:
    """Does the grade the sales document reports resolve to the grade the batch carries?

    A structured code comparison, on resolved codes, and nothing else. The purchase side's
    free-text description is not read here and is not compared to anything: a shipment bound for
    China carries different customs wording for the same underlying code than the purchase
    paperwork used, that difference is expected, and treating it as an error would flag almost
    every export while telling nobody anything true.
    """
    stated = (raw_value or "").strip()
    if not stated:
        return CommodityConsistency(
            transaction_code=transaction.commodity_code,
            document_code=None,
            document_value=None,
            mismatch=False,
            message=(
                "The sales document did not state a commodity grade, so there is nothing to "
                "disagree with the batch's own."
            ),
        )

    resolved, _needs_review = await transaction_service.resolve_commodity(session, stated)
    if transaction.commodity_code is None or resolved is None:
        return CommodityConsistency(
            transaction_code=transaction.commodity_code,
            document_code=resolved,
            document_value=stated,
            mismatch=False,
            message=(
                f"The sales document describes the goods as '{stated}'. It cannot be compared to "
                "a resolved trade grade on either side, so no code disagreement is claimed."
            ),
        )

    mismatch = resolved.upper() != transaction.commodity_code.upper()
    return CommodityConsistency(
        transaction_code=transaction.commodity_code,
        document_code=resolved,
        document_value=stated,
        mismatch=mismatch,
        message=(
            f"The sales document's grade resolves to {resolved}, which is the batch's own grade. "
            "The description wording on the two sides may legitimately differ; the code agrees."
            if not mismatch
            else f"The sales document's grade resolves to {resolved}, but this batch is "
            f"{transaction.commodity_code}. The two sides of one cargo cannot be different "
            "grades - check that this shipment was matched to the right transaction before "
            "going any further."
        ),
    )


# --- attaching the leg --------------------------------------------------------------------------


@dataclass(frozen=True)
class SalesLegInput:
    customer_name: str
    territory: str
    sales_contract_no: str
    payment_condition: str
    contracted_quantity_mt: Decimal | None = None
    sales_invoice_number: str | None = None
    bl_reference: str | None = None
    port_of_discharge: str | None = None
    inland_container_depot: str | None = None
    customer_fixation_status: str = FixationStatus.UNFIXED.value
    fixation_rate: Decimal | None = None
    fixation_date: date | None = None
    quantity_mt: Decimal | None = None


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
        raise NotFoundError("Transaction not found.")
    return transaction


async def attach_sales_leg(
    session: AsyncSession,
    transaction: TradeTransaction,
    payload: SalesLegInput,
    *,
    actor_id: UUID,
    attachment: str,
    acknowledged_no_purchase: bool = False,
    document: Document | None = None,
    match_score: float | None = None,
) -> tuple[SalesLeg, CommodityConsistency]:
    """Create the sales leg on an already-identified transaction, and validate what results.

    The transaction is identified before this is called, every time, by one of exactly four
    routes: an exact batch match, a confident score, a suggestion a person confirmed, or a
    transaction a person searched for and picked. There is no fifth route in which the platform
    guesses, and none in which two records are stitched together afterwards.
    """
    if transaction.sales_leg is not None:
        raise ConflictError(
            f"Batch {transaction.batch_number} already carries a sales leg. Correct its fields "
            "rather than attaching a second one."
        )
    if transaction.status in (
        TransactionStatus.APPROVAL_PENDING.value,
        TransactionStatus.APPROVED.value,
    ):
        raise ConflictError(
            "This transaction is awaiting approval or already approved, so a sales leg can no "
            "longer be attached to it."
        )
    if transaction.purchase_leg is None and not acknowledged_no_purchase:
        raise ConflictError(
            f"Batch {transaction.batch_number} has no purchase leg. A sale is almost always of "
            "cargo AGFZE has already bought, so attaching a sales leg to a transaction with no "
            "purchase side has to be acknowledged explicitly.",
            code="purchase_leg_absent",
        )

    consistency = await check_commodity_consistency(
        session,
        transaction,
        (document is not None and matching_service.document_values(document).get("commodity_code"))
        or None,
    )

    leg = SalesLeg(
        transaction_id=transaction.id,
        customer_name=payload.customer_name.strip(),
        territory=payload.territory,
        sales_contract_no=payload.sales_contract_no.strip(),
        contracted_quantity_mt=payload.contracted_quantity_mt,
        sales_invoice_number=(payload.sales_invoice_number or None),
        bl_reference=(payload.bl_reference or None),
        payment_condition=payload.payment_condition,
        customer_fixation_status=payload.customer_fixation_status,
        fixation_rate=payload.fixation_rate,
        fixation_date=payload.fixation_date,
        port_of_discharge=(payload.port_of_discharge or None),
        inland_container_depot=(payload.inland_container_depot or None),
        extracted_commodity_value=consistency.document_value,
    )
    session.add(leg)
    await session.flush()
    transaction.sales_leg = leg

    # The shipped quantity, where the sales side is the first to know it. Never a silent
    # overwrite of a figure the purchase side already established.
    if payload.quantity_mt is not None and transaction.quantity_mt is None:
        transaction.quantity_mt = payload.quantity_mt

    if document is not None and document.transaction_id is None:
        await matching_service.link_document(
            session,
            transaction,
            document,
            method=(
                MatchMethod.SUGGESTION_CONFIRMED.value
                if attachment == Attachment.SUGGESTION_CONFIRMED
                else MatchMethod.MANUAL.value
                if attachment in (Attachment.USER_SELECTED, Attachment.NO_PURCHASE_ACKNOWLEDGED)
                else MatchMethod.FUZZY_AUTO.value
            ),
            score=match_score,
            rationale=(
                f"Sales leg for customer {leg.customer_name} attached to batch "
                f"{transaction.batch_number} ({attachment.replace('_', ' ')})."
            ),
            actor_id=actor_id,
        )

    transaction.updated_at = utcnow()
    await session.flush()

    await record_audit_event(
        session,
        event_type=AuditEvent.SALES_LEG_ATTACHED,
        entity_type="trade_transaction",
        entity_id=transaction.id,
        actor_id=actor_id,
        actor_type=ActorType.USER,
        metadata={
            "batch_number": transaction.batch_number,
            "attachment": attachment,
            "match_score": match_score,
            "customer_name": leg.customer_name,
            "territory": leg.territory,
            "sales_contract_no": leg.sales_contract_no,
            "contracted_quantity_mt": (
                str(leg.contracted_quantity_mt) if leg.contracted_quantity_mt is not None else None
            ),
            "payment_condition": leg.payment_condition,
            "document_id": str(document.id) if document is not None else None,
            "purchase_leg_present": transaction.purchase_leg is not None,
            "no_purchase_acknowledged": acknowledged_no_purchase,
            "commodity_code_mismatch": consistency.mismatch,
        },
    )

    if consistency.mismatch:
        await record_audit_event(
            session,
            event_type=AuditEvent.SALES_COMMODITY_MISMATCH,
            entity_type="trade_transaction",
            entity_id=transaction.id,
            actor_id=actor_id,
            actor_type=ActorType.USER,
            metadata={
                "batch_number": transaction.batch_number,
                "transaction_commodity_code": consistency.transaction_code,
                "document_commodity_code": consistency.document_code,
                "document_commodity_value": consistency.document_value,
            },
        )

    await rule_engine.run_validation(session, transaction)
    await propagate_coverage(session, transaction, actor_id=actor_id)
    return leg, consistency


async def record_no_match_acknowledgement(
    session: AsyncSession,
    *,
    document: Document | None,
    actor_id: UUID,
    note: str,
) -> None:
    """Put a "no purchase counterpart exists" decision on the record before it is acted on."""
    await record_audit_event(
        session,
        event_type=AuditEvent.SALES_MATCH_UNRESOLVED,
        entity_type="document" if document is not None else "trade_transaction",
        entity_id=document.id if document is not None else None,
        actor_id=actor_id,
        actor_type=ActorType.USER,
        metadata={
            "document_id": str(document.id) if document is not None else None,
            "acknowledgement": note,
        },
    )


# --- price fixation -----------------------------------------------------------------------------


async def record_fixation_audit(
    session: AsyncSession,
    transaction: TradeTransaction,
    *,
    actor_id: UUID,
    previous_status: str,
    rate: Decimal | None,
    fixed_on: date | None,
) -> None:
    """The audit entry behind a fixation.

    The fixation itself is written through `PATCH /transactions/{id}/fields`, which is Step 3's
    correction-and-revalidation path - the same reason gate, the same provenance record, the same
    synchronous re-run. This adds the governance event that names the act for what it is, because
    "customer fixed the price" is not the same fact as "three fields changed".
    """
    leg = transaction.sales_leg
    if leg is None:
        return
    await record_audit_event(
        session,
        event_type=AuditEvent.PRICE_FIXATION_RECORDED,
        entity_type="trade_transaction",
        entity_id=transaction.id,
        actor_id=actor_id,
        actor_type=ActorType.USER,
        metadata={
            "batch_number": transaction.batch_number,
            "sales_contract_no": leg.sales_contract_no,
            "customer_name": leg.customer_name,
            "previous_status": previous_status,
            "status": leg.customer_fixation_status,
            "fixation_rate": str(rate) if rate is not None else None,
            "fixation_date": fixed_on.isoformat() if fixed_on else None,
        },
    )


# --- keeping the aggregate honest across every shipment on one contract -----------------------


async def coverage_tolerance(session: AsyncSession, transaction: TradeTransaction) -> Decimal:
    """SL-01's configured allowance, read exactly the way an evaluator would read it."""
    resolver = RuleConfigurationResolver(
        list((await session.scalars(select(RuleConfiguration))).all())
    )
    row = resolver.resolve(
        RuleId.SL_01,
        CheckKey.CONTRACT_QUANTITY_COVERAGE,
        commodity_code=transaction.commodity_code,
        transaction_type="sales",
        stream=transaction.stream,
    )
    if row is None:
        raise ConflictError(
            f"{RuleId.SL_01} has no active configuration, so the sales contract's quantity "
            "coverage cannot be evaluated."
        )
    return row.threshold_value


async def current_coverage(
    session: AsyncSession, transaction: TradeTransaction
) -> ContractCoverage | None:
    """The aggregate position of this transaction's sales contract, for the workspace's meter."""
    leg = transaction.sales_leg
    contract_no = (getattr(leg, "sales_contract_no", None) or "").strip()
    if not contract_no:
        return None
    return await contract_coverage(session, contract_no)


async def propagate_coverage(
    session: AsyncSession,
    transaction: TradeTransaction,
    *,
    actor_id: UUID | None = None,
) -> list[UUID]:
    """Re-run SL-01, and only SL-01, on every other shipment against the same sales contract.

    SL-01 is a fact about the contract. The moment this transaction's quantity, its contracted
    total or its very existence changes, what SL-01 says about every sibling changes with it -
    and a sibling still showing yesterday's "part-shipped, more to come" while the contract has
    since been over-invoiced is exactly the stale result this exists to prevent.

    Scoped deliberately: a fresh row is written only where the sibling's own latest SL-01 result
    actually differs from what the aggregate now says, and no other rule is touched on any
    sibling. Re-validating every rule on every neighbour would rewrite acknowledgements and
    evaluation history that this event has nothing to do with.
    """
    leg = transaction.sales_leg
    contract_no = (getattr(leg, "sales_contract_no", None) or "").strip()
    if not contract_no:
        return []

    tolerance = await coverage_tolerance(session, transaction)
    refreshed: list[UUID] = []

    for sibling in await sibling_transactions(session, contract_no):
        if sibling.id == transaction.id:
            continue

        outcome, _ = await evaluate_coverage_for(session, sibling, tolerance)
        latest = (await rule_engine.latest_evaluations(session, sibling.id)).get(
            (RuleId.SL_01, CheckKey.CONTRACT_QUANTITY_COVERAGE)
        )
        unchanged = (
            latest is not None
            and latest.passed == outcome.passed
            and latest.severity == outcome.severity
            and latest.actual_value == outcome.actual_value
            and latest.expected_value == outcome.expected_value
        )
        if unchanged:
            continue

        row = RuleEvaluation(
            transaction_id=sibling.id,
            rule_id=outcome.rule_id,
            check_key=outcome.check_key,
            passed=outcome.passed,
            severity=outcome.severity,
            field_name=outcome.field_name,
            expected_value=outcome.expected_value,
            actual_value=outcome.actual_value,
            message=outcome.message,
        )
        session.add(row)
        await session.flush()
        refreshed.append(sibling.id)

        # Through the same generic hook every other rule's failures go through. A sibling that
        # has just become part of an over-invoiced contract gets a real, owned case, and one that
        # has merely moved between two passing states gets nothing.
        await governance_hooks.record_hard_failures(session, sibling, [row])

        await record_audit_event(
            session,
            event_type=AuditEvent.CONTRACT_COVERAGE_REEVALUATED,
            entity_type="trade_transaction",
            entity_id=sibling.id,
            actor_id=actor_id,
            actor_type=ActorType.USER if actor_id else ActorType.SYSTEM,
            metadata={
                "batch_number": sibling.batch_number,
                "sales_contract_no": contract_no,
                "triggered_by_transaction_id": str(transaction.id),
                "triggered_by_batch_number": transaction.batch_number,
                "rule_id": outcome.rule_id,
                "check_key": outcome.check_key,
                "passed": outcome.passed,
                "actual_value": outcome.actual_value,
            },
        )

    await session.flush()
    return refreshed


async def require_sales_leg(transaction: TradeTransaction) -> SalesLeg:
    if transaction.sales_leg is None:
        raise BadRequestError(
            "This transaction has no sales leg, so there is nothing on the sell side to act on.",
            code="sales_leg_absent",
        )
    return transaction.sales_leg


def _to_decimal(val: str | None) -> Decimal | None:
    if val is None:
        return None
    try:
        return Decimal(str(val).strip().replace(",", ""))
    except Exception:
        return None


async def create_sales_transaction(
    session: AsyncSession,
    *,
    request_id: UUID | None,
    stream: str = "scrap",
    batch_number: str | None = None,
    values: dict[str, str | None],
    match_method: str = MatchMethod.NEW_BATCH.value,
    match_score: float | None = None,
    match_rationale: str | None = None,
    created_by_id: UUID | None = None,
    document: Document | None = None,
) -> TradeTransaction:
    """Create a standalone TradeTransaction carrying a SalesLeg when no purchase counterpart exists."""
    stated = (batch_number or values.get("batch_number") or "").strip()
    number = stated or await transaction_service.next_batch_number(session)
    batch_source = (
        BatchNumberSource.DOCUMENT.value if stated else BatchNumberSource.ALLOCATED.value
    )

    commodity_code, needs_review = await transaction_service.resolve_commodity(
        session, values.get("commodity_code") or values.get("commodity")
    )
    price_basis, lme = transaction_service.infer_price_basis(values)

    transaction = TradeTransaction(
        transaction_code=number,
        batch_number=number,
        batch_number_source=batch_source,
        stream=stream,
        status=TransactionStatus.MATCHED.value,
        commodity_code=commodity_code,
        extracted_commodity_value=(values.get("commodity_code") or values.get("commodity") or None),
        commodity_needs_review=needs_review,
        quantity_mt=_to_decimal(values.get("quantity") or values.get("contracted_quantity")),
        price_basis=price_basis,
        lme_percentage=lme,
        currency=(values.get("currency") or "USD").strip().upper()[:3] or "USD",
        request_id=request_id or (document.request_id if document else None),
        match_method=match_method,
        match_score=Decimal(str(round(match_score, 2))) if match_score is not None else None,
        match_rationale=match_rationale,
        created_by_id=created_by_id,
        field_overrides={},
    )
    session.add(transaction)
    await session.flush()

    customer_name = (
        values.get("customer_name")
        or values.get("buyer")
        or values.get("counterparty")
        or (document.filename if document else "Customer")
    )
    territory = (document.territory if document else None) or values.get("territory") or "other"
    sales_contract_no = (
        values.get("sales_contract_no")
        or values.get("contract_number")
        or values.get("contract_reference")
        or number
    )
    payment_condition = values.get("payment_condition") or "CAD"
    fixation_status = (
        FixationStatus.FIXED.value
        if values.get("fixation_rate") or price_basis == PriceBasis.FIXED.value
        else FixationStatus.UNFIXED.value
    )

    leg = SalesLeg(
        transaction_id=transaction.id,
        customer_name=customer_name.strip(),
        territory=territory,
        sales_contract_no=sales_contract_no.strip(),
        contracted_quantity_mt=_to_decimal(values.get("contracted_quantity") or values.get("quantity")),
        sales_invoice_number=values.get("sales_invoice_number") or values.get("invoice_number"),
        bl_reference=values.get("bl_reference") or values.get("bl_number"),
        payment_condition=payment_condition,
        customer_fixation_status=fixation_status,
        fixation_rate=_to_decimal(values.get("fixation_rate") or values.get("rate")),
        fixation_date=transaction_service._parse_date(values.get("fixation_date")),
        port_of_discharge=values.get("port_of_discharge"),
        inland_container_depot=values.get("inland_container_depot"),
        extracted_commodity_value=values.get("commodity_code") or values.get("commodity"),
    )
    session.add(leg)
    await session.flush()

    transaction.sales_leg = leg
    transaction.purchase_leg = None
    transaction.fa_leg = None
    transaction_service._mark_empty_collections(transaction)
    await session.flush()

    if document is not None:
        await matching_service.link_document(
            session,
            transaction,
            document,
            method=match_method,
            score=match_score,
            rationale=match_rationale or f"Sales document opened new batch {transaction.batch_number}.",
            actor_id=created_by_id,
        )

    matching_service._record_duplicate_outcome(
        session,
        transaction.id,
        passed=True,
        message="No earlier copy of this document exists, so it opens a new sales batch.",
        actual="no duplicate found",
    )
    await matching_service.ensure_containers(
        session, transaction, values, document=document, actor_id=created_by_id
    )

    if transaction.commodity_needs_review:
        await record_audit_event(
            session,
            event_type=transaction_service.AuditEvent.TRANSACTION_COMMODITY_UNRESOLVED,
            entity_type="trade_transaction",
            entity_id=transaction.id,
            actor_id=created_by_id,
            actor_type=ActorType.AGENT,
            metadata={
                "batch_number": transaction.batch_number,
                "extracted_value": transaction.extracted_commodity_value,
            },
        )

    await record_audit_event(
        session,
        event_type=transaction_service.AuditEvent.TRANSACTION_CREATED,
        entity_type="trade_transaction",
        entity_id=transaction.id,
        actor_id=created_by_id,
        actor_type=ActorType.USER if created_by_id else ActorType.AGENT,
        metadata={
            "batch_number": transaction.batch_number,
            "origin": "document_match",
            "document_id": str(document.id) if document else None,
            "match_method": match_method,
            "stream": stream,
            "leg": "sales",
        },
    )

    await record_audit_event(
        session,
        event_type=AuditEvent.SALES_LEG_ATTACHED,
        entity_type="trade_transaction",
        entity_id=transaction.id,
        actor_id=created_by_id,
        actor_type=ActorType.USER if created_by_id else ActorType.AGENT,
        metadata={
            "batch_number": transaction.batch_number,
            "attachment": Attachment.NO_PURCHASE_ACKNOWLEDGED,
            "customer_name": leg.customer_name,
            "territory": leg.territory,
            "sales_contract_no": leg.sales_contract_no,
            "document_id": str(document.id) if document else None,
            "standalone_sale": True,
        },
    )

    await rule_engine.run_validation(session, transaction)
    await propagate_coverage(session, transaction, actor_id=created_by_id)
    return transaction


async def on_sales_extraction_confirmed(
    session: AsyncSession,
    document: Document,
    *,
    actor_id: UUID | None = None,
) -> matching_service.MatchResult:
    """Invoked when a sales document extraction is confirmed."""
    document = await matching_service._reload(session, document.id)
    values = matching_service.document_values(document)

    if document.transaction_id is not None:
        transaction = await transaction_service.get_transaction(session, document.transaction_id)
        return matching_service.MatchResult(
            outcome=matching_service.Outcome.ALREADY_LINKED,
            message=f"Already linked to batch {transaction.batch_number}."
            if transaction
            else "Already linked to a transaction.",
            transaction_id=document.transaction_id,
            batch_number=transaction.batch_number if transaction else None,
        )

    duplicate, basis = await matching_service.find_duplicate(session, document, values)
    if duplicate is not None and duplicate.transaction_id is not None:
        transaction = await transaction_service.get_transaction(session, duplicate.transaction_id)
        await matching_service.link_document(
            session,
            transaction,
            document,
            method=MatchMethod.DUPLICATE_LINK.value,
            score=None,
            rationale=f"Duplicate of {duplicate.filename} (matched on {basis}).",
            actor_id=actor_id,
        )
        matching_service._record_duplicate_outcome(
            session,
            transaction.id,
            passed=True,
            message=f"Duplicate of {duplicate.filename}",
            actual=f"linked to {transaction.batch_number}",
        )
        await matching_service.ensure_containers(
            session, transaction, values, document=document, actor_id=actor_id
        )
        await rule_engine.run_validation(session, transaction)
        return matching_service.MatchResult(
            outcome=matching_service.Outcome.DUPLICATE_LINKED,
            message=f"Duplicate of {duplicate.filename}",
            transaction_id=transaction.id,
            batch_number=transaction.batch_number,
        )

    match = await evaluate_attachment(session, document)
    if match.outcome == matching_service.Outcome.AUTO_LINKED and match.transaction_id is not None:
        transaction = await transaction_service.get_transaction(session, match.transaction_id)
        if transaction.sales_leg is None:
            await attach_sales_leg(
                session,
                transaction,
                SalesLegInput(
                    customer_name=values.get("customer_name") or values.get("buyer") or values.get("counterparty") or "Customer",
                    territory=document.territory or "other",
                    sales_contract_no=values.get("sales_contract_no") or values.get("contract_number") or values.get("contract_reference") or transaction.batch_number,
                    payment_condition=values.get("payment_condition") or "CAD",
                    contracted_quantity_mt=_to_decimal(values.get("contracted_quantity") or values.get("quantity")),
                    sales_invoice_number=values.get("sales_invoice_number") or values.get("invoice_number"),
                    bl_reference=values.get("bl_reference") or values.get("bl_number"),
                    port_of_discharge=values.get("port_of_discharge"),
                    inland_container_depot=values.get("inland_container_depot"),
                    customer_fixation_status=FixationStatus.FIXED.value if values.get("fixation_rate") else FixationStatus.UNFIXED.value,
                    fixation_rate=_to_decimal(values.get("fixation_rate") or values.get("rate")),
                    fixation_date=transaction_service._parse_date(values.get("fixation_date")),
                    quantity_mt=_to_decimal(values.get("quantity")),
                ),
                actor_id=actor_id or UUID("00000000-0000-0000-0000-000000000000"),
                attachment=Attachment.AUTO_MATCHED,
                document=document,
                match_score=match.score,
            )
        else:
            await matching_service.link_document(
                session,
                transaction,
                document,
                method=match.method or MatchMethod.FUZZY_AUTO.value,
                score=match.score,
                rationale=match.message,
                actor_id=actor_id,
            )
            await matching_service.ensure_containers(
                session, transaction, values, document=document, actor_id=actor_id
            )
            await rule_engine.run_validation(session, transaction)
        return matching_service.MatchResult(
            outcome=matching_service.Outcome.AUTO_LINKED,
            message=match.message,
            transaction_id=transaction.id,
            batch_number=transaction.batch_number,
            score=match.score,
        )

    if match.outcome == matching_service.Outcome.SUGGESTED:
        return matching_service.MatchResult(
            outcome=matching_service.Outcome.SUGGESTED,
            message=match.message,
            transaction_id=match.transaction_id,
            batch_number=match.batch_number,
            score=match.score,
            candidates=match.candidates,
        )

    # No purchase match exists -> create standalone sales transaction!
    transaction = await create_sales_transaction(
        session,
        request_id=document.request_id,
        stream=(document.request.stream if document.request else None) or "scrap",
        batch_number=values.get("batch_number"),
        values=values,
        match_method=match.method or MatchMethod.NEW_BATCH.value,
        match_score=match.score,
        match_rationale=match.message,
        created_by_id=actor_id,
        document=document,
    )
    return matching_service.MatchResult(
        outcome=matching_service.Outcome.NEW_TRANSACTION,
        message=f"No open purchase batch matched, so batch {transaction.batch_number} was created with a sales leg.",
        transaction_id=transaction.id,
        batch_number=transaction.batch_number,
        score=match.score,
    )
