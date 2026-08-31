"""Matching a confirmed document to the batch it belongs to.

Matching runs once per document, at the moment its extraction is confirmed or at the moment it is
attached directly to a transaction. It is a different concern from validation, which re-runs every
time the data underneath it moves: matching answers "which deal is this?", validation answers "is
this deal sound?", and conflating the two would mean re-deciding a settled link every time a
figure is corrected.

The comparison is deterministic string matching through rapidfuzz. It is not an AI call and shares
nothing with the Gemini classification and extraction services - a batch link is a fact about two
reference numbers, and it has to be reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from uuid import UUID

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import BadRequestError, ConflictError
from app.core.logging import get_logger
from app.db.base import utcnow
from app.models.configuration import RuleConfiguration
from app.models.enums import (
    BatchNumberSource,
    BusinessStream,
    DocumentType,
    InvoiceStatus,
    MatchMethod,
    RequestCategory,
    RuleSeverity,
    TransactionStatus,
)
from app.models.intake import Document
from app.models.logistics import Container
from app.models.transactions import FaLeg, PurchaseLeg, RuleEvaluation, TradeTransaction
from app.services import transaction_service
from app.services.audit_service import ActorType, record_audit_event
from app.services.rules import engine as rule_engine
from app.services.rules.catalog import CheckKey, RuleId
from app.services.rules.logistics_evaluators import (
    CONTAINER_FIELD_NAMES,
    container_numbers_in,
)
from app.services.rules.registry import LEG_FIELD_ALIASES, RuleConfigurationResolver
from app.services.rules.values import to_decimal

logger = get_logger(__name__)

# How far a quantity may sit from a candidate's before the proximity penalty reaches its maximum.
QUANTITY_SPREAD = Decimal("10")
# The most a mismatched commodity or a divergent quantity can cost a candidate's score.
COMMODITY_PENALTY = 10.0
QUANTITY_PENALTY = 10.0


class Outcome:
    AUTO_LINKED = "auto_linked"
    SUGGESTED = "suggested"
    NEW_TRANSACTION = "new_transaction"
    DUPLICATE_LINKED = "duplicate_linked"
    SUPERSEDED = "superseded"
    ALREADY_LINKED = "already_linked"
    NO_REFERENCE = "no_reference"
    NOT_APPLICABLE = "not_applicable"


@dataclass
class Candidate:
    transaction: TradeTransaction
    score: float
    contract_score: float
    supplier_score: float
    commodity_match: bool
    quantity_variance: Decimal | None

    def rationale(self) -> str:
        parts = [
            f"contract {self.contract_score:.0f}",
            f"supplier {self.supplier_score:.0f}",
            f"commodity {'match' if self.commodity_match else 'differs'}",
        ]
        if self.quantity_variance is not None:
            parts.append(f"quantity {self.quantity_variance:.2f}% apart")
        return ", ".join(parts)


@dataclass
class MatchResult:
    outcome: str
    message: str
    transaction_id: UUID | None = None
    batch_number: str | None = None
    score: float | None = None
    # How the link was arrived at, carried on the result so the caller that applies it does not
    # have to re-derive a decision the evaluation already made.
    method: str | None = None
    candidates: list[dict[str, object]] = field(default_factory=list)

    @property
    def needs_user_decision(self) -> bool:
        return self.outcome == Outcome.SUGGESTED


def document_values(document: Document) -> dict[str, str | None]:
    return {row.field_name: row.field_value for row in document.fields}


def comparable_text(values: dict[str, str | None]) -> str:
    """A stable rendering of everything a document says, for the similarity comparison."""
    return " ".join(
        f"{name}={value}" for name, value in sorted(values.items()) if (value or "").strip()
    )


def is_purchase_document(document: Document) -> bool:
    """Whether this document belongs to the purchase pipeline this step matches.

    Deal direction is the primary signal where present. A document identified as a purchase
    document triggers the purchase pipeline. Pure shipping paperwork inherits the direction
    of the deal it evidences.
    """
    if is_fa_document(document):
        return False
    if document.deal_direction == "purchase":
        return True
    if document.deal_direction == "sales" or document.deal_direction == "not_trade":
        return False

    request = document.request
    if request is None:
        return False
    if request.category == RequestCategory.PURCHASE.value:
        return True
    return request.stream == "scrap" and document.document_type in (
        DocumentType.INVOICE.value,
        DocumentType.CONTRACT.value,
    )


def is_fa_document(document: Document) -> bool:
    """Whether this document belongs to AGFZE's second business line.

    Either signal is enough, and they are the same two signals the purchase side uses: the type
    the classifier assigned, or the stream and category the desk did. Nothing about FA needed a
    second matching mechanism - it needed this predicate and the alias map the scorer already
    reads.
    """
    if document.document_type == DocumentType.FA_DOCUMENT.value:
        return True
    request = document.request
    if request is None:
        return False
    return request.category == RequestCategory.FA.value or request.stream == "fa"


def matchable_stream(document: Document) -> str | None:
    """Which stream's open transactions this document should be matched against, or None."""
    if is_fa_document(document):
        return BusinessStream.FA.value
    if is_purchase_document(document):
        return BusinessStream.SCRAP.value
    return None


