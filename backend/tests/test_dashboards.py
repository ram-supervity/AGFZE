"""The KPI definitions, the role scoping and the cache, proved against known fixture data.

Every test here builds real rows at real timestamps and asserts the number the definition in
Section 9.4 requires - not the number the code happens to produce. Where a definition involves a
judgement (the non-override rate, the exception-free automation rate), the test asserts the
judgement as written, so changing the definition breaks a test rather than quietly changing a
figure on somebody's screen.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.roles import PlatformRole
from app.db.base import utcnow
from app.models.enums import (
    ApprovalDecision,
    DocumentType,
    ExceptionCategory,
    IntegrationJobStatus,
    IntegrationTargetSystem,
    ShipmentStatus,
    TransactionStatus,
)
from app.services.analytics import kpis
from app.services.analytics.cache import TTLCache, build_key
from app.services.analytics.scope import DashboardScope, scope_for
from tests.utils.analytics import (
    account,
    approve,
    extracted_document,
    integration_job,
    open_exception,
    pending_approval,
    shipment,
    transaction_at,
)

NOW = utcnow()


def full_scope() -> DashboardScope:
    from app.models.enums import EXCEPTION_CATEGORIES

    return DashboardScope(
        streams=frozenset({"scrap", "fa"}),
        exception_categories=frozenset(EXCEPTION_CATEGORIES),
        cross_cutting=True,
        emphasis="transactions",
        roles=frozenset({PlatformRole.ADMIN.value}),
    )


# --- transaction counts by status ---------------------------------------------------------------


async def test_transaction_counts_group_by_status_and_report_real_zeros(db_session):
    await transaction_at(db_session, batch_number="D-1", created_at=NOW - timedelta(days=1))
    await transaction_at(
        db_session,
        batch_number="D-2",
        created_at=NOW - timedelta(days=2),
        status=TransactionStatus.APPROVED.value,
    )
    await transaction_at(
        db_session,
        batch_number="D-3",
        created_at=NOW - timedelta(days=3),
        status=TransactionStatus.APPROVED.value,
    )
    await db_session.commit()

    figures = await kpis.transaction_status_counts(db_session, full_scope())
    counted = {figure.key.rsplit(".", 1)[-1]: figure.value for figure in figures}

    assert counted[TransactionStatus.MATCHED.value] == 1
    assert counted[TransactionStatus.APPROVED.value] == 2
    # A status nothing is in is a real zero with a real tile, not an omitted one.
    assert counted[TransactionStatus.COMMITTED.value] == 0
    assert set(counted) == set(kpis.REPORTABLE_TRANSACTION_STATUSES)


async def test_every_status_figure_carries_the_filter_that_reproduces_it(db_session):
    await transaction_at(db_session, batch_number="D-4", created_at=NOW - timedelta(hours=2))
    await db_session.commit()

    figures = await kpis.transaction_status_counts(db_session, full_scope())
    for figure in figures:
        assert figure.target == "transactions"
        assert figure.filters["status"] == figure.key.rsplit(".", 1)[-1]


# --- exception counts, with ageing computed live ---------------------------------------------------


async def test_exception_counts_age_from_opened_at_at_query_time(db_session):
    transaction = await transaction_at(
        db_session, batch_number="E-1", created_at=NOW - timedelta(days=10)
    )
    await open_exception(
        db_session,
        exception_type=ExceptionCategory.LOW_CONFIDENCE.value,
        owner_role=PlatformRole.PURCHASE_USER.value,
        opened_at=NOW - timedelta(hours=2),
        transaction=transaction,
    )
    await open_exception(
        db_session,
        exception_type=ExceptionCategory.LOW_CONFIDENCE.value,
        owner_role=PlatformRole.PURCHASE_USER.value,
        opened_at=NOW - timedelta(hours=40),
        transaction=transaction,
    )
    await open_exception(
        db_session,
        exception_type=ExceptionCategory.LOW_CONFIDENCE.value,
        owner_role=PlatformRole.PURCHASE_USER.value,
        opened_at=NOW - timedelta(hours=100),
        transaction=transaction,
    )
    # Resolved, so it is not open and must not be counted.
    await open_exception(
        db_session,
        exception_type=ExceptionCategory.LOW_CONFIDENCE.value,
        owner_role=PlatformRole.PURCHASE_USER.value,
        opened_at=NOW - timedelta(hours=200),
        transaction=transaction,
        resolved_at=NOW - timedelta(hours=1),
    )
    await db_session.commit()

    summary = await kpis.exception_counts(db_session, full_scope(), now=NOW)
    row = next(
        item
        for item in summary["categories"]
        if item["category"] == ExceptionCategory.LOW_CONFIDENCE.value
    )

    assert row["open_count"] == 3
    assert row["ageing"] == {"under_24h": 1, "24_to_72h": 1, "over_72h": 1}
    assert row["oldest_age_hours"] == pytest.approx(100.0, abs=0.1)
    assert summary["total_open"] == 3
    assert summary["over_72h"] == 1


async def test_exception_ageing_moves_with_the_clock_rather_than_being_stored(db_session):
    transaction = await transaction_at(
        db_session, batch_number="E-2", created_at=NOW - timedelta(days=5)
    )
    await open_exception(
        db_session,
        exception_type=ExceptionCategory.LOW_CONFIDENCE.value,
        owner_role=PlatformRole.PURCHASE_USER.value,
        opened_at=NOW - timedelta(hours=20),
        transaction=transaction,
    )
    await db_session.commit()

    now_row = next(
        item
        for item in (await kpis.exception_counts(db_session, full_scope(), now=NOW))["categories"]
        if item["category"] == ExceptionCategory.LOW_CONFIDENCE.value
    )
    later_row = next(
        item
        for item in (
            await kpis.exception_counts(db_session, full_scope(), now=NOW + timedelta(hours=10))
        )["categories"]
        if item["category"] == ExceptionCategory.LOW_CONFIDENCE.value
    )

    # Same row, same opened_at, different band - because the age is computed, never stored.
    assert now_row["ageing"]["under_24h"] == 1
    assert later_row["ageing"]["24_to_72h"] == 1


# --- approval-queue depth -------------------------------------------------------------------------


async def test_approval_queue_depth_counts_pending_only(db_session):
    first = await transaction_at(db_session, batch_number="A-1", created_at=NOW - timedelta(days=2))
    second = await transaction_at(
        db_session, batch_number="A-2", created_at=NOW - timedelta(days=3)
    )
    third = await transaction_at(db_session, batch_number="A-3", created_at=NOW - timedelta(days=4))
    await pending_approval(db_session, first, requested_at=NOW - timedelta(hours=30))
    await pending_approval(db_session, second, requested_at=NOW - timedelta(hours=5))
    await approve(db_session, third, decided_at=NOW - timedelta(hours=1))
    await db_session.commit()

    depth = await kpis.approval_queue_depth(db_session, full_scope(), now=NOW)

    assert depth["pending"] == 2
    assert depth["oldest_waiting_hours"] == pytest.approx(30.0, abs=0.1)
    assert depth["filters"] == {"decision": ApprovalDecision.PENDING.value}


# --- extraction non-override rate ---------------------------------------------------------------


async def test_non_override_rate_is_the_share_of_fields_nobody_corrected(db_session):
    period = kpis.Period(start=NOW - timedelta(days=7), end=NOW + timedelta(minutes=1))
    await extracted_document(
        db_session,
        document_type=DocumentType.INVOICE.value,
        created_at=NOW - timedelta(days=1),
        field_count=10,
        overridden=2,
    )
    await extracted_document(
        db_session,
        document_type=DocumentType.CONTRACT.value,
        created_at=NOW - timedelta(days=2),
        field_count=10,
        overridden=5,
    )
    # Outside the window entirely, so it must not move either figure.
    await extracted_document(
        db_session,
        document_type=DocumentType.INVOICE.value,
        created_at=NOW - timedelta(days=40),
        field_count=10,
        overridden=10,
    )
    await db_session.commit()

    result = await kpis.extraction_non_override_rate(db_session, full_scope(), period)

    assert result["field_count"] == 20
    assert result["overridden_count"] == 7
    assert result["non_override_rate"] == pytest.approx(65.0)
    assert result["measure"] == "non_override_rate"
    # The label the UI renders never claims verified correctness.
    assert "not a verified-correctness measurement" in result["disclosure"]

    by_type = {row["document_type"]: row for row in result["by_document_type"]}
    assert by_type[DocumentType.INVOICE.value]["non_override_rate"] == pytest.approx(80.0)
    assert by_type[DocumentType.CONTRACT.value]["non_override_rate"] == pytest.approx(50.0)


async def test_non_override_rate_is_absent_rather_than_zero_when_nothing_was_extracted(db_session):
    period = kpis.Period(start=NOW - timedelta(days=7), end=NOW)
    result = await kpis.extraction_non_override_rate(db_session, full_scope(), period)

    # "Nothing was read" and "nothing was right" are different answers.
    assert result["field_count"] == 0
    assert result["non_override_rate"] is None


# --- turnaround -----------------------------------------------------------------------------------


async def test_turnaround_measures_request_created_to_approval_decided(db_session):
    period = kpis.Period(start=NOW - timedelta(days=30), end=NOW + timedelta(minutes=1))

    for batch, hours in (("T-1", 10), ("T-2", 20), ("T-3", 60)):
        decided = NOW - timedelta(days=1)
        transaction = await transaction_at(
            db_session,
            batch_number=batch,
            created_at=decided - timedelta(hours=hours),
            request_created_at=decided - timedelta(hours=hours),
        )
        await approve(db_session, transaction, decided_at=decided)
    await db_session.commit()

    rows = await kpis.approved_rows(db_session, full_scope(), period)
    turnaround = kpis.turnaround_from(rows)

    assert turnaround["sample_size"] == 3
    assert turnaround["mean_hours"] == pytest.approx(30.0, abs=0.05)
    assert turnaround["median_hours"] == pytest.approx(20.0, abs=0.05)
    assert turnaround["fastest_hours"] == pytest.approx(10.0, abs=0.05)
    assert turnaround["slowest_hours"] == pytest.approx(60.0, abs=0.05)


async def test_turnaround_ignores_a_rejection_and_anything_outside_the_period(db_session):
    period = kpis.Period(start=NOW - timedelta(days=7), end=NOW + timedelta(minutes=1))

    rejected = await transaction_at(
        db_session, batch_number="T-4", created_at=NOW - timedelta(days=2)
    )
    await approve(
        db_session,
        rejected,
        decided_at=NOW - timedelta(days=1),
        decision=ApprovalDecision.REJECTED.value,
    )

    old = await transaction_at(db_session, batch_number="T-5", created_at=NOW - timedelta(days=60))
    await approve(db_session, old, decided_at=NOW - timedelta(days=50))
    await db_session.commit()

    rows = await kpis.approved_rows(db_session, full_scope(), period)
    assert kpis.turnaround_from(rows)["sample_size"] == 0
    assert kpis.turnaround_from(rows)["mean_hours"] is None


# --- automation percentage ------------------------------------------------------------------------


async def test_automation_rate_counts_approvals_with_no_exception_ever_opened(db_session):
    period = kpis.Period(start=NOW - timedelta(days=30), end=NOW + timedelta(minutes=1))

    clean_one = await transaction_at(
        db_session, batch_number="M-1", created_at=NOW - timedelta(days=5)
    )
    clean_two = await transaction_at(
        db_session, batch_number="M-2", created_at=NOW - timedelta(days=5)
    )
    clean_three = await transaction_at(
        db_session, batch_number="M-3", created_at=NOW - timedelta(days=5)
    )
    intervened = await transaction_at(
        db_session, batch_number="M-4", created_at=NOW - timedelta(days=5)
    )

    for transaction in (clean_one, clean_two, clean_three, intervened):
        await approve(db_session, transaction, decided_at=NOW - timedelta(days=1))

    # Opened AND resolved. "Ever had an exception opened against it" is the definition, so this
    # transaction is not automated even though nothing is open against it now.
    await open_exception(
        db_session,
        exception_type=ExceptionCategory.INVOICE_AMOUNT_OUTSIDE_TOLERANCE.value,
        owner_role=PlatformRole.FINANCE_USER.value,
        opened_at=NOW - timedelta(days=4),
        transaction=intervened,
        resolved_at=NOW - timedelta(days=3),
    )
    await db_session.commit()

    rows = await kpis.approved_rows(db_session, full_scope(), period)
    automation = kpis.automation_from(rows)

    assert automation["approved_count"] == 4
    assert automation["exception_free_count"] == 3
    assert automation["intervened_count"] == 1
    assert automation["automation_rate"] == pytest.approx(75.0)


async def test_automation_rate_is_absent_rather_than_zero_with_no_approvals(db_session):
    period = kpis.Period(start=NOW - timedelta(days=7), end=NOW)
    automation = kpis.automation_from(await kpis.approved_rows(db_session, full_scope(), period))

    assert automation["approved_count"] == 0
    assert automation["automation_rate"] is None


# --- integration counts: two figures, never one --------------------------------------------------


async def test_failed_and_awaiting_manual_are_reported_separately(db_session):
    first = await transaction_at(db_session, batch_number="I-1", created_at=NOW - timedelta(days=1))
    second = await transaction_at(
        db_session, batch_number="I-2", created_at=NOW - timedelta(days=1)
    )

    await integration_job(
        db_session,
        first,
        target_system=IntegrationTargetSystem.SAP.value,
        status=IntegrationJobStatus.FAILED.value,
    )
    await integration_job(
        db_session,
        first,
        target_system=IntegrationTargetSystem.DMS.value,
        status=IntegrationJobStatus.AWAITING_MANUAL_ACTION.value,
    )
    await integration_job(
        db_session,
        second,
        target_system=IntegrationTargetSystem.DMS.value,
        status=IntegrationJobStatus.AWAITING_MANUAL_ACTION.value,
    )
    await integration_job(
        db_session,
        second,
        target_system=IntegrationTargetSystem.TRACKER.value,
        status=IntegrationJobStatus.SUCCEEDED.value,
    )
    await db_session.commit()

    counts = await kpis.integration_counts(db_session, full_scope())

    assert counts["failed"] == 1
    assert counts["awaiting_manual_action"] == 2
    assert counts["succeeded"] == 1
    # There is no key anywhere in the payload that adds the two together.
    assert not any(key for key in counts if "failure" in key and "awaiting" in key), (
        "the two figures must never be merged into one"
    )


# --- shipment summary ------------------------------------------------------------------------------


async def test_shipment_summary_counts_by_status_and_stale_separately(db_session):
    transaction = await transaction_at(
        db_session, batch_number="S-1", created_at=NOW - timedelta(days=3)
    )
    await shipment(
        db_session,
        transaction,
        status=ShipmentStatus.ON_SCHEDULE.value,
        last_checked_at=NOW - timedelta(hours=1),
    )
    await shipment(
        db_session,
        transaction,
        status=ShipmentStatus.DELAYED.value,
        last_checked_at=NOW - timedelta(hours=100),
    )
    # Never checked at all, which is stale by definition and must be counted as such.
    await shipment(db_session, transaction, status=ShipmentStatus.DELAYED.value)
    await db_session.commit()

    summary = await kpis.shipment_summary(db_session, full_scope(), stale_hours=48, now=NOW)
    by_status = {row["status"]: row["count"] for row in summary["by_status"]}

    assert by_status[ShipmentStatus.ON_SCHEDULE.value] == 1
    assert by_status[ShipmentStatus.DELAYED.value] == 2
    assert by_status[ShipmentStatus.ARRIVED.value] == 0
    assert summary["stale_count"] == 2
    assert summary["total"] == 3


# --- role scoping, at the query layer --------------------------------------------------------------


async def test_a_desk_role_cannot_count_an_exception_category_it_does_not_work(db_session):
    """The scoping test that matters: the data exists and the query never sees it."""
    transaction = await transaction_at(
        db_session, batch_number="R-1", created_at=NOW - timedelta(days=1)
    )
    await open_exception(
        db_session,
        exception_type=ExceptionCategory.INVOICE_AMOUNT_OUTSIDE_TOLERANCE.value,
        owner_role=PlatformRole.FINANCE_USER.value,
        opened_at=NOW - timedelta(hours=3),
        transaction=transaction,
    )
    await open_exception(
        db_session,
        exception_type=ExceptionCategory.SHIPMENT_STATUS_UNAVAILABLE.value,
        owner_role=PlatformRole.LOGISTICS_USER.value,
        opened_at=NOW - timedelta(hours=3),
        transaction=transaction,
    )
    await db_session.commit()

    logistics = await account(db_session, roles=[PlatformRole.LOGISTICS_USER.value])
    finance = await account(db_session, roles=[PlatformRole.FINANCE_USER.value])
    await db_session.commit()

    logistics_summary = await kpis.exception_counts(db_session, scope_for(logistics), now=NOW)
    finance_summary = await kpis.exception_counts(db_session, scope_for(finance), now=NOW)

    logistics_categories = {row["category"] for row in logistics_summary["categories"]}
    finance_categories = {row["category"] for row in finance_summary["categories"]}

    assert ExceptionCategory.SHIPMENT_STATUS_UNAVAILABLE.value in logistics_categories
    assert ExceptionCategory.INVOICE_AMOUNT_OUTSIDE_TOLERANCE.value not in logistics_categories
    assert logistics_summary["total_open"] == 1

    assert ExceptionCategory.INVOICE_AMOUNT_OUTSIDE_TOLERANCE.value in finance_categories
    assert ExceptionCategory.SHIPMENT_STATUS_UNAVAILABLE.value not in finance_categories
    assert finance_summary["total_open"] == 1


async def test_an_account_with_no_platform_role_counts_nothing_at_all(db_session):
    transaction = await transaction_at(
        db_session, batch_number="R-2", created_at=NOW - timedelta(days=1)
    )
    await open_exception(
        db_session,
        exception_type=ExceptionCategory.LOW_CONFIDENCE.value,
        owner_role=PlatformRole.PURCHASE_USER.value,
        opened_at=NOW - timedelta(hours=1),
        transaction=transaction,
    )
    stranger = await account(db_session, roles=[])
    await db_session.commit()

    scope = scope_for(stranger)
    assert scope.empty

    figures = await kpis.transaction_status_counts(db_session, scope)
    summary = await kpis.exception_counts(db_session, scope, now=NOW)

    # Real zeros over an empty scope, never an unfiltered fallback.
    assert all(figure.value == 0 for figure in figures)
    assert summary["total_open"] == 0
    assert summary["categories"] == []


async def test_the_cross_cutting_roles_see_every_category(db_session):
    hod = await account(db_session, roles=[PlatformRole.APPROVER_HOD.value])
    auditor = await account(db_session, roles=[PlatformRole.AUDITOR.value])
    await db_session.commit()

    from app.models.enums import EXCEPTION_CATEGORIES

    assert scope_for(hod).exception_categories == frozenset(EXCEPTION_CATEGORIES)
    assert scope_for(auditor).exception_categories == frozenset(EXCEPTION_CATEGORIES)


async def test_a_stream_filter_narrows_and_never_widens_what_a_role_may_see(db_session):
    logistics = await account(db_session, roles=[PlatformRole.LOGISTICS_USER.value])
    await db_session.commit()

    scope = scope_for(logistics)
    narrowed = scope.narrowed_to("fa")

    assert narrowed.streams == frozenset({"fa"})
    assert narrowed.streams <= scope.streams
    assert narrowed.exception_categories == scope.exception_categories
    assert narrowed.cache_key() != scope.cache_key()


# --- the cache -------------------------------------------------------------------------------------


def test_the_cache_serves_within_its_ttl_and_recomputes_after_it_expires():
    cache = TTLCache(ttl_seconds=30, max_entries=8)
    key = build_key("dashboard.summary", "scrap,fa|x|-", None)

    cache.set(key, {"tiles": ["first"]}, now=1000.0)

    inside = cache.get(key, now=1020.0)
    assert inside is not None
    assert inside.value == {"tiles": ["first"]}
    assert cache.hits == 1

    # One second past the TTL, and the entry is gone rather than stale-but-served.
    assert cache.get(key, now=1031.0) is None
    assert cache.misses == 1

    cache.set(key, {"tiles": ["second"]}, now=1031.0)
    assert cache.get(key, now=1040.0).value == {"tiles": ["second"]}


def test_two_roles_never_share_a_cache_entry():
    """The property that keeps the cache from being a permissions hole."""
    logistics = DashboardScope(
        streams=frozenset({"scrap", "fa"}),
        exception_categories=frozenset({ExceptionCategory.SHIPMENT_STATUS_UNAVAILABLE.value}),
        cross_cutting=False,
        emphasis="shipments",
        roles=frozenset({PlatformRole.LOGISTICS_USER.value}),
    )
    finance = DashboardScope(
        streams=frozenset({"scrap", "fa"}),
        exception_categories=frozenset({ExceptionCategory.INVOICE_AMOUNT_OUTSIDE_TOLERANCE.value}),
        cross_cutting=False,
        emphasis="exceptions",
        roles=frozenset({PlatformRole.FINANCE_USER.value}),
    )

    assert logistics.cache_key() != finance.cache_key()
    assert build_key("dashboard.summary", logistics.cache_key(), None) != build_key(
        "dashboard.summary", finance.cache_key(), None
    )


def test_the_cache_evicts_rather_than_growing_without_bound():
    cache = TTLCache(ttl_seconds=60, max_entries=3)
    for index in range(5):
        cache.set(f"key-{index}", index, now=1000.0)

    assert len(cache) == 3
    assert cache.get("key-0", now=1001.0) is None
    assert cache.get("key-4", now=1001.0).value == 4


# --- the assembled payloads -------------------------------------------------------------------------


async def test_the_summary_payload_carries_every_kpi_and_keeps_the_two_integration_figures_apart(
    db_session,
):
    transaction = await transaction_at(
        db_session, batch_number="P-1", created_at=NOW - timedelta(days=2)
    )
    await approve(db_session, transaction, decided_at=NOW - timedelta(hours=6))
    await integration_job(
        db_session,
        transaction,
        target_system=IntegrationTargetSystem.SAP.value,
        status=IntegrationJobStatus.AWAITING_MANUAL_ACTION.value,
    )
    await db_session.commit()

    payload = await kpis.build_summary(db_session, full_scope(), now=NOW)
    tiles = {tile["key"]: tile for tile in payload["tiles"]}

    assert "tile.integration_failed" in tiles
    assert "tile.integration_awaiting_manual" in tiles
    assert tiles["tile.integration_failed"]["value"] == 0
    assert tiles["tile.integration_awaiting_manual"]["value"] == 1
    assert payload["definitions"]["automation_rate"]
    assert "not a verified-correctness measurement" in payload["extraction"]["disclosure"]

    # Every tile that names a screen carries a filter set the UI can turn into a link.
    for tile in payload["tiles"]:
        if tile["target"] is not None:
            assert isinstance(tile["filters"], dict)


async def test_the_kpi_payload_buckets_the_series_and_leaves_a_quiet_day_empty(db_session):
    decided = NOW - timedelta(days=1)
    transaction = await transaction_at(
        db_session,
        batch_number="P-2",
        created_at=decided - timedelta(hours=5),
        request_created_at=decided - timedelta(hours=5),
    )
    await approve(db_session, transaction, decided_at=decided)
    await db_session.commit()

    period = kpis.Period(start=NOW - timedelta(days=3), end=NOW + timedelta(minutes=1))
    payload = await kpis.build_kpis(db_session, full_scope(), period, interval="day", now=NOW)

    assert len(payload["series"]) >= 3
    busy = [bucket for bucket in payload["series"] if bucket["approved_count"] > 0]
    quiet = [bucket for bucket in payload["series"] if bucket["approved_count"] == 0]

    assert len(busy) == 1
    assert busy[0]["mean_hours"] == pytest.approx(5.0, abs=0.05)
    # A day nothing was approved on has no turnaround, and reports none rather than zero.
    assert all(bucket["mean_hours"] is None for bucket in quiet)
    assert all(bucket["automation_rate"] is None for bucket in quiet)
