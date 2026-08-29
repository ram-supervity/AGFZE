"""Read and write models for the administration module.

Every update schema on this page carries a mandatory `change_reason`. That is not a new rule
introduced here: `rule_configurations.change_reason` and `document_type_schemas.change_reason`
have both been NOT NULL since the migrations that created them, in  3 and 2. This  is
where the requirement finally has a screen and an endpoint that enforce it rather than a seed
script that satisfies it.

The reason is validated on the server, in the schema, before any handler runs. A UI that forgot
to ask for one cannot get an edit through.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.roles import ALL_ROLES
from app.models.enums import DOCUMENT_TYPES, TERRITORIES
from app.models.reporting import (
    DISTRIBUTABLE_REPORT_TYPES,
    DISTRIBUTION_CHANNELS,
    REPORT_TYPES,
)
from app.services.analytics.report_templates import (
    HEADLINE_FIGURE_KEYS,
    KIND_AI_SUMMARY,
    KIND_KPI_GRID,
    SECTION_KINDS,
    SECTION_SOURCES,
    SOURCE_HEADLINE,
)

# Long enough to be a reason rather than a keystroke. The same floor the approval decision and the
# manual integration completion already hold their reasons to.
MIN_CHANGE_REASON = 10


class ChangeReasoned(BaseModel):
    """Anything that edits configuration. The reason is the price of the edit."""

    change_reason: str = Field(min_length=MIN_CHANGE_REASON, max_length=2000)

    @field_validator("change_reason")
    @classmethod
    def _meaningful(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < MIN_CHANGE_REASON:
            raise ValueError(
                f"Give a reason of at least {MIN_CHANGE_REASON} characters. A threshold that "
                "moved without a stated reason is not a change anybody can audit."
            )
        return cleaned


class RuleConfigurationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    rule_id: str
    check_key: str
    scope_commodity_code: str | None
    scope_transaction_type: str | None
    scope_stream: str | None
    threshold_value: Decimal
    threshold_unit: str
    description: str | None
    is_active: bool
    change_reason: str
    changed_at: datetime
    changed_by_name: str | None = None
    # Prose from the rule catalog, so a reader editing "quantity_tolerance" can see which
    # governing rule they are moving. Not stored on the row; resolved on read.
    rule_title: str | None = None
    rule_statement: str | None = None


class RuleConfigurationUpdate(ChangeReasoned):
    """What may be changed on a threshold row, and nothing more.

    The rule, the check and the scope are the row's identity - changing any of them would make
    this a different configuration wearing an existing row's audit history, so they are absent
    here by construction. A new scope is a new row.
    """

    threshold_value: Decimal | None = None
    is_active: bool | None = None
    description: str | None = Field(default=None, max_length=2000)


class RuleConfigurationList(BaseModel):
    items: list[RuleConfigurationRead]
    # Every distinct rule identifier present in the data, for the screen's filter. Read from the
    # rows themselves, so a rule a later  adds appears without a code change here.
    rule_ids: list[str]
    streams: list[str]


class DocumentTypeSchemaRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_type: str
    territory: str | None
    field_schema: dict[str, Any]
    mandatory_documents: list[str]
    change_reason: str
    changed_at: datetime
    changed_by_name: str | None = None
    field_count: int = 0
    required_field_count: int = 0


class DocumentTypeSchemaUpdate(ChangeReasoned):
    """The field list and the territory's document checklist.

    `document_type` and `territory` are the row's identity and are not editable, for the same
    reason a rule's scope is not: a schema row carries the history of what was extracted under
    it, and re-pointing it at another document type would silently rewrite that history.
    """

    field_schema: dict[str, Any] | None = None
    mandatory_documents: list[str] | None = None

    @field_validator("field_schema")
    @classmethod
    def _shape(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        """A schema is `{"fields": [...]}`, and every field has at least a name and a type.

        Checked here rather than trusted, because this is the one table whose contents the
        extraction prompts are built from: a malformed row would not fail loudly, it would
        quietly extract nothing.
        """
        if value is None:
            return None
        fields = value.get("fields")
        if not isinstance(fields, list) or not fields:
            raise ValueError('The schema must be {"fields": [...]} with at least one field.')
        seen: set[str] = set()
        for entry in fields:
            if not isinstance(entry, dict):
                raise ValueError("Every field must be an object.")
            name = str(entry.get("name") or "").strip()
            if not name:
                raise ValueError("Every field needs a name.")
            if name in seen:
                raise ValueError(f"'{name}' is listed twice; field names must be unique.")
            seen.add(name)
            if not str(entry.get("type") or "").strip():
                raise ValueError(f"'{name}' needs a type.")
        return value

    @field_validator("mandatory_documents")
    @classmethod
    def _known_documents(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        unknown = [item for item in value if item not in DOCUMENT_TYPES]
        if unknown:
            raise ValueError(
                "These are not document types this platform recognises: " + ", ".join(unknown)
            )
        return list(dict.fromkeys(value))


class DocumentTypeSchemaList(BaseModel):
    items: list[DocumentTypeSchemaRead]
    document_types: list[str] = Field(default_factory=lambda: list(DOCUMENT_TYPES))
    territories: list[str] = Field(default_factory=lambda: list(TERRITORIES))


class AdminUserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    display_name: str
    roles: list[str]
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None


class AdminUserList(BaseModel):
    items: list[AdminUserRead]
    assignable_roles: list[str] = Field(default_factory=lambda: list(ALL_ROLES))
    # Whether this deployment actually has an Admin API credential. The screen says so plainly
    # rather than offering an edit that can only fail.
    identity_provider_configured: bool
    provisioning_note: str


class UserRoleUpdate(ChangeReasoned):
    user_id: UUID
    roles: list[str] = Field(min_length=1)

    @field_validator("roles")
    @classmethod
    def _known_roles(cls, value: list[str]) -> list[str]:
        unknown = [role for role in value if role not in ALL_ROLES]
        if unknown:
            raise ValueError("Not platform roles: " + ", ".join(unknown))
        return list(dict.fromkeys(value))


class UserRoleUpdateResult(BaseModel):
    user: AdminUserRead
    roles_added: list[str]
    roles_removed: list[str]
    # Always true on a successful response. The local row is only ever written after Keycloak has
    # confirmed the change, so a result that exists at all is a result Keycloak accepted.
    identity_provider_confirmed: bool


# --- report distribution -------------------------------------------------------------------------


class ReportDistributionRuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    report_type: str
    recipient_roles: list[str]
    recipient_user_ids: list[UUID]
    channel: str
    is_active: bool
    change_reason: str
    changed_at: datetime
    changed_by_name: str | None = None
    # Resolved on read so the screen can show who a rule actually reaches today rather than the
    # role names it was written with. A role's membership changes; the rule does not.
    recipient_names: list[str] = Field(default_factory=list)


class ReportDistributionRuleWrite(ChangeReasoned):
    """Creating or replacing a distribution rule.

    A rule that names nobody is refused rather than stored inactive, because an active rule with
    an empty recipient list reads on the screen as "this report is distributed" while distributing
    to nobody - which is exactly the kind of quiet, wrong reassurance this platform is built to
    avoid. Deactivating a rule is what "stop sending this" means; an empty one is a mistake.
    """

    report_type: str
    recipient_roles: list[str] = Field(default_factory=list)
    recipient_user_ids: list[UUID] = Field(default_factory=list)
    channel: str = "in_app"
    is_active: bool = True

    @field_validator("report_type")
    @classmethod
    def _distributable(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if cleaned not in DISTRIBUTABLE_REPORT_TYPES:
            raise ValueError(
                "Only the scheduled reports can be distributed ("
                + ", ".join(DISTRIBUTABLE_REPORT_TYPES)
                + "). An ad-hoc report's requester is already watching it generate."
            )
        return cleaned

    @field_validator("channel")
    @classmethod
    def _known_channel(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if cleaned not in DISTRIBUTION_CHANNELS:
            raise ValueError("Choose one of: " + ", ".join(DISTRIBUTION_CHANNELS) + ".")
        return cleaned

    @field_validator("recipient_roles")
    @classmethod
    def _known_roles(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item and item.strip()]
        unknown = [item for item in cleaned if item not in ALL_ROLES]
        if unknown:
            raise ValueError("Not a platform role: " + ", ".join(sorted(unknown)) + ".")
        # De-duplicated here rather than at send time so the stored rule reads the way it behaves.
        return list(dict.fromkeys(cleaned))

    @field_validator("recipient_user_ids")
    @classmethod
    def _unique_users(cls, value: list[UUID]) -> list[UUID]:
        return list(dict.fromkeys(value))

    @model_validator(mode="after")
    def _reaches_somebody(self) -> ReportDistributionRuleWrite:
        if self.is_active and not self.recipient_roles and not self.recipient_user_ids:
            raise ValueError(
                "An active rule has to name at least one role or one person. To stop a report "
                "being distributed, deactivate the rule rather than emptying it."
            )
        return self


class ReportDistributionRuleList(BaseModel):
    items: list[ReportDistributionRuleRead]
    # The vocabularies the screen offers, read from the model rather than retyped in the client.
    report_types: list[str] = Field(default_factory=lambda: list(DISTRIBUTABLE_REPORT_TYPES))
    channels: list[str] = Field(default_factory=lambda: list(DISTRIBUTION_CHANNELS))
    roles: list[str] = Field(default_factory=lambda: list(ALL_ROLES))


# --- report templates ----------------------------------------------------------------------------


class ReportSectionWrite(BaseModel):
    """One section of a report, as an administrator edits it.

    Every field here decides what is *asked for*, never what the answer is. A section names a data
    block the report service already produces and, optionally, which of that block's figures to
    print and in what order; the figures themselves are computed from the governed tables at
    generation time and are not reachable from this screen at all.
    """

    key: str = Field(min_length=1, max_length=48)
    title: str = Field(min_length=1, max_length=160)
    kind: str
    source: str
    description: str | None = Field(default=None, max_length=1000)
    figures: list[str] = Field(default_factory=list)

    @field_validator("kind")
    @classmethod
    def _known_kind(cls, value: str) -> str:
        if value not in SECTION_KINDS:
            raise ValueError("A section renders as one of: " + ", ".join(SECTION_KINDS) + ".")
        return value

    @field_validator("source")
    @classmethod
    def _known_source(cls, value: str) -> str:
        # Checked here rather than at render time. A section naming a source nothing produces
        # fails the document build, which is correct and far too late: the report is already
        # scheduled, and the failure surfaces to a worker rather than to the person who caused it.
        if value not in SECTION_SOURCES:
            raise ValueError(
                "This platform produces no such data block. Choose one of: "
                + ", ".join(SECTION_SOURCES)
                + "."
            )
        return value

    @model_validator(mode="after")
    def _figures_belong_to_the_source(self) -> ReportSectionWrite:
        chosen = [value.strip() for value in self.figures if value and value.strip()]
        if not chosen:
            return self
        if self.kind != KIND_KPI_GRID or self.source != SOURCE_HEADLINE:
            raise ValueError(
                "Only a headline figure grid narrows to chosen figures. Every other section "
                "prints the whole block its source produces."
            )
        unknown = [value for value in chosen if value not in HEADLINE_FIGURE_KEYS]
        if unknown:
            raise ValueError("Not figures this platform computes: " + ", ".join(unknown) + ".")
        object.__setattr__(self, "figures", list(dict.fromkeys(chosen)))
        return self


class ReportTemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    template_key: str
    report_type: str
    title: str
    description: str
    sections: list[dict[str, Any]]
    disclosures: list[str]
    wants_ai_summary: bool
    include_detail_rows: bool
    default_period_days: int
    change_reason: str
    changed_at: datetime
    changed_by_name: str | None = None
    section_count: int = 0


class ReportTemplateUpdate(ChangeReasoned):
    """The structure, and nothing that would make this a different template.

    `template_key` and `report_type` are absent by construction, exactly as a rule's scope and a
    document schema's type are. A generated report records which template produced it, and
    re-pointing a template at another report type would leave those records claiming a structure
    the document was never built to.
    """

    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, min_length=1, max_length=2000)
    sections: list[ReportSectionWrite] | None = None
    disclosures: list[str] | None = None

    @field_validator("sections")
    @classmethod
    def _coherent(cls, value: list[ReportSectionWrite] | None) -> list[ReportSectionWrite] | None:
        if value is None:
            return None
        if not value:
            raise ValueError("A report has to carry at least one section.")
        keys = [section.key for section in value]
        duplicates = sorted({key for key in keys if keys.count(key) > 1})
        if duplicates:
            raise ValueError("Section keys must be unique: " + ", ".join(duplicates) + ".")
        summaries = [section for section in value if section.kind == KIND_AI_SUMMARY]
        if len(summaries) > 1:
            raise ValueError("A report carries at most one AI summary section.")
        return value

    @field_validator("disclosures")
    @classmethod
    def _non_empty_disclosures(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        cleaned = [item.strip() for item in value if item and item.strip()]
        return list(dict.fromkeys(cleaned))


class ReportTemplateList(BaseModel):
    items: list[ReportTemplateRead]
    # The vocabularies the screen offers, read from the service rather than retyped in the client.
    report_types: list[str] = Field(default_factory=lambda: list(REPORT_TYPES))
    section_kinds: list[str] = Field(default_factory=lambda: list(SECTION_KINDS))
    section_sources: list[str] = Field(default_factory=lambda: list(SECTION_SOURCES))
    headline_figures: list[str] = Field(default_factory=lambda: list(HEADLINE_FIGURE_KEYS))