async def _thresholds(session: AsyncSession, *, stream: str | None = None) -> dict[str, Decimal]:
    """Every matching threshold, read from configuration rather than written into this file.

    The stream is passed through so a stream that has been given scoped rows of its own resolves
    to them and one that has not lands on the unscoped platform default - which is the whole of
    what "FA gets its own tolerances" required of this function.
    """
    resolver = RuleConfigurationResolver(
        list((await session.scalars(select(RuleConfiguration))).all())
    )
    wanted = {
        "contract": (RuleId.BR_02, CheckKey.CONTRACT_MATCH_THRESHOLD),
        "supplier": (RuleId.BR_02, CheckKey.SUPPLIER_MATCH_THRESHOLD),
        "floor": (RuleId.BR_02, CheckKey.SUGGESTION_FLOOR),
        "duplicate": (RuleId.BR_13, CheckKey.DUPLICATE_SIMILARITY),
    }
    transaction_type = "fa" if stream == BusinessStream.FA.value else "purchase"
    resolved: dict[str, Decimal] = {}
    for name, (rule_id, check_key) in wanted.items():
        row = resolver.resolve(
            rule_id,
            check_key,
            commodity_code=None,
            transaction_type=transaction_type,
            stream=stream,
        )
        if row is None:
            raise ConflictError(
                f"Matching cannot run: {rule_id}/{check_key} has no active configuration."
            )
        resolved[name] = row.threshold_value
    return resolved


# Which alias set describes each leg class, so one scorer can read either stream's leg. The
# aliases themselves live in the rule registry and are shared with the evaluators, because a
# second place naming the same columns is a second place to forget to update.
LEG_KINDS: tuple[tuple[type, str], ...] = (
    (PurchaseLeg, "purchase"),
    (FaLeg, "fa"),
)


def leg_of(transaction: TradeTransaction) -> object | None:
    """The commercial leg this transaction carries, whichever stream it belongs to."""
    return transaction.purchase_leg or getattr(transaction, "fa_leg", None)


def leg_field(leg: object | None, concept: str) -> str | None:
    """One shared concept off a leg, through the same alias map the rule engine reads.

    A purchase leg spells its counterparty `supplier_name` and an FA leg spells it
    `counterparty_name`. That difference is data, held in one map, and it is the only thing that
    stood between the existing scorer and a second business stream.
    """
    kind = next((name for cls, name in LEG_KINDS if isinstance(leg, cls)), None)
    attribute = LEG_FIELD_ALIASES.get(kind or "", {}).get(concept)
    if attribute is None:
        return None
    value = getattr(leg, attribute, None)
    return str(value).strip() or None if value is not None else None


def score_candidate(
    *,
    transaction: TradeTransaction,
    leg: object | None,
    contract_reference: str | None,
    supplier_name: str | None,
    commodity_code: str | None,
    quantity: Decimal | None,
) -> Candidate:
    """Score one open transaction against what the document says.

    The composite is the weaker of the two identifying comparisons, not their average: a perfect
    contract reference cannot carry a supplier name that plainly belongs to somebody else. The
    commodity and quantity are corroborating evidence and only ever subtract.
    """
    leg_contract = leg_field(leg, "contract_reference")
    leg_counterparty = leg_field(leg, "counterparty")
    contract_score = (
        fuzz.partial_ratio(
            (contract_reference or "").strip().lower(),
            (leg_contract or "").strip().lower(),
        )
        if contract_reference and leg_contract
        else 0.0
    )
    supplier_score = (
        fuzz.token_sort_ratio(
            (supplier_name or "").strip().lower(),
            (leg_counterparty or "").strip().lower(),
        )
        if supplier_name and leg_counterparty
        else 0.0
    )

    commodity_match = bool(
        commodity_code
        and transaction.commodity_code
        and commodity_code.upper() == transaction.commodity_code.upper()
    )

    variance: Decimal | None = None
    quantity_deduction = 0.0
    if quantity is not None and transaction.quantity_mt:
        variance = abs(quantity - transaction.quantity_mt) / abs(transaction.quantity_mt) * 100
        penalty = Decimal(str(QUANTITY_PENALTY))
        quantity_deduction = float(min(penalty, variance / QUANTITY_SPREAD * penalty))

    score = min(contract_score, supplier_score)
    if commodity_code and transaction.commodity_code and not commodity_match:
        score -= COMMODITY_PENALTY
    score -= quantity_deduction

    return Candidate(
        transaction=transaction,
        score=max(0.0, round(float(score), 2)),
        contract_score=float(contract_score),
        supplier_score=float(supplier_score),
        commodity_match=commodity_match,
        quantity_variance=variance,
    )


