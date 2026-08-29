"""The administration module: reason-required configuration edits, and the role override.

Two things are proved here more than once, because they are the two that would matter most if
they were wrong:

* a configuration change without a stated reason does not happen, and is refused by the server
  rather than merely discouraged by a dialog;
* a role override reaches Keycloak before it reaches this platform's own record, and a Keycloak
  that refuses or cannot be reached leaves that record byte-for-byte as it was.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditEvent
from app.models.configuration import DocumentTypeSchema, RuleConfiguration
from app.models.enums import BusinessStream, DocumentType
from app.models.identity import User
from app.services import keycloak_admin
from app.services.rules.catalog import CheckKey, RuleId
from tests.utils.admin import (
    FakeKeycloakAdminClient,
    admin_user,
    auditor_user,
    install_fake_client,
    purchase_user,
    restore_client,
)

pytestmark = pytest.mark.usefixtures("patched_jwks")

RULES = "/api/v1/admin/rules"
SCHEMAS = "/api/v1/admin/document-types"
USERS = "/api/v1/admin/users"

GOOD_REASON = "Confirmed with the trading desk after the May contract review."


@pytest.fixture(autouse=True)
def _fake_identity_provider():
    """Every test in this module drives a fake Keycloak, never a real one."""
    yield
    restore_client()


# --- rule configuration --------------------------------------------------------------------------


async def test_rules_list_covers_rows_seeded_by_every_step(client: AsyncClient, signed_in):
    """Step 3's purchase tolerances, Step 5's sales rule and Step 6's FA defaults, in one list.

    The assertion that matters is not that each is present but that none of them needed a branch
    to get here: they are all rows in `rule_configurations` reached by one query.
    """
    _, headers = await admin_user(signed_in)

    response = await client.get(RULES, headers=headers)
    assert response.status_code == 200, response.text
    data = response.json()["data"]

    by_rule = {(row["rule_id"], row["check_key"]) for row in data["items"]}
    # Step 3: the purchase-side quantity tolerance.
    assert (RuleId.BR_05, CheckKey.QUANTITY_TOLERANCE) in by_rule
    # Step 5: the sales module's own rule, in its own namespace.
    assert (RuleId.SL_01, CheckKey.CONTRACT_QUANTITY_COVERAGE) in by_rule
    # Step 6: FA-scoped defaults are rows scoped to the FA stream, not a separate table.
    assert BusinessStream.FA.value in data["streams"]
    assert any(row["scope_stream"] == BusinessStream.FA.value for row in data["items"])

    # The filter's own vocabulary comes from the data rather than a hardcoded list.
    assert RuleId.BR_05 in data["rule_ids"]
    assert RuleId.SL_01 in data["rule_ids"]


async def test_an_fa_scoped_row_edits_exactly_like_a_purchase_one(
    client: AsyncClient, db_session: AsyncSession, signed_in
):
    _, headers = await admin_user(signed_in)
    fa_row = await db_session.scalar(
        select(RuleConfiguration).where(RuleConfiguration.scope_stream == BusinessStream.FA.value)
    )
    assert fa_row is not None

    response = await client.patch(
        f"{RULES}/{fa_row.id}",
        headers=headers,
        json={"threshold_value": "4.5", "change_reason": GOOD_REASON},
    )
    assert response.status_code == 200, response.text
    assert Decimal(response.json()["data"]["threshold_value"]) == Decimal("4.5")


async def test_a_rule_edit_without_a_reason_is_refused_by_the_server(
    client: AsyncClient, db_session: AsyncSession, signed_in
):
    """No dialog is involved. The schema refuses it before a handler runs."""
    _, headers = await admin_user(signed_in)
    row = await db_session.scalar(
        select(RuleConfiguration).where(RuleConfiguration.rule_id == RuleId.BR_05)
    )
    assert row is not None
    before = Decimal(row.threshold_value)

    missing = await client.patch(
        f"{RULES}/{row.id}", headers=headers, json={"threshold_value": "99"}
    )
    assert missing.status_code == 422

    blank = await client.patch(
        f"{RULES}/{row.id}",
        headers=headers,
        json={"threshold_value": "99", "change_reason": "   "},
    )
    assert blank.status_code == 422

    token = await client.patch(
        f"{RULES}/{row.id}",
        headers=headers,
        json={"threshold_value": "99", "change_reason": "fix"},
    )
    assert token.status_code == 422

    await db_session.refresh(row)
    assert Decimal(row.threshold_value) == before


async def test_a_valid_rule_edit_is_persisted_and_audited(
    client: AsyncClient, db_session: AsyncSession, signed_in
):
    user, headers = await admin_user(signed_in)
    row = await db_session.scalar(
        select(RuleConfiguration).where(
            RuleConfiguration.rule_id == RuleId.BR_05,
            RuleConfiguration.check_key == CheckKey.QUANTITY_TOLERANCE,
        )
    )
    assert row is not None
    before = str(row.threshold_value)

    response = await client.patch(
        f"{RULES}/{row.id}",
        headers=headers,
        json={"threshold_value": "3.5", "change_reason": GOOD_REASON},
    )
    assert response.status_code == 200, response.text

    await db_session.refresh(row)
    assert Decimal(row.threshold_value) == Decimal("3.5")
    assert row.change_reason == GOOD_REASON
    assert row.changed_by_id == user.id

    event = await db_session.scalar(
        select(AuditEvent).where(
            AuditEvent.entity_type == "rule_configuration",
            AuditEvent.entity_id == str(row.id),
        )
    )
    assert event is not None
    assert event.event_type == "admin.rule_configuration.updated"
    assert event.actor_id == user.id
    assert event.event_metadata["before"]["threshold_value"] == before
    assert Decimal(event.event_metadata["after"]["threshold_value"]) == Decimal("3.5")
    assert event.event_metadata["change_reason"] == GOOD_REASON


async def test_the_rule_screens_are_closed_to_every_other_role(client: AsyncClient, signed_in):
    _, purchase = await purchase_user(signed_in)
    _, auditor = await auditor_user(signed_in)

    assert (await client.get(RULES, headers=purchase)).status_code == 403
    # The Auditor reads the trail, not the configuration behind it.
    assert (await client.get(RULES, headers=auditor)).status_code == 403


# --- document type schemas -------------------------------------------------------------------------


async def test_schema_list_covers_rows_seeded_by_every_step(client: AsyncClient, signed_in):
    """Step 2's invoice and contract, Step 5's bill of lading, Step 6's FA document."""
    _, headers = await admin_user(signed_in)

    response = await client.get(SCHEMAS, headers=headers)
    assert response.status_code == 200, response.text
    types = {row["document_type"] for row in response.json()["data"]["items"]}

    assert DocumentType.INVOICE.value in types
    assert DocumentType.CONTRACT.value in types
    assert DocumentType.BL.value in types
    assert DocumentType.FA_DOCUMENT.value in types


