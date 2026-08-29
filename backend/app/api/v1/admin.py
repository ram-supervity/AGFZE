"""The administration module: rules, document schemas, and the manual role override.

Rules, document schemas, report distribution, report templates, and the manual role override.
Two other things this platform stores are, technically, configuration and still get no editing
screen here, deliberately:

* the integration endpoints are infrastructure. Changing where an approved deal is posted should
  require a deployment and a review, not a form somebody can fill in at four in the afternoon;
* the rule-to-category mapping is seed data that decides which desk owns which failure. It has
  never been part of this platform's page catalog and stays migration-driven.

Report *templates* were on that list until now. They are on this page instead because the
governing material asks for reports to be built against configuration rather than hard-coded
layouts and for the exact templates to be confirmed with AGFZE - which is a conversation, not a
release, and a conversation needs a screen.

Every endpoint here enforces the Admin role server-side through the shared dependency, not by
which link the sidebar happened to draw.

Two invariants run through this module:

1. **No configuration change without a recorded reason.** `RuleConfiguration` and
   `DocumentTypeSchema` have carried a mandatory `change_reason` since the migrations that
   created them; this is where that finally has an endpoint behind it. The reason is validated in
   the schema, so a request without one never reaches a handler, and the audit event is written
   before the session is committed - the change and the record of it land together or not at all.
2. **Keycloak first, local second.** A role override calls the identity provider synchronously
   and commits nothing locally until that call has come back confirmed. A failure leaves this
   platform's own record exactly as it was, because a local role Keycloak never granted is a
   claim the next sign-in would silently overwrite.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.dependencies import DbSession, require_roles
from app.core.errors import BadRequestError, NotFoundError
from app.core.roles import ALL_ROLES, PlatformRole, normalise_roles
from app.db.base import utcnow
from app.models.configuration import DocumentTypeSchema, RuleConfiguration
from app.models.identity import User
from app.models.reporting import ReportDistributionRule, ReportTemplateConfiguration
from app.schemas.admin import (
    AdminUserList,
    AdminUserRead,
    DocumentTypeSchemaList,
    DocumentTypeSchemaRead,
    DocumentTypeSchemaUpdate,
    ReportDistributionRuleList,
    ReportDistributionRuleRead,
    ReportDistributionRuleWrite,
    ReportTemplateList,
    ReportTemplateRead,
    ReportTemplateUpdate,
    RuleConfigurationList,
    RuleConfigurationRead,
    RuleConfigurationUpdate,
    UserRoleUpdate,
    UserRoleUpdateResult,
)
from app.schemas.common import ResponseEnvelope
from app.services import keycloak_admin, notification_service
from app.services.analytics.report_templates import SectionSpec, section_as_row
from app.services.audit_service import ActorType, record_audit_event
from app.services.rules.catalog import RULE_BY_ID

router = APIRouter(prefix="/admin", tags=["admin"])

# Enforced here, on the server, on every call.
PlatformAdmin = Annotated[User, Depends(require_roles(PlatformRole.ADMIN.value))]

PROVISIONING_NOTE = (
    "Accounts appear here the first time somebody signs in, mirrored from the identity provider. "
    "Roles normally arrive with the token on every sign-in, mapped from Entra ID groups. Editing "
    "a role here is the manual exception to that: it is written to Keycloak first and mirrored "
    "locally only once Keycloak has confirmed it."
)


class AdminAuditEvent:
    RULE_UPDATED = "admin.rule_configuration.updated"
    REPORT_DISTRIBUTION_SAVED = "admin.report_distribution.saved"
    REPORT_DISTRIBUTION_DELETED = "admin.report_distribution.deleted"
    REPORT_TEMPLATE_UPDATED = "admin.report_template.updated"
    DOCUMENT_SCHEMA_UPDATED = "admin.document_type_schema.updated"
    USER_ROLES_UPDATED = "admin.user.roles_updated"
    USER_ROLES_UPDATE_FAILED = "admin.user.roles_update_failed"


# --- rule configuration ------------------------------------------------------------------------


def _rule_read(row: RuleConfiguration) -> RuleConfigurationRead:
    read = RuleConfigurationRead.model_validate(row)
    read.changed_by_name = row.changed_by.display_name if row.changed_by else None
    definition = RULE_BY_ID.get(row.rule_id)
    if definition is not None:
        read.rule_title = definition.title
        read.rule_statement = definition.statement
    return read


@router.get(
    "/rules",
    response_model=ResponseEnvelope[RuleConfigurationList],
    summary="Every configured threshold, whichever step first seeded it",
)
async def list_rules(
    user: PlatformAdmin,
    session: DbSession,
    rule_id: str | None = Query(None),
    stream: str | None = Query(None),
) -> ResponseEnvelope[RuleConfigurationList]:
    """One query over one table, with no special-casing by which step created a row.

    The purchase tolerances seeded in Step 3, the sales rule added in Step 5 and the FA-scoped
    defaults added in Step 6 are all rows in `rule_configurations` and all reach this screen the
    same way. That they need no branch here is the concrete proof the table was built generically.
    """
    statement = select(RuleConfiguration).options(selectinload(RuleConfiguration.changed_by))
    if rule_id:
        statement = statement.where(RuleConfiguration.rule_id == rule_id)
    if stream:
        statement = statement.where(RuleConfiguration.scope_stream == stream)

    rows = list(
        (
            await session.scalars(
                statement.order_by(
                    RuleConfiguration.rule_id,
                    RuleConfiguration.check_key,
                    RuleConfiguration.scope_stream,
                )
            )
        ).all()
    )
    every = list(
        (
            await session.scalars(
                select(RuleConfiguration.rule_id).distinct().order_by(RuleConfiguration.rule_id)
            )
        ).all()
    )
    streams = list(
        (
            await session.scalars(
                select(RuleConfiguration.scope_stream)
                .distinct()
                .where(RuleConfiguration.scope_stream.is_not(None))
                .order_by(RuleConfiguration.scope_stream)
            )
        ).all()
    )

    return ResponseEnvelope[RuleConfigurationList](
        data=RuleConfigurationList(
            items=[_rule_read(row) for row in rows],
            rule_ids=[str(value) for value in every],
            streams=[str(value) for value in streams],
        )
    )


@router.patch(
    "/rules/{configuration_id}",
    response_model=ResponseEnvelope[RuleConfigurationRead],
    summary="Change a threshold, with a mandatory recorded reason",
)
async def update_rule(
    configuration_id: UUID,
    payload: RuleConfigurationUpdate,
    user: PlatformAdmin,
    session: DbSession,
) -> ResponseEnvelope[RuleConfigurationRead]:
    """The reason is not optional and is not merely encouraged by the dialog.

    It is required by the schema, so a request that omits it is rejected with a 422 before this
    function runs. The audit event is written before the commit, in the same transaction as the
    change, so the trail and the new value land together.
    """
    row = await session.get(RuleConfiguration, configuration_id)
    if row is None:
        raise NotFoundError("That rule configuration does not exist.")

    before = {
        "threshold_value": str(row.threshold_value),
        "is_active": row.is_active,
        "description": row.description,
    }
    if payload.threshold_value is not None:
        row.threshold_value = payload.threshold_value
    if payload.is_active is not None:
        row.is_active = payload.is_active
    if payload.description is not None:
        row.description = payload.description.strip() or None
    row.change_reason = payload.change_reason
    row.changed_by_id = user.id
    row.changed_at = utcnow()
    await session.flush()

    await record_audit_event(
        session,
        event_type=AdminAuditEvent.RULE_UPDATED,
        entity_type="rule_configuration",
        entity_id=row.id,
        actor_id=user.id,
        actor_type=ActorType.USER,
        metadata={
            "rule_id": row.rule_id,
            "check_key": row.check_key,
            "scope_stream": row.scope_stream,
            "scope_commodity_code": row.scope_commodity_code,
            "scope_transaction_type": row.scope_transaction_type,
            "before": before,
            "after": {
                "threshold_value": str(row.threshold_value),
                "is_active": row.is_active,
                "description": row.description,
            },
            "change_reason": row.change_reason,
        },
    )
    await session.commit()

    refreshed = await session.scalar(
        select(RuleConfiguration)
        .where(RuleConfiguration.id == row.id)
        .options(selectinload(RuleConfiguration.changed_by))
    )
    return ResponseEnvelope[RuleConfigurationRead](
        data=_rule_read(refreshed or row),
        message=(
            f"{row.rule_id} · {row.check_key} updated. Every evaluation from now on reads the "
            "new value; decisions already made keep the value that was live at the time."
        ),
    )


# --- document type schemas ---------------------------------------------------------------------


def _schema_read(row: DocumentTypeSchema) -> DocumentTypeSchemaRead:
    read = DocumentTypeSchemaRead.model_validate(row)
    read.changed_by_name = row.changed_by.display_name if row.changed_by else None
    fields = (row.field_schema or {}).get("fields") or []
    read.field_count = len(fields)
    read.required_field_count = sum(
        1 for field in fields if isinstance(field, dict) and field.get("required")
    )
    return read


@router.get(
    "/document-types",
    response_model=ResponseEnvelope[DocumentTypeSchemaList],
    summary="Every document type's field list and mandatory-document checklist",
)
async def list_document_types(
    user: PlatformAdmin,
    session: DbSession,
    document_type: str | None = Query(None),
) -> ResponseEnvelope[DocumentTypeSchemaList]:
    """The Step 2 invoice and contract schemas, the Step 5 bill of lading and the Step 6
    `fa_document` schema, in one list with no branch distinguishing them."""
    statement = select(DocumentTypeSchema).options(selectinload(DocumentTypeSchema.changed_by))
    if document_type:
        statement = statement.where(DocumentTypeSchema.document_type == document_type)
    rows = list(
        (
            await session.scalars(
                statement.order_by(DocumentTypeSchema.document_type, DocumentTypeSchema.territory)
            )
        ).all()
    )
    return ResponseEnvelope[DocumentTypeSchemaList](
        data=DocumentTypeSchemaList(items=[_schema_read(row) for row in rows])
    )


@router.patch(
    "/document-types/{schema_id}",
    response_model=ResponseEnvelope[DocumentTypeSchemaRead],
    summary="Change a document type's fields or its mandatory pack, with a recorded reason",
)
async def update_document_type(
    schema_id: UUID,
    payload: DocumentTypeSchemaUpdate,
    user: PlatformAdmin,
    session: DbSession,
) -> ResponseEnvelope[DocumentTypeSchemaRead]:
    row = await session.get(DocumentTypeSchema, schema_id)
    if row is None:
        raise NotFoundError("That document type schema does not exist.")

    before_fields = [
        str(field.get("name"))
        for field in ((row.field_schema or {}).get("fields") or [])
        if isinstance(field, dict)
    ]
    before_documents = list(row.mandatory_documents or [])

    if payload.field_schema is not None:
        row.field_schema = payload.field_schema
    if payload.mandatory_documents is not None:
        row.mandatory_documents = payload.mandatory_documents
    row.change_reason = payload.change_reason
    row.changed_by_id = user.id
    row.changed_at = utcnow()
    await session.flush()

    after_fields = [
        str(field.get("name"))
        for field in ((row.field_schema or {}).get("fields") or [])
        if isinstance(field, dict)
    ]
    await record_audit_event(
        session,
        event_type=AdminAuditEvent.DOCUMENT_SCHEMA_UPDATED,
        entity_type="document_type_schema",
        entity_id=row.id,
        actor_id=user.id,
        actor_type=ActorType.USER,
        # Field *names* and counts, never the schema body: the trail records that the shape
        # changed and how, not a copy of every document's field list.
        metadata={
            "document_type": row.document_type,
            "territory": row.territory,
            "fields_added": sorted(set(after_fields) - set(before_fields)),
            "fields_removed": sorted(set(before_fields) - set(after_fields)),
            "field_count": len(after_fields),
            "mandatory_documents_before": before_documents,
            "mandatory_documents_after": list(row.mandatory_documents or []),
            "change_reason": row.change_reason,
        },
    )
    await session.commit()

    refreshed = await session.scalar(
        select(DocumentTypeSchema)
        .where(DocumentTypeSchema.id == row.id)
        .options(selectinload(DocumentTypeSchema.changed_by))
    )
    return ResponseEnvelope[DocumentTypeSchemaRead](
        data=_schema_read(refreshed or row),
        message=(
            f"The {row.document_type.replace('_', ' ')} schema is updated. Documents extracted "
            "from now on are read against it; those already extracted keep what they were read "
            "with."
        ),
    )


# --- users and the manual role override ----------------------------------------------------------


@router.get(
    "/users",
    response_model=ResponseEnvelope[AdminUserList],
    summary="Every account mirrored from the identity provider, with its current roles",
)
async def list_users(
    user: PlatformAdmin,
    session: DbSession,
    search: str | None = Query(None),
) -> ResponseEnvelope[AdminUserList]:
    statement = select(User)
    if search:
        term = f"%{search.strip().lower()}%"
        statement = statement.where(User.display_name.ilike(term) | User.email.ilike(term))
    rows = list((await session.scalars(statement.order_by(User.display_name))).all())
    return ResponseEnvelope[AdminUserList](
        data=AdminUserList(
            items=[AdminUserRead.model_validate(row) for row in rows],
            assignable_roles=list(ALL_ROLES),
            identity_provider_configured=settings.keycloak_admin_configured,
            provisioning_note=PROVISIONING_NOTE,
        )
    )


@router.patch(
    "/users",
    response_model=ResponseEnvelope[UserRoleUpdateResult],
    summary="Override an account's roles - Keycloak first, local record only on confirmation",
)
async def update_user_roles(
    payload: UserRoleUpdate,
    user: PlatformAdmin,
    session: DbSession,
) -> ResponseEnvelope[UserRoleUpdateResult]:
    """The ordering here is the whole point of the endpoint.

    Keycloak is called synchronously and its success is confirmed before one local column is
    written. If the call fails, is refused, or the provider is unreachable, this function raises
    and the session is rolled back by the request lifecycle with nothing changed - never a local
    role the identity provider has never granted, and never a half-applied state between the two
    systems.
    """
    target = await session.get(User, payload.user_id)
    if target is None:
        raise NotFoundError("That account does not exist on this platform.")

    wanted = normalise_roles(payload.roles)
    # Read off the row before anything else happens. The failure path below rolls the session
    # back, which expires every loaded object, and re-reading an expired attribute mid-handler is
    # exactly the kind of incidental IO that turns a clean 502 into an opaque 500.
    target_id = target.id
    subject_id = target.subject_id
    email = target.email
    actor_id = user.id
    previous = normalise_roles(target.roles or [])

    client = keycloak_admin.get_keycloak_admin_client()
    try:
        keycloak_user_id = await client.find_user_id(subject_id=subject_id, email=email)
        added, removed = await client.set_platform_roles(keycloak_user_id, wanted)
    except keycloak_admin.KeycloakAdminError as exc:
        # The refusal is itself auditable, and is recorded on a session rolled back to the state
        # it was in before the attempt - so the only row this path writes is the record that the
        # attempt was refused. The role change is not applied.
        await session.rollback()
        await record_audit_event(
            session,
            event_type=AdminAuditEvent.USER_ROLES_UPDATE_FAILED,
            entity_type="user",
            entity_id=target_id,
            actor_id=actor_id,
            actor_type=ActorType.USER,
            metadata={
                "requested_roles": wanted,
                "current_roles": previous,
                "reason": exc.reason,
                "change_reason": payload.change_reason,
                "local_state_changed": False,
            },
        )
        await session.commit()
        raise

    # Only now. Keycloak holds the new mapping; this is the mirror catching up to it.
    target.roles = wanted
    await session.flush()

    await record_audit_event(
        session,
        event_type=AdminAuditEvent.USER_ROLES_UPDATED,
        entity_type="user",
        entity_id=target.id,
        actor_id=user.id,
        actor_type=ActorType.USER,
        metadata={
            "subject_id": target.subject_id,
            "roles_before": previous,
            "roles_after": wanted,
            "roles_added": added,
            "roles_removed": removed,
            "identity_provider_confirmed": True,
            "change_reason": payload.change_reason,
        },
    )
    await session.commit()

    return ResponseEnvelope[UserRoleUpdateResult](
        data=UserRoleUpdateResult(
            user=AdminUserRead.model_validate(target),
            roles_added=added,
            roles_removed=removed,
            identity_provider_confirmed=True,
        ),
        message=(
            f"{target.display_name}'s roles are updated in Keycloak and mirrored here. They take "
            "effect on their next sign-in, when the new token is issued."
        ),
    )


# --- report distribution -------------------------------------------------------------------------
#
# The one configuration on this platform whose effect is that somebody's phone buzzes. It is held
# to the same discipline as every threshold above it - a mandatory reason, an attributed editor, an
# audit row written in the same transaction as the change - and to one additional rule of its own:
# a rule that reaches nobody cannot be stored active. See `ReportDistributionRuleWrite`.


async def _distribution_read(
    session: DbSession, row: ReportDistributionRule
) -> ReportDistributionRuleRead:
    read = ReportDistributionRuleRead.model_validate(row)
    read.changed_by_name = row.changed_by.display_name if row.changed_by else None

    # Who this rule reaches as things stand today, resolved the same way the sender resolves it so
    # the screen cannot show a different answer from the one the report will actually use.
    names: dict[UUID, str] = {}
    for role in row.recipient_roles or ():
        for user in await notification_service.active_users_with_role(session, role):
            names[user.id] = user.display_name
    named = [UUID(str(value)) for value in (row.recipient_user_ids or ())]
    if named:
        for user in (await session.scalars(select(User).where(User.id.in_(named)))).all():
            names[user.id] = user.display_name
    read.recipient_names = sorted(names.values())
    return read


@router.get(
    "/report-distribution",
    response_model=ResponseEnvelope[ReportDistributionRuleList],
    summary="Who receives which scheduled report, and on which channel",
)
async def list_report_distribution(
    user: PlatformAdmin,
    session: DbSession,
    report_type: str | None = Query(None),
) -> ResponseEnvelope[ReportDistributionRuleList]:
    """Every rule, including the inactive ones.

    An inactive rule is deliberately still listed: "we used to send this to the finance desk and
    stopped in March, for this stated reason" is exactly the kind of thing somebody signing this
    platform off needs to be able to read, and hiding it would leave only the audit trail to say so.
    """
    statement = select(ReportDistributionRule).options(
        selectinload(ReportDistributionRule.changed_by)
    )
    if report_type:
        statement = statement.where(ReportDistributionRule.report_type == report_type)
    rows = list(
        (
            await session.scalars(
                statement.order_by(
                    ReportDistributionRule.report_type, ReportDistributionRule.created_at
                )
            )
        ).all()
    )
    return ResponseEnvelope[ReportDistributionRuleList](
        data=ReportDistributionRuleList(
            items=[await _distribution_read(session, row) for row in rows]
        )
    )


@router.post(
    "/report-distribution",
    response_model=ResponseEnvelope[ReportDistributionRuleRead],
    summary="Configure who receives a scheduled report, with a mandatory recorded reason",
)
async def create_report_distribution(
    payload: ReportDistributionRuleWrite,
    user: PlatformAdmin,
    session: DbSession,
) -> ResponseEnvelope[ReportDistributionRuleRead]:
    """Add a rule. Nothing is sent until one exists, and nothing is retrospective.

    A rule created now governs the next scheduled generation, not the reports already produced -
    there is no path here that distributes an existing report, deliberately, because a report is
    generated over a period and circulating an old one on a new list is a decision a person should
    make by sending its link, not something a configuration change should do silently.
    """
    named = list(payload.recipient_user_ids)
    if named:
        found = {
            row.id for row in (await session.scalars(select(User).where(User.id.in_(named)))).all()
        }
        missing = [str(value) for value in named if value not in found]
        if missing:
            raise BadRequestError(
                "No such account: " + ", ".join(missing) + ".",
                code="unknown_recipient",
            )

    row = ReportDistributionRule(
        report_type=payload.report_type,
        recipient_roles=list(payload.recipient_roles),
        recipient_user_ids=[str(value) for value in payload.recipient_user_ids],
        channel=payload.channel,
        is_active=payload.is_active,
        change_reason=payload.change_reason,
        changed_by_id=user.id,
        changed_at=utcnow(),
    )
    session.add(row)
    await session.flush()

    await record_audit_event(
        session,
        event_type=AdminAuditEvent.REPORT_DISTRIBUTION_SAVED,
        entity_type="report_distribution_rule",
        entity_id=row.id,
        actor_id=user.id,
        actor_type=ActorType.USER,
        metadata={
            "report_type": row.report_type,
            "recipient_roles": list(row.recipient_roles or ()),
            "recipient_user_ids": list(row.recipient_user_ids or ()),
            "channel": row.channel,
            "is_active": row.is_active,
            "change_reason": row.change_reason,
            "created": True,
        },
    )
    await session.commit()

    refreshed = await session.scalar(
        select(ReportDistributionRule)
        .where(ReportDistributionRule.id == row.id)
        .options(selectinload(ReportDistributionRule.changed_by))
    )
    target = refreshed or row
    return ResponseEnvelope[ReportDistributionRuleRead](
        data=await _distribution_read(session, target),
        message=(
            f"The {row.report_type} report will be distributed from its next scheduled "
            "generation. Recipients are notified with a link; the file itself is never sent."
        ),
    )


@router.patch(
    "/report-distribution/{rule_id}",
    response_model=ResponseEnvelope[ReportDistributionRuleRead],
    summary="Change or deactivate a distribution rule, with a mandatory recorded reason",
)
async def update_report_distribution(
    rule_id: UUID,
    payload: ReportDistributionRuleWrite,
    user: PlatformAdmin,
    session: DbSession,
) -> ResponseEnvelope[ReportDistributionRuleRead]:
    """A full replacement of the rule's recipients, channel and active flag, reason included."""
    row = await session.get(ReportDistributionRule, rule_id)
    if row is None:
        raise NotFoundError("That distribution rule does not exist.")

    named = list(payload.recipient_user_ids)
    if named:
        found = {
            item.id
            for item in (await session.scalars(select(User).where(User.id.in_(named)))).all()
        }
        missing = [str(value) for value in named if value not in found]
        if missing:
            raise BadRequestError(
                "No such account: " + ", ".join(missing) + ".",
                code="unknown_recipient",
            )

    before = {
        "report_type": row.report_type,
        "recipient_roles": list(row.recipient_roles or ()),
        "recipient_user_ids": list(row.recipient_user_ids or ()),
        "channel": row.channel,
        "is_active": row.is_active,
    }
    row.report_type = payload.report_type
    row.recipient_roles = list(payload.recipient_roles)
    row.recipient_user_ids = [str(value) for value in payload.recipient_user_ids]
    row.channel = payload.channel
    row.is_active = payload.is_active
    row.change_reason = payload.change_reason
    row.changed_by_id = user.id
    row.changed_at = utcnow()
    await session.flush()

    await record_audit_event(
        session,
        event_type=AdminAuditEvent.REPORT_DISTRIBUTION_SAVED,
        entity_type="report_distribution_rule",
        entity_id=row.id,
        actor_id=user.id,
        actor_type=ActorType.USER,
        metadata={
            "before": before,
            "after": {
                "report_type": row.report_type,
                "recipient_roles": list(row.recipient_roles or ()),
                "recipient_user_ids": list(row.recipient_user_ids or ()),
                "channel": row.channel,
                "is_active": row.is_active,
            },
            "change_reason": row.change_reason,
            "created": False,
        },
    )
    await session.commit()

    refreshed = await session.scalar(
        select(ReportDistributionRule)
        .where(ReportDistributionRule.id == row.id)
        .options(selectinload(ReportDistributionRule.changed_by))
    )
    target = refreshed or row
    state = "active" if row.is_active else "inactive"
    return ResponseEnvelope[ReportDistributionRuleRead](
        data=await _distribution_read(session, target),
        message=f"The {row.report_type} distribution rule is saved and {state}.",
    )