async def _open_transactions(session: AsyncSession, stream: str) -> list[TradeTransaction]:
    """Transactions still open to a new document.

    A transaction already in the approval queue is excluded: attaching a document to it would
    change what the approver is being asked to sign, behind their back.
    """
    return list(
        (
            await session.scalars(
                select(TradeTransaction)
                .where(
                    TradeTransaction.stream == stream,
                    TradeTransaction.status != TransactionStatus.APPROVAL_PENDING.value,
                    TradeTransaction.closed_at.is_(None),
                )
                .options(
                    selectinload(TradeTransaction.purchase_leg),
                    selectinload(TradeTransaction.sales_leg),
                    selectinload(TradeTransaction.fa_leg),
                )
            )
        ).all()
    )


# Where a counterparty name and a contract reference can be reported, across every seeded
# schema. Read as a list rather than one field name because each document type names them
# differently and the FA schema names them differently again.
CONTRACT_REFERENCE_FIELDS: tuple[str, ...] = (
    "contract_reference",
    "contract_number",
    "transaction_reference",
)
COUNTERPARTY_FIELDS: tuple[str, ...] = ("supplier_name", "seller", "counterparty")


def first_value(values: dict[str, str | None], names: tuple[str, ...]) -> str | None:
    for name in names:
        value = (values.get(name) or "").strip()
        if value:
            return value
    return None


async def find_candidates(
    session: AsyncSession, document: Document, values: dict[str, str | None]
) -> tuple[list[Candidate], dict[str, Decimal]]:
    stream = (document.request.stream if document.request else None) or "scrap"
    thresholds = await _thresholds(session, stream=stream)

    contract_reference = first_value(values, CONTRACT_REFERENCE_FIELDS)
    supplier_name = first_value(values, COUNTERPARTY_FIELDS)
    commodity_code, _ = await transaction_service.resolve_commodity(
        session, values.get("commodity_code") or values.get("commodity")
    )
    quantity = to_decimal(values.get("quantity"))

    scored = [
        score_candidate(
            transaction=transaction,
            leg=leg_of(transaction),
            contract_reference=contract_reference,
            supplier_name=supplier_name,
            commodity_code=commodity_code,
            quantity=quantity,
        )
        for transaction in await _open_transactions(session, stream)
        if leg_of(transaction) is not None
    ]
    scored.sort(key=lambda candidate: candidate.score, reverse=True)
    return scored, thresholds


def classify_candidate(candidate: Candidate, thresholds: dict[str, Decimal]) -> str:
    """Auto, suggested or nothing at all - the three bands, and no fourth."""
    if (
        candidate.contract_score >= float(thresholds["contract"])
        and candidate.supplier_score >= float(thresholds["supplier"])
        and candidate.score >= float(thresholds["contract"])
    ):
        return Outcome.AUTO_LINKED
    if candidate.score >= float(thresholds["floor"]):
        return Outcome.SUGGESTED
    return Outcome.NEW_TRANSACTION


# --- duplicate detection --------------------------------------------------------------------


async def find_duplicate(
    session: AsyncSession, document: Document, values: dict[str, str | None]
) -> tuple[Document | None, str]:
    """The same document again, by content hash first and by extracted content second."""
    thresholds = await _thresholds(
        session, stream=(document.request.stream if document.request else None)
    )

    exact = await session.scalar(
        select(Document)
        .where(
            Document.content_hash == document.content_hash,
            Document.id != document.id,
            Document.transaction_id.is_not(None),
        )
        .options(selectinload(Document.fields))
        .order_by(Document.created_at)
    )
    if exact is not None:
        return exact, "content_hash"

    mine = comparable_text(values)
    if not mine:
        return None, ""

    others = (
        await session.scalars(
            select(Document)
            .where(Document.id != document.id, Document.transaction_id.is_not(None))
            .options(selectinload(Document.fields))
        )
    ).all()
    for other in others:
        if other.document_type != document.document_type:
            continue
        score = fuzz.token_set_ratio(mine, comparable_text(document_values(other)))
        if score >= float(thresholds["duplicate"]):
            return other, "extracted_content"
    return None, ""


