"""The sales module: attachment, cross-contract consistency, SL-01 and BR-07.

Every test here works against the real services and the real rule engine. Nothing about matching,
validation or exception routing is mocked, because what these tests are for is proving that the
sales module rides on the machinery  3 and 4 built rather than on a copy of it.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import (
    DocumentType,
    ExceptionCategory,
    FixationStatus,
    MatchMethod,
    PaymentCondition,
    RuleSeverity,
    Territory,
)
from app.models.governance import ExceptionCase, RuleExceptionMapping
from app.models.transactions import RuleEvaluation
from app.services import matching_service, sales_service
from app.services.rules import engine as rule_engine
from app.services.rules.catalog import CheckKey, RuleId
from app.services.rules.registry import registered_rules
from tests.utils.sales import (
    CUSTOMER,
    SALES_CONTRACT,
    bl_values,
    make_bl_document,
    sales_transaction,
)
from tests.utils.transactions import (
    CONTRACT,
    SUPPLIER,
    make_request,
    make_transaction,
)


def _result(evaluations: list[RuleEvaluation], rule_id: str, check_key: str) -> RuleEvaluation:
    match = [row for row in evaluations if row.rule_id == rule_id and row.check_key == check_key]
    assert match, f"{rule_id}/{check_key} was not evaluated"
    return match[-1]


# --- attachment: the same matching, one different band -----------------------------------------


async def test_a_bill_of_lading_quoting_the_batch_matches_the_purchase_transaction(
    db_session: AsyncSession,
) -> None:
    """The batch-number-first branch  established, reused unchanged on the sales side."""
    transaction = await make_transaction(db_session, batch_number="I2626-1")
    document = await make_bl_document(db_session, values=bl_values(batch_number="I2626-1"))
    await db_session.commit()

    match = await sales_service.evaluate_attachment(db_session, document)

    assert match.outcome == matching_service.Outcome.AUTO_LINKED
    assert match.transaction_id == transaction.id
    assert match.method == MatchMethod.BATCH_NUMBER.value
    assert match.score == 100.0


async def test_a_confident_score_on_contract_and_counterparty_matches_without_a_batch(
    db_session: AsyncSession,
) -> None:
    """No batch quoted, so the same fuzzy scorer and the same configured thresholds decide."""
    transaction = await make_transaction(db_session, batch_number="I2626-7")
    document = await make_bl_document(
        db_session,
        values=bl_values(batch_number=None, shipper=SUPPLIER, contract_reference=CONTRACT),
    )
    await db_session.commit()

    match = await sales_service.evaluate_attachment(db_session, document)

    # The scorer compares the shipper against the purchase leg's supplier, exactly as it does on
    # the purchase side - the sales side did not get a second scoring implementation.
    assert match.transaction_id == transaction.id
    assert match.outcome in (
        matching_service.Outcome.AUTO_LINKED,
        matching_service.Outcome.SUGGESTED,
    )


async def test_a_suggested_band_match_creates_nothing_until_a_person_confirms_it(
    db_session: AsyncSession,
) -> None:
    """A candidate below the auto-link threshold is offered for confirmation, never applied.

    The contract reference matches exactly, but the grade on the shipping document does not
    match the batch's - so the corroborating commodity penalty pulls the composite under the
    configured auto-link threshold and leaves it above the suggestion floor. That is precisely
    the case a person should look at rather than the platform deciding.
    """
    await make_transaction(
        db_session,
        batch_number="I2626-8",
        supplier_name=SUPPLIER,
        contract_number=CONTRACT,
        commodity_code="CU",
    )
    document = await make_bl_document(
        db_session,
        values=bl_values(batch_number=None, contract_reference=CONTRACT, commodity_code="AL"),
    )
    await db_session.commit()

    match = await sales_service.evaluate_attachment(db_session, document)

    assert match.outcome == matching_service.Outcome.SUGGESTED
    assert match.needs_user_decision is True
    assert match.candidates, "a suggestion must name what is being suggested"
    # Nothing was created and nothing was attached by evaluating the match.
    assert document.transaction_id is None
    evaluations = (await db_session.scalars(select(RuleEvaluation))).all()
    assert all(row.rule_id != RuleId.SL_01 for row in evaluations)


async def test_no_match_refuses_to_open_a_purchase_less_transaction_on_its_own(
    db_session: AsyncSession,
) -> None:
    """The one place the sales path deliberately differs from the purchase path.

    On the purchase side nothing matching means a new batch, and that is right: a purchase is
    where a batch begins. On the sales side it is not - a sale is of cargo already bought - so
    the platform refuses to invent a second, purchase-less transaction and asks a person instead.
    """
    document = await make_bl_document(
        db_session,
        values=bl_values(
            batch_number=None,
            shipper="Somebody Nobody Has Ever Traded With",
            contract_reference="ZZZ-9999",
        ),
    )
    await db_session.commit()

    match = await sales_service.evaluate_attachment(db_session, document)

    assert match.outcome == sales_service.Outcome.NO_PURCHASE_MATCH
    assert match.outcome != matching_service.Outcome.NEW_TRANSACTION
    assert match.needs_user_decision is True
    assert match.transaction_id is None


async def test_a_transaction_that_already_carries_a_sales_leg_is_not_offered_again(
    db_session: AsyncSession,
) -> None:
    taken = await sales_transaction(db_session, batch_number="I2626-9")
    document = await make_bl_document(
        db_session, values=bl_values(batch_number=None, shipper=SUPPLIER)
    )
    await db_session.commit()

    match = await sales_service.evaluate_attachment(db_session, document)

    assert match.transaction_id != taken.id
    assert all(candidate["transaction_id"] != str(taken.id) for candidate in match.candidates)


# --- cross-contract consistency: the code, never the wording ------------------------------------


async def test_a_genuine_commodity_code_disagreement_is_flagged(
    db_session: AsyncSession,
) -> None:
    """A code that resolves to a different grade means the wrong batch was matched."""
    transaction = await make_transaction(db_session, batch_number="I2626-2", commodity_code="CU")
    await db_session.commit()

    consistency = await sales_service.check_commodity_consistency(db_session, transaction, "AL")

    assert consistency.mismatch is True
    assert consistency.document_code == "AL"
    assert consistency.transaction_code == "CU"


@pytest.mark.parametrize(
    "sales_side_wording",
    [
        # The same grade, described the way each destination's customs paperwork needs it. Every
        # one of these is a legitimate description of copper, and not one of them is an error.
        "Copper",
        "Copper Millberry 99.9%",
        "Recovered copper wire scrap (GB/T 38470)",
        "COPPER SCRAP - MILLBERRY - ISRI BARLEY",
        "銅くず (copper scrap)",
    ],
)
async def test_a_differing_description_for_the_same_code_is_never_flagged(
    db_session: AsyncSession, sales_side_wording: str
) -> None:
    """The single most important behaviour in this , verified precisely.

    A China-bound shipment legitimately needs different customs wording for the same underlying
    commodity code than the purchase-side description used. Comparing the free-text descriptions
    field-by-field would flag nearly every export the desk makes and would teach people to ignore
    the platform. The consistency check compares codes, and only codes.
    """
    transaction = await make_transaction(db_session, batch_number="I2626-3", commodity_code="CU")
    await db_session.commit()

    consistency = await sales_service.check_commodity_consistency(
        db_session, transaction, sales_side_wording
    )

    assert consistency.mismatch is False, (
        f"'{sales_side_wording}' describes the same commodity code and must not be flagged"
    )


async def test_an_unresolvable_grade_claims_no_disagreement(
    db_session: AsyncSession,
) -> None:
    """A grade that resolves to nothing is not evidence of a mismatch, and is not reported as one."""
    transaction = await make_transaction(db_session, batch_number="I2626-11", commodity_code="CU")
    await db_session.commit()

    consistency = await sales_service.check_commodity_consistency(
        db_session, transaction, "Palladium sponge"
    )

    assert consistency.mismatch is False
    assert consistency.document_code is None


# --- SL-01: a cross-transaction aggregate, with three real states -------------------------------


async def test_a_part_shipped_contract_is_informational_and_opens_no_exception(
    db_session: AsyncSession,
) -> None:
    """Below the contracted total is the normal, expected state of a live sales contract."""
    transaction = await sales_transaction(
        db_session, batch_number="I2626-20", quantity="24.500", contracted_quantity="100.000"
    )

    evaluations = await rule_engine.current_results(db_session, transaction.id)
    outcome = _result(evaluations, RuleId.SL_01, CheckKey.CONTRACT_QUANTITY_COVERAGE)

    assert outcome.passed is True
    assert outcome.severity == RuleSeverity.INFORMATIONAL.value
    assert "part-shipped" in outcome.message.lower()

    cases = (
        await db_session.scalars(select(ExceptionCase).where(ExceptionCase.rule_id == RuleId.SL_01))
    ).all()
    assert cases == [], "an awaiting-further-shipments state must never open a formal exception"


async def test_a_fully_shipped_contract_is_a_clean_pass(db_session: AsyncSession) -> None:
    transaction = await sales_transaction(
        db_session, batch_number="I2626-21", quantity="100.000", contracted_quantity="100.000"
    )

    outcome = _result(
        await rule_engine.current_results(db_session, transaction.id),
        RuleId.SL_01,
        CheckKey.CONTRACT_QUANTITY_COVERAGE,
    )

    assert outcome.passed is True
    assert outcome.severity == RuleSeverity.HARD.value
    assert "fully shipped" in outcome.message.lower()


async def test_invoicing_past_the_contracted_total_is_a_hard_failure_with_a_real_case(
    db_session: AsyncSession,
) -> None:
    transaction = await sales_transaction(
        db_session, batch_number="I2626-22", quantity="120.000", contracted_quantity="100.000"
    )

    outcome = _result(
        await rule_engine.current_results(db_session, transaction.id),
        RuleId.SL_01,
        CheckKey.CONTRACT_QUANTITY_COVERAGE,
    )

    assert outcome.passed is False
    assert outcome.severity == RuleSeverity.HARD.value

    case = await db_session.scalar(
        select(ExceptionCase).where(ExceptionCase.rule_id == RuleId.SL_01)
    )
    assert case is not None
    # Routed through 's existing generic hook, into the existing quantity category, owned
    # by the selling desk.
    assert case.exception_type == ExceptionCategory.QUANTITY_VARIATION_OUTSIDE_TOLERANCE.value
    assert case.owner_role == "sales_user"
    assert case.transaction_id == transaction.id


async def test_the_check_sums_across_every_shipment_on_the_contract(
    db_session: AsyncSession,
) -> None:
    """Genuinely cross-transaction. Neither shipment breaches alone; together they do."""
    await sales_transaction(
        db_session, batch_number="I2626-30", quantity="60.000", contracted_quantity="100.000"
    )
    second = await sales_transaction(
        db_session, batch_number="I2626-31", quantity="60.000", contracted_quantity="100.000"
    )

    outcome = _result(
        await rule_engine.current_results(db_session, second.id),
        RuleId.SL_01,
        CheckKey.CONTRACT_QUANTITY_COVERAGE,
    )

    assert outcome.passed is False
    assert "120" in (outcome.actual_value or "")
    # A single-transaction reading of 60 against 100 would have passed. It does not, because the
    # rule is an aggregate over the contract by design.


async def test_shipments_on_a_different_contract_are_not_summed_in(
    db_session: AsyncSession,
) -> None:
    await sales_transaction(
        db_session,
        batch_number="I2626-32",
        quantity="90.000",
        contracted_quantity="100.000",
        sales_contract_no="AGF-SC-2026-OTHER",
    )
    mine = await sales_transaction(
        db_session, batch_number="I2626-33", quantity="90.000", contracted_quantity="100.000"
    )

    outcome = _result(
        await rule_engine.current_results(db_session, mine.id),
        RuleId.SL_01,
        CheckKey.CONTRACT_QUANTITY_COVERAGE,
    )

    assert outcome.passed is True
    assert "90" in (outcome.actual_value or "")


async def test_a_sibling_result_is_refreshed_when_the_aggregate_changes(
    db_session: AsyncSession,
) -> None:
    """The stale-sibling problem, and the whole reason `propagate_coverage` exists.

    The first shipment is evaluated while the contract is comfortably part-shipped. A second
    shipment then takes the contract past its total, and the first transaction's own recorded
    SL-01 result has to stop saying "more to come" - because it is no longer true of the contract
    it is a shipment against.
    """
    first = await sales_transaction(
        db_session, batch_number="I2626-40", quantity="60.000", contracted_quantity="100.000"
    )
    before = _result(
        await rule_engine.current_results(db_session, first.id),
        RuleId.SL_01,
        CheckKey.CONTRACT_QUANTITY_COVERAGE,
    )
    assert before.passed is True

    second = await sales_transaction(
        db_session, batch_number="I2626-41", quantity="70.000", contracted_quantity="100.000"
    )
    refreshed = await sales_service.propagate_coverage(db_session, second, actor_id=None)
    await db_session.commit()

    assert first.id in refreshed

    after = _result(
        await rule_engine.current_results(db_session, first.id),
        RuleId.SL_01,
        CheckKey.CONTRACT_QUANTITY_COVERAGE,
    )
    assert after.passed is False, "the sibling's own result must not go stale"
    assert after.id != before.id, "a fresh row, never an edit of the old one"

    # The sibling gets a real, owned case of its own, through the same generic hook.
    cases = (
        await db_session.scalars(
            select(ExceptionCase).where(ExceptionCase.transaction_id == first.id)
        )
    ).all()
    assert any(row.rule_id == RuleId.SL_01 for row in cases)


async def test_the_sibling_refresh_touches_only_this_one_rule(
    db_session: AsyncSession,
) -> None:
    """Scoped deliberately: no full cascading re-validation of every rule on every neighbour."""
    first = await sales_transaction(
        db_session, batch_number="I2626-50", quantity="60.000", contracted_quantity="100.000"
    )
    before = {
        (row.rule_id, row.check_key): row.id
        for row in await rule_engine.current_results(db_session, first.id)
    }

    second = await sales_transaction(
        db_session, batch_number="I2626-51", quantity="70.000", contracted_quantity="100.000"
    )
    await sales_service.propagate_coverage(db_session, second, actor_id=None)
    await db_session.commit()

    after = {
        (row.rule_id, row.check_key): row.id
        for row in await rule_engine.current_results(db_session, first.id)
    }

    moved = {key for key, value in after.items() if before.get(key) != value}
    assert moved == {(RuleId.SL_01, CheckKey.CONTRACT_QUANTITY_COVERAGE)}


async def test_an_unchanged_sibling_is_left_alone(db_session: AsyncSession) -> None:
    """A change that does not move the aggregate's story writes no row on a neighbour."""
    first = await sales_transaction(
        db_session, batch_number="I2626-60", quantity="10.000", contracted_quantity="100.000"
    )
    second = await sales_transaction(
        db_session, batch_number="I2626-61", quantity="10.000", contracted_quantity="100.000"
    )
    await sales_service.propagate_coverage(db_session, second, actor_id=None)
    await db_session.commit()

    baseline = _result(
        await rule_engine.current_results(db_session, first.id),
        RuleId.SL_01,
        CheckKey.CONTRACT_QUANTITY_COVERAGE,
    ).id

    again = await sales_service.propagate_coverage(db_session, second, actor_id=None)
    await db_session.commit()

    assert first.id not in again
    assert (
        _result(
            await rule_engine.current_results(db_session, first.id),
            RuleId.SL_01,
            CheckKey.CONTRACT_QUANTITY_COVERAGE,
        ).id
        == baseline
    )


