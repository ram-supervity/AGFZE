"""Approval tasks, the ranked queue, the decision, and the deliberately narrow bulk action.

Two things are proved repeatedly here because they are the two that would matter most if they
were wrong: the identity on a decision comes from the token and nothing else, and an approval
does exactly as much as it is entitled to do - it records the decision and, from , raises
the three integration jobs it authorises. It never marks anything as posted itself.
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
from app.models.enums import (
    ApprovalDecision,
    ExceptionCategory,
    IntegrationJobStatus,
    TransactionStatus,
)
from app.models.governance import ApprovalTask, ExceptionCase
from app.models.integration import IntegrationJob
from app.models.jobs import BackgroundJob
from app.models.transactions import TradeTransaction
from app.services import gemini_service
from app.services.governance import approval_service, thresholds
from app.services.governance.hooks import GovernanceAuditEvent
from app.services.rules.catalog import CheckKey, RuleId
from tests.utils.governance import seeded_transaction

pytestmark = pytest.mark.usefixtures("patched_jwks")

BASE = "/api/v1/approvals"
TRANSACTIONS = "/api/v1/transactions"

CALCULATED = Decimal("199062.50")
SELF_APPROVABLE_AMOUNT = CALCULATED + Decimal("5.00")


async def purchase_user(signed_in):
    return await signed_in(
        "0a1b2c3d-0000-4000-8000-00000000f001",
        "purchase.desk@agfze.ae",
        "Marco Bellini",
        ["purchase_user"],
    )


async def approver(signed_in):
    return await signed_in(
        "0a1b2c3d-0000-4000-8000-00000000f002",
        "hod.desk@agfze.ae",
        "Priya Raghunathan",
        ["approver_hod"],
    )


async def second_approver(signed_in):
    return await signed_in(
        "0a1b2c3d-0000-4000-8000-00000000f003",
        "deputy.hod@agfze.ae",
        "Yusuf Demir",
        ["approver_hod"],
    )


async def auditor(signed_in):
    return await signed_in(
        "0a1b2c3d-0000-4000-8000-00000000f004",
        "auditor.desk@agfze.ae",
        "Kenji Watanabe",
        ["auditor"],
    )


async def dual_role_user(signed_in):
    """One account that can both prepare a transaction and decide approvals.

    The seeded local realm ships exactly this overlap as `dual.user`, so it is a real account
    shape rather than a contrived one, and it is the only shape in which self-approval is even
    reachable - every other account is refused by the role dependency long before the decision.
    """
    return await signed_in(
        "0a1b2c3d-0000-4000-8000-00000000f005",
        "dual.desk@agfze.ae",
        "Amara Okonkwo",
        ["purchase_user", "approver_hod"],
    )


async def dual_role_admin(signed_in):
    """The same overlap through `admin`, which is the queue's other deciding role."""
    return await signed_in(
        "0a1b2c3d-0000-4000-8000-00000000f006",
        "dual.admin@agfze.ae",
        "Ravi Menon",
        ["purchase_user", "admin"],
    )


async def _submitted(
    client: AsyncClient,
    session: AsyncSession,
    headers: dict[str, str],
    *,
    batch_number: str = "I2626-1",
    **kwargs,
) -> TradeTransaction:
    """A clean transaction, submitted through the real endpoint so the real hook runs."""
    transaction = await seeded_transaction(session, batch_number=batch_number, **kwargs)
    response = await client.post(f"{TRANSACTIONS}/{transaction.id}/submit", headers=headers)
    assert response.status_code == 200, response.text
    await session.refresh(transaction)
    return transaction


async def _task(session: AsyncSession, transaction: TradeTransaction) -> ApprovalTask:
    return (
        await session.scalars(
            select(ApprovalTask).where(ApprovalTask.transaction_id == transaction.id)
        )
    ).one()