def _record_duplicate_outcome(
    session: AsyncSession,
    transaction_id: UUID,
    *,
    passed: bool,
    message: str,
    actual: str | None,
) -> RuleEvaluation:
    """BR-13's own row, written at the moment the link is made.

    A duplicate that quietly linked and left no trace would be a side-channel; recording it as a
    rule evaluation puts it in the same place as every other check an auditor reads.
    """
    row = RuleEvaluation(
        transaction_id=transaction_id,
        rule_id=RuleId.BR_13,
        check_key=CheckKey.DUPLICATE_CONTENT,
        passed=passed,
        severity=RuleSeverity.HARD.value,
        field_name="content_hash",
        expected_value="link to the transaction that already holds this document",
        actual_value=actual,
        message=message,
    )
    session.add(row)
    return row


# --- supersession ---------------------------------------------------------------------------


async def apply_supersession(
    session: AsyncSession,
    transaction: TradeTransaction,
    document: Document,
    values: dict[str, str | None],
    *,
    actor_id: UUID | None,
) -> bool:
    """A final invoice replaces the provisional figures on the leg it belongs to.

    The provisional document and everything extracted from it stay exactly where they are, so
    both states remain inspectable in the transaction's document history. What changes is the
    leg's current position, and the audit entry is what records that a supersession happened.
    """
    leg = transaction.purchase_leg
    if leg is None or document.document_type != DocumentType.INVOICE.value:
        return False

    incoming_status = transaction_service.infer_invoice_status(values, document)
    if incoming_status != InvoiceStatus.FINAL.value:
        return False
    if leg.invoice_status == InvoiceStatus.FINAL.value:
        return False

    previous = {
        "invoice_status": leg.invoice_status,
        "amount": str(leg.amount) if leg.amount is not None else None,
        "rate": str(leg.rate) if leg.rate is not None else None,
        "supplier_invoice_number": leg.supplier_invoice_number,
    }

    leg.invoice_status = InvoiceStatus.FINAL.value
    amount = to_decimal(values.get("amount"))
    rate = to_decimal(values.get("rate"))
    if amount is not None:
        leg.amount = amount
    if rate is not None:
        leg.rate = rate
    if values.get("invoice_number"):
        leg.supplier_invoice_number = values["invoice_number"]
    leg.updated_at = utcnow()

    transaction.match_method = MatchMethod.SUPERSESSION.value
    transaction.match_rationale = (
        f"Final invoice {leg.supplier_invoice_number or document.filename} superseded the "
        "provisional figures on this batch."
    )
    transaction.updated_at = utcnow()

    await record_audit_event(
        session,
        event_type=transaction_service.AuditEvent.TRANSACTION_SUPERSEDED,
        entity_type="trade_transaction",
        entity_id=transaction.id,
        actor_id=actor_id,
        actor_type=ActorType.USER if actor_id else ActorType.AGENT,
        metadata={
            "batch_number": transaction.batch_number,
            "document_id": str(document.id),
            "previous": previous,
            "current": {
                "invoice_status": leg.invoice_status,
                "amount": str(leg.amount) if leg.amount is not None else None,
                "rate": str(leg.rate) if leg.rate is not None else None,
                "supplier_invoice_number": leg.supplier_invoice_number,
            },
        },
    )
    return True


# --- linking ----------------------------------------------------------------------------------


async def link_document(
    session: AsyncSession,
    transaction: TradeTransaction,
    document: Document,
    *,
    method: str,
    score: float | None,
    rationale: str,
    actor_id: UUID | None,
) -> None:
    document.transaction_id = transaction.id
    # The most recent matching decision, not the first: the panel asks how this transaction was
    # matched, and the full sequence of links is on the transaction's audit trail behind it.
    transaction.match_method = method
    if score is not None:
        transaction.match_score = Decimal(str(round(score, 2)))
    transaction.match_rationale = rationale
    transaction.updated_at = utcnow()
    await session.flush()

    await record_audit_event(
        session,
        event_type=transaction_service.AuditEvent.TRANSACTION_DOCUMENT_LINKED,
        entity_type="trade_transaction",
        entity_id=transaction.id,
        actor_id=actor_id,
        actor_type=ActorType.USER if actor_id else ActorType.AGENT,
        metadata={
            "document_id": str(document.id),
            "document_type": document.document_type,
            "batch_number": transaction.batch_number,
            "method": method,
            "score": score,
            "rationale": rationale,
        },
    )