# --- BR-07: a draft starts the paperwork, an original finishes it --------------------------------


async def test_a_draft_bill_of_lading_permits_a_draft_but_not_a_submission(
    db_session: AsyncSession,
) -> None:
    transaction = await sales_transaction(
        db_session, batch_number="I2626-70", with_final_bl=False, with_draft_bl=True
    )
    evaluations = await rule_engine.current_results(db_session, transaction.id)

    draft_check = _result(evaluations, RuleId.BR_07, CheckKey.DRAFT_BL_PRESENT)
    final_check = _result(evaluations, RuleId.BR_07, CheckKey.FINAL_BL_PRESENT)

    assert draft_check.passed is True, "a draft B/L is enough to prepare a sales document"
    assert final_check.passed is False, "a draft B/L is not enough to submit"
    assert "final bill of lading is required before submission" in final_check.message


async def test_an_original_bill_of_lading_satisfies_both_checks(
    db_session: AsyncSession,
) -> None:
    transaction = await sales_transaction(db_session, batch_number="I2626-71", with_final_bl=True)
    evaluations = await rule_engine.current_results(db_session, transaction.id)

    assert _result(evaluations, RuleId.BR_07, CheckKey.DRAFT_BL_PRESENT).passed is True
    assert _result(evaluations, RuleId.BR_07, CheckKey.FINAL_BL_PRESENT).passed is True