async def test_a_schema_edit_without_a_reason_is_refused(
    client: AsyncClient, db_session: AsyncSession, signed_in
):
    _, headers = await admin_user(signed_in)
    row = await db_session.scalar(
        select(DocumentTypeSchema).where(
            DocumentTypeSchema.document_type == DocumentType.INVOICE.value
        )
    )
    assert row is not None
    before = list((row.field_schema or {}).get("fields") or [])

    response = await client.patch(
        f"{SCHEMAS}/{row.id}",
        headers=headers,
        json={"field_schema": {"fields": [{"name": "only_field", "type": "string"}]}},
    )
    assert response.status_code == 422

    await db_session.refresh(row)
    assert (row.field_schema or {}).get("fields") == before


async def test_a_valid_schema_edit_is_persisted_and_audited(
    client: AsyncClient, db_session: AsyncSession, signed_in
):
    user, headers = await admin_user(signed_in)
    row = await db_session.scalar(
        select(DocumentTypeSchema).where(
            DocumentTypeSchema.document_type == DocumentType.FA_DOCUMENT.value
        )
    )
    assert row is not None
    existing = list((row.field_schema or {}).get("fields") or [])

    added = {"name": "customs_reference", "label": "Customs reference", "type": "string"}
    response = await client.patch(
        f"{SCHEMAS}/{row.id}",
        headers=headers,
        json={
            "field_schema": {"fields": [*existing, added]},
            "change_reason": "Customs started quoting a reference we have to capture.",
        },
    )
    assert response.status_code == 200, response.text

    await db_session.refresh(row)
    names = [field["name"] for field in row.field_schema["fields"]]
    assert "customs_reference" in names
    assert row.changed_by_id == user.id

    event = await db_session.scalar(
        select(AuditEvent).where(
            AuditEvent.entity_type == "document_type_schema",
            AuditEvent.entity_id == str(row.id),
        )
    )
    assert event is not None
    assert event.event_metadata["fields_added"] == ["customs_reference"]
    # Field names and counts only. The schema body itself never goes on the trail.
    assert "field_schema" not in event.event_metadata


async def test_a_malformed_schema_is_refused_rather_than_stored(
    client: AsyncClient, db_session: AsyncSession, signed_in
):
    """A bad schema does not fail loudly later - it quietly extracts nothing. So it is refused."""
    _, headers = await admin_user(signed_in)
    row = await db_session.scalar(
        select(DocumentTypeSchema).where(
            DocumentTypeSchema.document_type == DocumentType.INVOICE.value
        )
    )
    assert row is not None

    for bad in (
        {"fields": []},
        {"fields": [{"label": "No name", "type": "string"}]},
        {"fields": [{"name": "a", "type": "string"}, {"name": "a", "type": "string"}]},
        {"not_fields": []},
    ):
        response = await client.patch(
            f"{SCHEMAS}/{row.id}",
            headers=headers,
            json={"field_schema": bad, "change_reason": GOOD_REASON},
        )
        assert response.status_code == 422, bad


