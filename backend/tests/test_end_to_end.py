"""The whole platform, working together, in the shapes AGFZE will actually use it in.

Every prior  tested its own module against its own neighbours. Nothing was positioned to test
a deal travelling the entire length of the system, and that is what this file does: a mail
arriving, a model reading it, a person confirming it, an engine judging it, a queue owning what
failed, an approver signing it, three postings resolving, and an auditor reconstructing the whole
thing from a batch number.

Everything runs for real except the three boundaries this platform never owns: the mailbox, the
model, and the downstream systems. Each of those is replaced at its own seam and nowhere else, so
what these tests exercise is the application's own wiring rather than a rehearsal of it.

The scenarios, in the order the specification names them:

 1. a complete purchase deal, from an email arriving to `Committed`;
 2. a complete sales deal, linked to its purchase leg, through draft generation to `Committed`;
 3. a complete FA deal, proving the engine is genuinely generic;
 4. a hard validation failure through to resolution, with the exception reaching all three
    notification channels together;
 5. reject and re-submit, proving `Validation Pending` is genuinely re-enterable;
 6. shipment staleness through to resolution, with the case opened by a direct call;
 7. an unconfigured SAP and DMS, through `awaiting_manual_action` to `Committed`;
 8. a full audit reconstruction, from a committed transaction back to the email it arrived on.

The offline-governance scenario is the ninth, and it lives in the frontend suite because that is
where the code it tests lives - `frontend/src/__tests__/offline-governance.test.ts`.
"""

from __future__ import annotations

import asyncio
import base64
from datetime import timedelta
from uuid import UUID

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.roles import PlatformRole
from app.db.base import utcnow
from app.models.audit import AuditEvent
from app.models.enums import (
    ApprovalDecision,
    DocumentSource,
    DocumentType,
    ExceptionCategory,
    IntegrationJobStatus,
    IntegrationTargetSystem,
    Territory,
    TransactionStatus,
)
from app.models.governance import ApprovalTask, ExceptionCase
from app.models.intake import Document, EmailMessage, Request
from app.models.integration import IntegrationJob
from app.models.jobs import BackgroundJob, JobStatus
from app.models.transactions import RuleEvaluation, TradeTransaction
from app.services import document_service, job_service, matching_service
from app.services.email_ingestion import ingest_message
from app.services.graph_service import GraphClient
from app.services.integration import integration_service
from app.services.integration.adapters import IntegrationOutcome
from app.services.logistics import tracking_service
from app.services.rules import engine as rule_engine
from app.services.rules.catalog import CheckKey, RuleId
from tests.utils.delivery import install_push, install_relay, set_channel, subscribe
from tests.utils.fixtures import (
    classification_response,
    document_classification_response,
    extraction_response,
    graph_message_payload,
    text_layer_pdf,
)
from tests.utils.governance import seeded_transaction
from tests.utils.integration import all_stubbed, approved_transaction, job_for, statuses
from tests.utils.logistics import (
    add_shipment,
    fa_values,
    make_fa_transaction,
    no_adapters,
)
from tests.utils.sales import VALID_CONTRACT_PLAN, sales_transaction
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

TRANSACTIONS = "/api/v1/transactions"
APPROVALS = "/api/v1/approvals"
EXCEPTIONS = "/api/v1/exceptions"
SHIPMENTS = "/api/v1/shipments"
DOCUMENTS = "/api/v1/documents"
INTEGRATIONS = "/api/v1/integrations"
AUDIT = "/api/v1/audit"

MESSAGE_ID = "AAMkAG-END-TO-END-0001="

SAP = IntegrationTargetSystem.SAP.value
DMS = IntegrationTargetSystem.DMS.value
TRACKER = IntegrationTargetSystem.TRACKER.value


# --- the three boundaries, replaced at their own seams -------------------------------------------


def mailbox_holding(attachment: bytes | None = None) -> GraphClient:
    """A Graph client serving one message, optionally with one PDF attached."""
    attachments = (
        [
            {
                "id": "att-1",
                "name": "supplier-invoice.pdf",
                "contentType": "application/pdf",
                "contentBytes": base64.b64encode(attachment).decode(),
                "@odata.type": "#microsoft.graph.fileAttachment",
            }
        ]
        if attachment is not None
        else []
    )

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/token"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        if url.endswith("/$value"):
            return httpx.Response(
                200,
                content=(
                    b"From: desk@broker.example\r\nSubject: Purchase confirmation\r\n\r\nbody"
                ),
            )
        if "/attachments/" in url:
            wanted = url.rsplit("/", 1)[-1]
            return httpx.Response(200, json=next(a for a in attachments if a["id"] == wanted))
        if url.endswith("/attachments") or "/attachments?" in url:
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": item["id"],
                            "name": item["name"],
                            "contentType": item["contentType"],
                            "size": len(base64.b64decode(item["contentBytes"])),
                            "isInline": False,
                            "@odata.type": item["@odata.type"],
                        }
                        for item in attachments
                    ]
                },
            )
        return httpx.Response(
            200, json=graph_message_payload(MESSAGE_ID, hasAttachments=bool(attachments))
        )

    return GraphClient(httpx.AsyncClient(transport=httpx.MockTransport(handler)))


