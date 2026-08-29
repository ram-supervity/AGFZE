"""Report structure as editable configuration.

Two promises are what this file exists to hold.

**Nothing changed at cutover.** The three structures were seeded exactly as they shipped, so the
first report generated after the table existed is the same document as the last one generated
before it. A migration that quietly reshaped a report while claiming to move it into a table would
be worse than no migration at all.

**An edit reaches the next report and no report already produced.** A generated report keeps its
own content and its own template key; there is no path from this screen back to a document that
has already been written.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditEvent
from app.models.reporting import ReportTemplateConfiguration
from app.services.analytics import report_templates
from app.services.analytics.report_templates import TEMPLATES, section_as_row, template_for
from tests.utils.admin import admin_user, auditor_user, purchase_user, restore_client

pytestmark = pytest.mark.usefixtures("patched_jwks")

TEMPLATES_URL = "/api/v1/admin/report-templates"
GOOD_REASON = "Confirmed with the HOD in the March reporting review."


@pytest.fixture(autouse=True)
def _restore_identity_provider():
    yield
    restore_client()


async def _row(session: AsyncSession, report_type: str) -> ReportTemplateConfiguration:
    row = await session.scalar(
        select(ReportTemplateConfiguration).where(
            ReportTemplateConfiguration.report_type == report_type
        )
    )
    assert row is not None
    return row


# --- the seed ------------------------------------------------------------------------------------


async def test_the_seed_is_the_shipped_structure_byte_for_byte(db_session: AsyncSession):
    """Every shipped template is in the table, unchanged, so nothing about a report moved."""
    for template in TEMPLATES:
        row = await _row(db_session, template.report_type)
        assert row.template_key == template.key
        assert row.title == template.title
        assert row.description == template.description
        assert row.wants_ai_summary is template.wants_ai_summary
        assert row.include_detail_rows is template.include_detail_rows
        assert row.default_period_days == template.default_period_days
        assert row.disclosures == list(template.disclosures)
        assert row.sections == [section_as_row(section) for section in template.sections]
        # The seed carries its own reason, so the very first thing this table records is not an
        # exception to the rule the table exists to enforce.
        assert len(row.change_reason.strip()) >= 10


async def test_resolving_a_template_returns_the_row_and_it_matches_what_shipped(
    db_session: AsyncSession,
):
    for template in TEMPLATES:
        resolved = await report_templates.resolve(db_session, template.report_type)
        assert resolved == template


async def test_a_missing_row_falls_back_to_the_shipped_structure_rather_than_failing(
    db_session: AsyncSession,
):
    """A report generated to the structure it has always had beats a report that refuses to run.

    The fallback is logged, so it is never silent, and a deployment whose migrations have run
    never reaches it.
    """
    row = await _row(db_session, "adhoc")
    await db_session.delete(row)
    await db_session.flush()

    assert await report_templates.resolve(db_session, "adhoc") == template_for("adhoc")


# --- the screen ----------------------------------------------------------------------------------


async def test_only_an_administrator_reaches_the_screen(client: AsyncClient, signed_in):
    _, admin_headers = await admin_user(signed_in)
    assert (await client.get(TEMPLATES_URL, headers=admin_headers)).status_code == 200

    _, desk_headers = await purchase_user(signed_in)
    assert (await client.get(TEMPLATES_URL, headers=desk_headers)).status_code == 403

    # Read-only oversight is oversight of the trail, not of the configuration behind it.
    _, auditor_headers = await auditor_user(signed_in)
    assert (await client.get(TEMPLATES_URL, headers=auditor_headers)).status_code == 403


async def test_the_list_shows_every_template_with_its_structure(client: AsyncClient, signed_in):
    _, headers = await admin_user(signed_in)

    response = await client.get(TEMPLATES_URL, headers=headers)
    assert response.status_code == 200, response.text
    data = response.json()["data"]

    assert {row["report_type"] for row in data["items"]} == {"daily", "monthly", "adhoc"}
    daily = next(row for row in data["items"] if row["report_type"] == "daily")
    assert daily["section_count"] == len(template_for("daily").sections)
    assert daily["sections"][0]["source"] == "headline"
    # The screen's vocabularies come from the service, not from a list retyped in the client.
    assert "kpi_grid" in data["section_kinds"]
    assert "transactions_by_status" in data["section_sources"]
    assert "automation_rate" in data["headline_figures"]


async def test_an_edit_without_a_reason_is_refused_by_the_server(
    client: AsyncClient, signed_in, db_session: AsyncSession
):
    _, headers = await admin_user(signed_in)
    row = await _row(db_session, "daily")
    before = list(row.sections)

    response = await client.patch(
        f"{TEMPLATES_URL}/{row.id}",
        headers=headers,
        json={"title": "Something else"},
    )
    assert response.status_code == 422

    await db_session.refresh(row)
    assert row.sections == before


async def test_an_edit_changes_the_structure_and_lands_on_the_audit_trail(
    client: AsyncClient, signed_in, db_session: AsyncSession
):
    _, headers = await admin_user(signed_in)
    row = await _row(db_session, "daily")

    kept = [section for section in row.sections if section["key"] != "shipments"]
    response = await client.patch(
        f"{TEMPLATES_URL}/{row.id}",
        headers=headers,
        json={"change_reason": GOOD_REASON, "sections": kept},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["section_count"] == len(kept)

    await db_session.refresh(row)
    assert [section["key"] for section in row.sections] == [section["key"] for section in kept]
    assert row.change_reason == GOOD_REASON

    event = await db_session.scalar(
        select(AuditEvent).where(AuditEvent.event_type == "admin.report_template.updated")
    )
    assert event is not None
    assert event.event_metadata["sections_removed"] == ["shipments"]
    assert event.event_metadata["change_reason"] == GOOD_REASON
    # Keys and counts, never a second copy of the layout.
    assert "sections" not in event.event_metadata["after"]


async def test_a_generation_reads_the_edited_structure(
    client: AsyncClient, signed_in, db_session: AsyncSession
):
    _, headers = await admin_user(signed_in)
    row = await _row(db_session, "daily")
    kept = [section for section in row.sections if section["key"] in {"headline", "approvals"}]

    response = await client.patch(
        f"{TEMPLATES_URL}/{row.id}",
        headers=headers,
        json={"change_reason": GOOD_REASON, "sections": kept, "title": "Morning position"},
    )
    assert response.status_code == 200, response.text

    # The edit was made through the API's own session; this one still holds the row it read
    # before it. Expiring is what makes the next read go back to the database, which is what a
    # later generation - in a session of its own - genuinely does.
    db_session.expire_all()
    resolved = await report_templates.resolve(db_session, "daily")
    assert resolved.title == "Morning position"
    assert [section.key for section in resolved.sections] == ["headline", "approvals"]
    # The template's identity is untouched, so the reports already produced under it still
    # resolve to a structure that exists.
    assert resolved.key == template_for("daily").key


# --- what an edit is not allowed to be -----------------------------------------------------------


async def test_a_section_naming_a_source_nothing_produces_is_refused_at_the_edit(
    client: AsyncClient, signed_in, db_session: AsyncSession
):
    """Refused here rather than at render time.

    The build does raise on an unknown source, which is correct and much too late: the report is
    already scheduled and the failure surfaces to a worker instead of to the person who caused it.
    """
    _, headers = await admin_user(signed_in)
    row = await _row(db_session, "daily")

    response = await client.patch(
        f"{TEMPLATES_URL}/{row.id}",
        headers=headers,
        json={
            "change_reason": GOOD_REASON,
            "sections": [
                {
                    "key": "invented",
                    "title": "Invented",
                    "kind": "breakdown",
                    "source": "profit_by_broker",
                }
            ],
        },
    )
    assert response.status_code == 422
    assert "produces no such data block" in response.text


async def test_a_figure_the_platform_does_not_compute_is_refused(
    client: AsyncClient, signed_in, db_session: AsyncSession
):
    _, headers = await admin_user(signed_in)
    row = await _row(db_session, "daily")

    response = await client.patch(
        f"{TEMPLATES_URL}/{row.id}",
        headers=headers,
        json={
            "change_reason": GOOD_REASON,
            "sections": [
                {
                    "key": "headline",
                    "title": "Where things stand",
                    "kind": "kpi_grid",
                    "source": "headline",
                    "figures": ["open_exceptions", "gross_margin"],
                }
            ],
        },
    )
    assert response.status_code == 422
    assert "gross_margin" in response.text


async def test_an_empty_or_duplicated_structure_is_refused(
    client: AsyncClient, signed_in, db_session: AsyncSession
):
    _, headers = await admin_user(signed_in)
    row = await _row(db_session, "daily")

    empty = await client.patch(
        f"{TEMPLATES_URL}/{row.id}",
        headers=headers,
        json={"change_reason": GOOD_REASON, "sections": []},
    )
    assert empty.status_code == 422

    duplicated = await client.patch(
        f"{TEMPLATES_URL}/{row.id}",
        headers=headers,
        json={
            "change_reason": GOOD_REASON,
            "sections": [
                {"key": "same", "title": "One", "kind": "breakdown", "source": "shipments"},
                {"key": "same", "title": "Two", "kind": "breakdown", "source": "shipments"},
            ],
        },
    )
    assert duplicated.status_code == 422


async def test_the_template_identity_cannot_be_edited(
    client: AsyncClient, signed_in, db_session: AsyncSession
):
    """`report_type` and `template_key` have no field on the update schema at all.

    A rejected value is not enough here: the reports already generated record which template
    produced them, so re-pointing one would leave those records claiming a structure the document
    was never built to.
    """
    _, headers = await admin_user(signed_in)
    row = await _row(db_session, "daily")

    response = await client.patch(
        f"{TEMPLATES_URL}/{row.id}",
        headers=headers,
        json={
            "change_reason": GOOD_REASON,
            "report_type": "monthly",
            "template_key": "something_else",
        },
    )
    assert response.status_code == 200, response.text

    await db_session.refresh(row)
    assert row.report_type == "daily"
    assert row.template_key == "daily_operations"