async def test_no_bill_of_lading_at_all_fails_both_checks(db_session: AsyncSession) -> None:
    transaction = await sales_transaction(
        db_session, batch_number="I2626-72", with_final_bl=False, with_draft_bl=False
    )
    # The recorded reference is what the fixture puts on the leg; without it there is nothing.
    transaction.sales_leg.bl_reference = None
    await rule_engine.run_validation(db_session, transaction)
    await db_session.commit()

    evaluations = await rule_engine.current_results(db_session, transaction.id)
    assert _result(evaluations, RuleId.BR_07, CheckKey.DRAFT_BL_PRESENT).passed is False
    assert _result(evaluations, RuleId.BR_07, CheckKey.FINAL_BL_PRESENT).passed is False


async def test_br_07_is_not_evaluated_on_a_purchase_only_transaction(
    db_session: AsyncSession,
) -> None:
    """Declared against the sales leg, so the orchestrator skips it without asking what this is."""
    transaction = await make_transaction(db_session, batch_number="I2626-73")
    await rule_engine.run_validation(db_session, transaction)
    await db_session.commit()

    evaluations = await rule_engine.current_results(db_session, transaction.id)
    assert all(row.rule_id not in (RuleId.BR_07, RuleId.SL_01) for row in evaluations)


# --- the reuse promises, checked rather than assumed ---------------------------------------------


