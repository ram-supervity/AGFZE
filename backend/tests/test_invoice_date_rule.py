"""IV-01: the invoice-dating rule, and the promise that it never blocks anything.

Every assertion about the window reads the threshold back out of `rule_configurations` rather than
restating three months, for the same reason no other rule test hardcodes a tolerance: the value is
configuration, and a test that hardcoded it would keep passing after somebody changed it.

The severity assertions are the important ones. AGFZE has not confirmed how far back an invoice
may be dated, nor who signs off one that is further back than that, and until they do, a rule that
stopped a real deal on that policy would be this platform inventing a business rule. So the tests
below assert what must remain true: the flag exists, it is visible, it is self-approvable by the
desk that raised it, and there is no path from it to a hard failure or an exception case.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.roles import PlatformRole
from app.db.base import utcnow
from app.models.configuration import RuleConfiguration
from app.models.enums import DocumentType, RuleSeverity, Territory
from app.models.governance import ExceptionCase
from app.models.transactions import RuleEvaluation
from app.services.rules import engine as rule_engine
from app.services.rules.catalog import RULE_BY_ID, CheckKey, RuleId
from app.services.rules.invoice_evaluators import months_before, parse_document_date
from app.services.rules.registry import registered_rules
from tests.utils.transactions import (
    contract_values,
    invoice_values,
    make_document,
    make_request,
    make_transaction,
)

pytestmark = pytest.mark.usefixtures("patched_jwks")

TRANSACTIONS = "/api/v1/transactions"


async def configured_months(session: AsyncSession) -> int:
    row = await session.scalar(
        select(RuleConfiguration).where(
            RuleConfiguration.rule_id == RuleId.IV_01,
            RuleConfiguration.check_key == CheckKey.INVOICE_DATE_WINDOW,
        )
    )
    assert row is not None, "IV-01's threshold was never seeded"
    return int(row.threshold_value)


async def dated_transaction(
    session: AsyncSession,
    *,
    invoice_date: str | None,
    territory: str | None = None,
):
    """A complete, otherwise-clean pack whose invoice carries exactly the date under test."""
    request = await make_request(session)
    transaction = await make_transaction(session, request=request)
    values = invoice_values()
    if invoice_date is None:
        values.pop("invoice_date", None)
    else:
        values["invoice_date"] = invoice_date
    await make_document(
        session,
        request,
        values=values,
        document_type=DocumentType.INVOICE.value,
        filename="invoice.pdf",
        territory=territory,
        transaction_id=transaction.id,
    )
    await make_document(
        session,
        request,
        values=contract_values(),
        document_type=DocumentType.CONTRACT.value,
        filename="contract.pdf",
        territory=territory,
        transaction_id=transaction.id,
    )
    await session.commit()
    return transaction


def window_check(rows: list[RuleEvaluation]) -> RuleEvaluation | None:
    return next(
        (
            row
            for row in rows
            if row.rule_id == RuleId.IV_01 and row.check_key == CheckKey.INVOICE_DATE_WINDOW
        ),
        None,
    )


# --- registration ------------------------------------------------------------------------------


def test_the_rule_is_registered_the_same_way_every_other_rule_is() -> None:
    """No new dispatch, no new context field, no new persistence path - one registry entry."""
    rule = registered_rules()[RuleId.IV_01]

    assert rule.implemented is True
    # It applies to any transaction that carries a dated value document, whichever desk prepared
    # it, so it demands no particular leg.
    assert rule.requires_legs == frozenset()
    assert RULE_BY_ID[RuleId.IV_01].title == "Invoice dating"


def test_the_identifier_sits_outside_the_governing_numbering() -> None:
    """The same decision SL-01 made, for the same reason: it is not one of the thirteen."""
    assert RuleId.IV_01 == "IV-01"
    assert not RuleId.IV_01.startswith("BR-")


async def test_the_threshold_is_configuration_and_not_a_literal(db_session: AsyncSession) -> None:
    row = await db_session.scalar(
        select(RuleConfiguration).where(
            RuleConfiguration.rule_id == RuleId.IV_01,
            RuleConfiguration.check_key == CheckKey.INVOICE_DATE_WINDOW,
        )
    )

    assert row is not None
    assert row.threshold_value == Decimal("3")
    assert row.is_active is True
    assert row.change_reason
    # It is seeded unscoped, so it is the value every stream and every commodity resolves to
    # until somebody adds a narrower row beside it.
    assert (row.scope_stream, row.scope_commodity_code, row.scope_transaction_type) == (
        None,
        None,
        None,
    )


# --- the window --------------------------------------------------------------------------------


async def test_an_invoice_inside_the_window_passes(db_session: AsyncSession) -> None:
    recent = (utcnow().date() - timedelta(days=5)).isoformat()
    transaction = await dated_transaction(db_session, invoice_date=recent)

    evaluations = await rule_engine.run_validation(db_session, transaction)
    check = window_check(evaluations)

    assert check is not None
    assert check.passed is True
    assert recent in (check.actual_value or "")


async def test_a_backdated_invoice_is_flagged_and_never_hard_fails(
    db_session: AsyncSession,
) -> None:
    months = await configured_months(db_session)
    stale = (months_before(utcnow().date(), months) - timedelta(days=1)).isoformat()
    transaction = await dated_transaction(db_session, invoice_date=stale)

    evaluations = await rule_engine.run_validation(db_session, transaction)
    check = window_check(evaluations)

    assert check is not None
    assert check.passed is False
    # The whole point of the rule as shipped.
    assert check.severity == RuleSeverity.ACKNOWLEDGEABLE.value
    assert f"{months}-month" in check.message
    assert "flag rather than a block" in check.message


async def test_a_future_dated_invoice_is_flagged_too_and_still_not_a_block(
    db_session: AsyncSession,
) -> None:
    """The discovery material proposes rejecting this outright; the business never confirmed it.

    So it is flagged, loudly and specifically, and the desk decides. Shipping the rejection would
    be enforcing a policy nobody agreed to.
    """
    ahead = (utcnow().date() + timedelta(days=3)).isoformat()
    transaction = await dated_transaction(db_session, invoice_date=ahead)

    check = window_check(await rule_engine.run_validation(db_session, transaction))

    assert check is not None
    assert check.passed is False
    assert check.severity == RuleSeverity.ACKNOWLEDGEABLE.value
    assert "in the future" in check.message


async def test_an_unreadable_date_is_reported_rather_than_guessed_at(
    db_session: AsyncSession,
) -> None:
    transaction = await dated_transaction(db_session, invoice_date="last Thursday")

    check = window_check(await rule_engine.run_validation(db_session, transaction))

    assert check is not None
    assert check.passed is False
    assert check.severity == RuleSeverity.ACKNOWLEDGEABLE.value
    assert "could not be read as a date" in check.message


async def test_a_transaction_with_no_extracted_date_records_nothing_at_all(
    db_session: AsyncSession,
) -> None:
    """Not applicable is not the same as passing, and neither is it a failure."""
    transaction = await dated_transaction(db_session, invoice_date=None)

    evaluations = await rule_engine.run_validation(db_session, transaction)

    assert window_check(evaluations) is None
    assert not [row for row in evaluations if row.rule_id == RuleId.IV_01]


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        ("2026-03-04", "2026-03-04"),
        ("04/03/2026", "2026-03-04"),
        ("04-03-2026", "2026-03-04"),
        ("4 Mar 2026", "2026-03-04"),
        ("not a date", None),
        ("", None),
        (None, None),
    ],
)
def test_the_shapes_a_date_actually_arrives_in(written: str | None, expected: str | None) -> None:
    parsed = parse_document_date(written)
    assert (parsed.isoformat() if parsed else None) == expected


def test_the_window_lands_on_a_real_day_when_the_target_month_is_short() -> None:
    """31 May minus three months is 28 or 29 February, not a date that does not exist."""
    from datetime import date

    assert months_before(date(2026, 5, 31), 3) == date(2026, 2, 28)
    assert months_before(date(2024, 5, 31), 3) == date(2024, 2, 29)
    assert months_before(date(2026, 1, 15), 3) == date(2025, 10, 15)


# --- the India advisory --------------------------------------------------------------------------


async def test_an_india_transaction_carries_the_advisory_note(db_session: AsyncSession) -> None:
    transaction = await dated_transaction(
        db_session,
        invoice_date=(utcnow().date() - timedelta(days=2)).isoformat(),
        territory=Territory.INDIA.value,
    )

    evaluations = await rule_engine.run_validation(db_session, transaction)
    advisory = next(
        row for row in evaluations if row.check_key == CheckKey.INDIA_PAYMENT_TERMS_ADVISORY
    )

    assert advisory.passed is True
    assert advisory.severity == RuleSeverity.INFORMATIONAL.value
    assert "registered small or micro supplier" in advisory.message


async def test_the_advisory_computes_no_liability_and_names_no_figure(
    db_session: AsyncSession,
) -> None:
    """It states the rule and stops. A calculated interest figure would be a number this platform
    has no basis for: it does not hold the payment date, and it does not know whether the
    counterparty is registered."""
    transaction = await dated_transaction(
        db_session,
        invoice_date=(utcnow().date() - timedelta(days=2)).isoformat(),
        territory=Territory.INDIA.value,
    )

    advisory = next(
        row
        for row in await rule_engine.run_validation(db_session, transaction)
        if row.check_key == CheckKey.INDIA_PAYMENT_TERMS_ADVISORY
    )

    assert "it does not calculate any liability" in advisory.message
    for forbidden in ("%", "interest of", "45 day", "AED", "USD"):
        assert forbidden not in advisory.message


async def test_a_non_india_transaction_carries_no_advisory(db_session: AsyncSession) -> None:
    transaction = await dated_transaction(
        db_session,
        invoice_date=(utcnow().date() - timedelta(days=2)).isoformat(),
        territory=Territory.CHINA.value,
    )

    evaluations = await rule_engine.run_validation(db_session, transaction)

    assert not [
        row for row in evaluations if row.check_key == CheckKey.INDIA_PAYMENT_TERMS_ADVISORY
    ]


# --- what it must never do ------------------------------------------------------------------------


async def test_a_backdated_invoice_opens_no_exception_case(db_session: AsyncSession) -> None:
    """An acknowledgeable flag never reaches the hard-fail hook, so it never opens a case.

    That is deliberate and is the reason no `rule_exception_mappings` row was written for IV-01: a
    queue entry demanding somebody resolve an unconfirmed policy is exactly the noise this rule is
    written to avoid.
    """
    months = await configured_months(db_session)
    stale = (months_before(utcnow().date(), months) - timedelta(days=40)).isoformat()
    transaction = await dated_transaction(db_session, invoice_date=stale)

    await rule_engine.run_validation(db_session, transaction)
    await db_session.commit()

    cases = list(
        (
            await db_session.scalars(
                select(ExceptionCase).where(ExceptionCase.transaction_id == transaction.id)
            )
        ).all()
    )
    assert [case for case in cases if case.rule_id == RuleId.IV_01] == []


async def test_the_desk_clears_the_flag_itself_and_the_transaction_then_submits(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    """End to end through the existing endpoints, with no change made to either of them.

    The acknowledgement endpoint was written for BR-06's middle tier and asks the evaluation for
    its severity rather than naming a rule. IV-01 is self-approvable through it because it carries
    the same severity - which is the whole of what "the same severity model" was supposed to buy.
    """
    _, headers = await signed_in(
        "00000000-0000-4000-8000-0000000000b1",
        "purchase@agfze.test",
        "Purchase Desk",
        [PlatformRole.PURCHASE_USER.value],
    )
    months = await configured_months(db_session)
    stale = (months_before(utcnow().date(), months) - timedelta(days=10)).isoformat()
    transaction = await dated_transaction(db_session, invoice_date=stale)

    blocked = await client.post(f"{TRANSACTIONS}/{transaction.id}/submit", headers=headers, json={})
    assert blocked.status_code == 409
    assert RuleId.IV_01 in blocked.text

    acknowledged = await client.post(
        f"{TRANSACTIONS}/{transaction.id}/acknowledge-tolerance",
        headers=headers,
        json={
            "rule_id": RuleId.IV_01,
            "check_key": CheckKey.INVOICE_DATE_WINDOW,
            "reason": "Supplier reissued the original March invoice unchanged; date confirmed.",
        },
    )
    assert acknowledged.status_code == 200, acknowledged.text

    submitted = await client.post(
        f"{TRANSACTIONS}/{transaction.id}/submit", headers=headers, json={}
    )
    assert submitted.status_code == 200, submitted.text

    rows = await rule_engine.current_results(db_session, transaction.id)
    check = window_check(rows)
    assert check is not None
    assert check.passed is True
    assert check.acknowledged is True
    assert check.acknowledged_by_id is not None


async def test_an_administrator_can_move_the_window_through_the_existing_screen(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    """No new admin screen, no new endpoint: it is a row in the table /admin/rules already edits."""
    _, headers = await signed_in(
        "00000000-0000-4000-8000-0000000000b2",
        "admin@agfze.test",
        "Administrator",
        [PlatformRole.ADMIN.value],
    )

    listed = await client.get("/api/v1/admin/rules", headers=headers, params={"rule_id": "IV-01"})
    assert listed.status_code == 200
    row = listed.json()["data"]["items"][0]
    assert row["rule_id"] == RuleId.IV_01
    assert row["check_key"] == CheckKey.INVOICE_DATE_WINDOW
    assert row["rule_title"] == "Invoice dating"

    updated = await client.patch(
        f"/api/v1/admin/rules/{row['id']}",
        headers=headers,
        json={
            "threshold_value": "6",
            "change_reason": "Finance confirmed a six-month window for the Gulf suppliers.",
        },
    )
    assert updated.status_code == 200, updated.text

    # And the engine reads the new value on the very next evaluation.
    four_months_ago = (months_before(utcnow().date(), 4)).isoformat()
    transaction = await dated_transaction(db_session, invoice_date=four_months_ago)
    check = window_check(await rule_engine.run_validation(db_session, transaction))

    assert check is not None
    assert check.passed is True, "the engine is still reading the old three-month window"


async def test_a_deactivated_row_leaves_the_rule_flagging_rather_than_blocking(
    db_session: AsyncSession,
) -> None:
    """Every other rule hard-fails when its threshold is missing. This one must not.

    An unconfirmed policy whose row an administrator switched off must not become the thing that
    stops a desk from working, so the unconfigured branch is acknowledgeable as well.
    """
    row = await db_session.scalar(
        select(RuleConfiguration).where(
            RuleConfiguration.rule_id == RuleId.IV_01,
            RuleConfiguration.check_key == CheckKey.INVOICE_DATE_WINDOW,
        )
    )
    row.is_active = False
    await db_session.commit()

    transaction = await dated_transaction(
        db_session, invoice_date=(utcnow().date() - timedelta(days=1)).isoformat()
    )
    check = window_check(await rule_engine.run_validation(db_session, transaction))

    assert check is not None
    assert check.passed is False
    assert check.severity == RuleSeverity.ACKNOWLEDGEABLE.value
    assert "no active configuration" in check.message