async def adopt_stated_batch_number(
    session: AsyncSession,
    transaction: TradeTransaction,
    values: dict[str, str | None],
    *,
    actor_id: UUID | None,
) -> str | None:
    """Take the counterparty's own batch reference over a placeholder the platform allocated.

    A pack does not arrive in a helpful order. A purchase contract quotes a contract number and
    no batch, so the transaction it opens is given a number off the platform's sequence to have
    an identity at all. The invoice, the packing list and the certificates that follow all quote
    the real batch - and before this existed, the invoice would fuzzy-match onto the placeholder
    and leave it in place, and then the packing list, matching strictly on batch number, would
    find nothing and open a *second* transaction for the same physical container.

    That is the split BR-13 exists to prevent, and BR-03 caught it downstream every time: one
    container on two batches, a hard block, and a deal that could not be submitted at all.

    Adoption is deliberately narrow. It happens only where the transaction's number is a
    placeholder, only where a document states one, and never where another transaction already
    holds the stated reference - that case is a genuine collision for a person to look at, not
    something to resolve by moving a number. `transaction_code` is left exactly as it was: it is
    the platform's own permanent handle on this record, and rewriting it would change the
    identity of a row that other systems have already been told about.

    Returns the adopted number, or None where nothing was adopted.
    """
    stated = (values.get("batch_number") or "").strip()
    if not stated or stated == transaction.batch_number:
        return None
    if transaction.batch_number_source != BatchNumberSource.ALLOCATED.value:
        return None

    clash = await session.scalar(
        select(TradeTransaction.id)
        .where(TradeTransaction.batch_number == stated)
        .where(TradeTransaction.id != transaction.id)
    )
    if clash is not None:
        return None

    placeholder = transaction.batch_number
    transaction.batch_number = stated[:32]
    transaction.batch_number_source = BatchNumberSource.DOCUMENT.value
    transaction.updated_at = utcnow()
    await session.flush()

    await record_audit_event(
        session,
        event_type=transaction_service.AuditEvent.TRANSACTION_BATCH_NUMBER_ADOPTED,
        entity_type="trade_transaction",
        entity_id=transaction.id,
        actor_id=actor_id,
        actor_type=ActorType.USER if actor_id else ActorType.AGENT,
        metadata={
            "allocated_batch_number": placeholder,
            "adopted_batch_number": transaction.batch_number,
            "transaction_code": transaction.transaction_code,
        },
    )
    return transaction.batch_number


def _enrich_leg(transaction: TradeTransaction, values: dict[str, str | None]) -> None:
    """Fill in what the leg does not know yet, without overwriting what it does.

    This is the mechanism that has been implicit since the purchase leg was built and is stated
    plainly here: a leg's columns are populated from the confirmed document's already-extracted,
    confidence-and-evidence-tracked field values. A later document adds detail; it never silently
    rewrites a figure a person or an earlier document already established. Replacing a value is
    what supersession and an explicit correction are for.

    Which leg is filled follows the leg the transaction carries. The FA branch delegates to
    `commit_fa_values`, which applies the same "never overwrite" discipline and additionally
    routes anything without a named column into the leg's configured extra fields.
    """
    if transaction.fa_leg is not None:
        transaction_service.commit_fa_values(transaction, transaction.fa_leg, values)
        return

    leg = transaction.purchase_leg
    if leg is None:
        return
    mapping = {
        "supplier_name": values.get("supplier_name") or values.get("seller"),
        "supplier_invoice_number": values.get("invoice_number"),
        "contract_number": values.get("contract_number") or values.get("contract_reference"),
        "port_of_loading": values.get("port_of_loading"),
    }
    for attribute, value in mapping.items():
        if (value or "").strip() and not getattr(leg, attribute, None):
            setattr(leg, attribute, value.strip())

    if leg.amount is None:
        leg.amount = to_decimal(values.get("amount"))
    if leg.rate is None:
        leg.rate = to_decimal(values.get("rate"))
    if transaction.quantity_mt is None:
        transaction.quantity_mt = to_decimal(values.get("quantity"))


# --- containers, as a side effect of the link that already happens -----------------------------


def extracted_container_numbers(values: dict[str, str | None]) -> list[str]:
    """Every container number a document's extraction reported, normalised and de-duplicated."""
    numbers: list[str] = []
    for field_name in CONTAINER_FIELD_NAMES:
        numbers.extend(container_numbers_in(values.get(field_name)))
    return list(dict.fromkeys(numbers))


