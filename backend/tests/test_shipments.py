"""Container tracking, shipment tracking, and the honesty the module is built around.

Two claims are under test here and they pull in opposite directions, which is why both are worth
proving. The first is that the automated path is real: registered adapters are genuinely called,
their results genuinely applied. The second is that the manual path is not a fallback: it writes
the same row, the same columns, through the same function, subject to the same plausibility check
and the same audit trail, and the screen cannot tell the two apart.

The stand-in adapter these tests register is the only carrier implementation anywhere near this
codebase. That is deliberate: no carrier's API is specified in this platform's material, so the
application ships the seam and not a fabricated client, and a test is the right place for a
stand-in to live.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utcnow
from app.models.audit import AuditEvent as AuditEventRow
from app.models.enums import (
    BillOfLadingType,
    ExceptionCategory,
    ShipmentMilestone,
    ShipmentStatus,
)
from app.models.governance import ExceptionCase
from app.models.logistics import Container, Shipment
from app.services.governance import thresholds
from app.services.logistics import shipment_service, tracking_service
from app.services.logistics.adapters import TrackingResult, registered_adapters
from app.services.rules import engine as rule_engine
from app.services.rules.catalog import CheckKey, RuleId
from tests.utils.logistics import (
    CONTAINER_A,
    CONTAINER_B,
    StubCarrierAdapter,
    add_bill_of_lading,
    add_container,
    add_shipment,
    make_user,
    no_adapters,
    use_adapter,
)
from tests.utils.sales import sales_transaction
from tests.utils.transactions import invoice_values, make_document, make_request, make_transaction

pytestmark = pytest.mark.usefixtures("patched_jwks")

BASE = "/api/v1/shipments"


@pytest.fixture(autouse=True)
def empty_adapter_registry():
    """Every test starts in the state every deployment actually ships in: no adapter at all."""
    no_adapters()
    yield
    no_adapters()


async def logistics_user(signed_in):
    return await signed_in("log-1", "log@agfze.test", "Logistics", ["logistics_user"])


async def sales_reader(signed_in):
    return await signed_in("sal-1", "sal@agfze.test", "Sales", ["sales_user"])


# --- containers, created as a side effect of matching -------------------------------------------


async def test_a_confirmed_document_creates_the_containers_it_quotes(
    db_session: AsyncSession,
) -> None:
    """Container capture is a side effect of the link that already happens, not a second ."""
    from app.services import matching_service

    request = await make_request(db_session)
    transaction = await make_transaction(db_session, batch_number="I2626-40")
    document = await make_document(
        db_session,
        request,
        values=invoice_values(container_or_bl_reference=CONTAINER_A),
        transaction_id=transaction.id,
    )

    created = await matching_service.ensure_containers(
        db_session,
        transaction,
        matching_service.document_values(document),
        document=document,
        actor_id=None,
    )
    await db_session.commit()

    assert [row.container_number for row in created] == [CONTAINER_A]

    # Idempotent: the same document confirmed again adds nothing.
    again = await matching_service.ensure_containers(
        db_session,
        transaction,
        matching_service.document_values(document),
        document=document,
        actor_id=None,
    )
    await db_session.commit()
    assert again == []


async def test_a_bill_of_lading_listing_several_containers_creates_each_of_them(
    db_session: AsyncSession,
) -> None:
    from app.services import matching_service

    transaction = await make_transaction(db_session, batch_number="I2626-41")

    created = await matching_service.ensure_containers(
        db_session,
        transaction,
        {"container_numbers": f"{CONTAINER_A}, {CONTAINER_B}"},
        document=None,
        actor_id=None,
    )
    await db_session.commit()

    assert {row.container_number for row in created} == {CONTAINER_A, CONTAINER_B}


async def test_a_bill_of_lading_number_is_never_mistaken_for_a_container(
    db_session: AsyncSession,
) -> None:
    """The invoice schema's field holds a container *or* a B/L reference, and they differ."""
    from app.services.rules.logistics_evaluators import normalise_container_number

    assert normalise_container_number(CONTAINER_A) == CONTAINER_A
    assert normalise_container_number("msku 778 1234") == CONTAINER_A
    assert normalise_container_number("MAEU-2026-77812") is None
    assert normalise_container_number("") is None


async def test_container_creation_is_audited(db_session: AsyncSession) -> None:
    from app.services import matching_service

    transaction = await make_transaction(db_session, batch_number="I2626-42")
    await matching_service.ensure_containers(
        db_session,
        transaction,
        {"container_numbers": CONTAINER_A},
        document=None,
        actor_id=None,
    )
    await db_session.commit()

    events = (
        await db_session.scalars(
            select(AuditEventRow).where(
                AuditEventRow.event_type == "transaction.container_recorded"
            )
        )
    ).all()
    assert len(events) == 1
    assert events[0].event_metadata["container_numbers"] == [CONTAINER_A]


# --- BR-03 ---------------------------------------------------------------------------------------