async def test_the_new_rule_reached_the_registry_without_a_new_registry(
    db_session: AsyncSession,
) -> None:
    """SL-01 is in 's registry, registered by the same decorator as every other rule."""
    registry = registered_rules()

    assert RuleId.SL_01 in registry
    assert registry[RuleId.SL_01].implemented is True
    assert registry[RuleId.SL_01].requires_legs == frozenset({"sales"})
    # BR-07 stopped being a placeholder in the same registry, under the same identifier.
    assert registry[RuleId.BR_07].implemented is True


async def test_the_new_rule_reached__fours_mapping_as_a_row(
    db_session: AsyncSession,
) -> None:
    """Routing SL-01's failures was two rows in a table, not a branch in the hook."""
    mapping = await db_session.scalar(
        select(RuleExceptionMapping).where(RuleExceptionMapping.rule_id == RuleId.SL_01)
    )

    assert mapping is not None
    assert mapping.check_key == CheckKey.CONTRACT_QUANTITY_COVERAGE
    assert mapping.exception_type == ExceptionCategory.QUANTITY_VARIATION_OUTSIDE_TOLERANCE.value
    assert mapping.owner_role == "sales_user"
    assert mapping.is_active is True


def test_neither_engine_grew_a_branch_for_the_sales_or_shipment_rules() -> None:
    """Read the two files and check that neither names a rule a later  introduced.

    A blunt test, and the right one: the whole architectural claim of  3 and 4 is that the
    orchestrator and the exception hook never learn about an individual rule. If either of them
    had to be taught about SL-01, BR-07 or BR-03, that claim was false, and this is what would
    say so. The token list grows with every  that adds a rule, and this one adds three.
    """
    from pathlib import Path

    import app.services.governance.hooks as hooks_module
    import app.services.rules.engine as engine_module

    for module in (engine_module, hooks_module):
        source = Path(module.__file__).read_text()
        for token in (
            RuleId.SL_01,
            "BR-07",
            "BR-03",
            "sales_leg",
            "contract_quantity_coverage",
            "container_cross_transaction",
        ):
            assert token not in source, (
                f"{Path(module.__file__).name} names '{token}'. Each of these modules was "
                "supposed to extend these engines by adding rows and a function, not by editing "
                "them."
            )


