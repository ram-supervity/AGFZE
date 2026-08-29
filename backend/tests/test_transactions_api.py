"""The `/transactions` surface: reads, manual registration, corrections, acknowledgement, submit.

Every role check here is made against the API rather than against a helper, because the point of
the check is that the server refuses - a frontend that never renders the button proves nothing.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import func, inspect, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.models.audit import AuditEvent
from app.models.enums import DocumentType, RuleSeverity, TransactionStatus
from app.models.transactions import RuleEvaluation, TradeTransaction
from app.services import transaction_service
from app.services.rules import engine as rule_engine
from app.services.rules.catalog import CheckKey, RuleId
from tests.utils.transactions import (
    CONTRACT,
    SUPPLIER,
    contract_values,
    invoice_values,
    make_document,
    make_request,
    make_transaction,
)

pytestmark = pytest.mark.usefixtures("patched_jwks")

BASE = "/api/v1/transactions"


async def purchase_user(signed_in):
    return await signed_in(
        "0a1b2c3d-0000-4000-8000-00000000c001",
        "purchase.desk@agfze.ae",
        "Marco Bellini",
        ["purchase_user"],
    )


async def approver(signed_in):
    return await signed_in(
        "0a1b2c3d-0000-4000-8000-00000000c002",
        "hod.desk@agfze.ae",
        "Priya Raghunathan",
        ["approver_hod"],
    )


async def auditor(signed_in):
    return await signed_in(
        "0a1b2c3d-0000-4000-8000-00000000c003",
        "auditor.desk@agfze.ae",
        "Kenji Watanabe",
        ["auditor"],
    )


NEW_TRANSACTION_BODY = {
    "stream": "scrap",
    "supplier_name": SUPPLIER,
    "contract_number": CONTRACT,
    "supplier_invoice_number": "INV-2026-0451",
    "invoice_status": "provisional",
    "commodity_code": "CU",
    "quantity_mt": "24.5",
    "price_basis": "fixed",
    "currency": "USD",
    "rate": "8125.00",
    "amount": "199062.50",
}


async def _clean_transaction(session: AsyncSession, **invoice_overrides):
    """A transaction whose pack satisfies every rule this  evaluates for real."""
    request = await make_request(session)
    transaction = await make_transaction(session, request=request)
    await make_document(
        session,
        request,
        values=invoice_values(**invoice_overrides),
        document_type=DocumentType.INVOICE.value,
        transaction_id=transaction.id,
    )
    await make_document(
        session,
        request,
        values=contract_values(),
        document_type=DocumentType.CONTRACT.value,
        filename="contract.pdf",
        transaction_id=transaction.id,
    )
    await rule_engine.run_validation(session, transaction)
    await session.commit()
    return transaction


# --- the deferred foreign keys ------------------------------------------------------------------


async def test_both_deferred_foreign_keys_are_constrained_after_this_migration(
    db_engine: AsyncEngine,
) -> None:
    async with db_engine.connect() as connection:

        def _read(sync_connection):
            inspector = inspect(sync_connection)
            return {
                table: inspector.get_foreign_keys(table)
                for table in ("documents", "background_jobs")
            }

        keys = await connection.run_sync(_read)

    for table in ("documents", "background_jobs"):
        targets = {
            (key["referred_table"], tuple(key["constrained_columns"])) for key in keys[table]
        }
        assert ("trade_transactions", ("transaction_id",)) in targets, table


# --- reads ---------------------------------------------------------------------------------------


async def test_every_signed_in_role_may_read_the_list(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    await make_transaction(db_session)
    await db_session.commit()

    for provision in (purchase_user, approver, auditor):
        _, headers = await provision(signed_in)
        response = await client.get(BASE, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["data"]["page"]["total"] == 1


async def test_the_list_reports_an_honest_empty_shipment_column(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    await make_transaction(db_session)
    await db_session.commit()
    _, headers = await purchase_user(signed_in)

    response = await client.get(BASE, headers=headers)

    row = response.json()["data"]["items"][0]
    # Declared for  and honestly empty until there is a shipment to report.
    assert row["shipment_status"] is None


async def test_the_list_filters_sorts_and_paginates(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    await make_transaction(db_session, batch_number="I2626-100")
    await make_transaction(
        db_session,
        batch_number="I2626-200",
        supplier_name="Gulf Recycling FZC",
        contract_number="GRF-2026-01",
        invoice_number="INV-777",
        commodity_code="AL",
    )
    await db_session.commit()
    _, headers = await purchase_user(signed_in)

    assert (await client.get(f"{BASE}?search=gulf", headers=headers)).json()["data"]["page"][
        "total"
    ] == 1
    assert (await client.get(f"{BASE}?commodity_code=AL", headers=headers)).json()["data"]["page"][
        "total"
    ] == 1
    assert (await client.get(f"{BASE}?status=approval_pending", headers=headers)).json()["data"][
        "page"
    ]["total"] == 0

    sorted_response = await client.get(f"{BASE}?sort_by=batch_number&sort_dir=asc", headers=headers)
    codes = [row["batch_number"] for row in sorted_response.json()["data"]["items"]]
    assert codes == ["I2626-100", "I2626-200"]


async def test_the_detail_carries_the_leg_the_rules_and_the_history(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    transaction = await _clean_transaction(db_session)
    _, headers = await purchase_user(signed_in)

    response = await client.get(f"{BASE}/{transaction.id}", headers=headers)

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["purchase_leg"]["supplier_name"] == SUPPLIER
    # The legs the other desks bring are simply absent, which is the honest state of the record.
    assert data["sales_leg"] is None
    assert data["fa_leg"] is None
    assert data["document_count"] == 2
    assert {row["rule_id"] for row in data["rule_evaluations"]} == {
        RuleId.BR_02,
        RuleId.BR_03,
        RuleId.BR_04,
        RuleId.BR_05,
        RuleId.BR_06,
        RuleId.BR_13,
        # The invoice's own date, checked against the configured window. It is on this list
        # because the seeded pack carries an invoice date, and it passes for the same reason.
        RuleId.IV_01,
        # The invoiced weight against the bill of lading's. On this list because it is evaluated
        # for every transaction, and *passing* here because this pack has no bill of lading at
        # all - which is not a discrepancy, it is a comparison there is nothing to make yet.
        RuleId.LG_01,
    }
    assert any(field["name"] == "supplier_name" for field in data["fields"])


async def test_a_placeholder_rule_never_reaches_the_workspace(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    transaction = await _clean_transaction(db_session)
    _, headers = await purchase_user(signed_in)

    response = await client.get(f"{BASE}/{transaction.id}", headers=headers)

    shown = {row["rule_id"] for row in response.json()["data"]["rule_evaluations"]}
    # BR-01 is guaranteed structurally rather than checked, and BR-07 needs a sales leg this
    # transaction does not carry. Neither may be shown as a check somebody has to read.
    assert RuleId.BR_01 not in shown
    assert RuleId.BR_07 not in shown


async def test_an_unknown_transaction_is_a_plain_not_found(client: AsyncClient, signed_in) -> None:
    _, headers = await purchase_user(signed_in)

    response = await client.get(f"{BASE}/{uuid.uuid4()}", headers=headers)

    assert response.status_code == 404


# --- manual registration ---------------------------------------------------------------------


async def test_a_purchase_user_registers_a_transaction_with_no_email_trigger(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    _, headers = await purchase_user(signed_in)

    response = await client.post(BASE, headers=headers, json=NEW_TRANSACTION_BODY)

    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert data["batch_number"].startswith("I")
    assert data["transaction_code"] == data["batch_number"]
    # Zero documents is a normal state for a hand-registered deal, not an error.
    assert data["document_count"] == 0
    assert data["purchase_leg"]["supplier_name"] == SUPPLIER
    # A synthetic portal request satisfies BR-01 exactly as an email-triggered one does.
    assert data["request_code"].startswith("REQ-")


async def test_a_supplied_batch_number_is_kept_and_a_blank_one_is_proposed(
    client: AsyncClient, signed_in
) -> None:
    _, headers = await purchase_user(signed_in)

    supplied = await client.post(
        BASE, headers=headers, json={**NEW_TRANSACTION_BODY, "batch_number": "I2626-642"}
    )
    proposed = await client.post(
        BASE,
        headers=headers,
        json={**NEW_TRANSACTION_BODY, "supplier_invoice_number": "INV-2026-0999"},
    )

    assert supplied.json()["data"]["batch_number"] == "I2626-642"
    assert proposed.json()["data"]["batch_number"] != "I2626-642"


async def test_an_approver_may_not_register_a_transaction(client: AsyncClient, signed_in) -> None:
    _, headers = await approver(signed_in)

    response = await client.post(BASE, headers=headers, json=NEW_TRANSACTION_BODY)

    assert response.status_code == 403


# --- corrections -------------------------------------------------------------------------------


async def test_a_correction_rewrites_the_field_and_re_runs_validation(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    transaction = await _clean_transaction(db_session)
    _, headers = await purchase_user(signed_in)
    before = await db_session.scalar(
        select(func.count(RuleEvaluation.id)).where(RuleEvaluation.transaction_id == transaction.id)
    )

    response = await client.patch(
        f"{BASE}/{transaction.id}/fields",
        headers=headers,
        json={"changes": [{"name": "port_of_loading", "value": "Jebel Ali"}]},
    )

    assert response.status_code == 200, response.text
    after = await db_session.scalar(
        select(func.count(RuleEvaluation.id)).where(RuleEvaluation.transaction_id == transaction.id)
    )
    # New rows, every time. Nothing earlier was rewritten to make room for them.
    assert after > before

    field = next(
        row for row in response.json()["data"]["fields"] if row["name"] == "port_of_loading"
    )
    assert field["value"] == "Jebel Ali"
    assert field["is_overridden"] is True


async def test_a_correction_to_a_low_confidence_field_needs_a_reason(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    request = await make_request(db_session)
    transaction = await make_transaction(db_session, request=request)
    await make_document(
        db_session,
        request,
        values=invoice_values(),
        transaction_id=transaction.id,
        confidences={"supplier_name": 0.41},
    )
    await db_session.commit()
    _, headers = await purchase_user(signed_in)

    refused = await client.patch(
        f"{BASE}/{transaction.id}/fields",
        headers=headers,
        json={"changes": [{"name": "supplier_name", "value": "Emirates Metal Trading FZE"}]},
    )
    assert refused.status_code == 409
    assert "reason" in refused.json()["message"]

    accepted = await client.patch(
        f"{BASE}/{transaction.id}/fields",
        headers=headers,
        json={
            "changes": [
                {
                    "name": "supplier_name",
                    "value": "Emirates Metal Trading FZE",
                    "reason": "The contract names the FZE entity, not the LLC.",
                }
            ]
        },
    )
    assert accepted.status_code == 200, accepted.text
    field = next(row for row in accepted.json()["data"]["fields"] if row["name"] == "supplier_name")
    # The machine's first reading and its score survive the correction, exactly as they do at the
    # document layer.
    assert field["original_ai_value"] == SUPPLIER
    assert field["original_confidence"] == pytest.approx(0.41)
    assert field["override_reason"].startswith("The contract names")


async def test_corrections_are_refused_once_a_transaction_is_awaiting_approval(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    transaction = await _clean_transaction(db_session)
    transaction.status = TransactionStatus.APPROVAL_PENDING.value
    await db_session.commit()
    _, headers = await purchase_user(signed_in)

    response = await client.patch(
        f"{BASE}/{transaction.id}/fields",
        headers=headers,
        json={"changes": [{"name": "port_of_loading", "value": "Jebel Ali"}]},
    )

    # Server-side, not merely a disabled button: the figures an approver is being asked to sign
    # cannot move underneath them.
    assert response.status_code == 409


async def test_an_auditor_may_not_correct_a_transaction(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    transaction = await _clean_transaction(db_session)
    _, headers = await auditor(signed_in)

    response = await client.patch(
        f"{BASE}/{transaction.id}/fields",
        headers=headers,
        json={"changes": [{"name": "port_of_loading", "value": "Jebel Ali"}]},
    )

    assert response.status_code == 403


# --- tolerance acknowledgement -------------------------------------------------------------------


async def test_a_self_approvable_amount_breach_can_be_acknowledged_and_is_logged(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    # $5.00 out: above the $1.00 rounding tolerance, inside the $10.00 self-approval limit.
    transaction = await _clean_transaction(db_session, amount="199067.50")
    _, headers = await purchase_user(signed_in)

    response = await client.post(
        f"{BASE}/{transaction.id}/acknowledge-tolerance",
        headers=headers,
        json={
            "rule_id": RuleId.BR_06,
            "check_key": CheckKey.AMOUNT_ROUNDING,
            "reason": "Supplier rounded the line total; the rate and quantity are correct.",
        },
    )

    assert response.status_code == 200, response.text
    current = await rule_engine.latest_evaluations(db_session, transaction.id)
    row = current[(RuleId.BR_06, CheckKey.AMOUNT_ROUNDING)]
    assert row.passed is True
    assert row.acknowledged is True
    assert row.acknowledged_by_id is not None

    # The audit entry is written before the acknowledgement is committed, never after.
    logged = await db_session.scalar(
        select(func.count(AuditEvent.id)).where(
            AuditEvent.event_type
            == transaction_service.AuditEvent.TRANSACTION_TOLERANCE_ACKNOWLEDGED,
            AuditEvent.entity_id == str(transaction.id),
        )
    )
    assert logged == 1


async def test_a_hard_amount_breach_cannot_be_acknowledged(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    # $50.00 out: past the self-approval ceiling entirely.
    transaction = await _clean_transaction(db_session, amount="199112.50")
    _, headers = await purchase_user(signed_in)

    response = await client.post(
        f"{BASE}/{transaction.id}/acknowledge-tolerance",
        headers=headers,
        json={
            "rule_id": RuleId.BR_06,
            "check_key": CheckKey.AMOUNT_ROUNDING,
            "reason": "The supplier says the figure is right and I would like to move on.",
        },
    )

    assert response.status_code == 409
    assert "hard failure" in response.json()["message"]


async def test_a_quantity_breach_has_no_self_approval_path(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    transaction = await _clean_transaction(db_session, quantity="27.000 MT", amount="219375.00")
    _, headers = await purchase_user(signed_in)

    response = await client.post(
        f"{BASE}/{transaction.id}/acknowledge-tolerance",
        headers=headers,
        json={
            "rule_id": RuleId.BR_05,
            "check_key": CheckKey.QUANTITY_TOLERANCE,
            "reason": "The load was heavier than contracted and the supplier confirmed it.",
        },
    )

    assert response.status_code == 409
    assert "cannot be self-approved" in response.json()["message"]


async def test_a_price_difference_has_no_self_approval_path(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    transaction = await _clean_transaction(db_session, rate="8125.01", amount="199062.75")
    _, headers = await purchase_user(signed_in)

    response = await client.post(
        f"{BASE}/{transaction.id}/acknowledge-tolerance",
        headers=headers,
        json={
            "rule_id": RuleId.BR_06,
            "check_key": CheckKey.RATE_TOLERANCE,
            "reason": "It is only a cent and the supplier will not reissue the invoice.",
        },
    )

    assert response.status_code == 409


async def test_an_acknowledgement_survives_a_re_validation_of_unchanged_figures(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    transaction = await _clean_transaction(db_session, amount="199067.50")
    _, headers = await purchase_user(signed_in)
    await client.post(
        f"{BASE}/{transaction.id}/acknowledge-tolerance",
        headers=headers,
        json={
            "rule_id": RuleId.BR_06,
            "check_key": CheckKey.AMOUNT_ROUNDING,
            "reason": "Supplier rounded the line total; the rate and quantity are correct.",
        },
    )

    response = await client.patch(
        f"{BASE}/{transaction.id}/fields",
        headers=headers,
        json={"changes": [{"name": "port_of_loading", "value": "Jebel Ali"}]},
    )

    assert response.status_code == 200, response.text
    current = await rule_engine.latest_evaluations(db_session, transaction.id)
    row = current[(RuleId.BR_06, CheckKey.AMOUNT_ROUNDING)]
    assert row.passed is True
    assert row.acknowledged is True


async def test_an_acknowledgement_lapses_when_the_figure_behind_it_moves(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    transaction = await _clean_transaction(db_session, amount="199067.50")
    _, headers = await purchase_user(signed_in)
    await client.post(
        f"{BASE}/{transaction.id}/acknowledge-tolerance",
        headers=headers,
        json={
            "rule_id": RuleId.BR_06,
            "check_key": CheckKey.AMOUNT_ROUNDING,
            "reason": "Supplier rounded the line total; the rate and quantity are correct.",
        },
    )

    document = next(
        row
        for row in await rule_engine.linked_documents(db_session, transaction.id)
        if row.document_type == DocumentType.INVOICE.value
    )
    field = next(row for row in document.fields if row.field_name == "amount")
    field.field_value = "199500.00"
    await db_session.commit()

    await client.patch(
        f"{BASE}/{transaction.id}/fields",
        headers=headers,
        json={"changes": [{"name": "port_of_loading", "value": "Khalifa Port"}]},
    )

    current = await rule_engine.latest_evaluations(db_session, transaction.id)
    row = current[(RuleId.BR_06, CheckKey.AMOUNT_ROUNDING)]
    # A person accepted one specific discrepancy; a different one has to be looked at again.
    assert row.acknowledged is False
    assert row.passed is False


# --- submission ------------------------------------------------------------------------------------


async def test_submission_is_blocked_while_a_rule_is_failing_and_the_block_is_logged(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    transaction = await _clean_transaction(db_session, quantity="27.000 MT", amount="219375.00")
    _, headers = await purchase_user(signed_in)

    response = await client.post(f"{BASE}/{transaction.id}/submit", headers=headers)

    assert response.status_code == 409
    assert RuleId.BR_05 in response.json()["message"]

    await db_session.refresh(transaction)
    assert transaction.status != TransactionStatus.APPROVAL_PENDING.value

    blocked = await db_session.scalar(
        select(func.count(AuditEvent.id)).where(
            AuditEvent.event_type == transaction_service.AuditEvent.TRANSACTION_SUBMISSION_BLOCKED,
            AuditEvent.entity_id == str(transaction.id),
        )
    )
    assert blocked == 1


async def test_submission_is_blocked_while_a_flagged_amount_is_unacknowledged(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    transaction = await _clean_transaction(db_session, amount="199067.50")
    _, headers = await purchase_user(signed_in)

    response = await client.post(f"{BASE}/{transaction.id}/submit", headers=headers)

    assert response.status_code == 409
    assert CheckKey.AMOUNT_ROUNDING.replace("_", " ") in response.json()["message"]


async def test_submission_succeeds_once_every_applicable_rule_is_satisfied(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    transaction = await _clean_transaction(db_session)
    _, headers = await purchase_user(signed_in)

    response = await client.post(f"{BASE}/{transaction.id}/submit", headers=headers)

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    # `Approval Pending` is the end of the road in this . Nothing was posted anywhere.
    assert data["status"] == TransactionStatus.APPROVAL_PENDING.value
    assert data["submitted_at"] is not None

    await db_session.refresh(transaction)
    assert transaction.status == TransactionStatus.APPROVAL_PENDING.value
    assert transaction.submitted_by_id is not None

    logged = await db_session.scalar(
        select(func.count(AuditEvent.id)).where(
            AuditEvent.event_type == transaction_service.AuditEvent.TRANSACTION_SUBMITTED,
            AuditEvent.entity_id == str(transaction.id),
        )
    )
    assert logged == 1


async def test_a_submitted_transaction_cannot_be_submitted_twice(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    transaction = await _clean_transaction(db_session)
    _, headers = await purchase_user(signed_in)
    await client.post(f"{BASE}/{transaction.id}/submit", headers=headers)

    again = await client.post(f"{BASE}/{transaction.id}/submit", headers=headers)

    assert again.status_code == 409


async def test_an_acknowledged_breach_lets_a_submission_through(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    transaction = await _clean_transaction(db_session, amount="199067.50")
    _, headers = await purchase_user(signed_in)
    await client.post(
        f"{BASE}/{transaction.id}/acknowledge-tolerance",
        headers=headers,
        json={
            "rule_id": RuleId.BR_06,
            "check_key": CheckKey.AMOUNT_ROUNDING,
            "reason": "Supplier rounded the line total; the rate and quantity are correct.",
        },
    )

    response = await client.post(f"{BASE}/{transaction.id}/submit", headers=headers)

    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == TransactionStatus.APPROVAL_PENDING.value


async def test_an_approver_may_not_submit_on_the_desk_s_behalf(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    transaction = await _clean_transaction(db_session)
    _, headers = await approver(signed_in)

    response = await client.post(f"{BASE}/{transaction.id}/submit", headers=headers)

    assert response.status_code == 403


# --- direct document attachment -------------------------------------------------------------------


async def test_the_commodity_reference_list_is_seeded_and_readable(
    client: AsyncClient, signed_in
) -> None:
    _, headers = await purchase_user(signed_in)

    response = await client.get(f"{BASE}/commodity-codes", headers=headers)

    assert response.status_code == 200
    codes = {row["code"] for row in response.json()["data"]}
    assert codes == {"CU", "AL", "CUZNS", "MIX", "HMS", "TIP"}


async def test_the_manual_registration_records_its_own_audit_entry(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    _, headers = await purchase_user(signed_in)

    response = await client.post(BASE, headers=headers, json=NEW_TRANSACTION_BODY)
    transaction_id = response.json()["data"]["id"]

    events = (
        await db_session.scalars(
            select(AuditEvent).where(
                AuditEvent.entity_id == transaction_id,
                AuditEvent.event_type == transaction_service.AuditEvent.TRANSACTION_CREATED,
            )
        )
    ).all()

    assert len(events) == 1
    assert events[0].event_metadata["origin"] == "manual_registration"


async def test_a_transaction_with_no_documents_reads_back_cleanly(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    _, headers = await purchase_user(signed_in)
    created = await client.post(BASE, headers=headers, json=NEW_TRANSACTION_BODY)
    transaction_id = created.json()["data"]["id"]

    response = await client.get(f"{BASE}/{transaction_id}", headers=headers)

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["documents"] == []
    assert data["can_submit"] is False
    # The blocking rules say exactly what is missing rather than reporting a bare failure.
    assert any("BR-05" in reason for reason in data["blocking_rules"])


async def test_the_quantity_recorded_on_a_manual_registration_is_kept_exactly(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    _, headers = await purchase_user(signed_in)

    response = await client.post(BASE, headers=headers, json=NEW_TRANSACTION_BODY)

    created = await db_session.get(TradeTransaction, uuid.UUID(response.json()["data"]["id"]))
    assert created.quantity_mt == Decimal("24.500")
    assert created.purchase_leg.amount == Decimal("199062.5000")
    assert created.commodity_code == "CU"


async def test_a_rule_that_cannot_be_configured_is_never_silently_passed(
    db_session: AsyncSession,
) -> None:
    """A missing configuration blocks rather than waving the rule through."""
    from app.models.configuration import RuleConfiguration

    # The unscoped row specifically. BR-05 also carries an FA-scoped row from , and a
    # transaction on the scrap stream resolves to the unscoped one - so this names it rather than
    # taking whichever of the two the database happens to return first.
    row = await db_session.scalar(
        select(RuleConfiguration).where(
            RuleConfiguration.rule_id == RuleId.BR_05,
            RuleConfiguration.check_key == CheckKey.QUANTITY_TOLERANCE,
            RuleConfiguration.scope_stream.is_(None),
            RuleConfiguration.scope_commodity_code.is_(None),
            RuleConfiguration.scope_transaction_type.is_(None),
        )
    )
    assert row is not None
    row.is_active = False
    await db_session.commit()
    try:
        transaction = await _clean_transaction(db_session)
        current = await rule_engine.latest_evaluations(db_session, transaction.id)
        outcome = current[(RuleId.BR_05, CheckKey.QUANTITY_TOLERANCE)]

        assert outcome.passed is False
        assert outcome.severity == RuleSeverity.HARD.value
        assert "no active configuration" in outcome.message
    finally:
        # Reference data the migration seeded is restored: the suite deliberately does not wipe
        # and reseed it between tests.
        row.is_active = True
        await db_session.commit()
