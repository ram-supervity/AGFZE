"""The validation engine: its registry, its five real evaluators and its append-only history.

Every threshold these tests assert against is the seeded configuration, read back out of
`rule_configurations`. Nothing here restates a number the application is supposed to be reading
from the database, because a test that hardcoded ±5% would keep passing after somebody changed
the configured tolerance to something else.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import DocumentType, RuleSeverity, TransactionStatus
from app.models.transactions import RuleEvaluation
from app.services.rules import engine as rule_engine
from app.services.rules.catalog import ALL_RULE_IDS, CheckKey, RuleId
from app.services.rules.registry import registered_rules
from app.services.rules.values import money, percentage_difference, to_decimal
from tests.utils.transactions import (
    contract_values,
    invoice_values,
    make_document,
    make_request,
    make_transaction,
)


async def _context(session: AsyncSession, transaction):
    return await rule_engine.build_context(session, transaction)


async def _seeded_transaction(
    session: AsyncSession,
    *,
    invoice_overrides: dict | None = None,
    contract_overrides: dict | None = None,
    territory: str | None = None,
    with_contract: bool = True,
    **transaction_kwargs,
):
    request = await make_request(session)
    transaction = await make_transaction(session, request=request, **transaction_kwargs)
    await make_document(
        session,
        request,
        values=invoice_values(**(invoice_overrides or {})),
        document_type=DocumentType.INVOICE.value,
        filename="invoice.pdf",
        territory=territory,
        transaction_id=transaction.id,
    )
    if with_contract:
        await make_document(
            session,
            request,
            values=contract_values(**(contract_overrides or {})),
            document_type=DocumentType.CONTRACT.value,
            filename="contract.pdf",
            territory=territory,
            transaction_id=transaction.id,
        )
    await session.commit()
    return transaction


def _by_check(rows: list[RuleEvaluation]) -> dict[tuple[str, str | None], RuleEvaluation]:
    return {(row.rule_id, row.check_key): row for row in rows}


# --- the registry ------------------------------------------------------------------------------


def test_the_registry_carries_every_catalogued_rule() -> None:
    """The thirteen governing rules, plus the sales module's own SL-01.

    The registry and the catalog have to agree exactly, in both directions: a rule nobody
    registered would be silently skipped, and a registered rule the catalog does not name would
    show a user a check with no statement behind it.
    """
    registered = registered_rules()

    assert set(registered) == set(ALL_RULE_IDS)
    # Sixteen: the thirteen governing rules, the sales module's cross-transaction quantity rule,
    # the invoice-dating rule, and the invoiced-weight-against-the-bill-of-lading rule - the last
    # three each under a namespace of their own, for the same reason: none of them is one of the
    # thirteen, and appending them to that numbering would misrepresent where they came from.
    assert len(ALL_RULE_IDS) == 16
    assert RuleId.SL_01 in registered
    assert RuleId.IV_01 in registered
    assert RuleId.LG_01 in registered


def test_only_the_evaluable_rules_are_marked_implemented() -> None:
    """BR-07 joined the five with the sales module, BR-03 with the shipment one, then IV-01, then
    LG-01.

    Nothing else moved. The six that remain unimplemented are still registered, still walked by
    the orchestrator, and still write nothing - which is what they should do until the  that
    brings their data replaces the body.
    """
    implemented = {rule_id for rule_id, rule in registered_rules().items() if rule.implemented}

    assert implemented == {
        RuleId.BR_02,
        RuleId.BR_03,
        RuleId.BR_04,
        RuleId.BR_05,
        RuleId.BR_06,
        RuleId.BR_07,
        RuleId.BR_13,
        RuleId.IV_01,
        RuleId.LG_01,
        RuleId.SL_01,
    }


async def test_the_placeholders_run_without_error_and_report_themselves_unevaluated(
    db_session: AsyncSession,
) -> None:
    transaction = await _seeded_transaction(db_session)
    context = await _context(db_session, transaction)

    for rule_id in (RuleId.BR_01, RuleId.BR_08, RuleId.BR_09, RuleId.BR_10):
        outcomes = await registered_rules()[rule_id].evaluator(context)
        assert outcomes, rule_id
        assert all(outcome.applicable is False for outcome in outcomes), rule_id


async def test_a_placeholder_is_never_written_or_shown_as_a_check(
    db_session: AsyncSession,
) -> None:
    transaction = await _seeded_transaction(db_session)

    written = await rule_engine.run_validation(db_session, transaction)
    await db_session.commit()

    recorded = {row.rule_id for row in written}
    # BR-07 needs a sales leg this transaction does not carry, so it may not appear as a check a
    # person is asked to read. BR-03 does now appear: it has real container data to judge from
    # the shipment module onwards, and on a clean transaction it passes.
    assert RuleId.BR_07 not in recorded
    assert RuleId.BR_01 not in recorded
    assert {
        RuleId.BR_02,
        RuleId.BR_03,
        RuleId.BR_04,
        RuleId.BR_05,
        RuleId.BR_06,
        RuleId.BR_13,
    } <= recorded


async def test_a_rule_scoped_to_a_leg_the_transaction_lacks_is_skipped(
    db_session: AsyncSession,
) -> None:
    transaction = await _seeded_transaction(db_session)
    context = await _context(db_session, transaction)

    assert context.leg("purchase") is not None
    # The orchestrator reads the leg map rather than asking what kind of transaction this is,
    # which is exactly what lets  add BR-07's real evaluator without touching dispatch.
    assert registered_rules()[RuleId.BR_07].requires_legs == frozenset({"sales"})


# --- BR-02  business reference ------------------------------------------------------------------


async def test_br02_passes_when_a_business_reference_is_recorded(
    db_session: AsyncSession,
) -> None:
    transaction = await _seeded_transaction(db_session)
    context = await _context(db_session, transaction)

    outcomes = await registered_rules()[RuleId.BR_02].evaluator(context)

    assert len(outcomes) == 1
    assert outcomes[0].passed is True
    # Named by concept rather than by column from the FA stream onwards, because the same
    # evaluator now reads a purchase leg's `contract_number` and an FA leg's own reference.
    assert "contract_reference" in (outcomes[0].actual_value or "")


async def test_br02_fails_when_nothing_identifies_the_deal(db_session: AsyncSession) -> None:
    transaction = await _seeded_transaction(db_session, contract_number=None, invoice_number=None)
    # The batch number is the last surviving reference, so it is cleared too - and only then is
    # there genuinely nothing to match on.
    transaction.batch_number = ""
    await db_session.commit()

    context = await _context(db_session, transaction)
    outcomes = await registered_rules()[RuleId.BR_02].evaluator(context)

    assert outcomes[0].passed is False
    assert outcomes[0].severity == RuleSeverity.HARD.value


# --- BR-04  mandatory document pack -------------------------------------------------------------


async def test_br04_fails_and_names_what_the_india_pack_is_missing(
    db_session: AsyncSession,
) -> None:
    transaction = await _seeded_transaction(db_session, territory="india")
    context = await _context(db_session, transaction)

    outcomes = await registered_rules()[RuleId.BR_04].evaluator(context)

    assert outcomes[0].passed is False
    assert "packing list" in outcomes[0].message
    assert "certificate of origin" in outcomes[0].message


async def test_br04_passes_once_every_checklist_entry_is_evidenced(
    db_session: AsyncSession,
) -> None:
    request = await make_request(db_session)
    transaction = await make_transaction(db_session, request=request)
    await make_document(
        db_session,
        request,
        values=invoice_values(),
        filename="invoice.pdf",
        territory="india",
        transaction_id=transaction.id,
    )
    for entry in (
        "packing_list",
        "certificate_of_origin",
        "freight_certificate",
        "form_6",
        "form_9",
        "mill_test_certificate",
        "chemical_analysis_certificate",
    ):
        await make_document(
            db_session,
            request,
            values={},
            document_type=DocumentType.SHIPPING_DOCUMENT.value,
            filename=f"{entry}.pdf",
            territory="india",
            transaction_id=transaction.id,
        )
    await db_session.commit()

    context = await _context(db_session, transaction)
    outcomes = await registered_rules()[RuleId.BR_04].evaluator(context)

    assert outcomes[0].passed is True


# --- BR-05  quantity variation ------------------------------------------------------------------


async def test_br05_passes_inside_the_configured_tolerance(db_session: AsyncSession) -> None:
    # 24.500 contracted against 25.000 invoiced is a 2.04% variation, comfortably inside ±5%.
    transaction = await _seeded_transaction(db_session, invoice_overrides={"quantity": "25.000 MT"})
    context = await _context(db_session, transaction)
    tolerance, _ = context.threshold(RuleId.BR_05, CheckKey.QUANTITY_TOLERANCE)

    outcomes = await registered_rules()[RuleId.BR_05].evaluator(context)

    assert percentage_difference(Decimal("24.5"), Decimal("25.0")) < tolerance
    assert outcomes[0].passed is True


async def test_br05_fails_outside_the_tolerance_and_offers_no_self_approval(
    db_session: AsyncSession,
) -> None:
    # 27.000 against 24.500 is a 10.2% variation.
    transaction = await _seeded_transaction(db_session, invoice_overrides={"quantity": "27.000 MT"})
    context = await _context(db_session, transaction)

    outcomes = await registered_rules()[RuleId.BR_05].evaluator(context)

    assert outcomes[0].passed is False
    # Hard, not acknowledgeable: quantity has no self-approval tier at any size, which is what
    # separates it from the invoice amount.
    assert outcomes[0].severity == RuleSeverity.HARD.value
    assert "cannot be acknowledged" in outcomes[0].message


# --- BR-06  three checks, three behaviours -------------------------------------------------------


async def _amount_outcome(session: AsyncSession, amount: str):
    transaction = await _seeded_transaction(session, invoice_overrides={"amount": amount})
    context = await _context(session, transaction)
    outcomes = await registered_rules()[RuleId.BR_06].evaluator(context)
    return next(row for row in outcomes if row.check_key == CheckKey.AMOUNT_ROUNDING)


@pytest.mark.parametrize(
    ("amount", "expected_passed", "expected_severity"),
    [
        # Calculated value is 8125.00 x 24.500 = 199062.50.
        ("199063.50", True, RuleSeverity.ACKNOWLEDGEABLE.value),  # exactly $1.00 out
        ("199063.51", False, RuleSeverity.ACKNOWLEDGEABLE.value),  # $1.01 out
        ("199072.50", False, RuleSeverity.ACKNOWLEDGEABLE.value),  # exactly $10.00 out
        ("199072.51", False, RuleSeverity.HARD.value),  # $10.01 out
    ],
)
async def test_br06_amount_tiers_land_exactly_on_their_boundaries(
    db_session: AsyncSession,
    amount: str,
    expected_passed: bool,
    expected_severity: str,
) -> None:
    outcome = await _amount_outcome(db_session, amount)

    assert outcome.passed is expected_passed
    assert outcome.severity == expected_severity


async def test_br06_amount_auto_passes_when_it_agrees_exactly(
    db_session: AsyncSession,
) -> None:
    outcome = await _amount_outcome(db_session, "199062.50")

    assert outcome.passed is True
    assert money(to_decimal(outcome.actual_value)) == Decimal("199062.50")


async def test_br06_quantity_has_no_self_approval_tier(db_session: AsyncSession) -> None:
    transaction = await _seeded_transaction(
        db_session, invoice_overrides={"quantity": "27.000 MT", "amount": "219375.00"}
    )
    context = await _context(db_session, transaction)

    outcomes = await registered_rules()[RuleId.BR_06].evaluator(context)
    quantity = next(row for row in outcomes if row.check_key == CheckKey.QUANTITY_TOLERANCE)

    assert quantity.passed is False
    assert quantity.severity == RuleSeverity.HARD.value


async def test_br06_rate_requires_an_exact_match_at_zero_tolerance(
    db_session: AsyncSession,
) -> None:
    transaction = await _seeded_transaction(
        db_session,
        invoice_overrides={"rate": "8125.01", "amount": "199062.75"},
    )
    context = await _context(db_session, transaction)
    tolerance, _ = context.threshold(RuleId.BR_06, CheckKey.RATE_TOLERANCE)

    outcomes = await registered_rules()[RuleId.BR_06].evaluator(context)
    rate = next(row for row in outcomes if row.check_key == CheckKey.RATE_TOLERANCE)

    assert tolerance == Decimal("0")
    # A single cent is a different negotiated price, and it is never self-approvable.
    assert rate.passed is False
    assert rate.severity == RuleSeverity.HARD.value


async def test_br06_rate_passes_when_it_matches_the_contract(db_session: AsyncSession) -> None:
    transaction = await _seeded_transaction(db_session)
    context = await _context(db_session, transaction)

    outcomes = await registered_rules()[RuleId.BR_06].evaluator(context)
    rate = next(row for row in outcomes if row.check_key == CheckKey.RATE_TOLERANCE)

    assert rate.passed is True


# --- BR-13  duplicate handling -------------------------------------------------------------------


async def test_br13_passes_when_no_copy_sits_on_a_competing_transaction(
    db_session: AsyncSession,
) -> None:
    transaction = await _seeded_transaction(db_session)
    context = await _context(db_session, transaction)

    outcomes = await registered_rules()[RuleId.BR_13].evaluator(context)

    assert outcomes[0].passed is True


async def test_br13_fails_when_the_same_bytes_are_linked_elsewhere(
    db_session: AsyncSession,
) -> None:
    shared_hash = "a" * 64
    request = await make_request(db_session)
    first = await make_transaction(db_session, request=request, batch_number="I2626-1")
    second = await make_transaction(
        db_session,
        request=request,
        batch_number="I2626-2",
        invoice_number="INV-2026-0999",
    )
    await make_document(
        db_session,
        request,
        values=invoice_values(),
        content_hash=shared_hash,
        transaction_id=first.id,
    )
    await make_document(
        db_session,
        request,
        values=invoice_values(),
        content_hash=shared_hash,
        filename="invoice-copy.pdf",
        transaction_id=second.id,
    )
    await db_session.commit()

    context = await _context(db_session, second)
    outcomes = await registered_rules()[RuleId.BR_13].evaluator(context)

    assert outcomes[0].passed is False
    assert "different transaction" in outcomes[0].message


# --- the append-only history ---------------------------------------------------------------------


async def test_revalidation_inserts_new_rows_and_leaves_the_old_ones_untouched(
    db_session: AsyncSession,
) -> None:
    transaction = await _seeded_transaction(db_session)

    first = await rule_engine.run_validation(db_session, transaction)
    await db_session.commit()
    original = {
        row.id: (row.passed, row.message, row.evaluated_at)
        for row in (
            await db_session.scalars(
                select(RuleEvaluation).where(RuleEvaluation.transaction_id == transaction.id)
            )
        ).all()
    }

    second = await rule_engine.run_validation(db_session, transaction)
    await db_session.commit()

    everything = (
        await db_session.scalars(
            select(RuleEvaluation).where(RuleEvaluation.transaction_id == transaction.id)
        )
    ).all()

    assert len(first) == len(second)
    assert len(everything) == len(first) + len(second)
    # Not one earlier row was rewritten: the table is the history, not a status flag.
    for row in everything:
        if row.id in original:
            assert (row.passed, row.message, row.evaluated_at) == original[row.id]


async def test_the_latest_row_per_check_is_the_authoritative_one(
    db_session: AsyncSession,
) -> None:
    transaction = await _seeded_transaction(db_session, invoice_overrides={"quantity": "27.000 MT"})
    await rule_engine.run_validation(db_session, transaction)
    await db_session.commit()

    before = _by_check(await rule_engine.current_results(db_session, transaction.id))
    assert before[(RuleId.BR_05, CheckKey.QUANTITY_TOLERANCE)].passed is False

    document = next(
        row
        for row in await rule_engine.linked_documents(db_session, transaction.id)
        if row.document_type == DocumentType.INVOICE.value
    )
    field = next(row for row in document.fields if row.field_name == "quantity")
    field.field_value = "24.500 MT"
    await db_session.commit()

    await rule_engine.run_validation(db_session, transaction)
    await db_session.commit()

    after = _by_check(await rule_engine.current_results(db_session, transaction.id))
    assert after[(RuleId.BR_05, CheckKey.QUANTITY_TOLERANCE)].passed is True


async def test_validation_moves_a_matched_transaction_to_validation_pending(
    db_session: AsyncSession,
) -> None:
    transaction = await _seeded_transaction(db_session)

    await rule_engine.run_validation(db_session, transaction)
    await db_session.commit()

    assert transaction.status == TransactionStatus.VALIDATION_PENDING.value