async def _acknowledged_transaction(
    client: AsyncClient,
    session: AsyncSession,
    headers: dict[str, str],
    batch_number: str,
    *,
    leg_amount: Decimal,
) -> TradeTransaction:
    """A transaction whose amount breach was accepted in the workspace, then submitted.

    The acknowledgement is what makes it higher-risk, and it is made through the real endpoint so
    the risk profile is reading a fact the platform actually recorded.
    """
    transaction = await seeded_transaction(
        session,
        batch_number=batch_number,
        invoice_overrides={"amount": str(SELF_APPROVABLE_AMOUNT)},
    )
    acknowledged = await client.post(
        f"{TRANSACTIONS}/{transaction.id}/acknowledge-tolerance",
        headers=headers,
        json={
            "rule_id": RuleId.BR_06,
            "check_key": CheckKey.AMOUNT_ROUNDING,
            "reason": "Supplier rounded the line total; rate and quantity are both correct.",
        },
    )
    assert acknowledged.status_code == 200, acknowledged.text

    transaction.purchase_leg.amount = leg_amount
    await session.commit()

    submitted = await client.post(f"{TRANSACTIONS}/{transaction.id}/submit", headers=headers)
    assert submitted.status_code == 200, submitted.text
    await session.refresh(transaction)
    return transaction


@pytest.fixture
def stub_summary(monkeypatch: pytest.MonkeyPatch):
    """Replace only the model call. Everything around it - caching, failure handling - is real."""
    calls: list[dict] = []

    async def _summarize(facts: dict):
        calls.append(facts)
        return gemini_service.ApprovalSummary(
            summary="A 24.5 MT copper purchase from Emirates Metal Trading, fully checked.",
            what_to_check=["The contract's rate against the invoice."],
        )

    monkeypatch.setattr(gemini_service, "summarize_for_approval", _summarize)
    return calls


@pytest.fixture
def failing_summary(monkeypatch: pytest.MonkeyPatch):
    async def _summarize(facts: dict):
        raise gemini_service.AIServiceError(reason="timeout")

    monkeypatch.setattr(gemini_service, "summarize_for_approval", _summarize)


# --- the task ------------------------------------------------------------------------------------


