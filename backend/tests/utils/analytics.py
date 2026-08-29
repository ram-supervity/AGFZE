"""Fixtures for the dashboard, KPI and reporting suite.

Everything is written through the real tables, at real timestamps, so the KPI definitions are
exercised against rows shaped exactly as the services leave them. Nothing here builds a summary,
a rollup or a stored aggregate - if one existed, these helpers could not construct the situations
the tests need.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import (
    ApprovalDecision,
    DocumentType,
    ExceptionPriority,
    ExtractionStatus,
    IntegrationJobStatus,
    IntegrationTargetSystem,
    ShipmentStatus,
    TransactionStatus,
)
from app.models.governance import ApprovalTask, ExceptionCase
from app.models.identity import User
from app.models.intake import Document, ExtractedField
from app.models.integration import IntegrationJob
from app.models.logistics import Shipment
from app.models.transactions import TradeTransaction
from tests.utils.transactions import make_request, make_transaction


async def transaction_at(
    session: AsyncSession,
    *,
    batch_number: str,
    created_at: datetime,
    status: str = TransactionStatus.MATCHED.value,
    stream: str = "scrap",
    request_created_at: datetime | None = None,
) -> TradeTransaction:
    """One transaction, and the request behind it, both stamped where the test needs them."""
    request = await make_request(session, stream=stream)
    request.created_at = request_created_at or created_at
    transaction = await make_transaction(
        session, request=request, batch_number=batch_number, status=status
    )
    transaction.stream = stream
    transaction.created_at = created_at
    await session.flush()
    return transaction


async def approve(
    session: AsyncSession,
    transaction: TradeTransaction,
    *,
    decided_at: datetime,
    decision: str = ApprovalDecision.APPROVED.value,
    requested_at: datetime | None = None,
) -> ApprovalTask:
    task = ApprovalTask(
        transaction_id=transaction.id,
        approver_role="approver_hod",
        requested_at=requested_at or decided_at - timedelta(hours=1),
        decision=decision,
        decided_at=decided_at,
    )
    session.add(task)
    await session.flush()
    return task


async def pending_approval(
    session: AsyncSession, transaction: TradeTransaction, *, requested_at: datetime
) -> ApprovalTask:
    task = ApprovalTask(
        transaction_id=transaction.id,
        approver_role="approver_hod",
        requested_at=requested_at,
        decision=ApprovalDecision.PENDING.value,
    )
    session.add(task)
    await session.flush()
    return task


async def open_exception(
    session: AsyncSession,
    *,
    exception_type: str,
    owner_role: str,
    opened_at: datetime,
    transaction: TradeTransaction | None = None,
    resolved_at: datetime | None = None,
    escalated: bool = False,
) -> ExceptionCase:
    case = ExceptionCase(
        transaction_id=transaction.id if transaction is not None else None,
        exception_type=exception_type,
        owner_role=owner_role,
        priority=ExceptionPriority.MEDIUM.value,
        summary="Opened by the analytics test suite.",
        opened_at=opened_at,
        resolved_at=resolved_at,
        escalated=escalated,
    )
    session.add(case)
    await session.flush()
    return case


async def extracted_document(
    session: AsyncSession,
    *,
    document_type: str = DocumentType.INVOICE.value,
    created_at: datetime,
    field_count: int,
    overridden: int,
    request=None,
    stream: str = "scrap",
) -> Document:
    """One document with a known number of fields, a known number of them overridden."""
    request = request or await make_request(session, stream=stream)
    request.created_at = created_at
    document = Document(
        request_id=request.id,
        filename=f"{document_type}-{uuid.uuid4().hex[:6]}.pdf",
        content_type="application/pdf",
        byte_size=2048,
        storage_ref=f"documents/source/{uuid.uuid4().hex}.pdf",
        content_hash=uuid.uuid4().hex * 2,
        document_type=document_type,
        page_count=1,
        extraction_status=ExtractionStatus.COMPLETED.value,
        created_at=created_at,
    )
    session.add(document)
    await session.flush()

    for index in range(field_count):
        session.add(
            ExtractedField(
                document_id=document.id,
                field_name=f"field_{index}",
                field_value="value",
                confidence=0.9,
                original_ai_value="value",
                original_confidence=0.9,
                is_overridden=index < overridden,
                created_at=created_at,
            )
        )
    await session.flush()
    return document


async def integration_job(
    session: AsyncSession,
    transaction: TradeTransaction,
    *,
    target_system: str = IntegrationTargetSystem.SAP.value,
    status: str = IntegrationJobStatus.QUEUED.value,
) -> IntegrationJob:
    job = IntegrationJob(
        transaction_id=transaction.id,
        target_system=target_system,
        status=status,
    )
    session.add(job)
    await session.flush()
    return job


async def shipment(
    session: AsyncSession,
    transaction: TradeTransaction,
    *,
    status: str = ShipmentStatus.ON_SCHEDULE.value,
    last_checked_at: datetime | None = None,
) -> Shipment:
    row = Shipment(
        transaction_id=transaction.id,
        bl_number=f"BL-{uuid.uuid4().hex[:8].upper()}",
        carrier="Sample Line",
        status=status,
        last_checked_at=last_checked_at,
    )
    session.add(row)
    await session.flush()
    return row


async def account(session: AsyncSession, *, roles: list[str], name: str = "Test Account") -> User:
    """A user row for the services that take one directly, without going through the API."""
    user = User(
        subject_id=f"test-{uuid.uuid4().hex[:12]}",
        email=f"{uuid.uuid4().hex[:8]}@agfze.test",
        display_name=name,
        roles=roles,
    )
    session.add(user)
    await session.flush()
    return user