async def test_br03_does_not_flag_a_batch_that_spans_several_containers(
    db_session: AsyncSession,
) -> None:
    """The prohibition, tested directly. More than one container is ordinary loading."""
    transaction = await make_transaction(db_session, batch_number="I2626-43")
    await add_container(db_session, transaction, container_number=CONTAINER_A)
    await add_container(db_session, transaction, container_number=CONTAINER_B)
    await db_session.commit()

    written = await rule_engine.run_validation(db_session, transaction)
    await db_session.commit()

    outcome = next(row for row in written if row.rule_id == RuleId.BR_03)
    assert outcome.passed is True
    assert outcome.check_key == CheckKey.CONTAINER_CROSS_TRANSACTION
    assert "2 containers" in (outcome.actual_value or "")


async def test_br03_flags_a_container_already_held_by_a_different_transaction(
    db_session: AsyncSession,
) -> None:
    """A genuine cross-transaction conflict: one physical box, two deals."""
    first = await make_transaction(db_session, batch_number="I2626-44")
    await add_container(db_session, first, container_number=CONTAINER_A)

    second = await make_transaction(
        db_session, batch_number="I2626-45", invoice_number="INV-2026-0999"
    )
    await add_container(db_session, second, container_number=CONTAINER_A)
    await db_session.commit()

    written = await rule_engine.run_validation(db_session, second)
    await db_session.commit()

    outcome = next(row for row in written if row.rule_id == RuleId.BR_03)
    assert outcome.passed is False
    assert outcome.severity == "hard"
    assert "I2626-44" in outcome.message
    assert CONTAINER_A in outcome.message


async def test_br03_passes_when_nothing_has_been_recorded_yet(
    db_session: AsyncSession,
) -> None:
    transaction = await make_transaction(db_session, batch_number="I2626-46")
    await db_session.commit()

    written = await rule_engine.run_validation(db_session, transaction)
    await db_session.commit()

    outcome = next(row for row in written if row.rule_id == RuleId.BR_03)
    assert outcome.passed is True
    assert "nothing whose ownership could be in dispute" in outcome.message


async def test_a_container_conflict_opens_a_logistics_owned_exception(
    db_session: AsyncSession,
) -> None:
    """Through the ordinary mapping table, with no branch anywhere."""
    first = await make_transaction(db_session, batch_number="I2626-47")
    await add_container(db_session, first, container_number=CONTAINER_A)
    second = await make_transaction(
        db_session, batch_number="I2626-48", invoice_number="INV-2026-0888"
    )
    await add_container(db_session, second, container_number=CONTAINER_A)
    await db_session.commit()

    await rule_engine.run_validation(db_session, second)
    await db_session.commit()

    case = await db_session.scalar(
        select(ExceptionCase).where(
            ExceptionCase.transaction_id == second.id,
            ExceptionCase.exception_type == ExceptionCategory.MISMATCHED_CONTAINER_NUMBER.value,
        )
    )
    assert case is not None
    assert case.owner_role == "logistics_user"
    assert case.rule_id == RuleId.BR_03


# --- BR-07 now reads the real entity -------------------------------------------------------------


async def test_br07_reads_the_bill_of_lading_record_rather_than_the_document_type(
    db_session: AsyncSession,
) -> None:
    """The upgrade Section 9.6 asks for.

    An original B/L *document* is attached, which used to be enough on its own. A bill-of-lading
    record now exists beside it saying the original has not arrived, and that record is the
    authority: submission waits for the paper, not for the file.
    """
    transaction = await sales_transaction(db_session, batch_number="I2626-50")
    shipment = await add_shipment(db_session, transaction)
    await add_bill_of_lading(db_session, shipment, received=False)
    await db_session.commit()

    written = await rule_engine.run_validation(db_session, transaction)
    await db_session.commit()

    final = next(
        row
        for row in written
        if row.rule_id == RuleId.BR_07 and row.check_key == CheckKey.FINAL_BL_PRESENT
    )
    assert final.passed is False
    assert "not been marked as received" in final.message


async def test_br07_passes_once_the_original_is_recorded_as_received(
    db_session: AsyncSession,
) -> None:
    transaction = await sales_transaction(db_session, batch_number="I2626-51")
    shipment = await add_shipment(db_session, transaction)
    bill = await add_bill_of_lading(db_session, shipment, received=False)
    await db_session.commit()

    bill.is_original_received = True
    bill.received_at = utcnow()
    await db_session.commit()

    written = await rule_engine.run_validation(db_session, transaction)
    await db_session.commit()

    final = next(
        row
        for row in written
        if row.rule_id == RuleId.BR_07 and row.check_key == CheckKey.FINAL_BL_PRESENT
    )
    assert final.passed is True
    assert "recorded as received" in final.message


async def test_a_draft_bill_record_never_satisfies_the_submission_check(
    db_session: AsyncSession,
) -> None:
    transaction = await sales_transaction(db_session, batch_number="I2626-52")
    shipment = await add_shipment(db_session, transaction)
    await add_bill_of_lading(
        db_session, shipment, bl_type=BillOfLadingType.DRAFT.value, received=True
    )
    await db_session.commit()

    written = await rule_engine.run_validation(db_session, transaction)
    await db_session.commit()

    final = next(
        row
        for row in written
        if row.rule_id == RuleId.BR_07 and row.check_key == CheckKey.FINAL_BL_PRESENT
    )
    assert final.passed is False


