"""Matching: exact batch links, the fuzzy bands, supersession, duplicates and batch numbering.

The scoring here is deterministic by design, so these tests assert real rapidfuzz scores against
real supplier names rather than stubbing the comparison out. Nothing in this module touches an
AI service, and nothing in the code under test does either.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.models.enums import (
    BusinessStream,
    DocumentType,
    InvoiceStatus,
    MatchMethod,
    TransactionStatus,
)
from app.models.intake import Document
from app.models.transactions import PurchaseLeg, RuleEvaluation, TradeTransaction
from app.services import matching_service, transaction_service
from app.services.rules.catalog import CheckKey, RuleId
from tests.utils.transactions import (
    CONTRACT,
    SUPPLIER,
    invoice_values,
    make_document,
    make_request,
    make_transaction,
)

pytestmark = pytest.mark.usefixtures("patched_jwks")


async def _confirm(session: AsyncSession, document: Document):
    """Run the confirm-time path without the HTTP layer in the way."""
    return await matching_service.on_extraction_confirmed(session, document)


# --- exact batch matching -------------------------------------------------------------------


async def test_a_quoted_batch_number_links_to_that_exact_transaction(
    db_session: AsyncSession,
) -> None:
    existing = await make_transaction(db_session, batch_number="I2626-642")
    request = await make_request(db_session)
    document = await make_document(
        db_session,
        request,
        values=invoice_values(batch_number="I2626-642", invoice_number="INV-2026-0777"),
    )
    await db_session.commit()

    result = await _confirm(db_session, document)

    assert result.outcome == matching_service.Outcome.AUTO_LINKED
    assert result.transaction_id == existing.id
    refreshed = await db_session.get(Document, document.id)
    assert refreshed.transaction_id == existing.id
    # Exactly one transaction: an exact batch quote never opens a second one.
    assert await db_session.scalar(select(func.count(TradeTransaction.id))) == 1


# --- the fuzzy bands ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("supplier_on_document", "expected_outcome"),
    [
        # token_sort_ratio 98.11 - at or above the configured 90, so it links on its own.
        ("Emirates Metals Trading LLC", matching_service.Outcome.AUTO_LINKED),
        # 85.71 - inside the 80-to-threshold suggestion band, so a person decides.
        ("Emirates Metal Trading Limited", matching_service.Outcome.SUGGESTED),
        # 76.60 - below the 80 floor, so nothing is offered and a new batch is opened.
        ("Emirates Metal Co LLC", matching_service.Outcome.NEW_TRANSACTION),
    ],
)
async def test_supplier_similarity_decides_which_band_a_candidate_lands_in(
    db_session: AsyncSession, supplier_on_document: str, expected_outcome: str
) -> None:
    await make_transaction(db_session, batch_number="I2626-1")
    request = await make_request(db_session)
    document = await make_document(
        db_session,
        request,
        values=invoice_values(supplier_name=supplier_on_document, invoice_number="INV-2026-0888"),
    )
    await db_session.commit()

    outcome = await matching_service.evaluate_match(db_session, document)

    assert outcome.outcome == expected_outcome


async def test_a_suggested_match_creates_nothing_until_a_person_resolves_it(
    db_session: AsyncSession,
) -> None:
    await make_transaction(db_session, batch_number="I2626-1")
    request = await make_request(db_session)
    document = await make_document(
        db_session,
        request,
        values=invoice_values(
            supplier_name="Emirates Metal Trading Limited", invoice_number="INV-2026-0888"
        ),
    )
    await db_session.commit()

    result = await _confirm(db_session, document)

    assert result.outcome == matching_service.Outcome.SUGGESTED
    assert result.needs_user_decision is True
    assert result.candidates
    refreshed = await db_session.get(Document, document.id)
    assert refreshed.transaction_id is None
    # No competing transaction was opened while the question was outstanding.
    assert await db_session.scalar(select(func.count(TradeTransaction.id))) == 1


async def test_confirming_a_suggestion_links_it_and_records_the_decision(
    db_session: AsyncSession, signed_in
) -> None:
    user, _ = await signed_in(
        "0a1b2c3d-0000-4000-8000-00000000b001",
        "purchase.matcher@agfze.ae",
        "Marco Bellini",
        ["purchase_user"],
    )
    existing = await make_transaction(db_session, batch_number="I2626-1")
    request = await make_request(db_session)
    document = await make_document(
        db_session,
        request,
        values=invoice_values(
            supplier_name="Emirates Metal Trading Limited", invoice_number="INV-2026-0888"
        ),
    )
    await db_session.commit()

    result = await matching_service.resolve_suggestion(
        db_session,
        document,
        decision="confirm",
        transaction_id=existing.id,
        actor_id=user.id,
    )

    assert result.transaction_id == existing.id
    refreshed = await db_session.get(Document, document.id)
    assert refreshed.transaction_id == existing.id
    reloaded = await db_session.get(TradeTransaction, existing.id)
    assert reloaded.match_method == MatchMethod.SUGGESTION_CONFIRMED.value


async def test_rejecting_a_suggestion_opens_a_new_batch_instead(
    db_session: AsyncSession, signed_in
) -> None:
    user, _ = await signed_in(
        "0a1b2c3d-0000-4000-8000-00000000b002",
        "purchase.rejector@agfze.ae",
        "Marco Bellini",
        ["purchase_user"],
    )
    await make_transaction(db_session, batch_number="I2626-1")
    request = await make_request(db_session)
    document = await make_document(
        db_session,
        request,
        values=invoice_values(
            supplier_name="Emirates Metal Trading Limited", invoice_number="INV-2026-0888"
        ),
    )
    await db_session.commit()

    result = await matching_service.resolve_suggestion(
        db_session, document, decision="reject", transaction_id=None, actor_id=user.id
    )

    assert result.outcome == matching_service.Outcome.NEW_TRANSACTION
    assert await db_session.scalar(select(func.count(TradeTransaction.id))) == 2


async def test_a_candidate_that_was_never_offered_cannot_be_confirmed(
    db_session: AsyncSession, signed_in
) -> None:
    user, _ = await signed_in(
        "0a1b2c3d-0000-4000-8000-00000000b003",
        "purchase.sneaky@agfze.ae",
        "Marco Bellini",
        ["purchase_user"],
    )
    await make_transaction(db_session, batch_number="I2626-1")
    unrelated = await make_transaction(
        db_session,
        batch_number="I2626-9",
        supplier_name="Gulf Recycling FZC",
        contract_number="ZZZ-999",
        invoice_number="INV-9",
    )
    request = await make_request(db_session)
    document = await make_document(
        db_session,
        request,
        values=invoice_values(
            supplier_name="Emirates Metal Trading Limited", invoice_number="INV-2026-0888"
        ),
    )
    await db_session.commit()

    from app.core.errors import BadRequestError

    with pytest.raises(BadRequestError):
        await matching_service.resolve_suggestion(
            db_session,
            document,
            decision="confirm",
            transaction_id=unrelated.id,
            actor_id=user.id,
        )


# --- supersession ---------------------------------------------------------------------------


async def test_a_final_invoice_supersedes_the_provisional_leg_rather_than_duplicating_it(
    db_session: AsyncSession,
) -> None:
    existing = await make_transaction(
        db_session,
        batch_number="I2626-642",
        invoice_status=InvoiceStatus.PROVISIONAL.value,
        amount="199062.50",
        rate="8125.00",
    )
    request = await make_request(db_session)
    provisional = await make_document(
        db_session,
        request,
        values=invoice_values(batch_number="I2626-642"),
        filename="provisional-invoice.pdf",
        transaction_id=existing.id,
    )
    final = await make_document(
        db_session,
        request,
        values=invoice_values(
            batch_number="I2626-642",
            invoice_status="final",
            invoice_number="INV-2026-0451-F",
            rate="8210.00",
            amount="201145.00",
        ),
        filename="final-invoice.pdf",
    )
    await db_session.commit()

    result = await _confirm(db_session, final)

    assert result.outcome == matching_service.Outcome.SUPERSEDED
    assert await db_session.scalar(select(func.count(TradeTransaction.id))) == 1
    assert await db_session.scalar(select(func.count(PurchaseLeg.id))) == 1

    leg = await db_session.scalar(
        select(PurchaseLeg).where(PurchaseLeg.transaction_id == existing.id)
    )
    await db_session.refresh(leg)
    assert leg.invoice_status == InvoiceStatus.FINAL.value
    assert leg.rate == Decimal("8210.0000")
    assert leg.amount == Decimal("201145.0000")

    # The provisional document and everything read off it stay exactly where they were, so both
    # states remain inspectable in the transaction's history.
    kept = await db_session.get(Document, provisional.id)
    assert kept is not None
    values = {row.field_name: row.field_value for row in kept.fields}
    assert values["rate"] == "8125.00"


async def test_supersession_applies_to_a_manually_registered_transaction_too(
    db_session: AsyncSession, signed_in
) -> None:
    user, _ = await signed_in(
        "0a1b2c3d-0000-4000-8000-00000000b004",
        "purchase.manual@agfze.ae",
        "Marco Bellini",
        ["purchase_user"],
    )
    manual = await transaction_service.create_manual_transaction(
        db_session,
        user=user,
        stream="scrap",
        batch_number=None,
        values={
            "supplier_name": SUPPLIER,
            "contract_number": CONTRACT,
            "invoice_number": "INV-2026-0451",
            "commodity_code": "CU",
            "quantity": "24.500",
            "rate": "8125.00",
            "amount": "199062.50",
            "currency": "USD",
        },
    )
    await db_session.commit()

    request = await make_request(db_session)
    final = await make_document(
        db_session,
        request,
        values=invoice_values(
            batch_number=manual.batch_number,
            invoice_status="final",
            rate="8210.00",
            amount="201145.00",
        ),
        filename="final-invoice.pdf",
    )
    await db_session.commit()

    result = await _confirm(db_session, final)

    # Nothing special-cases the origin: a manually registered batch supersedes exactly as an
    # email-triggered one does.
    assert result.outcome == matching_service.Outcome.SUPERSEDED
    assert await db_session.scalar(select(func.count(TradeTransaction.id))) == 1


# --- duplicates -------------------------------------------------------------------------------


async def test_the_same_bytes_link_to_the_existing_transaction_and_record_br13(
    db_session: AsyncSession,
) -> None:
    shared_hash = "b" * 64
    existing = await make_transaction(db_session, batch_number="I2626-1")
    request = await make_request(db_session)
    await make_document(
        db_session,
        request,
        values=invoice_values(),
        content_hash=shared_hash,
        transaction_id=existing.id,
    )
    repeat = await make_document(
        db_session,
        request,
        values=invoice_values(),
        content_hash=shared_hash,
        filename="invoice-again.pdf",
    )
    await db_session.commit()

    result = await _confirm(db_session, repeat)

    assert result.outcome == matching_service.Outcome.DUPLICATE_LINKED
    assert result.transaction_id == existing.id
    assert await db_session.scalar(select(func.count(TradeTransaction.id))) == 1

    linked = await db_session.get(Document, repeat.id)
    assert linked.transaction_id == existing.id

    # Recorded as its own rule evaluation rather than as a silent side effect.
    duplicate_rows = (
        await db_session.scalars(
            select(RuleEvaluation).where(
                RuleEvaluation.transaction_id == existing.id,
                RuleEvaluation.rule_id == RuleId.BR_13,
                RuleEvaluation.check_key == CheckKey.DUPLICATE_CONTENT,
            )
        )
    ).all()
    assert duplicate_rows
    assert any(
        "links to batch" in row.message or "same document" in row.message for row in duplicate_rows
    )


async def test_a_document_with_no_business_reference_is_not_matched_at_all(
    db_session: AsyncSession,
) -> None:
    request = await make_request(db_session)
    document = await make_document(
        db_session,
        request,
        values=invoice_values(invoice_number=None, contract_reference=None, batch_number=None),
    )
    await db_session.commit()

    result = await _confirm(db_session, document)

    assert result.outcome == matching_service.Outcome.NO_REFERENCE
    assert "BR-02" in result.message
    assert await db_session.scalar(select(func.count(TradeTransaction.id))) == 0


# --- commodity resolution -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected_code", "expected_review"),
    [
        ("CU", "CU", False),
        ("ALU", "AL", False),
        ("Copper Millberry 99.9%", "CU", False),
        ("Palladium sponge", None, True),
    ],
)
async def test_an_unrecognised_grade_is_flagged_rather_than_coerced(
    db_session: AsyncSession, raw: str, expected_code: str | None, expected_review: bool
) -> None:
    code, needs_review = await transaction_service.resolve_commodity(db_session, raw)

    assert code == expected_code
    assert needs_review is expected_review


# --- batch numbering ---------------------------------------------------------------------------


def test_the_batch_prefix_follows_the_documented_format() -> None:
    from datetime import datetime, timezone

    prefix = transaction_service.batch_prefix(datetime(2026, 8, 28, tzinfo=timezone.utc))

    # 'I' + the financial year's last two digits + the two-digit company code.
    assert prefix.startswith("I")
    assert len(prefix) == 5
    assert (
        transaction_service.financial_year_suffix(datetime(2026, 2, 1, tzinfo=timezone.utc)) == "25"
    )
    assert (
        transaction_service.financial_year_suffix(datetime(2026, 8, 1, tzinfo=timezone.utc)) == "26"
    )


async def test_a_batch_number_already_allocated_is_never_renumbered(
    db_session: AsyncSession,
) -> None:
    """The safeguard that has to hold if the prefix format is ever corrected.

    Discovery's worked example does not parse under the format discovery itself states, so the
    field order is an open question (`KNOWN-GAPS.md` §18). Whatever it is resolved to, a number
    already allocated must keep it: it is quoted on generated documents, synced into the tracker
    workbook and carried into SAP as the posting's header text - three systems, two of them
    outside this platform, and none of them told about a renumbering.

    Allocation reads the prefix once, at the moment a batch is created, and nothing anywhere
    recomputes it for a transaction that already has one. Asserted by changing the prefix under a
    live allocation and checking the earlier one is untouched.
    """
    original = await transaction_service.next_batch_number(db_session)
    await db_session.commit()

    transaction = TradeTransaction(
        request_id=(await make_request(db_session)).id,
        transaction_code="TXN-BATCH-STABILITY",
        stream=BusinessStream.SCRAP.value,
        status=TransactionStatus.MATCHED.value,
        batch_number=original,
    )
    db_session.add(transaction)
    await db_session.commit()

    # The format changes. Every number allocated from here on carries the new company segment.
    settings.BATCH_COMPANY_CODE = "70"
    try:
        later = await transaction_service.next_batch_number(db_session)
        await db_session.commit()
    finally:
        settings.BATCH_COMPANY_CODE = "26"

    assert later.split("-", 1)[0] != original.split("-", 1)[0]

    await db_session.refresh(transaction)
    assert transaction.batch_number == original


async def test_sequential_allocations_never_repeat_a_number(db_session: AsyncSession) -> None:
    first = await transaction_service.next_batch_number(db_session)
    second = await transaction_service.next_batch_number(db_session)
    await db_session.commit()

    assert first != second
    assert int(second.rsplit("-", 1)[1]) == int(first.rsplit("-", 1)[1]) + 1


async def test_concurrent_allocations_hand_out_distinct_numbers(db_engine) -> None:
    """The locked counter, under contention.

    Each allocation runs on its own session and its own connection, which is what a concurrent
    HTTP request would do. A contended writer on the SQLite fallback can be turned away rather
    than queued, so the retry here stands in for the caller retrying; what is being proved is
    that no two callers ever walk away with the same number.
    """
    factory = async_sessionmaker(db_engine, expire_on_commit=False)

    async def allocate() -> str:
        for _ in range(8):
            async with factory() as session:
                try:
                    number = await transaction_service.next_batch_number(session)
                    await session.commit()
                    return number
                except OperationalError:
                    await session.rollback()
                    await asyncio.sleep(0.05)
        raise AssertionError("the batch sequence never became available")

    numbers = await asyncio.gather(*(allocate() for _ in range(6)))

    assert len(set(numbers)) == len(numbers)


async def test_a_new_batch_number_is_proposed_when_the_document_quotes_none(
    db_session: AsyncSession,
) -> None:
    request = await make_request(db_session)
    document = await make_document(db_session, request, values=invoice_values(batch_number=None))
    await db_session.commit()

    result = await _confirm(db_session, document)

    assert result.outcome == matching_service.Outcome.NEW_TRANSACTION
    created = await db_session.scalar(select(TradeTransaction))
    assert created.batch_number.startswith("I")
    assert created.transaction_code == created.batch_number
    assert created.status == TransactionStatus.VALIDATION_PENDING.value
    assert created.purchase_leg.supplier_name == SUPPLIER
    assert created.commodity_code == "CU"


async def test_a_document_outside_the_purchase_pipeline_is_left_alone(
    db_session: AsyncSession,
) -> None:
    # Deliberately outside both matched pipelines: a logistics-category shipping document on the
    # scrap stream. The FA stream is no longer an example of "outside the pipeline" - it has one
    # of its own from the FA module onwards - so this fixture names something that genuinely is.
    request = await make_request(db_session, category="logistics", stream="scrap")
    document = await make_document(
        db_session,
        request,
        values=invoice_values(),
        document_type=DocumentType.SHIPPING_DOCUMENT.value,
    )
    await db_session.commit()

    result = await _confirm(db_session, document)

    assert result.outcome == matching_service.Outcome.NOT_APPLICABLE
    assert await db_session.scalar(select(func.count(TradeTransaction.id))) == 0
