"""The exception hook, the queue, and what it takes to actually close a case.

The point of most of these is that the hook is data-driven. A real rule and a rule invented inside
the test are both routed by the same mapping table, and if any of that were a conditional chain
over the five rule identifiers that exist today, the synthetic-rule tests below could not pass.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utcnow
from app.models.audit import AuditEvent
from app.models.enums import ExceptionCategory, RuleSeverity, TransactionStatus
from app.models.governance import ExceptionCase
from app.models.transactions import RuleEvaluation
from app.services.governance import exception_service
from app.services.governance.categories import ALL_CATEGORIES, CATEGORY_CATALOG
from app.services.governance.hooks import GovernanceAuditEvent
from app.services.rules import engine as rule_engine
from app.services.rules.catalog import CheckKey, RuleId
from tests.utils.governance import (
    SYNTHETIC_CHECK_KEY,
    seeded_transaction,
    synthetic_hard_failing_rule,
)
from tests.utils.transactions import make_document, make_request, make_transaction

pytestmark = pytest.mark.usefixtures("patched_jwks")

BASE = "/api/v1/exceptions"

# rate x quantity on the clean fixture: 8125.00 x 24.500.
CALCULATED = Decimal("199062.50")
# Inside the $10 self-approval ceiling, so the preparing user clears it in the workspace.
SELF_APPROVABLE = CALCULATED + Decimal("5.00")
# Well past it, so nothing but a correction will do.
HARD_FAIL = CALCULATED + Decimal("500.00")


async def purchase_user(signed_in):
    return await signed_in(
        "0a1b2c3d-0000-4000-8000-00000000e001",
        "purchase.desk@agfze.ae",
        "Marco Bellini",
        ["purchase_user"],
    )


async def finance_user(signed_in):
    return await signed_in(
        "0a1b2c3d-0000-4000-8000-00000000e002",
        "finance.desk@agfze.ae",
        "Aisha Karim",
        ["finance_user"],
    )


async def logistics_user(signed_in):
    return await signed_in(
        "0a1b2c3d-0000-4000-8000-00000000e003",
        "logistics.desk@agfze.ae",
        "Tomas Novak",
        ["logistics_user"],
    )


async def approver(signed_in):
    return await signed_in(
        "0a1b2c3d-0000-4000-8000-00000000e004",
        "hod.desk@agfze.ae",
        "Priya Raghunathan",
        ["approver_hod"],
    )


async def _cases(session: AsyncSession, category: str | None = None) -> list[ExceptionCase]:
    statement = select(ExceptionCase).order_by(ExceptionCase.opened_at)
    if category:
        statement = statement.where(ExceptionCase.exception_type == category)
    return list((await session.scalars(statement)).all())


async def _lme_mismatch(session: AsyncSession, *, actual: str = "95"):
    """A transaction whose only hard failure is one an editable field can actually fix.

    BR-06's price check compares the contract's stated LME percentage against the transaction's
    own `lme_percentage`, which is an editable field of the transaction rather than a value read
    off a document. That makes this the honest fixture for the resolve path: the correction the
    user supplies is genuinely capable of making the rule pass, and equally capable of not.
    """
    return await seeded_transaction(
        session,
        contract_overrides={"price_basis": "97% of the LME cash settlement"},
        price_basis="lme_percent",
        lme_percentage=actual,
    )


# --- the hook: real rules ----------------------------------------------------------------------


async def test_a_clean_transaction_opens_no_exception_at_all(db_session: AsyncSession) -> None:
    await seeded_transaction(db_session)

    assert await _cases(db_session) == []


async def test_a_hard_failing_rule_opens_exactly_one_correctly_categorised_case(
    db_session: AsyncSession,
) -> None:
    # A byte-identical document already sitting on another transaction: BR-13's hard failure, and
    # the only rule the clean pack can be made to fail on its own.
    shared_hash = "d" * 64
    other = await make_transaction(db_session, batch_number="I2626-OTHER")
    await make_document(
        db_session,
        await make_request(db_session),
        values={"invoice_number": "INV-OTHER"},
        content_hash=shared_hash,
        transaction_id=other.id,
    )
    await db_session.commit()

    transaction = await seeded_transaction(db_session, invoice_content_hash=shared_hash)

    opened = await _cases(db_session)
    assert len(opened) == 1
    case = opened[0]
    # The category, the owner and the priority all came from the mapping row, not from code.
    assert case.exception_type == ExceptionCategory.DUPLICATE_DOCUMENT.value
    assert case.owner_role == "admin"
    assert case.rule_id == RuleId.BR_13
    assert case.check_key == CheckKey.DUPLICATE_CONTENT
    assert case.transaction_id == transaction.id
    assert case.resolved_at is None
    # Never a bare "invalid": the case carries the field and both values.
    assert case.field_name == "content_hash"
    assert case.expected_value == "no competing copy"


async def test_revalidating_while_the_case_is_open_never_duplicates_it(
    db_session: AsyncSession,
) -> None:
    transaction = await _lme_mismatch(db_session)
    first = await _cases(db_session, ExceptionCategory.INVOICE_AMOUNT_OUTSIDE_TOLERANCE.value)
    assert len(first) == 1

    for _ in range(3):
        await rule_engine.run_validation(db_session, transaction)
        await db_session.commit()

    again = await _cases(db_session, ExceptionCategory.INVOICE_AMOUNT_OUTSIDE_TOLERANCE.value)
    assert len(again) == 1
    assert again[0].id == first[0].id
    assert again[0].opened_at == first[0].opened_at


async def test_a_quantity_breach_is_routed_to_the_buying_desk_not_to_finance(
    db_session: AsyncSession,
) -> None:
    await seeded_transaction(db_session, invoice_overrides={"quantity": "30.000 MT"})

    quantity = await _cases(
        db_session, ExceptionCategory.QUANTITY_VARIATION_OUTSIDE_TOLERANCE.value
    )
    assert len(quantity) == 1
    assert quantity[0].owner_role == "purchase_user"
    # BR-05 and BR-06 both fail on quantity here, and both map to the same category, so the queue
    # shows one problem rather than the same problem twice.
    assert quantity[0].rule_id in {RuleId.BR_05, RuleId.BR_06}


# --- the hook: a rule that did not exist when it was written -----------------------------------


async def test_the_hook_categorises_a_rule_it_has_never_heard_of(
    db_session: AsyncSession,
) -> None:
    async with synthetic_hard_failing_rule(
        db_session,
        exception_type=ExceptionCategory.MISSING_MANDATORY_DOCUMENT.value,
        owner_role="logistics_user",
    ) as rule_id:
        await seeded_transaction(db_session)

        opened = await _cases(db_session)
        assert len(opened) == 1
        assert opened[0].rule_id == rule_id
        assert opened[0].check_key == SYNTHETIC_CHECK_KEY
        # Straight off the mapping row the test inserted; nothing in the application knows this
        # rule exists, let alone what it means.
        assert opened[0].exception_type == ExceptionCategory.MISSING_MANDATORY_DOCUMENT.value
        assert opened[0].owner_role == "logistics_user"


async def test_the_same_synthetic_rule_maps_wherever_its_row_points(
    db_session: AsyncSession,
) -> None:
    async with synthetic_hard_failing_rule(
        db_session,
        exception_type=ExceptionCategory.INTEGRATION_FAILURE.value,
        owner_role="admin",
    ):
        await seeded_transaction(db_session)

    opened = await _cases(db_session)
    assert [case.exception_type for case in opened] == [ExceptionCategory.INTEGRATION_FAILURE.value]


async def test_an_uncategorised_hard_failure_is_recorded_rather_than_guessed(
    db_session: AsyncSession,
) -> None:
    from app.services.rules.registry import _REGISTRY, RegisteredRule
    from app.services.rules.registry import RuleOutcome as Outcome

    async def evaluate(context):
        return [
            Outcome(
                rule_id="BR-98",
                check_key="unmapped",
                passed=False,
                severity=RuleSeverity.HARD.value,
                message="A rule nobody has categorised yet.",
            )
        ]

    _REGISTRY["BR-98"] = RegisteredRule("BR-98", evaluate, frozenset(), True)
    try:
        await seeded_transaction(db_session)
    finally:
        _REGISTRY.pop("BR-98", None)

    # No case is invented for a rule with no mapping row, and the gap itself is on the record.
    assert await _cases(db_session) == []
    logged = (
        await db_session.scalars(
            select(AuditEvent).where(
                AuditEvent.event_type == GovernanceAuditEvent.EXCEPTION_MAPPING_MISSING
            )
        )
    ).all()
    assert len(logged) == 1
    assert logged[0].event_metadata["rule_id"] == "BR-98"


# --- the self-approvable tier never reaches this queue -----------------------------------------


async def test_a_self_approvable_amount_breach_opens_no_case(db_session: AsyncSession) -> None:
    await seeded_transaction(db_session, invoice_overrides={"amount": str(SELF_APPROVABLE)})

    failing = (
        await db_session.scalars(
            select(RuleEvaluation).where(
                RuleEvaluation.rule_id == RuleId.BR_06,
                RuleEvaluation.check_key == CheckKey.AMOUNT_ROUNDING,
                RuleEvaluation.passed.is_(False),
            )
        )
    ).all()
    assert len(failing) == 1
    assert failing[0].severity == RuleSeverity.ACKNOWLEDGEABLE.value
    # It is failing, and it is nonetheless not this queue's business: it is cleared in the
    # workspace by the preparing user, on the record, and never becomes a formal exception.
    assert await _cases(db_session) == []


async def test_the_same_check_beyond_the_ceiling_does_open_a_case(
    db_session: AsyncSession,
) -> None:
    await seeded_transaction(db_session, invoice_overrides={"amount": str(HARD_FAIL)})

    opened = await _cases(db_session, ExceptionCategory.INVOICE_AMOUNT_OUTSIDE_TOLERANCE.value)
    assert len(opened) == 1
    assert opened[0].owner_role == "finance_user"
    assert opened[0].check_key == CheckKey.AMOUNT_ROUNDING


# --- the queue -----------------------------------------------------------------------------------


async def test_the_queue_carries_all_ten_categories_and_none_is_dormant_any_more(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    """The structure was complete from ; the last empty category filled in .

    The container and shipment categories came to life with the shipment module, and the
    integration failure with the integration hub - so every one of the ten now has code behind it
    that can genuinely raise it, and none of them needs a dormancy note any more.
    """
    _, headers = await purchase_user(signed_in)

    response = await client.get(BASE, headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()["data"]

    assert [row["category"] for row in body["categories"]] == list(ALL_CATEGORIES)
    assert [row for row in body["categories"] if not row["triggerable"]] == []
    assert all(row["dormant_reason"] is None for row in body["categories"])
    integration = next(
        row
        for row in body["categories"]
        if row["category"] == ExceptionCategory.INTEGRATION_FAILURE.value
    )
    # Real, and correctly empty: nothing has failed against a downstream system in this test.
    assert integration["triggerable"] is True
    assert integration["open_count"] == 0


def test_every_registered_category_states_an_owner_and_a_description() -> None:
    for definition in CATEGORY_CATALOG:
        assert definition.owner_role
        assert definition.description.strip()
        # A category nothing can raise says why, rather than looking merely empty.
        assert bool(definition.dormant_reason) is not definition.triggerable


async def test_ageing_is_computed_live_from_the_stored_timestamp(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    _, headers = await purchase_user(signed_in)
    await _lme_mismatch(db_session)

    case = (await _cases(db_session))[0]
    assert case.escalated is False

    # Reach back only into `opened_at`. Nothing anywhere stores an age or an overdue flag, so
    # moving the timestamp is the whole of what it takes for the queue to report it as overdue.
    case.opened_at = utcnow() - timedelta(hours=60)
    await db_session.commit()

    response = await client.get(f"{BASE}?exception_type={case.exception_type}", headers=headers)
    row = response.json()["data"]["items"][0]
    assert row["overdue"] is True
    assert row["age_hours"] >= 60
    assert row["age_days"] == 2

    case.opened_at = utcnow() - timedelta(hours=1)
    await db_session.commit()
    response = await client.get(f"{BASE}?exception_type={case.exception_type}", headers=headers)
    assert response.json()["data"]["items"][0]["overdue"] is False


async def test_the_detail_names_the_rule_the_field_and_both_values(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    _, headers = await purchase_user(signed_in)
    await _lme_mismatch(db_session)
    case = (await _cases(db_session))[0]

    body = (await client.get(f"{BASE}/{case.id}", headers=headers)).json()["data"]

    assert body["rule_id"] == RuleId.BR_06
    assert body["field_name"] == "lme_percentage"
    assert body["expected_value"] == "97%"
    assert body["actual_value"] == "95%"
    assert body["current_evaluation"]["message"]
    assert body["rule_now_passes"] is False
    assert body["can_resolve"] is True


# --- resolving -----------------------------------------------------------------------------------


async def test_resolving_with_a_correction_that_actually_fixes_the_rule_succeeds(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    _, headers = await purchase_user(signed_in)
    transaction = await _lme_mismatch(db_session)
    case = (await _cases(db_session))[0]

    response = await client.post(
        f"{BASE}/{case.id}/resolve",
        headers=headers,
        json={
            "resolution_note": "The contract is 97%; the transaction had been keyed at 95%.",
            "correction": {"name": "lme_percentage", "value": "97"},
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()["data"]
    assert body["resolved_at"] is not None
    assert body["rule_now_passes"] is True

    await db_session.refresh(transaction)
    assert transaction.lme_percentage == Decimal("97")

    stored = await db_session.get(ExceptionCase, case.id)
    await db_session.refresh(stored)
    assert stored.resolution_note.startswith("The contract is 97%")
    assert stored.resolved_by_id is not None


async def test_resolving_with_a_correction_that_does_not_fix_the_rule_is_refused(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    _, headers = await purchase_user(signed_in)
    transaction = await _lme_mismatch(db_session)
    case = (await _cases(db_session))[0]

    response = await client.post(
        f"{BASE}/{case.id}/resolve",
        headers=headers,
        json={
            "resolution_note": "Corrected to 96, which is still not what the contract says.",
            "correction": {"name": "lme_percentage", "value": "96"},
        },
    )
    assert response.status_code == 409, response.text
    assert response.json()["errors"][0]["code"] == "rule_still_failing"

    # The whole request is one act: refusing it leaves nothing behind, neither a resolution nor a
    # half-applied correction. The workspace remains the place to correct a value incrementally.
    await db_session.refresh(transaction)
    assert transaction.lme_percentage == Decimal("95")
    stored = await db_session.get(ExceptionCase, case.id)
    await db_session.refresh(stored)
    assert stored.resolved_at is None


async def test_a_note_on_its_own_never_closes_a_case_whose_rule_still_fails(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    _, headers = await purchase_user(signed_in)
    await _lme_mismatch(db_session)
    case = (await _cases(db_session))[0]

    response = await client.post(
        f"{BASE}/{case.id}/resolve",
        headers=headers,
        json={"resolution_note": "Spoke to the supplier, everybody is happy with 95%."},
    )
    assert response.status_code == 409
    stored = await db_session.get(ExceptionCase, case.id)
    await db_session.refresh(stored)
    assert stored.resolved_at is None


async def test_escalating_flags_the_case_without_claiming_a_fix(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    _, headers = await purchase_user(signed_in)
    await _lme_mismatch(db_session)
    case = (await _cases(db_session))[0]

    response = await client.post(
        f"{BASE}/{case.id}/resolve",
        headers=headers,
        json={
            "resolution_note": "I cannot change a contracted price; this needs the HOD.",
            "escalate_to_hod": True,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()["data"]

    assert body["escalated"] is True
    assert body["priority"] == "high"
    # The whole point: escalated and still open, with the rule still failing underneath.
    assert body["resolved_at"] is None
    assert body["rule_now_passes"] is False
    # And nothing pretends a message went anywhere.
    assert "no notification has been sent" in response.json()["message"].lower()

    logged = (
        await db_session.scalars(
            select(AuditEvent).where(
                AuditEvent.event_type == GovernanceAuditEvent.EXCEPTION_ESCALATED
            )
        )
    ).all()
    assert len(logged) == 1
    assert logged[0].event_metadata["notification_sent"] is False


async def test_a_desk_that_does_not_own_the_category_cannot_resolve_it(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    _, headers = await logistics_user(signed_in)
    await _lme_mismatch(db_session)
    case = (await _cases(db_session))[0]

    response = await client.post(
        f"{BASE}/{case.id}/resolve",
        headers=headers,
        json={"resolution_note": "Not my desk, but let me close it anyway."},
    )
    assert response.status_code == 403


async def test_finance_may_settle_an_invoice_value_case_but_not_a_quantity_one(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    _, headers = await finance_user(signed_in)

    await _lme_mismatch(db_session)
    value_case = (
        await _cases(db_session, ExceptionCategory.INVOICE_AMOUNT_OUTSIDE_TOLERANCE.value)
    )[0]
    detail = (await client.get(f"{BASE}/{value_case.id}", headers=headers)).json()["data"]
    assert detail["can_resolve"] is True

    await seeded_transaction(
        db_session, batch_number="I2626-2", invoice_overrides={"quantity": "30.000 MT"}
    )
    quantity_case = (
        await _cases(db_session, ExceptionCategory.QUANTITY_VARIATION_OUTSIDE_TOLERANCE.value)
    )[0]
    refused = await client.post(
        f"{BASE}/{quantity_case.id}/resolve",
        headers=headers,
        json={"resolution_note": "Finance has no business settling a weighbridge dispute."},
    )
    assert refused.status_code == 403


async def test_an_approver_may_read_the_queue_but_not_act_on_it(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    _, headers = await approver(signed_in)
    await _lme_mismatch(db_session)
    case = (await _cases(db_session))[0]

    assert (await client.get(BASE, headers=headers)).status_code == 200
    detail = (await client.get(f"{BASE}/{case.id}", headers=headers)).json()["data"]
    assert detail["can_resolve"] is False

    refused = await client.post(
        f"{BASE}/{case.id}/resolve",
        headers=headers,
        json={"resolution_note": "Approvers sign transactions, they do not fix them."},
    )
    assert refused.status_code == 403


async def test_every_case_and_every_resolution_is_audited(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    _, headers = await purchase_user(signed_in)
    await _lme_mismatch(db_session)
    case = (await _cases(db_session))[0]

    await client.post(
        f"{BASE}/{case.id}/resolve",
        headers=headers,
        json={
            "resolution_note": "Keyed the contract's own 97% onto the transaction.",
            "correction": {"name": "lme_percentage", "value": "97"},
        },
    )

    events = dict(
        (
            await db_session.execute(
                select(AuditEvent.event_type, func.count(AuditEvent.id)).group_by(
                    AuditEvent.event_type
                )
            )
        ).all()
    )
    assert events.get(GovernanceAuditEvent.EXCEPTION_OPENED) == 1
    assert events.get(GovernanceAuditEvent.EXCEPTION_RESOLVED) == 1


# --- the transaction keeps moving afterwards -----------------------------------------------------


async def test_a_resolved_transaction_becomes_submittable_again(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    _, headers = await purchase_user(signed_in)
    transaction = await _lme_mismatch(db_session)
    case = (await _cases(db_session))[0]

    blocked = await client.post(f"/api/v1/transactions/{transaction.id}/submit", headers=headers)
    assert blocked.status_code == 409

    await client.post(
        f"{BASE}/{case.id}/resolve",
        headers=headers,
        json={
            "resolution_note": "Transaction now carries the contracted 97%.",
            "correction": {"name": "lme_percentage", "value": "97"},
        },
    )

    accepted = await client.post(f"/api/v1/transactions/{transaction.id}/submit", headers=headers)
    assert accepted.status_code == 200, accepted.text
    await db_session.refresh(transaction)
    assert transaction.status == TransactionStatus.APPROVAL_PENDING.value


def test_only_a_hard_failure_counts_as_one() -> None:
    hard = RuleEvaluation(passed=False, severity=RuleSeverity.HARD.value)
    acknowledgeable = RuleEvaluation(passed=False, severity=RuleSeverity.ACKNOWLEDGEABLE.value)
    passing = RuleEvaluation(passed=True, severity=RuleSeverity.HARD.value)

    from app.services.governance.hooks import is_hard_failure

    assert is_hard_failure(hard) is True
    assert is_hard_failure(acknowledgeable) is False
    assert is_hard_failure(passing) is False


def test_overdue_is_never_true_of_a_resolved_case() -> None:
    case = ExceptionCase(
        opened_at=utcnow() - timedelta(days=30),
        resolved_at=utcnow() - timedelta(days=29),
    )
    assert exception_service.is_overdue(case, Decimal("48")) is False
    assert exception_service.age_hours(case) == pytest.approx(24.0, abs=0.1)