async def test_the_document_type_signal_still_answers_where_no_record_exists(
    db_session: AsyncSession,
) -> None:
    """The looser signal remains, as the supporting one, for a shipment nobody has opened yet."""
    transaction = await sales_transaction(db_session, batch_number="I2626-53")
    await db_session.commit()

    written = await rule_engine.run_validation(db_session, transaction)
    await db_session.commit()

    final = next(
        row
        for row in written
        if row.rule_id == RuleId.BR_07 and row.check_key == CheckKey.FINAL_BL_PRESENT
    )
    assert final.passed is True
    assert "no shipment record contradicts it" in final.message


# --- the tracking orchestration -------------------------------------------------------------------


async def test_the_sweep_calls_a_registered_adapter_and_applies_what_it_returns(
    db_session: AsyncSession,
) -> None:
    transaction = await make_transaction(db_session, batch_number="I2626-60")
    container = await add_container(db_session, transaction)
    shipment = await add_shipment(
        db_session, transaction, container=container, milestone=ShipmentMilestone.LOADED.value
    )
    await db_session.commit()

    adapter = use_adapter(StubCarrierAdapter())
    outcome = await tracking_service.refresh_shipment(db_session, shipment)
    await db_session.commit()

    assert adapter.calls, "the orchestration never called the registered adapter"
    assert adapter.calls[0].container_number == CONTAINER_A
    assert outcome.attempted is True
    assert outcome.updated is True
    assert outcome.adapter == "stub-carrier"
    # The free-text description was mapped onto the fixed vocabulary deterministically.
    assert shipment.current_milestone == ShipmentMilestone.DEPARTED.value
    assert shipment.eta == date(2026, 9, 12)
    assert shipment.last_checked_source == "stub-carrier"
    assert shipment.consecutive_failures == 0


async def test_a_shipment_with_no_adapter_is_left_for_manual_entry_on_the_same_row(
    db_session: AsyncSession,
) -> None:
    """The path almost every shipment takes, and it is not treated as a failure.

    Nothing is written, nothing is invented, the failure counter does not move, and the message
    the desk is given points at the manual fields rather than apologising for an integration that
    was never promised.
    """
    transaction = await make_transaction(db_session, batch_number="I2626-61")
    shipment = await add_shipment(db_session, transaction)
    await db_session.commit()
    before = shipment.current_milestone

    assert registered_adapters() == ()
    outcome = await tracking_service.refresh_shipment(db_session, shipment)
    await db_session.commit()

    assert outcome.attempted is False
    assert outcome.updated is False
    assert outcome.adapter is None
    assert "kept up to date by hand" in outcome.message
    assert shipment.current_milestone == before
    assert shipment.consecutive_failures == 0


async def test_the_manual_path_writes_the_identical_row_the_adapter_would(
    db_session: AsyncSession,
) -> None:
    """The claim the whole module rests on, tested by comparing the two side by side."""
    transaction = await make_transaction(db_session, batch_number="I2626-62")
    automated = await add_shipment(db_session, transaction)
    manual = await add_shipment(db_session, transaction, bl_number="MAEU-2026-77813")
    await db_session.commit()

    use_adapter(
        StubCarrierAdapter(
            result=TrackingResult(
                available=True,
                milestone="in_transit",
                status=ShipmentStatus.ON_SCHEDULE.value,
                eta=date(2026, 9, 20),
                vessel="MV Northern Trader",
            )
        )
    )
    await tracking_service.refresh_shipment(db_session, automated)

    user = await make_user(db_session, roles=["logistics_user"])
    await tracking_service.apply_manual_update(
        db_session,
        manual,
        tracking_service.ShipmentUpdate(
            status=ShipmentStatus.ON_SCHEDULE.value,
            milestone="in_transit",
            eta=date(2026, 9, 20),
            vessel="MV Northern Trader",
        ),
        user=user,
    )
    await db_session.commit()

    tracked = (
        automated.status,
        automated.current_milestone,
        automated.eta,
        automated.vessel,
    )
    typed = (manual.status, manual.current_milestone, manual.eta, manual.vessel)
    assert tracked == typed
    # Both had their check timestamp moved; only the recorded source differs, which is exactly
    # where a question about provenance belongs.
    assert automated.last_checked_at is not None
    assert manual.last_checked_at is not None
    assert automated.last_checked_source == "stub-carrier"
    assert manual.last_checked_source == "manual"


async def test_a_failing_adapter_counts_the_failure_and_leaves_the_shipment_alone(
    db_session: AsyncSession,
) -> None:
    transaction = await make_transaction(db_session, batch_number="I2626-63")
    shipment = await add_shipment(db_session, transaction)
    await db_session.commit()
    before = shipment.last_checked_at

    use_adapter(StubCarrierAdapter(raises=True))
    outcome = await tracking_service.refresh_shipment(db_session, shipment)
    await db_session.commit()

    assert outcome.attempted is True
    assert outcome.updated is False
    assert shipment.consecutive_failures == 1
    assert shipment.last_error
    # A refusal is not a check, so the staleness clock is deliberately not reset by one.
    assert shipment.last_checked_at == before


