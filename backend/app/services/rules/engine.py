"""The validation orchestrator.

One entry point, one loop, no knowledge of any individual rule. Given a transaction it assembles
the context, walks the registry, calls whatever evaluators the transaction's legs make relevant,
and writes a fresh row for each outcome. Bringing the sales, shipment and FA work into it meant
registering evaluators and extending one map; the loop below is unchanged since Step 3.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import NotFoundError
from app.core.logging import get_logger
from app.db.base import utcnow
from app.models.configuration import RuleConfiguration
from app.models.enums import DocumentType, RuleSeverity, TransactionStatus
from app.models.intake import Document, ExtractedField
from app.models.transactions import RuleEvaluation, TradeTransaction
from app.services import extraction_service
from app.services.governance import hooks as governance_hooks
from app.services.rules import evaluators, registry  # noqa: F401  populates the registry
from app.services.rules.registry import (
    LEG_ATTRIBUTES,
    RuleConfigurationResolver,
    RuleContext,
    RuleOutcome,
    registered_rules,
)

logger = get_logger(__name__)


def _leg_load_options() -> tuple:
    """Eager-load every leg the registry knows about, without naming one."""
    return tuple(
        selectinload(getattr(TradeTransaction, attribute)) for attribute in LEG_ATTRIBUTES.values()
    )


# Statuses at or past which the rule engine has nothing left to decide. A transaction waiting on
# an approver, or already approved, keeps the status it has: re-validation still records what the
# checks say, but it must not drag a decided transaction back into the preparing desk's queue.
TERMINAL_STATUSES = frozenset(
    {TransactionStatus.APPROVAL_PENDING.value, TransactionStatus.APPROVED.value}
)


async def load_transaction(session: AsyncSession, transaction_id: UUID) -> TradeTransaction:
    transaction = await session.scalar(
        select(TradeTransaction)
        .where(TradeTransaction.id == transaction_id)
        # Derived from the leg map rather than listed. This file names no leg, which is the same
        # discipline the dispatch below follows and the reason a third stream cost it nothing.
        .options(*_leg_load_options())
    )
    if transaction is None:
        raise NotFoundError("Transaction not found.")
    return transaction


async def linked_documents(session: AsyncSession, transaction_id: UUID) -> list[Document]:
    return list(
        (
            await session.scalars(
                select(Document)
                .where(Document.transaction_id == transaction_id)
                .options(selectinload(Document.fields))
                .order_by(Document.created_at)
            )
        ).all()
    )


def field_map(documents: list[Document]) -> dict[UUID, dict[str, str]]:
    return {
        document.id: {
            row.field_name: row.field_value
            for row in document.fields
            if row.field_value is not None
        }
        for document in documents
    }


def contract_terms(documents: list[Document], fields: dict[UUID, dict[str, str]]) -> dict[str, str]:
    """The agreed terms, taken from the most recent contract attached to the transaction."""
    contracts = [
        document for document in documents if document.document_type == DocumentType.CONTRACT.value
    ]
    if not contracts:
        return {}
    latest = sorted(contracts, key=lambda row: row.created_at)[-1]
    return dict(fields.get(latest.id, {}))


def _territory(documents: list[Document]) -> str | None:
    return next((document.territory for document in documents if document.territory), None)


async def latest_evaluations(
    session: AsyncSession, transaction_id: UUID
) -> dict[tuple[str, str | None], RuleEvaluation]:
    """The current result per (rule, check): the newest row wins, older rows stay for the trail."""
    rows = (
        await session.scalars(
            select(RuleEvaluation)
            .where(RuleEvaluation.transaction_id == transaction_id)
            .order_by(RuleEvaluation.evaluated_at, RuleEvaluation.id)
        )
    ).all()
    current: dict[tuple[str, str | None], RuleEvaluation] = {}
    for row in rows:
        current[(row.rule_id, row.check_key)] = row
    return current


async def build_context(session: AsyncSession, transaction: TradeTransaction) -> RuleContext:
    documents = await linked_documents(session, transaction.id)
    fields = field_map(documents)
    territory = _territory(documents)

    # Read against whichever document type anchors this stream's pack rather than always the
    # invoice. Scrap's checklists hang off the invoice, as they always have; FA's hang off the
    # `fa_document` schema, whose checklist is empty because no FA document pack has been agreed.
    # Nothing is invented for FA - the rule simply reports that nothing is required.
    anchor = registry.value_document_types(transaction.stream)[0]
    checklist = await extraction_service.mandatory_documents_for(
        session, document_type=anchor, territory=territory
    )

    configuration = RuleConfigurationResolver(
        list((await session.scalars(select(RuleConfiguration))).all())
    )

    # Read generically from the leg map: nothing here names a purchase leg, so the sales and FA
    # legs added later become visible to the engine by extending that map alone.
    legs = {
        name: getattr(transaction, attribute, None) for name, attribute in LEG_ATTRIBUTES.items()
    }

    return RuleContext(
        session=session,
        transaction=transaction,
        legs=legs,
        documents=documents,
        document_fields=fields,
        contract_terms=contract_terms(documents, fields),
        mandatory_documents=checklist,
        territory=territory,
        config=configuration,
        previous=dict(await latest_evaluations(session, transaction.id)),
    )


def _carries_acknowledgement(previous: RuleEvaluation | None, outcome: RuleOutcome) -> bool:
    """Does an acknowledgement made earlier still apply to what the data now says?

    Only while the numbers behind it have not moved. An acknowledgement is a person accepting one
    specific discrepancy; if the amount changes, so does what they accepted, and the new figure
    has to be looked at again.
    """
    if previous is None or not previous.acknowledged:
        return False
    return (
        previous.expected_value == outcome.expected_value
        and previous.actual_value == outcome.actual_value
        and previous.field_name == outcome.field_name
    )


def _persist(
    session: AsyncSession,
    transaction: TradeTransaction,
    outcome: RuleOutcome,
    previous: RuleEvaluation | None,
) -> RuleEvaluation:
    carried = _carries_acknowledgement(previous, outcome)
    row = RuleEvaluation(
        transaction_id=transaction.id,
        rule_id=outcome.rule_id,
        check_key=outcome.check_key,
        passed=outcome.passed or carried,
        severity=outcome.severity,
        field_name=outcome.field_name,
        expected_value=outcome.expected_value,
        actual_value=outcome.actual_value,
        message=(
            outcome.message
            if not carried or outcome.passed
            else f"{outcome.message} Acknowledged by {previous.acknowledged_by_id or 'a user'}."
        ),
        acknowledged=carried,
        acknowledgement_reason=previous.acknowledgement_reason if carried else None,
        acknowledged_by_id=previous.acknowledged_by_id if carried else None,
        acknowledged_at=previous.acknowledged_at if carried else None,
    )
    session.add(row)
    return row


async def run_validation(
    session: AsyncSession, transaction: TradeTransaction | UUID
) -> list[RuleEvaluation]:
    """Evaluate every applicable rule and record a fresh row for each.

    Nothing is ever updated or deleted here. Re-validation after a correction adds a new row per
    check and leaves every earlier row exactly where it was, which is what makes the table a
    history rather than a status flag.
    """
    if isinstance(transaction, UUID):
        transaction = await load_transaction(session, transaction)

    context = await build_context(session, transaction)
    written: list[RuleEvaluation] = []

    for rule_id, rule in sorted(registered_rules().items()):
        # A rule that needs a leg the transaction does not carry is simply not its business.
        if rule.requires_legs and not any(
            context.leg(name) is not None for name in rule.requires_legs
        ):
            continue
        try:
            outcomes = await rule.evaluator(context)
        except Exception:
            logger.exception(
                "rule_evaluation_failed",
                extra={"rule_id": rule_id, "transaction_id": str(transaction.id)},
            )
            outcomes = [
                RuleOutcome(
                    rule_id=rule_id,
                    passed=False,
                    severity=RuleSeverity.HARD.value,
                    message=(
                        f"{rule_id} could not be evaluated. The transaction is held until it can."
                    ),
                )
            ]

        for outcome in outcomes:
            if not outcome.applicable:
                continue
            written.append(
                _persist(
                    session,
                    transaction,
                    outcome,
                    context.previous.get((outcome.rule_id, outcome.check_key)),
                )
            )

    if transaction.status not in TERMINAL_STATUSES:
        transaction.status = TransactionStatus.VALIDATION_PENDING.value
    transaction.updated_at = utcnow()
    await session.flush()

    # Every genuine hard failure becomes an owned, ageing exception case, whichever rule produced
    # it. The hook reads the rule-to-category mapping table; it is handed the rows this run wrote
    # and knows nothing about what any of them mean, which is what makes it work unchanged for
    # the rules Steps 5 and 6 bring with them.
    await governance_hooks.record_hard_failures(session, transaction, written)
    await session.flush()
    return written


def outstanding(evaluations: list[RuleEvaluation]) -> list[RuleEvaluation]:
    """The checks standing between the transaction and a submission."""
    return [row for row in evaluations if not row.passed]


async def current_results(session: AsyncSession, transaction_id: UUID) -> list[RuleEvaluation]:
    current = await latest_evaluations(session, transaction_id)
    return sorted(current.values(), key=lambda row: (row.rule_id, row.check_key or ""))


async def extracted_field_confidence(
    session: AsyncSession, document_ids: list[UUID], field_name: str
) -> float | None:
    """The confidence the machine originally reported for a field, wherever it was read.

    The reason gate on a correction is decided by what the model first scored, not by the value
    on screen, which is the same rule the document review screen applies.
    """
    if not document_ids:
        return None
    rows = (
        await session.scalars(
            select(ExtractedField).where(
                ExtractedField.document_id.in_(document_ids),
                ExtractedField.field_name == field_name,
            )
        )
    ).all()
    scores = [
        row.original_confidence if row.original_confidence is not None else row.confidence
        for row in rows
    ]
    present = [score for score in scores if score is not None]
    return min(present) if present else None