async def test_the_sales_leg_attached_with_no_change_to_the_parent_table(
    db_session: AsyncSession,
) -> None:
    """'s design, checked directly: the attachment is the child's own foreign key."""
    from app.models.transactions import TradeTransaction

    transaction = await sales_transaction(db_session, batch_number="I2626-80")

    assert transaction.sales_leg is not None
    assert transaction.sales_leg.transaction_id == transaction.id
    # `trade_transactions` carries no sales column at all - not an id, not a flag.
    columns = set(TradeTransaction.__table__.columns.keys())
    assert not any("sales" in name for name in columns)


# --- price fixation ------------------------------------------------------------------------------


async def test_recording_a_rate_and_a_date_moves_the_customer_to_fixed(
    db_session: AsyncSession,
) -> None:
    from datetime import date

    from app.models.identity import User
    from app.services import transaction_fields

    transaction = await sales_transaction(db_session, batch_number="I2626-90")
    user = User(subject_id="fix", email="s@x.test", display_name="Sales", roles=["sales_user"])
    db_session.add(user)
    await db_session.flush()

    assert transaction.sales_leg.customer_fixation_status == FixationStatus.UNFIXED.value

    changes = await transaction_fields.apply_corrections(
        db_session,
        transaction,
        [("fixation_rate", "8420.00", None), ("fixation_date", "2026-08-25", None)],
        user=user,
        audit_event_type="transaction.field_corrected",
        allowed_owners=transaction_fields.owners_for(user.roles),
    )
    await db_session.commit()

    assert transaction_fields.fixation_recorded(changes) is True
    assert transaction.sales_leg.customer_fixation_status == FixationStatus.FIXED.value
    assert transaction.sales_leg.fixation_rate == Decimal("8420.00")
    assert transaction.sales_leg.fixation_date == date(2026, 8, 25)