# --- report templates ----------------------------------------------------------------------------
#
# What a report is made of, rather than what it says. Nothing on this screen can change a figure:
# every number a report prints is computed from the governed tables at the moment it is generated,
# and these rows decide only which blocks are asked for and in what order they are laid out.


def _template_read(row: ReportTemplateConfiguration) -> ReportTemplateRead:
    read = ReportTemplateRead.model_validate(row)
    read.changed_by_name = row.changed_by.display_name if row.changed_by else None
    read.section_count = len(row.sections or [])
    return read


@router.get(
    "/report-templates",
    response_model=ResponseEnvelope[ReportTemplateList],
    summary="What each report is made of: its sections, their order and their figures",
)
async def list_report_templates(
    user: PlatformAdmin,
    session: DbSession,
    report_type: str | None = Query(None),
) -> ResponseEnvelope[ReportTemplateList]:
    statement = select(ReportTemplateConfiguration).options(
        selectinload(ReportTemplateConfiguration.changed_by)
    )
    if report_type:
        statement = statement.where(ReportTemplateConfiguration.report_type == report_type)
    rows = list(
        (await session.scalars(statement.order_by(ReportTemplateConfiguration.report_type))).all()
    )
    return ResponseEnvelope[ReportTemplateList](
        data=ReportTemplateList(items=[_template_read(row) for row in rows])
    )


