"""Document retention: the mechanism, and the three switches that keep it from acting.

Most of this file asserts that nothing happened. That is the point. The BRD asks for a retention
policy and leaves the period for AGFZE to confirm, so the only honest thing to ship is a mechanism
that is off, has no default period, and reports rather than acts even once configured. A wrong
threshold produces a wrong decision somebody can reverse; a wrong retention period destroys a trade
document nobody can get back.

The last test in this file is the one that matters most: there is no code path here that deletes
anything, and it fails if one appears.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.base import utcnow
from app.models.audit import AuditEvent
from app.models.intake import Document
from app.services.analytics import retention
from tests.utils.transactions import invoice_values, make_document, make_request

pytestmark = pytest.mark.usefixtures("patched_jwks")


async def _aged_document(session: AsyncSession, *, days_old: int, filename: str) -> Document:
    request = await make_request(session)
    document = await make_document(session, request, values=invoice_values(), filename=filename)
    document.created_at = utcnow() - timedelta(days=days_old)
    await session.commit()
    return document


def _configure(monkeypatch: pytest.MonkeyPatch, *, enabled: bool, days: int, dry_run: bool) -> None:
    monkeypatch.setattr(settings, "DOCUMENT_RETENTION_ENABLED", enabled)
    monkeypatch.setattr(settings, "DOCUMENT_RETENTION_DAYS", days)
    monkeypatch.setattr(settings, "DOCUMENT_RETENTION_DRY_RUN", dry_run)


# --- the shipped state ------------------------------------------------------------------------


def test_retention_ships_off_with_no_period_and_in_dry_run() -> None:
    """All three defaults, asserted together, because any one of them alone is not the safeguard.

    Read off the base `Settings` class rather than the live instance: the suite runs under
    `TestingSettings` with a development .env on the path, and what matters here is what a fresh
    deployment gets, not what this process happens to be holding.
    """
    from app.core.config import Settings

    assert Settings.model_fields["DOCUMENT_RETENTION_ENABLED"].default is False
    assert Settings.model_fields["DOCUMENT_RETENTION_DAYS"].default == 0
    assert Settings.model_fields["DOCUMENT_RETENTION_DRY_RUN"].default is True


async def test_a_disabled_sweep_looks_at_nothing(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, storage_root
) -> None:
    await _aged_document(db_session, days_old=4000, filename="ancient.pdf")
    _configure(monkeypatch, enabled=False, days=365, dry_run=False)

    result = await retention.run_due(db_session)

    assert result.skipped_reason == "retention_disabled"
    assert result.considered == 0
    assert result.flagged == []


async def test_enabling_retention_without_a_period_does_nothing_and_says_so(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, storage_root
) -> None:
    """Somebody turned this on expecting it to act. Silence would let them believe it had.

    Enabled but unconfigured is an intention rather than a policy, and acting on it would mean
    choosing the retention period on AGFZE's behalf - the exact thing this job must not do.
    """
    await _aged_document(db_session, days_old=4000, filename="ancient.pdf")
    _configure(monkeypatch, enabled=True, days=0, dry_run=False)

    result = await retention.run_due(db_session)

    assert result.skipped_reason == "no_period_configured"
    assert result.flagged == []


def test_the_worker_will_not_run_a_sweep_that_has_no_period(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "DOCUMENT_RETENTION_ENABLED", True)
    monkeypatch.setattr(settings, "DOCUMENT_RETENTION_DAYS", 0)
    monkeypatch.setattr(settings, "ENV", "production")
    assert retention.should_run() is False


# --- configured, and still not acting ------------------------------------------------------------


async def test_a_dry_run_finds_what_is_old_and_records_nothing(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, storage_root
) -> None:
    await _aged_document(db_session, days_old=400, filename="old.pdf")
    _configure(monkeypatch, enabled=True, days=365, dry_run=True)

    before = await db_session.scalar(select(func.count(AuditEvent.id)))
    result = await retention.run_due(db_session)
    await db_session.commit()

    assert result.dry_run is True
    assert len(result.flagged) == 1
    assert result.flagged[0].reference == "old.pdf"
    assert result.acted is False
    # Not one row written. A dry run that wrote an audit trail would not be a dry run.
    assert await db_session.scalar(select(func.count(AuditEvent.id))) == before


async def test_a_document_younger_than_the_period_is_never_considered(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, storage_root
) -> None:
    await _aged_document(db_session, days_old=10, filename="recent.pdf")
    _configure(monkeypatch, enabled=True, days=365, dry_run=True)

    result = await retention.run_due(db_session)

    assert result.flagged == []


# --- fully switched on ----------------------------------------------------------------------------


async def test_a_live_sweep_flags_for_review_and_deletes_nothing(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, storage_root
) -> None:
    """What the job does at its most enabled: writes a row saying a person should look.

    The document is still there afterwards, and the audit row says so in as many words.
    """
    document = await _aged_document(db_session, days_old=400, filename="old.pdf")
    _configure(monkeypatch, enabled=True, days=365, dry_run=False)

    result = await retention.run_due(db_session)
    await db_session.commit()

    assert result.acted is True
    events = (
        await db_session.scalars(
            select(AuditEvent).where(AuditEvent.event_type == retention.RETENTION_REVIEW_EVENT)
        )
    ).all()
    assert len(events) == 1
    assert events[0].event_metadata["action"] == "flagged_for_review"
    assert events[0].event_metadata["deleted"] is False
    assert events[0].event_metadata["retention_days"] == 365

    # The document itself is untouched. This is the assertion the whole feature turns on.
    assert await db_session.get(Document, document.id) is not None


async def test_a_sweep_is_bounded_so_a_first_run_cannot_hold_the_table(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, storage_root
) -> None:
    """A deployment switching this on may have years behind it; one long pass is the wrong shape."""
    assert retention.SWEEP_LIMIT > 0
    _configure(monkeypatch, enabled=True, days=365, dry_run=True)
    for index in range(3):
        await _aged_document(db_session, days_old=400 + index, filename=f"old-{index}.pdf")

    result = await retention.run_due(db_session)
    assert len(result.flagged) == 3


# --- the guard --------------------------------------------------------------------------------------


def test_the_retention_module_contains_no_deletion_path_at_all() -> None:
    """The assertion that keeps this feature safe as it is edited later.

    Archival to a colder storage class belongs in a bucket lifecycle rule, in Terraform, where it
    is reviewable - not in a job that could be misconfigured into a delete. If retention is ever
    genuinely meant to remove something, that is a deliberate change and this test is deleted with
    it, rather than quietly stopping being true.
    """
    from pathlib import Path

    source = Path(retention.__file__).read_text()
    for forbidden in (
        ".delete(",
        "storage.delete",
        "session.delete",
        "op.execute",
    ):
        assert forbidden not in source, (
            f"the retention module contains '{forbidden}'. It flags for review and removes "
            "nothing; see docs/KNOWN-GAPS.md before changing that."
        )
