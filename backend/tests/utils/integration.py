"""Builders and stand-ins for the  suite.

The stub adapters here are the only concrete SAP and DMS clients anywhere near this codebase, and
that is the whole point: neither system's contract is specified in this platform's material, so
the application ships an adapter with an honest fallback rather than a fabricated client, and a
test is the right place - the only place - for a stand-in to live.

`use_adapter` and `all_stubbed` replace an adapter for the duration of a test and always put the
real one back, so no test can leave the process believing an integration exists.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import (
    IntegrationJobStatus,
    IntegrationTargetSystem,
    TransactionStatus,
)
from app.models.integration import IntegrationJob
from app.services.integration import integration_service
from app.services.integration.adapters import IntegrationOutcome


class StubAdapter:
    """One target system, answering however the test needs it to.

    Shaped exactly like the real adapters: a target system, a `configured` flag the orchestration
    reads to decide which path to take, and a `run` that returns an `IntegrationOutcome`. If the
    orchestration needed anything more than this to work, no real adapter could be written either.
    """

    def __init__(
        self,
        target_system: str,
        outcome: IntegrationOutcome,
        *,
        configured: bool = True,
        raises: Exception | None = None,
    ) -> None:
        self.target_system = target_system
        self.outcome = outcome
        self._configured = configured
        self.raises = raises
        self.calls = 0

    @property
    def configured(self) -> bool:
        return self._configured

    async def run(self, session, job, transaction) -> IntegrationOutcome:
        self.calls += 1
        if self.raises is not None:
            raise self.raises
        return self.outcome


@contextmanager
def use_adapter(target_system: str, adapter) -> Iterator[object]:
    """Swap one adapter in for the duration of a test, and always put the real one back."""
    previous = integration_service.set_adapter(target_system, adapter)
    try:
        yield adapter
    finally:
        integration_service.set_adapter(target_system, previous)


@asynccontextmanager
async def all_stubbed(
    *,
    tracker: IntegrationOutcome | None = None,
    sap: IntegrationOutcome | None = None,
    dms: IntegrationOutcome | None = None,
) -> AsyncIterator[dict[str, StubAdapter]]:
    """Stub every target at once, defaulting each to the unconfigured manual path."""
    stubs = {
        IntegrationTargetSystem.TRACKER.value: StubAdapter(
            IntegrationTargetSystem.TRACKER.value,
            tracker
            or IntegrationOutcome.awaiting_manual_action(
                "Enter this row in the tracker by hand.", payload={"tracker_row": {}}
            ),
            configured=tracker is not None,
        ),
        IntegrationTargetSystem.SAP.value: StubAdapter(
            IntegrationTargetSystem.SAP.value,
            sap
            or IntegrationOutcome.awaiting_manual_action(
                "Key this into SAP by hand.", payload={"trade_contract": {}}
            ),
            configured=sap is not None,
        ),
        IntegrationTargetSystem.DMS.value: StubAdapter(
            IntegrationTargetSystem.DMS.value,
            dms
            or IntegrationOutcome.awaiting_manual_action(
                "File this pack by hand.", payload={"packs": []}
            ),
            configured=dms is not None,
        ),
    }
    previous = {
        target: integration_service.set_adapter(target, stub) for target, stub in stubs.items()
    }
    try:
        yield stubs
    finally:
        for target, adapter in previous.items():
            integration_service.set_adapter(target, adapter)


async def approved_transaction(session: AsyncSession, **kwargs):
    """A transaction sitting in `Approved`, ready for the integration hub to pick up."""
    from tests.utils.transactions import make_transaction

    transaction = await make_transaction(session, status=TransactionStatus.APPROVED.value, **kwargs)
    await session.commit()
    return transaction


async def job_for(session: AsyncSession, transaction_id, target_system: str) -> IntegrationJob:
    jobs = await integration_service.jobs_for(session, transaction_id)
    return next(job for job in jobs if job.target_system == target_system)


def statuses(jobs: list[IntegrationJob]) -> dict[str, str]:
    return {job.target_system: job.status for job in jobs}


AWAITING = IntegrationJobStatus.AWAITING_MANUAL_ACTION.value
SUCCEEDED = IntegrationJobStatus.SUCCEEDED.value
FAILED = IntegrationJobStatus.FAILED.value
QUEUED = IntegrationJobStatus.QUEUED.value