async def ensure_containers(
    session: AsyncSession,
    transaction: TradeTransaction,
    values: dict[str, str | None],
    *,
    document: Document | None,
    actor_id: UUID | None,
) -> list[Container]:
    """Create a `Container` for every new container number this document quotes.

    Deliberately a side effect of matching rather than a mechanism of its own. The moment a
    document is tied to a batch is the moment the platform learns which boxes that batch is in,
    and a separate container-capture step would be a second thing to remember to run.

    Idempotent, and quiet about it: a number this transaction already has produces nothing. A
    number some *other* transaction already has still produces a row here - the container really
    is quoted on this document - and BR-03 is what says that is a problem, on the validation
    panel where a person can see both sides of it.
    """
    numbers = extracted_container_numbers(values)
    if not numbers:
        return []

    existing = {
        row.container_number
        for row in (
            await session.scalars(
                select(Container).where(Container.transaction_id == transaction.id)
            )
        ).all()
    }
    seal = (values.get("seal_number") or "").strip() or None
    created: list[Container] = []
    for number in numbers:
        if number in existing:
            continue
        container = Container(
            transaction_id=transaction.id,
            container_number=number,
            seal_number=seal if len(numbers) == 1 else None,
        )
        session.add(container)
        created.append(container)
        existing.add(number)

    if not created:
        return []

    await session.flush()
    await record_audit_event(
        session,
        event_type=transaction_service.AuditEvent.CONTAINER_RECORDED,
        entity_type="trade_transaction",
        entity_id=transaction.id,
        actor_id=actor_id,
        actor_type=ActorType.USER if actor_id else ActorType.AGENT,
        metadata={
            "batch_number": transaction.batch_number,
            "container_numbers": [row.container_number for row in created],
            "document_id": str(document.id) if document is not None else None,
        },
    )
    return created


# --- the entry points -------------------------------------------------------------------------


async def _reload(session: AsyncSession, document_id: UUID) -> Document:
    document = await session.scalar(
        select(Document)
        .where(Document.id == document_id)
        .options(selectinload(Document.fields), selectinload(Document.request))
    )
    if document is None:
        raise BadRequestError("The document no longer exists.")
    return document


async def evaluate_match(session: AsyncSession, document: Document) -> MatchResult:
    """Work out what would happen to this document, without changing anything.

    The same function answers the confirm-time decision and the screen's read of a pending
    suggestion, so what a person is shown is always what the server would actually do.
    """
    stream = matchable_stream(document)
    if stream is None:
        return MatchResult(
            outcome=Outcome.NOT_APPLICABLE,
            message=(
                "This document is on neither the purchase nor the FA pipeline, so no batch "
                "matching applies."
            ),
        )

    if document.transaction_id is not None:
        transaction = await session.get(TradeTransaction, document.transaction_id)
        return MatchResult(
            outcome=Outcome.ALREADY_LINKED,
            message=f"Already linked to batch {transaction.batch_number}."
            if transaction
            else "Already linked to a transaction.",
            transaction_id=document.transaction_id,
            batch_number=transaction.batch_number if transaction else None,
        )

    values = document_values(document)

    duplicate, basis = await find_duplicate(session, document, values)
    if duplicate is not None and duplicate.transaction_id is not None:
        transaction = await session.get(TradeTransaction, duplicate.transaction_id)
        return MatchResult(
            outcome=Outcome.DUPLICATE_LINKED,
            message=(
                f"This is the same document as {duplicate.filename} "
                f"(matched on {basis.replace('_', ' ')}). It links to batch "
                f"{transaction.batch_number if transaction else 'the existing transaction'} "
                "rather than starting a second one."
            ),
            transaction_id=duplicate.transaction_id,
            batch_number=transaction.batch_number if transaction else None,
        )

    references = {
        "batch_number": values.get("batch_number"),
        "contract_reference": first_value(values, CONTRACT_REFERENCE_FIELDS),
        "invoice_number": values.get("invoice_number"),
    }
    if not any((value or "").strip() for value in references.values()):
        return MatchResult(
            outcome=Outcome.NO_REFERENCE,
            message=(
                "BR-02: no invoice, contract or batch reference was extracted, so there is "
                "nothing to match this document on. Correct the extracted references and confirm "
                "again."
            ),
        )

    batch = (values.get("batch_number") or "").strip()
    if batch:
        exact = await session.scalar(
            select(TradeTransaction)
            .where(TradeTransaction.batch_number == batch)
            .options(
                selectinload(TradeTransaction.purchase_leg),
                selectinload(TradeTransaction.fa_leg),
            )
        )
        if exact is not None:
            return MatchResult(
                outcome=Outcome.AUTO_LINKED,
                message=f"The document quotes batch {batch}, which is an exact match.",
                transaction_id=exact.id,
                batch_number=exact.batch_number,
                score=100.0,
                method=MatchMethod.BATCH_NUMBER.value,
            )

    candidates, thresholds = await find_candidates(session, document, values)
    best = candidates[0] if candidates else None
    band = classify_candidate(best, thresholds) if best else Outcome.NEW_TRANSACTION

    if best is not None and band == Outcome.AUTO_LINKED:
        return MatchResult(
            outcome=Outcome.AUTO_LINKED,
            message=(
                f"Matched to batch {best.transaction.batch_number} at {best.score:.0f} "
                f"({best.rationale()})."
            ),
            transaction_id=best.transaction.id,
            batch_number=best.transaction.batch_number,
            score=best.score,
            method=MatchMethod.FUZZY_AUTO.value,
        )

    if best is not None and band == Outcome.SUGGESTED:
        offered = [
            candidate for candidate in candidates if candidate.score >= float(thresholds["floor"])
        ][:5]
        return MatchResult(
            outcome=Outcome.SUGGESTED,
            message=(
                f"Batch {best.transaction.batch_number} looks like the same deal at "
                f"{best.score:.0f}, which is below the auto-link threshold. Confirm it or reject "
                "it before anything is created."
            ),
            transaction_id=best.transaction.id,
            batch_number=best.transaction.batch_number,
            score=best.score,
            candidates=[
                {
                    "transaction_id": str(candidate.transaction.id),
                    "batch_number": candidate.transaction.batch_number,
                    "supplier_name": leg_field(leg_of(candidate.transaction), "counterparty"),
                    "contract_number": leg_field(
                        leg_of(candidate.transaction), "contract_reference"
                    ),
                    "score": candidate.score,
                    "rationale": candidate.rationale(),
                }
                for candidate in offered
            ],
        )

    return MatchResult(
        outcome=Outcome.NEW_TRANSACTION,
        message=(
            "Nothing open resembles this document closely enough to link to, so it starts a new "
            "batch."
        ),
        score=best.score if best else None,
        method=MatchMethod.NEW_BATCH.value,
    )