async def test_a_sales_user_may_not_restate_the_suppliers_terms(
    db_session: AsyncSession,
) -> None:
    from app.core.errors import AuthorizationError
    from app.models.identity import User
    from app.services import transaction_fields

    transaction = await sales_transaction(db_session, batch_number="I2626-91")
    user = User(subject_id="fix2", email="s2@x.test", display_name="Sales", roles=["sales_user"])
    db_session.add(user)
    await db_session.flush()

    with pytest.raises(AuthorizationError):
        await transaction_fields.apply_corrections(
            db_session,
            transaction,
            [("supplier_name", "Somebody Else", None)],
            user=user,
            audit_event_type="transaction.field_corrected",
            allowed_owners=transaction_fields.owners_for(user.roles),
        )


# --- the leg itself ------------------------------------------------------------------------------


async def test_a_second_sales_leg_cannot_be_attached_to_the_same_batch(
    db_session: AsyncSession,
) -> None:
    from app.core.errors import ConflictError
    from app.models.identity import User

    transaction = await sales_transaction(db_session, batch_number="I2626-92")
    user = User(subject_id="dup", email="d@x.test", display_name="Sales", roles=["sales_user"])
    db_session.add(user)
    await db_session.flush()

    with pytest.raises(ConflictError):
        await sales_service.attach_sales_leg(
            db_session,
            transaction,
            sales_service.SalesLegInput(
                customer_name=CUSTOMER,
                territory=Territory.INDIA.value,
                sales_contract_no=SALES_CONTRACT,
                payment_condition=PaymentCondition.CAD.value,
            ),
            actor_id=user.id,
            attachment=sales_service.Attachment.USER_SELECTED,
        )


async def test_attaching_to_a_purchase_less_transaction_needs_an_acknowledgement(
    db_session: AsyncSession,
) -> None:
    from app.core.errors import ConflictError
    from app.models.enums import TransactionStatus
    from app.models.identity import User
    from app.models.transactions import TradeTransaction

    request = await make_request(db_session, category="sales")
    orphan = TradeTransaction(
        transaction_code="I2626-93",
        batch_number="I2626-93",
        stream="scrap",
        status=TransactionStatus.MATCHED.value,
        commodity_code="CU",
        quantity_mt=Decimal("24.5"),
        currency="USD",
        request_id=request.id,
        field_overrides={},
    )
    db_session.add(orphan)
    await db_session.flush()
    orphan.purchase_leg = None
    orphan.sales_leg = None
    # Stated for the same reason the other two are: an object nothing has queried has unset
    # relationships, and reading one inside an async session is an error rather than a query.
    orphan.fa_leg = None

    user = User(subject_id="ack", email="a@x.test", display_name="Sales", roles=["sales_user"])
    db_session.add(user)
    await db_session.flush()

    payload = sales_service.SalesLegInput(
        customer_name=CUSTOMER,
        territory=Territory.INDIA.value,
        sales_contract_no=SALES_CONTRACT,
        payment_condition=PaymentCondition.CAD.value,
        contracted_quantity_mt=Decimal("100"),
    )

    with pytest.raises(ConflictError):
        await sales_service.attach_sales_leg(
            db_session,
            orphan,
            payload,
            actor_id=user.id,
            attachment=sales_service.Attachment.USER_SELECTED,
        )

    leg, _ = await sales_service.attach_sales_leg(
        db_session,
        orphan,
        payload,
        actor_id=user.id,
        attachment=sales_service.Attachment.NO_PURCHASE_ACKNOWLEDGED,
        acknowledged_no_purchase=True,
    )
    await db_session.commit()

    assert leg.transaction_id == orphan.id


async def test_a_generated_document_type_is_a_real_vocabulary_entry(
    db_session: AsyncSession,
) -> None:
    from app.models.enums import DOCUMENT_TYPES

    assert DocumentType.BL_DRAFT.value in DOCUMENT_TYPES
    assert DocumentType.DRAFT_CONTRACT.value in DOCUMENT_TYPES
    assert DocumentType.DRAFT_INVOICE.value in DOCUMENT_TYPES