@router.patch(
    "/report-templates/{template_id}",
    response_model=ResponseEnvelope[ReportTemplateRead],
    summary="Change what a report carries, with a mandatory recorded reason",
)
async def update_report_template(
    template_id: UUID,
    payload: ReportTemplateUpdate,
    user: PlatformAdmin,
    session: DbSession,
) -> ResponseEnvelope[ReportTemplateRead]:
    """An edit governs the next generation and never a past one.

    The reports already produced keep their own `content` and their own `template_key`, which is
    exactly why neither is recomputed on read: a document says what it said when it was generated,
    and this endpoint cannot reach back and change that.
    """
    row = await session.get(ReportTemplateConfiguration, template_id)
    if row is None:
        raise NotFoundError("That report template does not exist.")

    before = {
        "title": row.title,
        "section_keys": [str(section.get("key")) for section in (row.sections or [])],
        "disclosure_count": len(row.disclosures or []),
    }

    if payload.title is not None:
        row.title = payload.title.strip()
    if payload.description is not None:
        row.description = payload.description.strip()
    if payload.sections is not None:
        # Written through the same converter the migration's seed and the generator's reader both
        # use, so a stored section can never be a shape only this endpoint knows how to produce.
        row.sections = [
            section_as_row(
                SectionSpec(
                    key=section.key,
                    title=section.title,
                    kind=section.kind,
                    source=section.source,
                    description=section.description,
                    figures=tuple(section.figures),
                )
            )
            for section in payload.sections
        ]
    if payload.disclosures is not None:
        row.disclosures = list(payload.disclosures)
    row.change_reason = payload.change_reason
    row.changed_by_id = user.id
    row.changed_at = utcnow()
    await session.flush()

    after_keys = [str(section.get("key")) for section in (row.sections or [])]
    await record_audit_event(
        session,
        event_type=AdminAuditEvent.REPORT_TEMPLATE_UPDATED,
        entity_type="report_template_configuration",
        entity_id=row.id,
        actor_id=user.id,
        actor_type=ActorType.USER,
        # Section keys and counts, never the section bodies: the trail records that the structure
        # changed and how, not a second copy of every report's layout.
        metadata={
            "template_key": row.template_key,
            "report_type": row.report_type,
            "before": before,
            "after": {
                "title": row.title,
                "section_keys": after_keys,
                "disclosure_count": len(row.disclosures or []),
            },
            "sections_added": sorted(set(after_keys) - set(before["section_keys"])),
            "sections_removed": sorted(set(before["section_keys"]) - set(after_keys)),
            "change_reason": row.change_reason,
        },
    )
    await session.commit()

    refreshed = await session.scalar(
        select(ReportTemplateConfiguration)
        .where(ReportTemplateConfiguration.id == row.id)
        .options(selectinload(ReportTemplateConfiguration.changed_by))
    )
    return ResponseEnvelope[ReportTemplateRead](
        data=_template_read(refreshed or row),
        message=(
            f"The {row.report_type} report is updated. It takes this shape from its next "
            "generation; the reports already produced keep the structure they were built to."
        ),
    )