async def test_an_unavailable_result_is_distinguished_from_a_quiet_shipment(
    db_session: AsyncSession,
) -> None:
    transaction = await make_transaction(db_session, batch_number="I2626-64")
    shipment = await add_shipment(db_session, transaction)
    await db_session.commit()

    use_adapter(
        StubCarrierAdapter(result=TrackingResult.unavailable("this container is not on our books"))
    )
    outcome = await tracking_service.refresh_shipment(db_session, shipment)
    await db_session.commit()

    assert outcome.updated is False
    assert "not on our books" in shipment.last_error


def test_the_milestone_keyword_table_reads_the_phrases_carriers_actually_use() -> None:
    assert tracking_service.keyword_milestone("Vessel departure from Jebel Ali") == "departed"
    assert tracking_service.keyword_milestone("Discharged at Nhava Sheva") == "discharged"
    assert tracking_service.keyword_milestone("Gate out - delivered to ICD") == "delivered"
    # Nothing recognised stays unread rather than being guessed at.
    assert tracking_service.keyword_milestone("some prose nobody wrote a rule for") is None
    assert tracking_service.keyword_status("Rolled to the next vessel") == "delayed"


# --- plausibility ----------------------------------------------------------------------------------


async def test_an_implausible_eta_is_flagged_and_neither_blocked_nor_silently_accepted(
    db_session: AsyncSession,
) -> None:
    """All three halves of the requirement in one test, because all three matter."""
    transaction = await make_transaction(db_session, batch_number="I2626-70")
    shipment = await add_shipment(db_session, transaction, eta=date(2026, 9, 30))
    await db_session.commit()
    user = await make_user(db_session, roles=["logistics_user"])

    outcome = await tracking_service.apply_manual_update(
        db_session,
        shipment,
        # Three weeks earlier in one update, well past the configured five-day margin.
        tracking_service.ShipmentUpdate(eta=date(2026, 9, 9)),
        user=user,
    )
    await db_session.commit()

    # Flagged...
    assert outcome.plausibility.flagged is True
    assert "moved 21 days earlier" in (outcome.plausibility.reason or "")
    assert shipment.review_flagged is True
    assert shipment.review_reason
    # ...not blocked: the change is saved, because the earlier figure was more likely the wrong one.
    assert shipment.eta == date(2026, 9, 9)
    # ...and not silent: the audit entry says so explicitly on every update, flagged or not.
    events = (
        await db_session.scalars(
            select(AuditEventRow).where(
                AuditEventRow.event_type == shipment_service.AuditEvent.SHIPMENT_REVIEW_FLAGGED
            )
        )
    ).all()
    assert len(events) == 1
    assert events[0].event_metadata["blocked"] is False


async def test_a_believable_eta_change_is_accepted_without_a_flag(
    db_session: AsyncSession,
) -> None:
    transaction = await make_transaction(db_session, batch_number="I2626-71")
    shipment = await add_shipment(db_session, transaction, eta=date(2026, 9, 30))
    await db_session.commit()
    user = await make_user(db_session, roles=["logistics_user"])

    outcome = await tracking_service.apply_manual_update(
        db_session,
        shipment,
        tracking_service.ShipmentUpdate(eta=date(2026, 9, 28)),
        user=user,
    )
    await db_session.commit()

    assert outcome.plausibility.flagged is False
    assert shipment.review_flagged is False
    assert shipment.eta == date(2026, 9, 28)


async def test_a_milestone_going_backwards_past_discharge_is_flagged(
    db_session: AsyncSession,
) -> None:
    transaction = await make_transaction(db_session, batch_number="I2626-72")
    shipment = await add_shipment(
        db_session, transaction, milestone=ShipmentMilestone.DISCHARGED.value
    )
    await db_session.commit()
    user = await make_user(db_session, roles=["logistics_user"])

    outcome = await tracking_service.apply_manual_update(
        db_session,
        shipment,
        tracking_service.ShipmentUpdate(milestone=ShipmentMilestone.IN_TRANSIT.value),
        user=user,
    )
    await db_session.commit()

    assert outcome.plausibility.flagged is True
    assert "does not un-discharge" in (outcome.plausibility.reason or "")
    assert shipment.current_milestone == ShipmentMilestone.IN_TRANSIT.value


# --- staleness into the exception queue -----------------------------------------------------------