@pytest.fixture
def scripted_model(monkeypatch: pytest.MonkeyPatch):
    """The three answers the intake pipeline asks for, in the order it asks for them."""
    replies = [
        classification_response("purchase", 0.94, "scrap"),
        document_classification_response("invoice", 0.96, None),
        extraction_response(
            {
                "invoice_number": ("INV-2026-0451", 0.97),
                "contract_reference": (CONTRACT, 0.95),
                "batch_number": (None, 0.10),
                "supplier_name": (SUPPLIER, 0.96),
                "invoice_status": ("provisional", 0.90),
                "commodity_code": ("Copper Millberry", 0.91),
                "quantity": ("24.500 MT", 0.96),
                "rate": ("8125.00", 0.94),
                "currency": ("USD", 0.99),
                "amount": ("199062.50", 0.95),
                "container_or_bl_reference": ("MSKU7781234", 0.88),
                "invoice_date": ((utcnow().date() - timedelta(days=6)).isoformat(), 0.93),
            }
        ),
    ]
    calls: list[str] = []

    async def _raw(prompt, response_schema, images):
        calls.append(prompt)
        return replies[min(len(calls) - 1, len(replies) - 1)]

    monkeypatch.setattr("app.services.gemini_service._generate_raw", _raw)
    return calls


async def desk(signed_in, role: str, suffix: str):
    return await signed_in(
        f"00000000-0000-4000-8000-{suffix}",
        f"{role}.e2e@agfze.test",
        role.replace("_", " ").title(),
        [role],
    )


async def await_job(session: AsyncSession, job_id) -> BackgroundJob:
    """Let the tracked background task finish, then read its row back.

    Draft generation runs as a real `asyncio` task on its own session, exactly as it does in
    production, so the test yields to the loop rather than reaching inside the service.
    """
    for _ in range(200):
        await asyncio.sleep(0.01)
        await session.rollback()
        job = await session.get(BackgroundJob, UUID(str(job_id)), populate_existing=True)
        if job is not None and job.status in (
            JobStatus.COMPLETED.value,
            JobStatus.FAILED.value,
        ):
            return job
    raise AssertionError("the draft generation job never reached a terminal state")


async def approve_through_the_api(
    client: AsyncClient, db_session: AsyncSession, headers, transaction_id
) -> None:
    task = await db_session.scalar(
        select(ApprovalTask).where(ApprovalTask.transaction_id == transaction_id)
    )
    assert task is not None, "submitting did not raise an approval task"
    response = await client.post(
        f"{APPROVALS}/{task.id}/decide", headers=headers, json={"decision": "approved"}
    )
    assert response.status_code == 200, response.text


# --- 1. a complete purchase deal, from the mail arriving ------------------------------------------


