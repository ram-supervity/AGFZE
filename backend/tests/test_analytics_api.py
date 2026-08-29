"""The four endpoints, through real HTTP, with real tokens and real role checks.

What is proved here is the contract rather than the arithmetic - the arithmetic has its own suite.
Two of these tests matter more than the rest: that the aggregate endpoints scope by role at the
API boundary as well as in the service, and that generating a report is refused server-side for a
role that may only read them, whatever a browser chose to render.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

from app.core.roles import PlatformRole
from app.db.base import utcnow
from app.models.enums import ExceptionCategory, IntegrationJobStatus, IntegrationTargetSystem
from app.services.analytics.cache import dashboard_cache
from tests.utils.analytics import (
    approve,
    integration_job,
    open_exception,
    pending_approval,
    shipment,
    transaction_at,
)

NOW = utcnow()


async def _seed(db_session):
    approved = await transaction_at(
        db_session,
        batch_number="API-1",
        created_at=NOW - timedelta(days=3),
        request_created_at=NOW - timedelta(days=3),
    )
    await approve(db_session, approved, decided_at=NOW - timedelta(days=2))
    await integration_job(
        db_session,
        approved,
        target_system=IntegrationTargetSystem.SAP.value,
        status=IntegrationJobStatus.AWAITING_MANUAL_ACTION.value,
    )
    await integration_job(
        db_session,
        approved,
        target_system=IntegrationTargetSystem.DMS.value,
        status=IntegrationJobStatus.FAILED.value,
    )
    await shipment(db_session, approved, last_checked_at=NOW - timedelta(hours=200))

    waiting = await transaction_at(
        db_session, batch_number="API-2", created_at=NOW - timedelta(days=1)
    )
    await pending_approval(db_session, waiting, requested_at=NOW - timedelta(hours=8))
    await open_exception(
        db_session,
        exception_type=ExceptionCategory.INVOICE_AMOUNT_OUTSIDE_TOLERANCE.value,
        owner_role=PlatformRole.FINANCE_USER.value,
        opened_at=NOW - timedelta(hours=5),
        transaction=waiting,
    )
    await open_exception(
        db_session,
        exception_type=ExceptionCategory.SHIPMENT_STATUS_UNAVAILABLE.value,
        owner_role=PlatformRole.LOGISTICS_USER.value,
        opened_at=NOW - timedelta(hours=5),
        transaction=waiting,
    )
    await db_session.commit()


async def test_the_summary_endpoint_answers_every_signed_in_role(
    client, db_session, signed_in, patched_jwks
):
    await _seed(db_session)
    dashboard_cache().clear()

    _, headers = await signed_in(
        "dash-purchase", "purchase@agfze.test", "Purchase Desk", ["purchase_user"]
    )
    response = await client.get("/api/v1/dashboards/summary", headers=headers)

    assert response.status_code == 200, response.text
    payload = response.json()["data"]

    assert payload["tiles"]
    assert payload["scope_note"]
    assert payload["emphasis"] == "transactions"
    assert payload["cache_age_seconds"] == 0.0
    # The two integration figures arrive as two figures and are never summed anywhere.
    tiles = {tile["key"]: tile["value"] for tile in payload["tiles"]}
    assert tiles["tile.integration_failed"] == 1
    assert tiles["tile.integration_awaiting_manual"] == 1


async def test_the_summary_is_scoped_to_the_caller_s_own_categories(
    client, db_session, signed_in, patched_jwks
):
    await _seed(db_session)
    dashboard_cache().clear()

    _, logistics = await signed_in(
        "dash-logistics", "logistics@agfze.test", "Logistics Desk", ["logistics_user"]
    )
    _, finance = await signed_in(
        "dash-finance", "finance@agfze.test", "Finance Desk", ["finance_user"]
    )

    logistics_payload = (await client.get("/api/v1/dashboards/summary", headers=logistics)).json()[
        "data"
    ]
    finance_payload = (await client.get("/api/v1/dashboards/summary", headers=finance)).json()[
        "data"
    ]

    logistics_categories = {
        row["category"] for row in logistics_payload["exceptions"]["categories"]
    }
    finance_categories = {row["category"] for row in finance_payload["exceptions"]["categories"]}

    # The invoice-value case exists, and the logistics query never counted it.
    assert ExceptionCategory.INVOICE_AMOUNT_OUTSIDE_TOLERANCE.value not in logistics_categories
    assert logistics_payload["exceptions"]["total_open"] == 1
    assert ExceptionCategory.INVOICE_AMOUNT_OUTSIDE_TOLERANCE.value in finance_categories
    assert finance_payload["exceptions"]["total_open"] == 1

    # And each desk's own panel leads.
    assert logistics_payload["emphasis"] == "shipments"
    assert finance_payload["emphasis"] == "exceptions"


async def test_a_cached_summary_reports_its_own_age(client, db_session, signed_in, patched_jwks):
    await _seed(db_session)
    dashboard_cache().clear()

    _, headers = await signed_in("dash-hod", "hod@agfze.test", "Department Head", ["approver_hod"])

    first = (await client.get("/api/v1/dashboards/summary", headers=headers)).json()["data"]
    await asyncio.sleep(0.01)
    second = (await client.get("/api/v1/dashboards/summary", headers=headers)).json()["data"]

    assert first["cache_age_seconds"] == 0.0
    # Served from the cache, and saying so rather than implying it was just computed.
    assert second["cache_age_seconds"] > 0.0
    assert second["cache_ttl_seconds"] == dashboard_cache().ttl_seconds
    assert second["generated_at"] == first["generated_at"]


async def test_the_summary_requires_authentication(client):
    assert (await client.get("/api/v1/dashboards/summary")).status_code == 401


async def test_the_kpi_endpoint_buckets_over_the_requested_range(
    client, db_session, signed_in, patched_jwks
):
    await _seed(db_session)
    dashboard_cache().clear()

    _, headers = await signed_in(
        "kpi-hod", "kpi.hod@agfze.test", "Department Head", ["approver_hod"]
    )
    response = await client.get(
        "/api/v1/dashboards/kpis",
        params={
            "date_from": (NOW - timedelta(days=5)).isoformat(),
            "date_to": NOW.isoformat(),
            "interval": "day",
        },
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]

    assert payload["interval"] == "day"
    assert len(payload["series"]) >= 5
    assert payload["automation"]["approved_count"] == 1
    assert payload["turnaround"]["sample_size"] == 1
    assert payload["extraction"]["measure"] == "non_override_rate"


async def test_the_kpi_endpoint_rejects_an_interval_it_does_not_bucket_by(
    client, signed_in, patched_jwks
):
    _, headers = await signed_in("kpi-a", "kpi.a@agfze.test", "Auditor", ["auditor"])
    response = await client.get(
        "/api/v1/dashboards/kpis", params={"interval": "fortnight"}, headers=headers
    )
    assert response.status_code == 422


# --- reports -------------------------------------------------------------------------------------


async def test_generating_a_report_is_refused_for_a_role_that_may_only_read_them(
    client, signed_in, patched_jwks
):
    _, headers = await signed_in(
        "rpt-finance", "rpt.finance@agfze.test", "Finance Desk", ["finance_user"]
    )
    response = await client.post(
        "/api/v1/reports",
        json={
            "report_type": "adhoc",
            "output_format": "pdf",
            "date_from": (NOW - timedelta(days=7)).isoformat(),
            "date_to": NOW.isoformat(),
            "stream": "both",
        },
        headers=headers,
    )

    assert response.status_code == 403
    assert response.json()["success"] is False


async def test_the_hod_can_generate_a_report_and_poll_the_existing_job_endpoint(
    client, db_session, signed_in, patched_jwks, storage_root
):
    await _seed(db_session)
    _, headers = await signed_in(
        "rpt-hod", "rpt.hod@agfze.test", "Department Head", ["approver_hod"]
    )

    accepted = await client.post(
        "/api/v1/reports",
        json={
            "report_type": "adhoc",
            "output_format": "pdf",
            "date_from": (NOW - timedelta(days=7)).isoformat(),
            "date_to": NOW.isoformat(),
            "stream": "both",
        },
        headers=headers,
    )
    assert accepted.status_code == 202, accepted.text
    body = accepted.json()["data"]
    assert body["poll_url"] == f"/api/v1/jobs/{body['job_id']}/status"
    # The response never claims the report went anywhere.
    assert "not sent to anybody" in body["message"]

    for _ in range(60):
        status = await client.get(f"/api/v1/jobs/{body['job_id']}/status", headers=headers)
        assert status.status_code == 200
        job = status.json()["data"]
        if job["status"] in {"completed", "failed"}:
            break
        await asyncio.sleep(0.1)

    assert job["status"] == "completed", job.get("error_message")
    assert job["result_ref"].startswith("report:")

    listing = await client.get("/api/v1/reports", headers=headers)
    assert listing.status_code == 200
    items = listing.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["generated_by_name"] == "Department Head"
    assert items[0]["scheduled"] is False


async def test_any_signed_in_role_may_read_a_report_and_gets_a_signed_download_link(
    client, db_session, signed_in, patched_jwks, storage_root
):
    await _seed(db_session)

    from app.services.analytics import kpis, report_service
    from tests.utils.analytics import account

    generator = await account(db_session, roles=[PlatformRole.ADMIN.value], name="Admin")
    report = await report_service.generate(
        db_session,
        report_service.validate_request(
            report_type="adhoc",
            output_format="pdf",
            period=kpis.Period(start=NOW - timedelta(days=7), end=NOW),
            stream="both",
            status_filter=None,
        ),
        requested_by=generator,
        now=NOW,
    )
    await db_session.commit()

    _, headers = await signed_in(
        "rpt-reader", "rpt.reader@agfze.test", "Sales Desk", ["sales_user"]
    )
    response = await client.get(f"/api/v1/reports/{report.id}", headers=headers)

    assert response.status_code == 200, response.text
    payload = response.json()["data"]

    assert payload["generation_reference"] == report.generation_reference
    assert payload["content"]["sections"]
    assert payload["parameters"]["stream"] == "both"
    # Signed and short-lived, through the existing authenticated file route. Never a raw path.
    assert payload["download_url"].startswith("http")
    assert "signature=" in payload["download_url"] and "expires=" in payload["download_url"]
    assert "has not been sent to any recipient" in payload["distribution_note"]

    # And the list tells this account it may not ask for a new one, matching what the API enforces.
    listing = await client.get("/api/v1/reports", headers=headers)
    assert listing.json()["data"]["can_generate"] is False


async def test_reading_a_report_that_does_not_exist_is_a_plain_404(client, signed_in, patched_jwks):
    _, headers = await signed_in("rpt-404", "rpt.404@agfze.test", "Auditor", ["auditor"])
    response = await client.get(
        "/api/v1/reports/11111111-2222-3333-4444-555555555555", headers=headers
    )
    assert response.status_code == 404


async def test_the_signed_download_link_actually_serves_the_generated_file(
    client, db_session, signed_in, patched_jwks, storage_root
):
    from app.services.analytics import kpis, report_service
    from tests.utils.analytics import account

    generator = await account(db_session, roles=[PlatformRole.ADMIN.value])
    report = await report_service.generate(
        db_session,
        report_service.validate_request(
            report_type="adhoc",
            output_format="pdf",
            period=kpis.Period(start=NOW - timedelta(days=7), end=NOW),
            stream="both",
            status_filter=None,
        ),
        requested_by=generator,
        now=NOW,
    )
    await db_session.commit()

    _, headers = await signed_in("rpt-dl", "rpt.dl@agfze.test", "Auditor", ["auditor"])
    detail = (await client.get(f"/api/v1/reports/{report.id}", headers=headers)).json()["data"]

    served = await client.get(detail["download_url"].replace("http://testserver", ""))
    assert served.status_code == 200
    assert served.headers["content-type"] == "application/pdf"
    assert served.content.startswith(b"%PDF")

    # A tampered signature is refused exactly as it is for any other stored document. The last
    # character is replaced with a *different* one rather than with a fixed "0": a hex signature
    # ends in "0" about one time in sixteen, and on those runs the "tampered" URL was the valid
    # one and the test passed for the wrong reason - or, once it started asserting a refusal,
    # failed for one.
    link = detail["download_url"].replace("http://testserver", "")
    tampered = link[:-1] + ("1" if link[-1] == "0" else "0")
    assert tampered != link
    assert (await client.get(tampered)).status_code == 404