async def test_a_stale_shipment_opens_a_logistics_owned_exception(
    db_session: AsyncSession,
) -> None:
    """Past the configured threshold, an owned, ageing case appears in the ordinary queue."""
    stale_hours = float(
        await thresholds.resolve(db_session, thresholds.GovernanceKey.SHIPMENT_STALE_HOURS)
    )
    assert stale_hours == 48.0

    transaction = await make_transaction(db_session, batch_number="I2626-80")
    shipment = await add_shipment(db_session, transaction, checked_hours_ago=stale_hours + 5)
    await db_session.commit()

    result = await tracking_service.run_sweep(db_session)
    await db_session.commit()

    assert result.exceptions_opened == 1
    case = await db_session.scalar(
        select(ExceptionCase).where(
            ExceptionCase.transaction_id == transaction.id,
            ExceptionCase.exception_type == ExceptionCategory.SHIPMENT_STATUS_UNAVAILABLE.value,
        )
    )
    assert case is not None
    assert case.owner_role == "logistics_user"
    assert case.field_name == "last_checked_at"
    # No rule behind it, because no rule evaluated anything - which is the honest record.
    assert case.rule_id is None
    assert case.check_key is None
    del shipment


async def test_the_stale_case_is_created_directly_and_never_through_a_synthetic_rule(
    db_session: AsyncSession,
) -> None:
    """The prohibition, tested where it would actually be broken.

    Shipment staleness is not a check on extracted data. If it were dressed up as one to reuse the
    hard-fail hook, a `rule_evaluations` row would appear naming a rule that never ran - and an
    auditor reading that table would be reading a fabrication.
    """
    from app.models.transactions import RuleEvaluation

    transaction = await make_transaction(db_session, batch_number="I2626-81")
    await add_shipment(db_session, transaction, checked_hours_ago=100)
    await db_session.commit()

    before = len(
        (
            await db_session.scalars(
                select(RuleEvaluation).where(RuleEvaluation.transaction_id == transaction.id)
            )
        ).all()
    )
    await tracking_service.run_sweep(db_session)
    await db_session.commit()

    after = list(
        (
            await db_session.scalars(
                select(RuleEvaluation).where(RuleEvaluation.transaction_id == transaction.id)
            )
        ).all()
    )
    assert len(after) == before
    assert not any(row.rule_id.startswith("SHIP") for row in after)


async def test_repeated_tracking_failures_age_a_shipment_in_on_their_own(
    db_session: AsyncSession,
) -> None:
    limit = int(
        await thresholds.resolve(db_session, thresholds.GovernanceKey.SHIPMENT_FAILURE_LIMIT)
    )
    transaction = await make_transaction(db_session, batch_number="I2626-82")
    shipment = await add_shipment(
        db_session, transaction, checked_hours_ago=1, consecutive_failures=limit
    )
    await db_session.commit()

    result = await tracking_service.run_sweep(db_session)
    await db_session.commit()

    assert result.exceptions_opened == 1
    case = await db_session.scalar(
        select(ExceptionCase).where(ExceptionCase.transaction_id == transaction.id)
    )
    assert "consecutive tracking attempts have failed" in case.summary
    del shipment


async def test_a_recently_checked_shipment_opens_nothing(db_session: AsyncSession) -> None:
    transaction = await make_transaction(db_session, batch_number="I2626-83")
    await add_shipment(db_session, transaction, checked_hours_ago=2)
    await db_session.commit()

    result = await tracking_service.run_sweep(db_session)
    await db_session.commit()

    assert result.exceptions_opened == 0
    assert result.left_for_manual == 1


async def test_a_delivered_shipment_is_not_aged_into_the_queue(
    db_session: AsyncSession,
) -> None:
    """A finished shipment is not a silent one, and a queue full of them is a queue nobody reads."""
    transaction = await make_transaction(db_session, batch_number="I2626-84")
    await add_shipment(
        db_session,
        transaction,
        checked_hours_ago=500,
        status=ShipmentStatus.ARRIVED.value,
        milestone=ShipmentMilestone.DELIVERED.value,
    )
    await db_session.commit()

    result = await tracking_service.run_sweep(db_session)
    await db_session.commit()

    assert result.considered == 0
    assert result.exceptions_opened == 0


# --- the milestone timeline is derived, never stored ----------------------------------------------


async def test_the_timeline_is_derived_from_audit_events_with_no_history_table(
    db_session: AsyncSession,
) -> None:
    from app.models import Base

    transaction = await make_transaction(db_session, batch_number="I2626-90")
    shipment = await shipment_service.open_shipment(db_session, transaction, carrier="Sample Line")
    user = await make_user(db_session, roles=["logistics_user"])
    await tracking_service.apply_manual_update(
        db_session,
        shipment,
        tracking_service.ShipmentUpdate(
            milestone=ShipmentMilestone.DEPARTED.value, note="Carrier confirmed by telephone."
        ),
        user=user,
    )
    await db_session.commit()

    timeline = await shipment_service.milestone_timeline(db_session, shipment)

    assert [entry.event_type for entry in timeline] == [
        shipment_service.AuditEvent.SHIPMENT_OPENED,
        shipment_service.AuditEvent.SHIPMENT_STATUS_UPDATED,
    ]
    assert timeline[-1].milestone == ShipmentMilestone.DEPARTED.value
    assert timeline[-1].source == "manual"
    assert timeline[-1].actor_name == user.display_name

    # And there is genuinely no second table holding the same facts.
    tables = {table.name for table in Base.metadata.sorted_tables}
    assert "shipment_milestones" not in tables
    assert "shipment_status_history" not in tables
    assert "shipment_events" not in tables