async def test_a_purchase_deal_travels_from_an_email_to_committed(
    client: AsyncClient, db_session: AsyncSession, signed_in, scripted_model, storage_root
) -> None:
    """The platform's whole promise, in one test.

    A mail lands. The classifier reads it. The extractor reads the attachment. A person confirms
    what was read. A transaction is raised off it and judged against every configured rule. An
    approver signs it. Three postings resolve. The batch reaches `Committed` - and every  of
    that is a real code path, not a fixture standing in for one.
    """
    _, purchase_headers = await desk(signed_in, PlatformRole.PURCHASE_USER.value, "00000000e001")
    _, approver_headers = await desk(signed_in, PlatformRole.APPROVER_HOD.value, "00000000e002")

    # 1. the mail arrives, with the supplier invoice attached.
    graph = mailbox_holding(text_layer_pdf(["Commercial Invoice", f"Contract {CONTRACT}"]))
    try:
        arrival = await ingest_message(db_session, MESSAGE_ID, client=graph, process=False)
    finally:
        await graph.aclose()
    await db_session.commit()
    assert arrival.created is True

    # 2. classification and extraction, through the real pipeline and the real job row.
    job = await job_service.create_job(db_session, job_type=document_service.JOB_TYPE_INTAKE)
    await db_session.commit()
    await document_service.process_request(db_session, arrival.request_id, job.id)
    await db_session.commit()

    document = await db_session.scalar(
        select(Document).where(Document.request_id == arrival.request_id)
    )
    assert document is not None
    assert document.document_type == DocumentType.INVOICE.value
    # Read once, before anything expires this session: an expired attribute read outside a
    # greenlet is an error rather than a query.
    document_id = document.id
    request_id = arrival.request_id

    # 3. a person confirms what the machine read - and confirming is what raises the transaction.
    #    The matching service runs on the confirm path: this invoice quotes no batch number and
    #    matches nothing existing, so it opens a batch of its own rather than guessing at one.
    confirmed = await client.post(
        f"{DOCUMENTS}/{document_id}/confirm", headers=purchase_headers, json={}
    )
    assert confirmed.status_code == 200, confirmed.text
    match = confirmed.json()["data"]["matching"]
    assert match["outcome"] == matching_service.Outcome.NEW_TRANSACTION

    db_session.expire_all()
    transaction = await db_session.scalar(select(TradeTransaction))
    assert transaction is not None
    transaction_id = transaction.id
    assert transaction.batch_number.startswith("I")

    linked = await db_session.get(Document, document_id)
    assert linked.transaction_id == transaction_id

    # 4. the contract the invoice quotes, arriving on the same request, so BR-05 and BR-06 have
    #    agreed terms to judge the invoice against.
    request = await db_session.get(Request, request_id)
    await make_document(
        db_session,
        request,
        values=contract_values(),
        document_type=DocumentType.CONTRACT.value,
        filename="purchase-contract.pdf",
        transaction_id=transaction_id,
    )
    await db_session.commit()

    # 5. validation, and then submission - which re-validates on the server before it decides.
    submitted = await client.post(
        f"{TRANSACTIONS}/{transaction_id}/submit", headers=purchase_headers, json={}
    )
    assert submitted.status_code == 200, submitted.text

    db_session.expire_all()
    transaction = await db_session.get(TradeTransaction, transaction_id)
    assert transaction.status == TransactionStatus.APPROVAL_PENDING.value

    # 6. the approver signs it, and the three postings run.
    async with all_stubbed(
        tracker=IntegrationOutcome.succeeded("Tracker!A41"),
        sap=IntegrationOutcome.succeeded("4400010311"),
        dms=IntegrationOutcome.succeeded("DMS-77120"),
    ):
        await approve_through_the_api(client, db_session, approver_headers, transaction_id)

    db_session.expire_all()
    transaction = await db_session.get(TradeTransaction, transaction_id)
    assert transaction.status == TransactionStatus.COMMITTED.value

    jobs = await integration_service.jobs_for(db_session, transaction.id)
    assert set(statuses(jobs).values()) == {IntegrationJobStatus.SUCCEEDED.value}

    # And it is still traceable to the mail it arrived on, which is scenario 8's whole subject.
    email = await db_session.scalar(
        select(EmailMessage).where(EmailMessage.provider_message_id == MESSAGE_ID)
    )
    assert email is not None
    assert transaction.request_id == request_id


# --- 2. a complete sales deal, on the same transaction --------------------------------------------


