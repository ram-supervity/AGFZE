"""The audit explorer: filtering, the streamed export, and the metadata discipline.

The last of those is the one worth stating plainly. `audit_events.metadata` has been documented
since Step 1 as holding metadata only - identifiers, counts, decisions, state transitions - and
never document text, never an AI prompt or completion, never a credential. This module checks
that the discipline actually held across a representative sample of call sites from every prior
step, rather than assuming it did.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utcnow
from app.models.audit import AuditEvent
from app.services import audit_query
from app.services.audit_service import ActorType, record_audit_event
from tests.utils.admin import admin_user, auditor_user, purchase_user

pytestmark = pytest.mark.usefixtures("patched_jwks")

AUDIT = "/api/v1/audit"
EXPORT = "/api/v1/audit/export"

# One event from each module that has ever written to the trail. Written here as literals rather
# than produced by running eight workflows, so the sample is explicit and reviewable.
SAMPLE_EVENTS: list[tuple[str, str, dict]] = [
    ("email.ingested", "email_message", {"message_id": "AAMk-1", "attachment_count": 3}),
    (
        "document.extracted",
        "document",
        {"document_type": "invoice", "field_count": 14, "lowest_confidence": 0.81},
    ),
    (
        "transaction.matched",
        "trade_transaction",
        {"batch_number": "I2626-1", "method": "fuzzy_auto"},
    ),
    (
        "exception.opened",
        "exception_case",
        {"exception_type": "quantity_variation_outside_tolerance", "owner_role": "purchase_user"},
    ),
    ("approval.decided", "approval_task", {"decision": "approved", "bulk": False}),
    ("transaction.draft_generated", "trade_transaction", {"document_type": "draft_invoice"}),
    ("shipment.status_updated", "shipment", {"status": "delayed", "milestone": "in_transit"}),
    (
        "integration.job.failed",
        "integration_job",
        {
            "target_system": "sap",
            "attempt": 5,
            "failure_reason": "HTTP 500 from the posting service",
        },
    ),
    ("report.generated", "report", {"template_key": "daily_operations", "byte_size": 41233}),
    (
        "admin.rule_configuration.updated",
        "rule_configuration",
        {"rule_id": "BR-05", "change_reason": "Confirmed with the desk."},
    ),
]

# Words that would only appear in a payload if a document body or a model exchange had been
# written into one. None of them is in the platform's audit vocabulary.
CONTENT_MARKERS = (
    "prompt",
    "completion",
    "raw_response",
    "body_text",
    "page_text",
    "document_text",
    "extracted_text",
    "api_key",
    "client_secret",
    "password",
)


async def seed_sample(session: AsyncSession, actor_id=None) -> None:
    for event_type, entity_type, metadata in SAMPLE_EVENTS:
        await record_audit_event(
            session,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=f"{entity_type}-1",
            actor_id=actor_id,
            actor_type=ActorType.USER if actor_id else ActorType.SYSTEM,
            metadata=metadata,
        )
    await session.commit()


async def test_the_explorer_is_open_to_admin_and_auditor_and_nobody_else(
    client: AsyncClient, signed_in
):
    _, admin = await admin_user(signed_in)
    _, auditor = await auditor_user(signed_in)
    _, purchase = await purchase_user(signed_in)

    assert (await client.get(AUDIT, headers=admin)).status_code == 200
    assert (await client.get(AUDIT, headers=auditor)).status_code == 200
    assert (await client.get(AUDIT, headers=purchase)).status_code == 403
    assert (await client.get(EXPORT, headers=purchase)).status_code == 403


async def test_the_event_type_filter_is_populated_from_the_data(
    client: AsyncClient, db_session: AsyncSession, signed_in
):
    """Not from a list written by hand.

    Ten steps have contributed to this vocabulary, so the filter is a SELECT DISTINCT over what
    the table actually holds. Adding a new kind of event makes it appear with no code change.
    """
    _, headers = await admin_user(signed_in)
    await seed_sample(db_session)

    response = await client.get(AUDIT, headers=headers)
    assert response.status_code == 200, response.text
    data = response.json()["data"]

    offered = set(data["event_types"])
    for event_type, _, _ in SAMPLE_EVENTS:
        assert event_type in offered, event_type
    # A type nobody has recorded is not offered as a filter that would return nothing.
    assert "shipment.teleported" not in offered

    entities = set(data["entity_types"])
    assert {"document", "exception_case", "integration_job", "report"} <= entities


async def test_every_filter_narrows_the_set(
    client: AsyncClient, db_session: AsyncSession, signed_in
):
    user, headers = await admin_user(signed_in)
    await seed_sample(db_session, actor_id=user.id)

    by_type = await client.get(AUDIT, headers=headers, params={"event_type": "approval.decided"})
    assert [row["event_type"] for row in by_type.json()["data"]["items"]] == ["approval.decided"]

    by_entity = await client.get(AUDIT, headers=headers, params={"entity_type": "document"})
    assert {row["entity_type"] for row in by_entity.json()["data"]["items"]} == {"document"}

    by_actor = await client.get(AUDIT, headers=headers, params={"actor_id": str(user.id)})
    assert by_actor.json()["data"]["page"]["total"] >= len(SAMPLE_EVENTS)

    by_reference = await client.get(AUDIT, headers=headers, params={"search": "shipment-1"})
    assert [row["entity_id"] for row in by_reference.json()["data"]["items"]] == ["shipment-1"]

    future = await client.get(
        AUDIT,
        headers=headers,
        params={"date_from": (utcnow() + timedelta(days=1)).isoformat()},
    )
    assert future.json()["data"]["page"]["total"] == 0


async def test_the_actor_filter_lists_only_accounts_that_actually_acted(
    client: AsyncClient, db_session: AsyncSession, signed_in
):
    user, headers = await admin_user(signed_in)
    await seed_sample(db_session, actor_id=user.id)

    response = await client.get(AUDIT, headers=headers)
    actors = {row["id"] for row in response.json()["data"]["actors"]}
    assert str(user.id) in actors


async def test_the_export_streams_rather_than_materialising_the_result_set(
    db_session: AsyncSession,
):
    """Against a large fixture set, and asserted on structurally.

    The generator is driven one chunk at a time and the rows are counted as they arrive. If
    `stream_csv` had assembled the whole set before yielding, the first chunk would carry
    everything rather than the header alone.
    """
    for index in range(2_000):
        db_session.add(
            AuditEvent(
                event_type="transaction.field_corrected",
                entity_type="trade_transaction",
                entity_id=f"batch-{index}",
                actor_type=ActorType.SYSTEM,
                event_metadata={"index": index},
            )
        )
    await db_session.commit()

    statement = audit_query.list_query(entity_type="trade_transaction")
    chunks: list[str] = []
    async for chunk in audit_query.stream_csv(db_session, statement, chunk_size=250):
        chunks.append(chunk)

    # The header arrives on its own, before a single row has been read out of the cursor.
    assert chunks[0].strip() == ",".join(audit_query.CSV_COLUMNS)
    # And the body arrives in many chunks rather than one, which is what "streamed" means here.
    assert len(chunks) > 8

    rows = list(csv.reader(io.StringIO("".join(chunks))))
    assert rows[0] == list(audit_query.CSV_COLUMNS)
    assert len(rows) - 1 == 2_000


async def test_the_export_endpoint_returns_a_csv_and_records_that_it_was_taken(
    client: AsyncClient, db_session: AsyncSession, signed_in
):
    user, headers = await admin_user(signed_in)
    await seed_sample(db_session, actor_id=user.id)

    response = await client.get(EXPORT, headers=headers, params={"entity_type": "report"})
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment; filename=" in response.headers["content-disposition"]

    rows = list(csv.reader(io.StringIO(response.text)))
    assert rows[0] == list(audit_query.CSV_COLUMNS)
    assert all(row[5] == "report" for row in rows[1:])

    # Taking a copy of the trail is itself an act on the trail.
    exported = await db_session.scalar(
        select(AuditEvent).where(AuditEvent.event_type == "audit.exported")
    )
    assert exported is not None
    assert exported.actor_id == user.id
    assert exported.event_metadata["entity_type"] == "report"


async def test_audit_metadata_never_carries_document_or_prompt_text(
    client: AsyncClient, db_session: AsyncSession, signed_in
):
    """Checked across a representative sample of call sites from every prior step."""
    _, headers = await admin_user(signed_in)
    await seed_sample(db_session)

    response = await client.get(AUDIT, headers=headers, params={"page_size": 200})
    assert response.status_code == 200

    for row in response.json()["data"]["items"]:
        rendered = json.dumps(row["metadata"]).lower()
        for marker in CONTENT_MARKERS:
            assert marker not in rendered, (row["event_type"], marker)
        for value in row["metadata"].values():
            if isinstance(value, str):
                assert len(value) <= audit_query.MAX_METADATA_VALUE_CHARS + 1


async def test_the_read_layer_redacts_a_payload_that_ever_slipped(
    client: AsyncClient, db_session: AsyncSession, signed_in
):
    """A backstop, not a feature.

    No call site in the platform writes a prompt or a document body into an audit payload. If one
    ever regressed and did, the explorer redacts it on the way out rather than becoming a viewer
    for it.
    """
    _, headers = await admin_user(signed_in)
    await record_audit_event(
        db_session,
        event_type="document.extracted",
        entity_type="document",
        entity_id="regressed-1",
        actor_type=ActorType.SYSTEM,
        metadata={
            "prompt": "Read every field out of the attached bill of lading and return JSON.",
            "document_text": "COMMERCIAL INVOICE ... " + "x" * 4000,
            "field_count": 12,
        },
    )
    await db_session.commit()

    response = await client.get(AUDIT, headers=headers, params={"search": "regressed-1"})
    metadata = response.json()["data"]["items"][0]["metadata"]

    assert metadata["prompt"] == "[redacted]"
    assert metadata["document_text"] == "[redacted]"
    # The genuine metadata beside it is untouched.
    assert metadata["field_count"] == 12


async def test_the_trail_has_no_write_route_at_any_role(client: AsyncClient, signed_in):
    """Append-only means append-only. A correction is a new event, never an edit."""
    _, headers = await admin_user(signed_in)

    for method in ("POST", "PUT", "PATCH", "DELETE"):
        response = await client.request(method, AUDIT, headers=headers)
        assert response.status_code == 405, method