# --- the API ---------------------------------------------------------------------------------------


async def test_any_signed_in_account_reads_the_board(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    transaction = await make_transaction(db_session, batch_number="I2626-100")
    await add_shipment(db_session, transaction, checked_hours_ago=100)
    await db_session.commit()
    _, headers = await sales_reader(signed_in)

    response = await client.get(BASE, headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()["data"]
    assert body["items"][0]["batch_number"] == "I2626-100"
    assert body["items"][0]["is_stale"] is True
    assert body["items"][0]["stale_threshold_hours"] == 48
    # The board is readable, but this account may not change anything on it.
    assert body["can_manage"] is False
    # And it says plainly that no carrier source exists, rather than leaving a user to wonder.
    assert body["carrier_adapters_available"] == 0


async def test_the_board_filters_on_status_carrier_and_discharge_port(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    transaction = await make_transaction(db_session, batch_number="I2626-101")
    await add_shipment(db_session, transaction, carrier="Line A", port_of_discharge="Nhava Sheva")
    await add_shipment(
        db_session,
        transaction,
        bl_number="OTHER-1",
        carrier="Line B",
        port_of_discharge="Shanghai",
        status=ShipmentStatus.DELAYED.value,
    )
    await db_session.commit()
    _, headers = await logistics_user(signed_in)

    by_carrier = await client.get(f"{BASE}?carrier=Line B", headers=headers)
    assert [row["carrier"] for row in by_carrier.json()["data"]["items"]] == ["Line B"]

    by_status = await client.get(f"{BASE}?status=delayed", headers=headers)
    assert [row["status"] for row in by_status.json()["data"]["items"]] == ["delayed"]

    by_port = await client.get(f"{BASE}?port_of_discharge=Shanghai", headers=headers)
    assert len(by_port.json()["data"]["items"]) == 1

    # The filters offer the values actually on the board, read from the data.
    assert set(by_port.json()["data"]["carriers"]) == {"Line A", "Line B"}


async def test_the_board_filters_to_the_shipments_nobody_has_checked_recently(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    """Filtered in the query from the stored timestamp, never from a stored staleness flag.

    The dashboard's "not checked recently" button is the one a logistics user presses first thing
    in the morning, so it has to answer from the same figure the indicator shows rather than from
    anything a job might have left behind.
    """
    transaction = await make_transaction(db_session, batch_number="I2626-108")
    await add_shipment(db_session, transaction, checked_hours_ago=100)
    await add_shipment(db_session, transaction, bl_number="FRESH-1", checked_hours_ago=1)
    # Never checked at all, and created long enough ago to count as silent.
    never = await add_shipment(db_session, transaction, bl_number="NEVER-1", checked_hours_ago=None)
    never.created_at = utcnow() - timedelta(hours=200)
    await db_session.commit()
    _, headers = await logistics_user(signed_in)

    response = await client.get(f"{BASE}?stale_only=true", headers=headers)

    assert response.status_code == 200, response.text
    references = {row["bl_number"] for row in response.json()["data"]["items"]}
    assert "FRESH-1" not in references
    assert "NEVER-1" in references
    assert len(references) == 2


async def test_the_detail_carries_the_timeline_the_issues_and_the_transaction(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    transaction = await make_transaction(db_session, batch_number="I2626-102")
    container = await add_container(db_session, transaction)
    shipment = await shipment_service.open_shipment(
        db_session, transaction, container=container, carrier="Sample Line"
    )
    await db_session.commit()
    _, headers = await logistics_user(signed_in)

    response = await client.get(f"{BASE}/{shipment.id}", headers=headers)

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["container_number"] == CONTAINER_A
    assert data["transaction"]["batch_number"] == "I2626-102"
    assert data["timeline"][0]["event_type"] == shipment_service.AuditEvent.SHIPMENT_OPENED
    assert data["can_manage"] is True
    # The vocabularies the manual form renders its controls from.
    assert ShipmentMilestone.DEPARTED.value in data["milestones"]
    assert ShipmentStatus.DELAYED.value in data["statuses"]


async def test_refresh_opens_the_record_for_manual_entry_when_no_adapter_exists(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    transaction = await make_transaction(db_session, batch_number="I2626-103")
    shipment = await add_shipment(db_session, transaction)
    await db_session.commit()
    _, headers = await logistics_user(signed_in)

    response = await client.post(f"{BASE}/{shipment.id}/refresh", headers=headers)

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["attempted"] is False
    assert data["updated"] is False
    assert "by hand" in data["message"]


async def test_a_manual_update_is_role_gated_audited_and_applied(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    """A hand-typed change is a first-class, authenticated, audited write."""
    transaction = await make_transaction(db_session, batch_number="I2626-104")
    shipment = await add_shipment(db_session, transaction)
    await db_session.commit()

    _, reader = await sales_reader(signed_in)
    refused = await client.patch(
        f"{BASE}/{shipment.id}", headers=reader, json={"milestone": "departed"}
    )
    assert refused.status_code == 403, refused.text

    _, headers = await logistics_user(signed_in)
    response = await client.patch(
        f"{BASE}/{shipment.id}",
        headers=headers,
        json={
            "milestone": "departed",
            "status": "delayed",
            "vessel": "MV Sample Trader",
            "eta": "2026-10-01",
            "note": "Carrier confirmed by telephone.",
        },
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["current_milestone"] == "departed"
    assert data["status"] == "delayed"
    assert data["vessel"] == "MV Sample Trader"
    assert data["last_checked_source"] == "manual"
    assert data["hours_since_check"] < 1
    # And it is on the timeline, indistinguishable in structure from an automated one.
    assert any(
        entry["event_type"] == shipment_service.AuditEvent.SHIPMENT_STATUS_UPDATED
        for entry in data["timeline"]
    )


async def test_recording_the_original_bill_of_lading_re_runs_the_transaction_validation(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    transaction = await sales_transaction(db_session, batch_number="I2626-105")
    shipment = await add_shipment(db_session, transaction)
    await add_bill_of_lading(db_session, shipment, received=False)
    await db_session.commit()
    await rule_engine.run_validation(db_session, transaction)
    await db_session.commit()

    _, headers = await logistics_user(signed_in)
    response = await client.patch(
        f"{BASE}/{shipment.id}",
        headers=headers,
        json={"bl_type": "original", "original_bl_received": True},
    )
    assert response.status_code == 200, response.text

    current = await rule_engine.current_results(db_session, transaction.id)
    final = next(
        row
        for row in current
        if row.rule_id == RuleId.BR_07 and row.check_key == CheckKey.FINAL_BL_PRESENT
    )
    assert final.passed is True


async def test_an_issue_is_logged_against_the_shipment_and_appears_on_its_timeline(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    transaction = await make_transaction(db_session, batch_number="I2626-106")
    shipment = await add_shipment(db_session, transaction)
    await db_session.commit()
    _, headers = await logistics_user(signed_in)

    response = await client.post(
        f"{BASE}/{shipment.id}/issues",
        headers=headers,
        json={
            "issue_type": "damage",
            "description": "Two bales water-damaged on arrival at the ICD.",
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["data"]["issue_type"] == "damage"

    detail = await client.get(f"{BASE}/{shipment.id}", headers=headers)
    body = detail.json()["data"]
    assert len(body["issues"]) == 1
    assert any(
        entry["event_type"] == shipment_service.AuditEvent.SHIPMENT_ISSUE_LOGGED
        for entry in body["timeline"]
    )


async def test_an_issue_needs_a_real_description(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    transaction = await make_transaction(db_session, batch_number="I2626-107")
    shipment = await add_shipment(db_session, transaction)
    await db_session.commit()
    _, headers = await logistics_user(signed_in)

    response = await client.post(
        f"{BASE}/{shipment.id}/issues",
        headers=headers,
        json={"issue_type": "damage", "description": "bad"},
    )

    assert response.status_code == 422, response.text


# --- shipment status where a transaction is viewed ------------------------------------------------


async def test_the_transaction_list_shows_the_real_linked_shipment_status(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    """The column that has been an honest placeholder since , populated for real."""
    tracked = await make_transaction(db_session, batch_number="I2626-110")
    await add_shipment(db_session, tracked, status=ShipmentStatus.DELAYED.value)
    untracked = await make_transaction(
        db_session, batch_number="I2626-111", invoice_number="INV-2026-0777"
    )
    await db_session.commit()
    _, headers = await signed_in("buy-9", "buy9@agfze.test", "Buyer", ["purchase_user"])

    response = await client.get("/api/v1/transactions", headers=headers)

    rows = {row["batch_number"]: row for row in response.json()["data"]["items"]}
    assert rows["I2626-110"]["shipment_status"] == ShipmentStatus.DELAYED.value
    assert rows["I2626-110"]["shipment_count"] == 1
    # Null still means "no shipment record exists", which is not the same as "on schedule".
    assert rows["I2626-111"]["shipment_status"] is None
    del untracked


async def test_the_worst_status_wins_where_a_batch_has_several_shipments(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    transaction = await make_transaction(db_session, batch_number="I2626-112")
    await add_shipment(db_session, transaction, status=ShipmentStatus.ARRIVED.value)
    await add_shipment(
        db_session,
        transaction,
        bl_number="OTHER-2",
        status=ShipmentStatus.EXCEPTION.value,
    )
    await db_session.commit()
    _, headers = await signed_in("buy-8", "buy8@agfze.test", "Buyer", ["purchase_user"])

    response = await client.get("/api/v1/transactions?search=I2626-112", headers=headers)

    row = response.json()["data"]["items"][0]
    assert row["shipment_status"] == ShipmentStatus.EXCEPTION.value


async def test_the_purchase_workspace_shows_its_linked_shipment(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    transaction = await make_transaction(db_session, batch_number="I2626-113")
    container = await add_container(db_session, transaction)
    await add_shipment(db_session, transaction, container=container, checked_hours_ago=100)
    await db_session.commit()
    _, headers = await signed_in("buy-7", "buy7@agfze.test", "Buyer", ["purchase_user"])

    response = await client.get(f"/api/v1/transactions/{transaction.id}", headers=headers)

    data = response.json()["data"]
    assert len(data["linked_shipments"]) == 1
    assert data["linked_shipments"][0]["container_number"] == CONTAINER_A
    assert data["linked_shipments"][0]["is_stale"] is True
    assert data["shipment_status"] == ShipmentStatus.ON_SCHEDULE.value
    assert data["shipment_stale"] is True
    assert data["containers"][0]["container_number"] == CONTAINER_A


async def test_the_sales_workspace_shows_its_linked_shipment_too(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    transaction = await sales_transaction(db_session, batch_number="I2626-114")
    shipment = await add_shipment(db_session, transaction)
    await add_bill_of_lading(db_session, shipment, received=True)
    await db_session.commit()
    _, headers = await sales_reader(signed_in)

    response = await client.get(f"/api/v1/transactions/{transaction.id}", headers=headers)

    data = response.json()["data"]
    assert data["has_sales_leg"] is True
    assert len(data["linked_shipments"]) == 1
    # The field BR-07 blocks on, in front of the desk that has to act on it.
    assert data["linked_shipments"][0]["original_bl_received"] is True


async def test_a_stale_shipment_shows_a_time_since_check_before_any_exception_exists(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    """The indicator is simpler than, and separate from, the formal exception it may trigger."""
    transaction = await make_transaction(db_session, batch_number="I2626-115")
    await add_shipment(db_session, transaction, checked_hours_ago=30)
    await db_session.commit()
    _, headers = await logistics_user(signed_in)

    response = await client.get(BASE, headers=headers)
    row = response.json()["data"]["items"][0]

    assert 29 <= row["hours_since_check"] <= 31
    assert row["is_stale"] is False
    # Nothing was opened, because 30 hours is inside the configured 48.
    cases = (
        await db_session.scalars(
            select(ExceptionCase).where(
                ExceptionCase.exception_type == ExceptionCategory.SHIPMENT_STATUS_UNAVAILABLE.value
            )
        )
    ).all()
    assert cases == []


# --- what the platform deliberately does not ship --------------------------------------------------


def test_no_concrete_carrier_adapter_ships_with_the_application() -> None:
    """The prohibition, checked where it would be broken: in the application, not the tests.

    A registry that is empty on a fresh import is the whole evidence. If somebody adds a
    plausible-looking client for a named carrier, this fails - which is the point, because no
    carrier's API is specified anywhere in this platform's material and a client written against
    a guess would be a fabricated integration.
    """
    from pathlib import Path

    import app.services.logistics.adapters as adapters_module

    source = Path(adapters_module.__file__).read_text()
    for carrier in ("maersk", "msc", "cma cgm", "hapag", "evergreen", "cosco", "one line"):
        assert carrier not in source.lower(), (
            f"the adapter module names '{carrier}'. No carrier's API is specified for this "
            "platform, so no concrete adapter may ship against one."
        )
    assert registered_adapters() == ()


async def test_the_sweep_records_that_it_looked_and_found_nothing_to_look_at(
    db_session: AsyncSession,
) -> None:
    """The honest history of a shipment no carrier can be asked about."""
    transaction = await make_transaction(db_session, batch_number="I2626-120")
    shipment = await add_shipment(db_session, transaction)
    await db_session.commit()

    await tracking_service.run_sweep(db_session)
    await db_session.commit()

    attempt = await db_session.scalar(
        select(AuditEventRow).where(
            AuditEventRow.entity_id == str(shipment.id),
            AuditEventRow.event_type == shipment_service.AuditEvent.SHIPMENT_TRACKING_ATTEMPTED,
        )
    )
    assert attempt is not None
    assert attempt.event_metadata["adapters_registered"] == 0
    assert attempt.event_metadata["adapters_matching"] == []


async def test_containers_and_shipments_did_not_alter_the_parent_table() -> None:
    from sqlalchemy import inspect as sa_inspect

    from app.models.transactions import TradeTransaction

    columns = {column.name for column in sa_inspect(TradeTransaction).columns}
    assert "container_id" not in columns
    assert "shipment_id" not in columns
    assert {column.name for column in sa_inspect(Container).columns} >= {
        "transaction_id",
        "container_number",
    }
    assert {column.name for column in sa_inspect(Shipment).columns} >= {
        "transaction_id",
        "last_checked_at",
    }


async def test_hours_since_check_counts_from_creation_when_nothing_has_checked(
    db_session: AsyncSession,
) -> None:
    """A shipment nobody has ever checked is the least-known one on the board, not the freshest."""
    transaction = await make_transaction(db_session, batch_number="I2626-121")
    shipment = await add_shipment(db_session, transaction, checked_hours_ago=None)
    shipment.created_at = utcnow() - timedelta(hours=72)
    await db_session.commit()

    assert shipment.last_checked_at is None
    assert shipment_service.hours_since_check(shipment) >= 71