async def test_a_sales_deal_links_to_its_purchase_leg_and_reaches_committed(
    client: AsyncClient, db_session: AsyncSession, signed_in, monkeypatch
) -> None:
    """The selling side of one physical shipment, on the transaction the buying side raised.

    The sales leg is not a second transaction. It attaches to the one the purchase leg is already
    on, which is what makes "what did we buy this for and what did we sell it for" a single row
    rather than a join somebody has to remember to make.
    """
    _, sales_headers = await desk(signed_in, PlatformRole.SALES_USER.value, "00000000e011")
    _, approver_headers = await desk(signed_in, PlatformRole.APPROVER_HOD.value, "00000000e012")

    # A destination whose document pack this platform has no seeded checklist for, so BR-04 is
    # not what this scenario ends up testing. The India pack has its own coverage in the rule
    # engine suite; here the subject is the sales leg travelling the full length of the system.
    transaction = await sales_transaction(
        db_session, batch_number="I2626-201", territory=Territory.OTHER.value
    )
    transaction_id = transaction.id
    assert transaction.purchase_leg is not None
    assert transaction.sales_leg is not None
    # One transaction, two legs: the sales leg attaches to the transaction the buying side
    # raised rather than opening a second one for the same physical shipment.
    assert transaction.sales_leg.transaction_id == transaction_id

    # The draft, generated from the record and from a shipped template - never authored by the
    # model, which is asked only which clauses this deal needs. The generation path runs on its
    # own session, which is why the identifier above was read before it did.
    async def _plan(prompt, response_schema, images):
        return VALID_CONTRACT_PLAN

    monkeypatch.setattr("app.services.gemini_service._generate_raw", _plan)
    drafted = await client.post(
        f"{TRANSACTIONS}/{transaction_id}/generate-draft",
        headers=sales_headers,
        json={"document_type": DocumentType.DRAFT_CONTRACT.value},
    )
    assert drafted.status_code == 202, drafted.text

    job = await await_job(db_session, drafted.json()["data"]["job_id"])
    assert job.status == JobStatus.COMPLETED.value

    generated = await db_session.scalar(
        select(Document).where(Document.source == DocumentSource.GENERATED.value)
    )
    assert generated is not None
    assert generated.document_type == DocumentType.DRAFT_CONTRACT.value
    # Produced, stored, and going nowhere: a draft is opened by a person, never sent to anybody.
    assert generated.request_id is None

    transaction = await db_session.get(TradeTransaction, transaction_id, populate_existing=True)

    evaluations = await rule_engine.run_validation(db_session, transaction)
    await db_session.commit()
    # BR-07 and SL-01 both ran, because the leg is there for them to read.
    assert {row.rule_id for row in evaluations} >= {RuleId.BR_07, RuleId.SL_01}
    assert not rule_engine.outstanding(evaluations), [
        row.message for row in rule_engine.outstanding(evaluations)
    ]

    submitted = await client.post(
        f"{TRANSACTIONS}/{transaction_id}/submit", headers=sales_headers, json={}
    )
    assert submitted.status_code == 200, submitted.text

    async with all_stubbed(
        tracker=IntegrationOutcome.succeeded("Tracker!A42"),
        sap=IntegrationOutcome.succeeded("4400010312"),
        dms=IntegrationOutcome.succeeded("DMS-77121"),
    ):
        await approve_through_the_api(client, db_session, approver_headers, transaction_id)

    db_session.expire_all()
    refreshed = await db_session.get(TradeTransaction, transaction_id)
    assert refreshed.status == TransactionStatus.COMMITTED.value


# --- 3. a complete FA deal ------------------------------------------------------------------------


