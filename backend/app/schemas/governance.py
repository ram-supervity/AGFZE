"""Wire models for the exception queue and the approval queue.

Note what the decision payload does not carry: no `decided_by`, no `decided_at`. They are absent
by construction rather than ignored by convention, so there is no field for a client to populate
and nothing for the server to have to remember to discard.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import APPROVAL_DECISIONS, EXCEPTION_CATEGORIES
from app.schemas.intake import DocumentSummary, Page
from app.schemas.transaction import RuleEvaluationRead


class ExceptionCategoryRead(BaseModel):
    """One of the ten tabs, including the three nothing can raise yet."""

    category: str
    label: str
    owner_role: str
    shared_with: list[str] = Field(default_factory=list)
    triggerable: bool
    description: str
    dormant_reason: str | None = None
    open_count: int = 0


class ExceptionCaseListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    exception_type: str
    exception_label: str | None = None
    rule_id: str | None
    check_key: str | None
    owner_role: str
    priority: str
    summary: str
    field_name: str | None
    expected_value: str | None
    actual_value: str | None
    opened_at: datetime
    resolved_at: datetime | None
    escalated: bool
    transaction_id: UUID | None
    document_id: UUID | None
    batch_number: str | None = None
    counterparty: str | None = None
    value: Decimal | None = None
    currency: str | None = None
    assigned_to_name: str | None = None
    # Both computed at read time from `opened_at` and the configured threshold. Neither is stored,
    # so neither can be stale.
    age_hours: float = 0.0
    age_days: int = 0
    overdue: bool = False
    ageing_threshold_hours: int = 0


class ExceptionCaseDetail(ExceptionCaseListItem):
    request_id: UUID | None = None
    resolution_note: str | None = None
    resolved_by_name: str | None = None
    escalated_at: datetime | None = None
    escalated_by_name: str | None = None
    escalation_note: str | None = None
    transaction_status: str | None = None
    # Where the rule that opened this case stands right now, as against what it said then.
    current_evaluation: RuleEvaluationRead | None = None
    rule_now_passes: bool | None = None
    documents: list[DocumentSummary] = Field(default_factory=list)
    # What the caller may actually do, decided server-side from their roles and the case's state.
    can_resolve: bool = False
    can_escalate: bool = False
    resolve_blocked_reason: str | None = None


class ExceptionQueue(BaseModel):
    items: list[ExceptionCaseListItem]
    page: Page
    categories: list[ExceptionCategoryRead] = Field(default_factory=list)
    ageing_threshold_hours: int = 0


class ExceptionFieldCorrection(BaseModel):
    """Exactly the shape `PATCH /transactions/{id}/fields` already takes.

    Same shape because it is the same path: the resolve endpoint hands this straight to the
    correction service Step 3 built rather than writing a second way to change a value.
    """

    name: str = Field(min_length=1, max_length=128)
    value: str | None = None
    reason: str | None = None


class ExceptionResolution(BaseModel):
    resolution_note: str = Field(min_length=10, max_length=2000)
    correction: ExceptionFieldCorrection | None = None
    # A distinct outcome from resolving, not a flavour of it: it raises the case's visibility and
    # leaves it open, because nothing has been fixed.
    escalate_to_hod: bool = False

    @field_validator("resolution_note")
    @classmethod
    def _meaningful(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 10:
            raise ValueError(
                "Give a note of at least 10 characters; this is the record of what was done."
            )
        return cleaned


class ApprovalSummaryRead(BaseModel):
    """The AI note, and an honest account of itself when there isn't one."""

    available: bool = False
    summary: str | None = None
    what_to_check: list[str] = Field(default_factory=list)
    generated_at: datetime | None = None
    unavailable_reason: str | None = None


class ApprovalRiskRead(BaseModel):
    label: str
    score: int
    reasons: list[str] = Field(default_factory=list)
    acknowledged_tolerance: bool = False
    prior_exception: bool = False
    bulk_eligible: bool = False


class ApprovalListItem(BaseModel):
    id: UUID
    transaction_id: UUID
    batch_number: str
    counterparty: str | None = None
    contract_number: str | None = None
    commodity_name: str | None = None
    quantity_mt: Decimal | None = None
    value: Decimal | None = None
    currency: str
    decision: str
    requested_at: datetime
    requested_by_name: str | None = None
    decided_at: datetime | None = None
    decided_by_name: str | None = None
    reason: str | None = None
    age_hours: float = 0.0
    age_days: int = 0
    overdue: bool = False
    risk: ApprovalRiskRead
    requires_confirmation: bool = False


class ApprovalQueue(BaseModel):
    items: list[ApprovalListItem]
    page: Page
    rank_by: str
    # Echoed back so the screen renders the filter it is actually showing rather than the one it
    # believes it asked for. Null means both streams, which is the queue's default.
    stream: str | None = None
    # Both read from configuration and sent to the screen, so the UI never restates a threshold.
    confirmation_threshold: Decimal
    bulk_value_ceiling: Decimal
    overdue_threshold_hours: int
    can_decide: bool = False


class ApprovalDetail(ApprovalListItem):
    transaction_status: str
    request_code: str | None = None
    submitted_by_name: str | None = None
    submitted_at: datetime | None = None
    price_basis: str | None = None
    lme_percentage: Decimal | None = None
    rate: Decimal | None = None
    invoice_status: str | None = None
    supplier_invoice_number: str | None = None
    port_of_loading: str | None = None
    hedge_date: date | None = None
    ai_summary: ApprovalSummaryRead
    rule_evaluations: list[RuleEvaluationRead] = Field(default_factory=list)
    documents: list[DocumentSummary] = Field(default_factory=list)
    open_exception_count: int = 0
    confirmation_threshold: Decimal
    can_decide: bool = False


class ApprovalDecisionRequest(BaseModel):
    decision: str
    reason: str | None = Field(default=None, max_length=2000)
    # The explicit second step for a high-value approval. It is a confirmation of intent, not an
    # identity claim: who approved is taken from the token regardless of what is sent here.
    confirm_above_threshold: bool = False

    @field_validator("decision")
    @classmethod
    def _actionable(cls, value: str) -> str:
        if value not in APPROVAL_DECISIONS or value == "pending":
            raise ValueError("Decision must be one of: approved, rejected, changes_requested.")
        return value


class BulkApprovalRequest(BaseModel):
    approval_ids: list[UUID] = Field(min_length=1, max_length=50)


class BulkApprovalOutcome(BaseModel):
    approval_id: UUID
    transaction_id: UUID | None = None
    batch_number: str | None = None
    approved: bool
    message: str


class BulkApprovalResult(BaseModel):
    approved: list[BulkApprovalOutcome] = Field(default_factory=list)
    rejected: list[BulkApprovalOutcome] = Field(default_factory=list)
    approved_count: int = 0
    skipped_count: int = 0


class ExceptionVocabulary(BaseModel):
    categories: list[ExceptionCategoryRead] = Field(default_factory=list)
    known_categories: list[str] = Field(default_factory=lambda: list(EXCEPTION_CATEGORIES))