async def apply_match(
    session: AsyncSession,
    document: Document,
    result: MatchResult,
    *,
    actor_id: UUID | None,
    method_override: str | None = None,
) -> MatchResult:
    """Carry out a decided match. A suggestion is never applied without a person resolving it."""
    values = document_values(document)

    if result.outcome == Outcome.SUGGESTED:
        return result

    if result.outcome in (Outcome.NOT_APPLICABLE, Outcome.NO_REFERENCE, Outcome.ALREADY_LINKED):
        if result.outcome == Outcome.ALREADY_LINKED and result.transaction_id:
            transaction = await transaction_service.get_transaction(session, result.transaction_id)
            await adopt_stated_batch_number(session, transaction, values, actor_id=actor_id)
            superseded = await apply_supersession(
                session, transaction, document, values, actor_id=actor_id
            )
            _enrich_leg(transaction, values)
            await ensure_containers(
                session, transaction, values, document=document, actor_id=actor_id
            )
            await rule_engine.run_validation(session, transaction)
            if superseded:
                return MatchResult(
                    outcome=Outcome.SUPERSEDED,
                    message=(
                        f"The final invoice replaced the provisional figures on batch "
                        f"{transaction.batch_number}."
                    ),
                    transaction_id=transaction.id,
                    batch_number=transaction.batch_number,
                )
        return result

    if result.outcome == Outcome.DUPLICATE_LINKED and result.transaction_id is not None:
        transaction = await transaction_service.get_transaction(session, result.transaction_id)
        await link_document(
            session,
            transaction,
            document,
            method=MatchMethod.DUPLICATE_LINK.value,
            score=None,
            rationale=result.message,
            actor_id=actor_id,
        )
        await adopt_stated_batch_number(session, transaction, values, actor_id=actor_id)
        _record_duplicate_outcome(
            session,
            transaction.id,
            passed=True,
            message=result.message,
            actual=f"linked to {transaction.batch_number}",
        )
        await ensure_containers(session, transaction, values, document=document, actor_id=actor_id)
        await rule_engine.run_validation(session, transaction)
        return result

    if result.outcome == Outcome.AUTO_LINKED and result.transaction_id is not None:
        transaction = await transaction_service.get_transaction(session, result.transaction_id)
        await link_document(
            session,
            transaction,
            document,
            method=method_override or result.method or MatchMethod.FUZZY_AUTO.value,
            score=result.score,
            rationale=result.message,
            actor_id=actor_id,
        )
        await adopt_stated_batch_number(session, transaction, values, actor_id=actor_id)
        superseded = await apply_supersession(
            session, transaction, document, values, actor_id=actor_id
        )
        _enrich_leg(transaction, values)
        await ensure_containers(session, transaction, values, document=document, actor_id=actor_id)
        await rule_engine.run_validation(session, transaction)
        if superseded:
            return MatchResult(
                outcome=Outcome.SUPERSEDED,
                message=(
                    f"Matched to batch {transaction.batch_number}, where the final invoice "
                    "replaced the provisional figures."
                ),
                transaction_id=transaction.id,
                batch_number=transaction.batch_number,
                score=result.score,
            )
        return MatchResult(
            outcome=Outcome.AUTO_LINKED,
            message=result.message,
            transaction_id=transaction.id,
            batch_number=transaction.batch_number,
            score=result.score,
        )

    method = method_override or result.method or MatchMethod.NEW_BATCH.value
    transaction = await transaction_service.create_transaction(
        session,
        request_id=document.request_id,
        stream=(document.request.stream if document.request else None) or "scrap",
        batch_number=values.get("batch_number"),
        values=values,
        match_method=method,
        match_score=result.score,
        match_rationale=result.message,
        created_by_id=actor_id,
        document=document,
    )
    await link_document(
        session,
        transaction,
        document,
        method=method,
        score=result.score,
        rationale=result.message,
        actor_id=actor_id,
    )
    _record_duplicate_outcome(
        session,
        transaction.id,
        passed=True,
        message="No earlier copy of this document exists, so it opens a new batch.",
        actual="no duplicate found",
    )
    await ensure_containers(session, transaction, values, document=document, actor_id=actor_id)
    if transaction.commodity_needs_review:
        await record_audit_event(
            session,
            event_type=transaction_service.AuditEvent.TRANSACTION_COMMODITY_UNRESOLVED,
            entity_type="trade_transaction",
            entity_id=transaction.id,
            actor_id=actor_id,
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
        actor_id=actor_id,
        actor_type=ActorType.USER if actor_id else ActorType.AGENT,
        metadata={
            "batch_number": transaction.batch_number,
            "origin": "document_match",
            "document_id": str(document.id),
            "match_method": transaction.match_method,
        },
    )
    await rule_engine.run_validation(session, transaction)
    return MatchResult(
        outcome=Outcome.NEW_TRANSACTION,
        message=(
            f"No open batch matched, so batch {transaction.batch_number} was created for this "
            "document."
        ),
        transaction_id=transaction.id,
        batch_number=transaction.batch_number,
        score=result.score,
    )