# --- the manual role override ----------------------------------------------------------------------


async def test_the_role_override_calls_keycloak_before_it_writes_anything_locally(
    client: AsyncClient, db_session: AsyncSession, signed_in
):
    _, headers = await admin_user(signed_in)
    target, _ = await purchase_user(signed_in)
    fake = install_fake_client(
        FakeKeycloakAdminClient(roles_by_user={target.subject_id: ["purchase_user"]})
    )

    response = await client.patch(
        USERS,
        headers=headers,
        json={
            "user_id": str(target.id),
            "roles": ["purchase_user", "sales_user"],
            "change_reason": "Covering the sales desk while Aisha is on leave.",
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["identity_provider_confirmed"] is True
    assert data["roles_added"] == ["sales_user"]
    assert data["roles_removed"] == []

    # Keycloak was asked first, and asked for exactly what was requested.
    assert [call[0] for call in fake.calls] == ["find_user_id", "set_platform_roles"]
    assert fake.roles_by_user[target.subject_id] == ["purchase_user", "sales_user"]

    await db_session.refresh(target)
    assert sorted(target.roles) == ["purchase_user", "sales_user"]


async def test_a_keycloak_failure_leaves_local_state_completely_unchanged(
    client: AsyncClient, db_session: AsyncSession, signed_in
):
    """The one invariant this endpoint exists to hold.

    A local role Keycloak never granted is a claim the next sign-in would silently overwrite, so
    nothing local may be written until the identity provider has confirmed the change.
    """
    _, headers = await admin_user(signed_in)
    target, _ = await purchase_user(signed_in)
    target_id = target.id
    before = list(target.roles)

    install_fake_client(
        FakeKeycloakAdminClient(fail_with=keycloak_admin.KeycloakAdminError(reason="transport"))
    )

    response = await client.patch(
        USERS,
        headers=headers,
        json={
            "user_id": str(target.id),
            "roles": ["admin"],
            "change_reason": "Attempted while the identity provider was unreachable.",
        },
    )
    assert response.status_code == 502
    assert response.json()["success"] is False

    db_session.expire_all()
    refreshed = await db_session.get(User, target_id)
    assert refreshed is not None
    assert list(refreshed.roles) == before

    # The refusal is itself recorded, and says plainly that nothing local moved.
    event = await db_session.scalar(
        select(AuditEvent).where(AuditEvent.event_type == "admin.user.roles_update_failed")
    )
    assert event is not None
    assert event.event_metadata["local_state_changed"] is False
    assert event.event_metadata["current_roles"] == before


async def test_an_unconfigured_deployment_refuses_the_override_and_says_so(
    client: AsyncClient, db_session: AsyncSession, signed_in
):
    _, headers = await admin_user(signed_in)
    target, _ = await purchase_user(signed_in)
    target_id = target.id
    before = list(target.roles)
    install_fake_client(
        FakeKeycloakAdminClient(fail_with=keycloak_admin.KeycloakAdminNotConfiguredError())
    )

    response = await client.patch(
        USERS,
        headers=headers,
        json={
            "user_id": str(target.id),
            "roles": ["admin"],
            "change_reason": "Trying the override on a deployment with no credential.",
        },
    )
    assert response.status_code == 503
    assert response.json()["errors"][0]["code"] == "identity_admin_not_configured"

    db_session.expire_all()
    refreshed = await db_session.get(User, target_id)
    assert refreshed is not None
    assert list(refreshed.roles) == before


async def test_the_role_override_refuses_a_role_this_platform_does_not_have(
    client: AsyncClient, signed_in
):
    _, headers = await admin_user(signed_in)
    target, _ = await purchase_user(signed_in)
    fake = install_fake_client(FakeKeycloakAdminClient())

    response = await client.patch(
        USERS,
        headers=headers,
        json={
            "user_id": str(target.id),
            "roles": ["realm-admin"],
            "change_reason": "Trying to grant a Keycloak role that is not a platform role.",
        },
    )
    assert response.status_code == 422
    # Nothing reached the identity provider at all.
    assert fake.calls == []


async def test_the_user_screen_is_closed_to_every_other_role(client: AsyncClient, signed_in):
    _, purchase = await purchase_user(signed_in)
    _, auditor = await auditor_user(signed_in)

    assert (await client.get(USERS, headers=purchase)).status_code == 403
    assert (await client.get(USERS, headers=auditor)).status_code == 403


async def test_the_user_list_never_returns_the_admin_api_credential(client: AsyncClient, signed_in):
    _, headers = await admin_user(signed_in)
    response = await client.get(USERS, headers=headers)
    assert response.status_code == 200

    body = response.text.lower()
    for forbidden in ("client_secret", "keycloak_admin_client_secret", "secret"):
        assert forbidden not in body