async def test_submitting_creates_exactly_one_approval_task(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    user, headers = await purchase_user(signed_in)
    transaction = await _submitted(client, db_session, headers)

    tasks = (
        await db_session.scalars(
            select(ApprovalTask).where(ApprovalTask.transaction_id == transaction.id)
        )
    ).all()
    assert len(tasks) == 1
    assert tasks[0].decision == ApprovalDecision.PENDING.value
    assert tasks[0].approver_role == "approver_hod"
    assert tasks[0].requested_by_id == user.id
    assert tasks[0].decided_by_id is None
    assert tasks[0].ai_summary is None

    logged = (
        await db_session.scalars(
            select(AuditEvent).where(
                AuditEvent.event_type == GovernanceAuditEvent.APPROVAL_REQUESTED
            )
        )
    ).all()
    assert len(logged) == 1


async def test_re_submitting_an_already_pending_transaction_is_refused(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    _, headers = await purchase_user(signed_in)
    transaction = await _submitted(client, db_session, headers)

    again = await client.post(f"{TRANSACTIONS}/{transaction.id}/submit", headers=headers)
    assert again.status_code == 409
    assert (
        await db_session.scalar(
            select(func.count(ApprovalTask.id)).where(ApprovalTask.transaction_id == transaction.id)
        )
        == 1
    )


# --- the queue -----------------------------------------------------------------------------------


async def test_the_queue_ranks_by_age_value_and_risk(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    _, purchase_headers = await purchase_user(signed_in)
    _, headers = await approver(signed_in)

    older = await _submitted(client, db_session, purchase_headers, batch_number="I2626-1")
    task = await _task(db_session, older)
    task.requested_at = utcnow() - timedelta(days=4)
    await db_session.commit()

    # Bigger, and carrying a tolerance somebody accepted by hand, so it is the riskier of the two.
    newer = await _acknowledged_transaction(
        client, db_session, purchase_headers, "I2626-2", leg_amount=Decimal("500000.00")
    )

    by_age = (await client.get(f"{BASE}?rank_by=age", headers=headers)).json()["data"]
    assert by_age["items"][0]["batch_number"] == older.batch_number

    by_value = (await client.get(f"{BASE}?rank_by=value", headers=headers)).json()["data"]
    assert by_value["items"][0]["batch_number"] == newer.batch_number

    by_risk = (await client.get(f"{BASE}?rank_by=risk", headers=headers)).json()["data"]
    top = by_risk["items"][0]
    assert top["batch_number"] == newer.batch_number
    assert top["risk"]["acknowledged_tolerance"] is True
    assert top["risk"]["label"] == "elevated"
    assert top["risk"]["bulk_eligible"] is False


async def test_anyone_signed_in_reads_the_queue_but_only_the_approver_sees_controls(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    _, purchase_headers = await purchase_user(signed_in)
    await _submitted(client, db_session, purchase_headers)

    _, audit_headers = await auditor(signed_in)
    observed = await client.get(BASE, headers=audit_headers)
    assert observed.status_code == 200
    assert observed.json()["data"]["can_decide"] is False

    _, approver_headers = await approver(signed_in)
    assert (await client.get(BASE, headers=approver_headers)).json()["data"]["can_decide"] is True


# --- the AI summary --------------------------------------------------------------------------


async def test_the_summary_is_generated_once_and_reused(
    client: AsyncClient, db_session: AsyncSession, signed_in, stub_summary
) -> None:
    _, purchase_headers = await purchase_user(signed_in)
    _, headers = await approver(signed_in)
    transaction = await _submitted(client, db_session, purchase_headers)
    task = await _task(db_session, transaction)

    first = (await client.get(f"{BASE}/{task.id}", headers=headers)).json()["data"]
    assert first["ai_summary"]["available"] is True
    assert "copper" in first["ai_summary"]["summary"].lower()

    second = (await client.get(f"{BASE}/{task.id}", headers=headers)).json()["data"]
    assert second["ai_summary"]["summary"] == first["ai_summary"]["summary"]
    # One model call for two views. The cached note is the one that comes back.
    assert len(stub_summary) == 1


async def test_a_failed_summary_never_blocks_viewing_or_deciding(
    client: AsyncClient, db_session: AsyncSession, signed_in, failing_summary
) -> None:
    _, purchase_headers = await purchase_user(signed_in)
    _, headers = await approver(signed_in)
    transaction = await _submitted(client, db_session, purchase_headers)
    task = await _task(db_session, transaction)

    detail = await client.get(f"{BASE}/{task.id}", headers=headers)
    assert detail.status_code == 200
    body = detail.json()["data"]

    assert body["ai_summary"]["available"] is False
    assert body["ai_summary"]["summary"] is None
    assert body["ai_summary"]["unavailable_reason"]
    # The page is complete without it: the real record is all still there.
    assert body["batch_number"] == transaction.batch_number
    assert body["value"] is not None
    assert len(body["rule_evaluations"]) > 0
    assert body["can_decide"] is True

    decided = await client.post(
        f"{BASE}/{task.id}/decide", headers=headers, json={"decision": "approved"}
    )
    assert decided.status_code == 200, decided.text


# --- the decision ----------------------------------------------------------------------------


async def test_approving_records_the_decision_and_raises_its_integration_jobs(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    """What an approval does, and the exact limit of it.

    Until  this test asserted that nothing downstream happened, because there was nothing
    downstream. There is now: an approval raises exactly three integration jobs. What has not
    changed is the discipline behind the original assertion - nothing is marked as posted. With
    no tracker, SAP or DMS configured, all three jobs land in `awaiting_manual_action`, and the
    transaction stops at `Integration Pending` rather than being called committed.
    """
    _, purchase_headers = await purchase_user(signed_in)
    user, headers = await approver(signed_in)
    transaction = await _submitted(client, db_session, purchase_headers)
    task = await _task(db_session, transaction)

    # The generic background-job table is untouched: integration jobs are their own record, with
    # their own five-value status, precisely because "completed or failed" cannot describe them.
    jobs_before = await db_session.scalar(select(func.count(BackgroundJob.id)))

    response = await client.post(
        f"{BASE}/{task.id}/decide", headers=headers, json={"decision": "approved"}
    )
    assert response.status_code == 200, response.text

    await db_session.refresh(transaction)
    await db_session.refresh(task)
    assert task.decision == ApprovalDecision.APPROVED.value
    assert task.decided_by_id == user.id
    assert task.decided_at is not None
    assert task.reason is None
    assert transaction.status == TransactionStatus.INTEGRATION_PENDING.value

    assert await db_session.scalar(select(func.count(BackgroundJob.id))) == jobs_before
    jobs = list(
        (
            await db_session.scalars(
                select(IntegrationJob).where(IntegrationJob.transaction_id == transaction.id)
            )
        ).all()
    )
    assert len(jobs) == 3
    assert {job.status for job in jobs} == {IntegrationJobStatus.AWAITING_MANUAL_ACTION.value}
    assert all(job.completed_manually is False for job in jobs)
    assert all(job.external_reference is None for job in jobs)
    assert "complete by hand" in response.json()["message"]


async def test_rejecting_raises_no_integration_job_at_all(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    """A returned transaction has authorised nothing, so nothing downstream exists for it."""
    _, purchase_headers = await purchase_user(signed_in)
    _user, headers = await approver(signed_in)
    transaction = await _submitted(client, db_session, purchase_headers, batch_number="I2626-4")
    task = await _task(db_session, transaction)

    response = await client.post(
        f"{BASE}/{task.id}/decide",
        headers=headers,
        json={
            "decision": "rejected",
            "reason": "The supplier invoice does not match the contract we hold.",
        },
    )
    assert response.status_code == 200, response.text

    await db_session.refresh(transaction)
    assert transaction.status == TransactionStatus.VALIDATION_PENDING.value
    assert (
        await db_session.scalar(
            select(func.count(IntegrationJob.id)).where(
                IntegrationJob.transaction_id == transaction.id
            )
        )
        == 0
    )


async def test_a_client_supplied_decider_is_never_trusted(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    _, purchase_headers = await purchase_user(signed_in)
    impersonated, _ = await second_approver(signed_in)
    user, headers = await approver(signed_in)
    transaction = await _submitted(client, db_session, purchase_headers)
    task = await _task(db_session, transaction)

    stolen_moment = (utcnow() - timedelta(days=400)).isoformat()
    response = await client.post(
        f"{BASE}/{task.id}/decide",
        headers=headers,
        json={
            "decision": "approved",
            "decided_by": str(impersonated.id),
            "decided_by_id": str(impersonated.id),
            "decided_at": stolen_moment,
        },
    )
    assert response.status_code == 200, response.text

    await db_session.refresh(task)
    # The token's subject and the server's clock won; the body's suggestions went nowhere.
    assert task.decided_by_id == user.id
    assert task.decided_by_id != impersonated.id
    # SQLite hands timestamps back naive; PostgreSQL keeps the offset, so normalise before
    # comparing rather than asserting against whichever engine the suite is running on.
    assert approval_service.aware(task.decided_at) > utcnow() - timedelta(minutes=5)


async def test_rejecting_needs_a_reason_and_returns_the_transaction_to_the_desk(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    _, purchase_headers = await purchase_user(signed_in)
    _, headers = await approver(signed_in)
    transaction = await _submitted(client, db_session, purchase_headers)
    task = await _task(db_session, transaction)

    refused = await client.post(
        f"{BASE}/{task.id}/decide", headers=headers, json={"decision": "rejected"}
    )
    assert refused.status_code == 409
    assert refused.json()["errors"][0]["code"] == "reason_required"

    accepted = await client.post(
        f"{BASE}/{task.id}/decide",
        headers=headers,
        json={
            "decision": "rejected",
            "reason": "The supplier's contract reference does not match our copy.",
        },
    )
    assert accepted.status_code == 200, accepted.text

    await db_session.refresh(transaction)
    await db_session.refresh(task)
    # Correctable, not a dead deal: back with the desk that raised it, with the reason attached.
    assert transaction.status == TransactionStatus.VALIDATION_PENDING.value
    assert task.reason.startswith("The supplier's contract reference")


async def test_requesting_changes_also_returns_it_and_it_can_be_submitted_again(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    _, purchase_headers = await purchase_user(signed_in)
    _, headers = await approver(signed_in)
    transaction = await _submitted(client, db_session, purchase_headers)
    task = await _task(db_session, transaction)

    await client.post(
        f"{BASE}/{task.id}/decide",
        headers=headers,
        json={
            "decision": "changes_requested",
            "reason": "Attach the mill test certificate before I sign this.",
        },
    )
    await db_session.refresh(transaction)
    assert transaction.status == TransactionStatus.VALIDATION_PENDING.value

    # Editable again, and genuinely re-submittable: a second, real request for a decision.
    edit = await client.patch(
        f"{TRANSACTIONS}/{transaction.id}/fields",
        headers=purchase_headers,
        json={"changes": [{"name": "port_of_loading", "value": "Jebel Ali"}]},
    )
    assert edit.status_code == 200, edit.text

    resubmitted = await client.post(
        f"{TRANSACTIONS}/{transaction.id}/submit", headers=purchase_headers
    )
    assert resubmitted.status_code == 200, resubmitted.text
    assert (
        await db_session.scalar(
            select(func.count(ApprovalTask.id)).where(ApprovalTask.transaction_id == transaction.id)
        )
        == 2
    )


async def test_only_the_approver_may_decide(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    _, purchase_headers = await purchase_user(signed_in)
    transaction = await _submitted(client, db_session, purchase_headers)
    task = await _task(db_session, transaction)

    refused = await client.post(
        f"{BASE}/{task.id}/decide", headers=purchase_headers, json={"decision": "approved"}
    )
    assert refused.status_code == 403

    _, audit_headers = await auditor(signed_in)
    assert (
        await client.post(
            f"{BASE}/{task.id}/decide", headers=audit_headers, json={"decision": "approved"}
        )
    ).status_code == 403


async def test_a_high_value_approval_needs_an_explicit_second_confirmation(
    client: AsyncClient, db_session: AsyncSession, signed_in, stub_summary
) -> None:
    _, purchase_headers = await purchase_user(signed_in)
    _, headers = await approver(signed_in)
    transaction = await _submitted(client, db_session, purchase_headers)
    task = await _task(db_session, transaction)

    threshold = await thresholds.resolve(
        db_session, thresholds.GovernanceKey.APPROVAL_CONFIRMATION_VALUE
    )
    transaction.purchase_leg.amount = threshold + Decimal("1000")
    await db_session.commit()

    detail = (await client.get(f"{BASE}/{task.id}", headers=headers)).json()["data"]
    assert detail["requires_confirmation"] is True

    unconfirmed = await client.post(
        f"{BASE}/{task.id}/decide", headers=headers, json={"decision": "approved"}
    )
    assert unconfirmed.status_code == 409
    assert unconfirmed.json()["errors"][0]["code"] == "confirmation_required"

    confirmed = await client.post(
        f"{BASE}/{task.id}/decide",
        headers=headers,
        json={"decision": "approved", "confirm_above_threshold": True},
    )
    assert confirmed.status_code == 200, confirmed.text


async def test_a_decided_approval_cannot_be_decided_twice(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    _, purchase_headers = await purchase_user(signed_in)
    _, headers = await approver(signed_in)
    transaction = await _submitted(client, db_session, purchase_headers)
    task = await _task(db_session, transaction)

    await client.post(f"{BASE}/{task.id}/decide", headers=headers, json={"decision": "approved"})
    again = await client.post(
        f"{BASE}/{task.id}/decide",
        headers=headers,
        json={"decision": "rejected", "reason": "Changed my mind after signing it off."},
    )
    assert again.status_code == 409


async def test_the_submitter_cannot_approve_their_own_transaction(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    """Maker-checker, enforced rather than merely recorded.

    The account here holds both `purchase_user` and `approver_hod`, so it passes the role
    dependency on the decide endpoint. What stops it is the transaction's own recorded submitter,
    and the transaction has to be left exactly where it was - still waiting on somebody else.
    """
    user, headers = await dual_role_user(signed_in)
    transaction = await _submitted(client, db_session, headers)
    task = await _task(db_session, transaction)
    assert transaction.submitted_by_id == user.id

    refused = await client.post(
        f"{BASE}/{task.id}/decide", headers=headers, json={"decision": "approved"}
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["errors"][0]["code"] == "segregation_of_duties"

    await db_session.refresh(transaction)
    await db_session.refresh(task)
    assert task.decision == ApprovalDecision.PENDING.value
    assert task.decided_by_id is None
    assert task.decided_at is None
    assert transaction.status == TransactionStatus.APPROVAL_PENDING.value

    # Nothing downstream was authorised either. A refused approval must not leave a job behind.
    assert (
        await db_session.scalar(
            select(func.count(IntegrationJob.id)).where(
                IntegrationJob.transaction_id == transaction.id
            )
        )
        == 0
    )
    assert (
        await db_session.scalar(
            select(func.count(AuditEvent.id)).where(
                AuditEvent.event_type == GovernanceAuditEvent.APPROVAL_DECIDED
            )
        )
        == 0
    )


async def test_the_bar_applies_to_an_admin_submitter_too(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    """`admin` is a deciding role on this queue, so it is subject to the same control."""
    _user, headers = await dual_role_admin(signed_in)
    transaction = await _submitted(client, db_session, headers)
    task = await _task(db_session, transaction)

    refused = await client.post(
        f"{BASE}/{task.id}/decide", headers=headers, json={"decision": "approved"}
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["errors"][0]["code"] == "segregation_of_duties"


async def test_the_submitter_may_still_reject_or_send_back_their_own_transaction(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    """Returning a transaction to its own desk commits nothing, so the bar does not apply.

    Refusing it would only strand work: the transaction goes back to the person who raised it,
    editable, with a reason attached, and no integration job is raised by either decision.
    """
    _user, headers = await dual_role_user(signed_in)
    transaction = await _submitted(client, db_session, headers, batch_number="I2626-7")
    task = await _task(db_session, transaction)

    sent_back = await client.post(
        f"{BASE}/{task.id}/decide",
        headers=headers,
        json={
            "decision": "changes_requested",
            "reason": "I have the wrong weight slip attached to this one; re-checking it.",
        },
    )
    assert sent_back.status_code == 200, sent_back.text

    await db_session.refresh(transaction)
    await db_session.refresh(task)
    assert task.decision == ApprovalDecision.CHANGES_REQUESTED.value
    assert transaction.status == TransactionStatus.VALIDATION_PENDING.value
    assert (
        await db_session.scalar(
            select(func.count(IntegrationJob.id)).where(
                IntegrationJob.transaction_id == transaction.id
            )
        )
        == 0
    )


async def test_a_different_approver_decides_the_same_transaction_normally(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    """The control bars one person, not the transaction. Somebody else approves it as usual."""
    _user, dual_headers = await dual_role_user(signed_in)
    decider, approver_headers = await approver(signed_in)
    transaction = await _submitted(client, db_session, dual_headers, batch_number="I2626-8")
    task = await _task(db_session, transaction)

    approved = await client.post(
        f"{BASE}/{task.id}/decide", headers=approver_headers, json={"decision": "approved"}
    )
    assert approved.status_code == 200, approved.text

    await db_session.refresh(task)
    await db_session.refresh(transaction)
    assert task.decision == ApprovalDecision.APPROVED.value
    assert task.decided_by_id == decider.id
    assert transaction.status == TransactionStatus.INTEGRATION_PENDING.value


async def test_a_transaction_with_no_recorded_submitter_is_not_caught_by_the_bar(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    """There is no self-approval to guard against when nobody is recorded as the submitter.

    `submitted_by_id` is nullable, and a row that never went through the submit endpoint - a
    system-created one, or one predating the column carrying a value - has no maker to check the
    checker against. Barring it would refuse an approval on no evidence at all.
    """
    _user, dual_headers = await dual_role_user(signed_in)
    transaction = await _submitted(client, db_session, dual_headers, batch_number="I2626-9")
    task = await _task(db_session, transaction)

    transaction.submitted_by_id = None
    await db_session.commit()

    approved = await client.post(
        f"{BASE}/{task.id}/decide", headers=dual_headers, json={"decision": "approved"}
    )
    assert approved.status_code == 200, approved.text

    await db_session.refresh(task)
    assert task.decision == ApprovalDecision.APPROVED.value


# --- bulk ------------------------------------------------------------------------------------


async def _bulk_eligible(
    client: AsyncClient, session: AsyncSession, headers: dict[str, str], batch_number: str
) -> TradeTransaction:
    """Small enough for the bulk ceiling, clean enough for the lowest risk tier."""
    ceiling = await thresholds.resolve(
        session, thresholds.GovernanceKey.BULK_APPROVAL_VALUE_CEILING
    )
    transaction = await seeded_transaction(session, batch_number=batch_number)
    transaction.purchase_leg.amount = ceiling - Decimal("1000")
    await session.commit()

    response = await client.post(f"{TRANSACTIONS}/{transaction.id}/submit", headers=headers)
    assert response.status_code == 200, response.text
    await session.refresh(transaction)
    return transaction


async def test_bulk_approval_performs_one_audited_approval_per_transaction(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    _, purchase_headers = await purchase_user(signed_in)
    user, headers = await approver(signed_in)

    first = await _bulk_eligible(client, db_session, purchase_headers, "I2626-1")
    second = await _bulk_eligible(client, db_session, purchase_headers, "I2626-2")
    tasks = [await _task(db_session, first), await _task(db_session, second)]

    response = await client.post(
        f"{BASE}/bulk-decide",
        headers=headers,
        json={"approval_ids": [str(task.id) for task in tasks]},
    )
    assert response.status_code == 200, response.text
    body = response.json()["data"]
    assert body["approved_count"] == 2
    assert body["skipped_count"] == 0

    for transaction in (first, second):
        await db_session.refresh(transaction)
        # Each one raised its own three jobs, exactly as a single decision does: a bulk action is
        # N approvals asked for together, and that stays true of everything downstream of them.
        assert transaction.status == TransactionStatus.INTEGRATION_PENDING.value
        assert (
            await db_session.scalar(
                select(func.count(IntegrationJob.id)).where(
                    IntegrationJob.transaction_id == transaction.id
                )
            )
            == 3
        )

    decisions = (
        await db_session.scalars(
            select(AuditEvent).where(AuditEvent.event_type == GovernanceAuditEvent.APPROVAL_DECIDED)
        )
    ).all()
    # Two independent entries, each naming its own transaction. Never one blanket act.
    assert len(decisions) == 2
    assert {event.event_metadata["transaction_id"] for event in decisions} == {
        str(first.id),
        str(second.id),
    }
    assert all(event.actor_id == user.id for event in decisions)
    assert all(event.event_metadata["bulk"] is True for event in decisions)


async def test_bulk_approval_refuses_only_the_submitters_own_row(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    """The bar reaches the batch path, and refuses one row rather than the whole request.

    Both transactions here are in the lowest risk tier, so nothing else would exclude either of
    them. The deciding account submitted one of the two; that one is refused by name, and the
    other still goes through - which is the existing promise of this endpoint, that a row the
    client should have filtered out is refused individually rather than failing the batch.
    """
    _, purchase_headers = await purchase_user(signed_in)
    dual_user, dual_headers = await dual_role_user(signed_in)

    own = await _bulk_eligible(client, db_session, dual_headers, "I2626-11")
    other = await _bulk_eligible(client, db_session, purchase_headers, "I2626-12")
    own_task = await _task(db_session, own)
    other_task = await _task(db_session, other)
    assert own.submitted_by_id == dual_user.id

    response = await client.post(
        f"{BASE}/bulk-decide",
        headers=dual_headers,
        json={"approval_ids": [str(own_task.id), str(other_task.id)]},
    )
    assert response.status_code == 200, response.text
    body = response.json()["data"]
    assert body["approved_count"] == 1
    assert body["skipped_count"] == 1
    assert body["approved"][0]["batch_number"] == other.batch_number
    refused = body["rejected"][0]
    assert refused["batch_number"] == own.batch_number
    assert "cannot also approve it" in refused["message"]

    await db_session.refresh(own)
    await db_session.refresh(other)
    assert own.status == TransactionStatus.APPROVAL_PENDING.value
    assert other.status == TransactionStatus.INTEGRATION_PENDING.value
    assert (
        await db_session.scalar(
            select(func.count(IntegrationJob.id)).where(IntegrationJob.transaction_id == own.id)
        )
        == 0
    )


async def test_bulk_approval_refuses_anything_outside_the_lowest_risk_tier(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    _, purchase_headers = await purchase_user(signed_in)
    _, headers = await approver(signed_in)

    clean = await _bulk_eligible(client, db_session, purchase_headers, "I2626-1")

    # Over the bulk ceiling, and therefore an individual decision however clean it is.
    large = await _bulk_eligible(client, db_session, purchase_headers, "I2626-2")
    ceiling = await thresholds.resolve(
        db_session, thresholds.GovernanceKey.BULK_APPROVAL_VALUE_CEILING
    )
    large.purchase_leg.amount = ceiling + Decimal("1")
    await db_session.commit()

    ineligible_task = await _task(db_session, large)
    clean_task = await _task(db_session, clean)

    response = await client.post(
        f"{BASE}/bulk-decide",
        headers=headers,
        # Both sent deliberately: the client's own filter is never the authority.
        json={"approval_ids": [str(clean_task.id), str(ineligible_task.id)]},
    )
    assert response.status_code == 200, response.text
    body = response.json()["data"]

    assert body["approved_count"] == 1
    assert [row["batch_number"] for row in body["approved"]] == [clean.batch_number]
    assert [row["batch_number"] for row in body["rejected"]] == [large.batch_number]

    await db_session.refresh(large)
    assert large.status == TransactionStatus.APPROVAL_PENDING.value


async def test_bulk_approval_refuses_a_transaction_with_an_acknowledged_tolerance(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    _, purchase_headers = await purchase_user(signed_in)
    _, headers = await approver(signed_in)

    ceiling = await thresholds.resolve(
        db_session, thresholds.GovernanceKey.BULK_APPROVAL_VALUE_CEILING
    )
    # Small enough for the ceiling, so the only thing keeping it out of the batch is the
    # acknowledgement itself.
    transaction = await _acknowledged_transaction(
        client, db_session, purchase_headers, "I2626-1", leg_amount=ceiling - Decimal("1000")
    )

    task = await _task(db_session, transaction)
    response = await client.post(
        f"{BASE}/bulk-decide", headers=headers, json={"approval_ids": [str(task.id)]}
    )
    body = response.json()["data"]

    assert body["approved_count"] == 0
    assert "accepted by the preparing user" in body["rejected"][0]["message"]
    await db_session.refresh(transaction)
    assert transaction.status == TransactionStatus.APPROVAL_PENDING.value


# --- ageing back into the exception queue --------------------------------------------------------


async def test_an_undecided_approval_ages_into_an_exception_and_closes_with_the_decision(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    _, purchase_headers = await purchase_user(signed_in)
    _, headers = await approver(signed_in)
    transaction = await _submitted(client, db_session, purchase_headers)
    task = await _task(db_session, transaction)

    overdue_hours = await thresholds.resolve(
        db_session, thresholds.GovernanceKey.APPROVAL_OVERDUE_HOURS
    )
    task.requested_at = utcnow() - timedelta(hours=float(overdue_hours) + 6)
    await db_session.commit()

    queue = await client.get("/api/v1/exceptions", headers=headers)
    assert queue.status_code == 200
    rows = [
        row
        for row in queue.json()["data"]["items"]
        if row["exception_type"] == ExceptionCategory.APPROVAL_NOT_RECEIVED.value
    ]
    assert len(rows) == 1
    assert rows[0]["owner_role"] == "approver_hod"
    # Honest about what it did and did not do.
    assert "no reminder has been sent" in rows[0]["summary"].lower()

    # Reading again reconciles the same state and adds nothing.
    await client.get("/api/v1/exceptions", headers=headers)
    assert (
        await db_session.scalar(
            select(func.count(ExceptionCase.id)).where(
                ExceptionCase.exception_type == ExceptionCategory.APPROVAL_NOT_RECEIVED.value
            )
        )
        == 1
    )

    await client.post(f"{BASE}/{task.id}/decide", headers=headers, json={"decision": "approved"})

    closed = (
        await db_session.scalars(
            select(ExceptionCase).where(
                ExceptionCase.exception_type == ExceptionCategory.APPROVAL_NOT_RECEIVED.value
            )
        )
    ).all()
    assert len(closed) == 1
    await db_session.refresh(closed[0])
    assert closed[0].resolved_at is not None