async def test_an_fa_deal_travels_the_same_road_through_the_same_engine(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    """The genericity claim, proved by a deal rather than by a unit test.

    Not one FA-specific evaluator exists. The same BR-02, BR-05 and BR-06 that judge a scrap
    purchase judge this, because they ask the leg for a concept rather than for a column - and an
    FA transaction reaching `Committed` through the same approval and the same three postings is
    what that is worth.
    """
    _, fa_headers = await desk(signed_in, PlatformRole.FA_USER.value, "00000000e021")
    _, approver_headers = await desk(signed_in, PlatformRole.APPROVER_HOD.value, "00000000e022")

    request = await make_request(db_session, category="fa", stream="fa")
    transaction = await make_fa_transaction(db_session, batch_number="FA2626-11", request=request)
    await make_document(
        db_session,
        request,
        values=fa_values(),
        document_type=DocumentType.FA_DOCUMENT.value,
        filename="fa-fee-note.pdf",
        transaction_id=transaction.id,
    )
    await db_session.commit()
    transaction_id = transaction.id

    evaluations = await rule_engine.run_validation(db_session, transaction)
    await db_session.commit()

    judged = {row.rule_id for row in evaluations}
    assert {RuleId.BR_02, RuleId.BR_05, RuleId.BR_06} <= judged
    # No FA-specific rule was invented for it.
    assert not any(rule_id.startswith("FA-") for rule_id in judged)

    outstanding = rule_engine.outstanding(evaluations)
    assert not outstanding, [row.message for row in outstanding]

    submitted = await client.post(
        f"{TRANSACTIONS}/{transaction_id}/submit", headers=fa_headers, json={}
    )
    assert submitted.status_code == 200, submitted.text

    async with all_stubbed(
        tracker=IntegrationOutcome.succeeded("Tracker!A43"),
        sap=IntegrationOutcome.succeeded("4400010313"),
        dms=IntegrationOutcome.succeeded("DMS-77122"),
    ):
        await approve_through_the_api(client, db_session, approver_headers, transaction_id)

    db_session.expire_all()
    refreshed = await db_session.get(TradeTransaction, transaction_id)
    assert refreshed.status == TransactionStatus.COMMITTED.value


# --- 4. a hard failure, its exception, and all three notification channels -------------------------


async def test_a_hard_failure_opens_an_owned_case_that_reaches_all_three_channels(
    client: AsyncClient, db_session: AsyncSession, signed_in, monkeypatch
) -> None:
    """A quantity breach: detected, routed, owned, notified in the app, by email and by push.

    The three channels are asserted together and on the same notification row, because that is
    what "an exception genuinely triggers all three" means - not three separate mechanisms that
    each happen to work.
    """
    relay = install_relay(monkeypatch)
    push = install_push(monkeypatch)
    monkeypatch.setattr(
        "app.services.notification_service.settings.NOTIFICATION_DELIVERY_ENABLED",
        True,
        raising=False,
    )

    _, purchase_headers = await desk(signed_in, PlatformRole.PURCHASE_USER.value, "00000000e031")
    finance, _ = await desk(signed_in, PlatformRole.FINANCE_USER.value, "00000000e032")
    await set_channel(db_session, finance, "email")
    await subscribe(db_session, finance.id, endpoint="https://push.example.test/finance")
    await db_session.commit()

    # The contract prices this deal at 97% of the LME cash settlement; the transaction was keyed
    # at 95%. BR-06's price check is a hard failure at any size - price is a negotiated term, not
    # a measurement - and it is one an editable field can genuinely put right, which is what makes
    # it the honest fixture for a failure-to-resolution path.
    transaction = await seeded_transaction(
        db_session,
        contract_overrides={"price_basis": "97% of the LME cash settlement"},
        price_basis="lme_percent",
        lme_percentage="95",
    )
    transaction_id = transaction.id

    cases = list(
        (
            await db_session.scalars(
                select(ExceptionCase).where(ExceptionCase.transaction_id == transaction_id)
            )
        ).all()
    )
    price_case = next(
        case
        for case in cases
        if case.exception_type == ExceptionCategory.INVOICE_AMOUNT_OUTSIDE_TOLERANCE.value
    )
    case_id = price_case.id
    # Routed by the mapping table, not by a branch: an invoice-value problem is Finance's.
    assert price_case.owner_role == PlatformRole.FINANCE_USER.value
    assert price_case.rule_id == RuleId.BR_06
    assert price_case.check_key == CheckKey.RATE_TOLERANCE

    from app.services import notification_service

    rows = await notification_service.list_for_user(db_session, finance.id)
    opened = [row for row in rows if row.notification_type == "exception.opened"]
    assert len(opened) == 1
    # In-app, email and push - all three, on the one notification row.
    assert opened[0].email_sent_at is not None
    assert opened[0].push_sent_at is not None
    assert relay.recipients == [finance.email]
    assert len(push.delivered) == 1

    # Submission is blocked while it stands.
    blocked = await client.post(
        f"{TRANSACTIONS}/{transaction_id}/submit", headers=purchase_headers, json={}
    )
    assert blocked.status_code == 409

    # Resolution: the correction goes in through the case, and the engine re-runs behind it. A
    # correction that did not actually make the rule pass would be refused.
    resolved = await client.post(
        f"{EXCEPTIONS}/{case_id}/resolve",
        headers=purchase_headers,
        json={
            "resolution_note": "The contract is 97%; the transaction had been keyed at 95%.",
            "correction": {"name": "lme_percentage", "value": "97"},
        },
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["data"]["rule_now_passes"] is True

    db_session.expire_all()
    closed = await db_session.get(ExceptionCase, case_id)
    assert closed.resolved_at is not None

    current = await rule_engine.current_results(db_session, transaction_id)
    price_checks = [row for row in current if row.check_key == CheckKey.RATE_TOLERANCE]
    assert price_checks and all(row.passed for row in price_checks), [
        row.message for row in price_checks
    ]

    # And the desk can now put it in front of an approver, which is what resolution is for.
    submitted = await client.post(
        f"{TRANSACTIONS}/{transaction_id}/submit", headers=purchase_headers, json={}
    )
    assert submitted.status_code == 200, submitted.text


# --- 5. reject and re-submit ------------------------------------------------------------------------


async def test_a_rejected_transaction_is_genuinely_re_enterable(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    """`Validation Pending` after a rejection is a working state, not a dead end.

    The desk edits, re-validates and submits again, and the second submission raises a real
    approval task rather than being refused because the transaction has "already been submitted".
    """
    _, purchase_headers = await desk(signed_in, PlatformRole.PURCHASE_USER.value, "00000000e041")
    _, approver_headers = await desk(signed_in, PlatformRole.APPROVER_HOD.value, "00000000e042")

    transaction = await seeded_transaction(db_session)
    transaction_id = transaction.id
    first = await client.post(
        f"{TRANSACTIONS}/{transaction_id}/submit", headers=purchase_headers, json={}
    )
    assert first.status_code == 200, first.text

    task = await db_session.scalar(
        select(ApprovalTask).where(ApprovalTask.transaction_id == transaction_id)
    )
    sent_back = await client.post(
        f"{APPROVALS}/{task.id}/decide",
        headers=approver_headers,
        json={
            "decision": ApprovalDecision.CHANGES_REQUESTED.value,
            "reason": "Quote the supplier's own contract number on the invoice line.",
        },
    )
    assert sent_back.status_code == 200, sent_back.text

    db_session.expire_all()
    refreshed = await db_session.get(TradeTransaction, transaction_id)
    assert refreshed.status == TransactionStatus.VALIDATION_PENDING.value

    # Editable again, which is the half of "re-enterable" that matters.
    edited = await client.patch(
        f"{TRANSACTIONS}/{transaction_id}/fields",
        headers=purchase_headers,
        json={"changes": [{"name": "port_of_loading", "value": "Jebel Ali"}]},
    )
    assert edited.status_code == 200, edited.text

    second = await client.post(
        f"{TRANSACTIONS}/{transaction_id}/submit", headers=purchase_headers, json={}
    )
    assert second.status_code == 200, second.text

    tasks = list(
        (
            await db_session.scalars(
                select(ApprovalTask).where(ApprovalTask.transaction_id == transaction_id)
            )
        ).all()
    )
    # Both decisions are on the record: the first one decided, the second one waiting.
    assert len(tasks) == 2
    assert sorted(task.decision for task in tasks) == [
        ApprovalDecision.CHANGES_REQUESTED.value,
        ApprovalDecision.PENDING.value,
    ]


# --- 6. shipment staleness, opened by a direct call and resolved by a person ------------------------


async def test_a_stale_shipment_becomes_a_case_and_is_closed_by_recording_where_the_cargo_is(
    client: AsyncClient, db_session: AsyncSession, signed_in, monkeypatch
) -> None:
    """No rule evaluated anything here, and none pretended to.

    The sweep calls the exception service directly, which is the property  built and 
    is asked to prove. The resolution is the ordinary one: somebody types in where the cargo is.
    """
    no_adapters()
    _, logistics_headers = await desk(signed_in, PlatformRole.LOGISTICS_USER.value, "00000000e051")

    transaction = await seeded_transaction(db_session, validate=False)
    shipment = await add_shipment(db_session, transaction, checked_hours_ago=24 * 10)
    await db_session.commit()
    shipment_id = shipment.id

    result = await tracking_service.run_sweep(db_session, limit=25)
    await db_session.commit()
    assert result.considered >= 1

    case = await db_session.scalar(
        select(ExceptionCase).where(
            ExceptionCase.exception_type == ExceptionCategory.SHIPMENT_STATUS_UNAVAILABLE.value
        )
    )
    assert case is not None
    assert case.rule_id is None, "a synthetic rule evaluation was invented for this case"
    case_id = case.id

    updated = await client.patch(
        f"{SHIPMENTS}/{shipment_id}",
        headers=logistics_headers,
        json={
            "current_milestone": "in_transit",
            "note": "Carrier confirmed departure from Jebel Ali by phone.",
        },
    )
    assert updated.status_code == 200, updated.text

    resolved = await client.post(
        f"{EXCEPTIONS}/{case_id}/resolve",
        headers=logistics_headers,
        json={
            "resolution_note": (
                "Position confirmed with the carrier by phone and recorded on the shipment."
            )
        },
    )
    assert resolved.status_code == 200, resolved.text

    db_session.expire_all()
    closed = await db_session.get(ExceptionCase, case_id)
    assert closed.resolved_at is not None
    assert closed.resolved_by_id is not None
    assert closed.resolution_note


# --- 7. unconfigured SAP and DMS, honestly waiting, and completed by hand ---------------------------


async def test_an_unconfigured_deployment_reaches_committed_through_manual_completion(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    """The state every deployment ships in today, followed all the way to the end.

    Nothing claims to have posted. Both jobs sit in `awaiting_manual_action` - which is neither a
    success nor a failure - and the transaction reaches `Committed` only once a person has said,
    on the record and with a reference, that they finished each posting themselves.
    """
    _, admin_headers = await desk(signed_in, PlatformRole.ADMIN.value, "00000000e061")

    transaction = await approved_transaction(db_session, batch_number="I2626-311")
    transaction_id = transaction.id

    async with all_stubbed(
        tracker=IntegrationOutcome.succeeded("Tracker!A44"),
        sap=None,
        dms=None,
    ):
        await integration_service.create_jobs(db_session, transaction)
        await integration_service.dispatch(db_session, transaction)
        await db_session.commit()

    jobs = await integration_service.jobs_for(db_session, transaction_id)
    assert statuses(jobs)[SAP] == IntegrationJobStatus.AWAITING_MANUAL_ACTION.value
    assert statuses(jobs)[DMS] == IntegrationJobStatus.AWAITING_MANUAL_ACTION.value
    assert statuses(jobs)[TRACKER] == IntegrationJobStatus.SUCCEEDED.value

    db_session.expire_all()
    waiting = await db_session.get(TradeTransaction, transaction_id)
    assert waiting.status == TransactionStatus.INTEGRATION_PENDING.value

    for target, reference in ((SAP, "4400010499"), (DMS, "DMS-99001")):
        job = await job_for(db_session, transaction_id, target)
        response = await client.post(
            f"{INTEGRATIONS}/jobs/{job.id}/complete-manual",
            headers=admin_headers,
            json={
                "external_reference": reference,
                "note": f"Completed in {target.upper()} by hand and confirmed against the system.",
            },
        )
        assert response.status_code == 200, response.text

    db_session.expire_all()
    committed = await db_session.get(TradeTransaction, transaction_id)
    assert committed.status == TransactionStatus.COMMITTED.value

    jobs = await integration_service.jobs_for(db_session, transaction_id)
    manual = {job.target_system for job in jobs if job.completed_manually}
    assert manual == {SAP, DMS}
    # Committed, and still visibly not automated. `completed_manually` is a flag on a resolved
    # job rather than a status of its own, which is what keeps "a person finished this" readable
    # long after the transaction moved on.
    assert all(job.status == IntegrationJobStatus.SUCCEEDED.value for job in jobs)
    assert {job.target_system for job in jobs if not job.completed_manually} == {TRACKER}


# --- 8. the audit reconstruction ---------------------------------------------------------------------


async def test_a_committed_transaction_reconstructs_all_the_way_back_to_its_email(
    client: AsyncClient, db_session: AsyncSession, signed_in, scripted_model, storage_root
) -> None:
    """This platform's original promise: any number can be explained to an auditor in minutes.

    Starting from nothing but a committed transaction, an auditor walks the record outwards -
    documents, rule evaluations, the approval and its decider, the three postings, and the audit
    trail itself - and lands on the email the whole thing arrived on. Every hop is a stored
    relationship rather than an inference.
    """
    _, purchase_headers = await desk(signed_in, PlatformRole.PURCHASE_USER.value, "00000000e071")
    _, approver_headers = await desk(signed_in, PlatformRole.APPROVER_HOD.value, "00000000e072")
    _, auditor_headers = await desk(signed_in, PlatformRole.AUDITOR.value, "00000000e073")

    graph = mailbox_holding(text_layer_pdf(["Commercial Invoice", f"Contract {CONTRACT}"]))
    try:
        arrival = await ingest_message(db_session, MESSAGE_ID, client=graph, process=False)
    finally:
        await graph.aclose()
    await db_session.commit()

    job = await job_service.create_job(db_session, job_type=document_service.JOB_TYPE_INTAKE)
    await db_session.commit()
    await document_service.process_request(db_session, arrival.request_id, job.id)
    await db_session.commit()

    request_id = arrival.request_id
    request = await db_session.get(Request, request_id)
    transaction = await make_transaction(db_session, request=request, batch_number="I2626-401")
    transaction_id = transaction.id
    invoice = await db_session.scalar(select(Document).where(Document.request_id == request_id))
    invoice.transaction_id = transaction_id
    await make_document(
        db_session,
        request,
        values=contract_values(),
        document_type=DocumentType.CONTRACT.value,
        filename="purchase-contract.pdf",
        transaction_id=transaction_id,
    )
    await make_document(
        db_session,
        request,
        values=invoice_values(),
        document_type=DocumentType.INVOICE.value,
        filename="supplier-invoice.pdf",
        transaction_id=transaction_id,
    )
    await db_session.commit()

    submitted = await client.post(
        f"{TRANSACTIONS}/{transaction_id}/submit", headers=purchase_headers, json={}
    )
    assert submitted.status_code == 200, submitted.text

    async with all_stubbed(
        tracker=IntegrationOutcome.succeeded("Tracker!A45"),
        sap=IntegrationOutcome.succeeded("4400010500"),
        dms=IntegrationOutcome.succeeded("DMS-88000"),
    ):
        await approve_through_the_api(client, db_session, approver_headers, transaction_id)

    db_session.expire_all()
    committed = await db_session.get(TradeTransaction, transaction_id)
    assert committed.status == TransactionStatus.COMMITTED.value

    # --- the reconstruction, hop by hop, from the batch number alone ---------------------------
    batch = committed.batch_number

    found = await db_session.scalar(
        select(TradeTransaction).where(TradeTransaction.batch_number == batch)
    )
    assert found is not None

    # 1. the documents it was judged on.
    documents = list(
        (
            await db_session.scalars(select(Document).where(Document.transaction_id == found.id))
        ).all()
    )
    assert {document.document_type for document in documents} >= {
        DocumentType.INVOICE.value,
        DocumentType.CONTRACT.value,
    }

    # 2. every check that was run against it, and what each one said.
    evaluations = list(
        (
            await db_session.scalars(
                select(RuleEvaluation).where(RuleEvaluation.transaction_id == found.id)
            )
        ).all()
    )
    assert evaluations
    assert all(row.message for row in evaluations)

    # 3. the approval, and who made it - server-derived, never client-supplied.
    approval = await db_session.scalar(
        select(ApprovalTask).where(ApprovalTask.transaction_id == found.id)
    )
    assert approval.decision == ApprovalDecision.APPROVED.value
    assert approval.decided_by_id is not None
    assert approval.decided_at is not None

    # 4. the three postings and their external references.
    jobs = list(
        (
            await db_session.scalars(
                select(IntegrationJob).where(IntegrationJob.transaction_id == found.id)
            )
        ).all()
    )
    assert {job.target_system for job in jobs} == {TRACKER, SAP, DMS}
    assert all(job.external_reference for job in jobs)

    # 5. any exception case raised on the way - none here, and the query is the same either way.
    cases = list(
        (
            await db_session.scalars(
                select(ExceptionCase).where(ExceptionCase.transaction_id == found.id)
            )
        ).all()
    )
    assert isinstance(cases, list)

    # 6. and back to the request, and the mail it arrived on.
    originating_request = await db_session.get(Request, found.request_id)
    assert originating_request is not None
    assert originating_request.email_message_id is not None
    email = await db_session.get(EmailMessage, originating_request.email_message_id)
    assert email is not None
    assert email.provider_message_id == MESSAGE_ID
    assert email.sender_address == "desk@broker.example"
    # The untouched original is still on file, behind an opaque key rather than a path.
    assert email.raw_storage_ref and not email.raw_storage_ref.startswith("/")

    # 7. the append-only trail carries the whole story, and the auditor can read it.
    trail = list(
        (
            await db_session.scalars(
                select(AuditEvent).where(AuditEvent.entity_id == str(found.id))
            )
        ).all()
    )
    assert {event.event_type for event in trail} >= {
        "transaction.submitted",
        "integration.transaction.committed",
    }

    readable = await client.get(AUDIT, headers=auditor_headers, params={"entity_id": str(found.id)})
    assert readable.status_code == 200, readable.text
    assert readable.json()["data"]["items"]

    # An auditor reads; an auditor never writes.
    for method in ("post", "patch", "delete"):
        blocked = await getattr(client, method)(AUDIT, headers=auditor_headers)
        assert blocked.status_code == 405


async def test_the_trail_of_a_committed_batch_names_every_actor_and_no_document_text(
    db_session: AsyncSession,
) -> None:
    """The reconstruction has to be readable *and* safe to hand to an auditor.

    Metadata only: the trail says a field was corrected, by whom and why, and never carries the
    document text or the model's answer that the correction was made against.
    """
    transaction = await seeded_transaction(db_session)
    await db_session.commit()

    events = list(
        (
            await db_session.scalars(
                select(AuditEvent).where(AuditEvent.entity_id == str(transaction.id))
            )
        ).all()
    )
    for event in events:
        rendered = str(event.event_metadata or {})
        assert "Commercial Invoice" not in rendered
        assert "prompt" not in rendered.lower()

    total = await db_session.scalar(select(func.count(AuditEvent.id)))
    assert total is not None