async def on_extraction_confirmed(
    session: AsyncSession, document: Document, *, actor_id: UUID | None = None
) -> MatchResult:
    """The seam Step 2 left open, wired up.

    Confirming an extraction is the event matching subscribes to. A document confirmed straight
    onto a known transaction takes the same path - the search simply finds the link that is
    already there - so an emailed document and a directly attached one are never special-cased
    against each other.
    """
    document = await _reload(session, document.id)
    result = await evaluate_match(session, document)
    applied = await apply_match(session, document, result, actor_id=actor_id)
    await session.commit()
    return applied


async def resolve_suggestion(
    session: AsyncSession,
    document: Document,
    *,
    decision: str,
    transaction_id: UUID | None,
    actor_id: UUID,
) -> MatchResult:
    """Settle an ambiguous match before anything is created.

    This is deliberately the only moment ambiguity can be resolved. There is no merge operation
    anywhere in the platform, because two transactions that should have been one are a far harder
    problem than one decision taken at the right time.
    """
    document = await _reload(session, document.id)
    if document.transaction_id is not None:
        raise ConflictError("This document is already linked to a transaction.")

    current = await evaluate_match(session, document)
    if current.outcome != Outcome.SUGGESTED:
        raise ConflictError(
            "There is no ambiguous match outstanding for this document; re-confirm it instead."
        )

    if decision == "reject":
        result = await apply_match(
            session,
            document,
            MatchResult(
                outcome=Outcome.NEW_TRANSACTION,
                message=(
                    "The suggested batch was rejected by the preparing user, so a new batch was "
                    "opened for this document."
                ),
                score=current.score,
                method=MatchMethod.NEW_BATCH.value,
            ),
            actor_id=actor_id,
        )
    else:
        offered = {candidate["transaction_id"] for candidate in current.candidates}
        if transaction_id is None or str(transaction_id) not in offered:
            raise BadRequestError(
                "Confirm one of the batches that was actually suggested for this document.",
                code="candidate_not_offered",
            )
        target = await transaction_service.get_transaction(session, transaction_id)
        result = await apply_match(
            session,
            document,
            MatchResult(
                outcome=Outcome.AUTO_LINKED,
                message=(
                    f"The preparing user confirmed batch {target.batch_number} as the same deal "
                    f"(scored {current.score:.0f})."
                ),
                transaction_id=target.id,
                batch_number=target.batch_number,
                score=current.score,
                method=MatchMethod.SUGGESTION_CONFIRMED.value,
            ),
            actor_id=actor_id,
            method_override=MatchMethod.SUGGESTION_CONFIRMED.value,
        )

    await record_audit_event(
        session,
        event_type=transaction_service.AuditEvent.TRANSACTION_MATCHED,
        entity_type="document",
        entity_id=document.id,
        actor_id=actor_id,
        actor_type=ActorType.USER,
        metadata={
            "decision": decision,
            "suggested_transaction_id": str(current.transaction_id)
            if current.transaction_id
            else None,
            "suggested_score": current.score,
            "resulting_transaction_id": str(result.transaction_id)
            if result.transaction_id
            else None,
            "outcome": result.outcome,
        },
    )
    await session.commit()
    return result
