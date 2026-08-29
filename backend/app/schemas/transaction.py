"""Wire models for the transaction list, the purchase workspace and the actions on it."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import (
    BUSINESS_STREAMS,
    FIXATION_STATUSES,
    GENERATED_DOCUMENT_TYPES,
    INVOICE_STATUSES,
    PAYMENT_CONDITIONS,
    PRICE_BASES,
    TERRITORIES,
    TRANSACTION_STATUSES,
)
from app.schemas.intake import DocumentSummary, Page
from app.schemas.integration import IntegrationJobRead
from app.schemas.logistics import ContainerRead, LinkedShipmentRead


class CommodityCodeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    display_name: str
    is_active: bool


class PurchaseLegRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    supplier_name: str | None
    supplier_invoice_number: str | None
    contract_number: str | None
    invoice_status: str
    amount: Decimal | None
    rate: Decimal | None
    advance_payment_percent: Decimal | None
    hedge_date: date | None
    # The hedging day's range. `hedge_low_price` is discovery's "LLME" - the lowest LME - which is
    # the low end of the range rather than a separate figure.
    hedge_low_price: Decimal | None = None
    hedge_high_price: Decimal | None = None
    port_of_loading: str | None
    created_at: datetime
    updated_at: datetime


class SalesLegRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    customer_name: str
    territory: str
    sales_contract_no: str
    contracted_quantity_mt: Decimal | None
    sales_invoice_number: str | None
    bl_reference: str | None
    payment_condition: str
    customer_fixation_status: str
    fixation_rate: Decimal | None
    fixation_date: date | None
    port_of_discharge: str | None
    inland_container_depot: str | None
    extracted_commodity_value: str | None
    created_at: datetime
    updated_at: datetime


class FaLegRead(BaseModel):
    """The FA leg, and nothing more than AGFZE has actually agreed it holds.

    Three named columns and a structured bag. `extra_fields` is returned raw beside the rendered,
    schema-driven field list on the detail model, so a caller that wants the values without the
    presentation has them.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    counterparty_name: str | None
    fa_contract_reference: str | None
    document_type: str | None
    extra_fields: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class FaFieldSchemaRead(BaseModel):
    """One configured FA field, exactly as `document_type_schemas` describes it.

    The workspace's Additional FA Fields panel renders from this list and from nothing else. It
    is why that panel needs no code change when the business finally settles what FA's fields
    are: the schema grows, this list grows, and the form grows with it.
    """

    name: str
    label: str
    type: str
    required: bool
    section: str
    description: str


class LinkedPurchaseContext(BaseModel):
    """What the sales workspace shows beside the sell side, and what it deliberately does not.

    The shared commodity code and the buying desk's own identifying context. There is no
    purchase-side commodity *description* on this model, because comparing one against the
    sales-side wording is exactly the false positive Section 9.5 forbids: a China-bound shipment
    legitimately describes the same grade differently.
    """

    present: bool = False
    supplier_name: str | None = None
    contract_number: str | None = None
    supplier_invoice_number: str | None = None
    invoice_status: str | None = None
    port_of_loading: str | None = None
    amount: Decimal | None = None
    rate: Decimal | None = None
    # The one comparison that is made: the batch's resolved grade against the grade the sales
    # document reported. A disagreement here means the wrong batch was matched.
    commodity_code: str | None = None
    sales_document_commodity_value: str | None = None
    commodity_code_mismatch: bool = False
    message: str | None = None


class ContractCoverageRead(BaseModel):
    """The quantity meter: everything invoiced against one sales contract, against its total."""

    sales_contract_no: str
    contracted_quantity_mt: Decimal | None
    invoiced_quantity_mt: Decimal
    remaining_quantity_mt: Decimal | None
    shipment_count: int
    # `partial` (informational, expected), `complete` (clean), `exceeded` (a hard failure), or
    # `unknown` where no contracted total has been recorded to measure against.
    state: str
    ratio: float
    message: str


class GeneratedDraftRead(BaseModel):
    """One draft this platform produced. Never overwritten; a regeneration adds another."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    filename: str
    document_type: str | None
    byte_size: int
    created_at: datetime
    generated_by_name: str | None = None
    download_url: str | None = None
    # 1 for the first draft of its type, 2 for the next, and so on, oldest first.
    version: int = 1


class RuleEvaluationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    rule_id: str
    check_key: str | None
    passed: bool
    severity: str
    field_name: str | None
    expected_value: str | None
    actual_value: str | None
    message: str
    acknowledged: bool
    acknowledgement_reason: str | None
    acknowledged_at: datetime | None
    evaluated_at: datetime
    # Resolved from the rule catalog so the screen never restates a rule's wording.
    title: str | None = None
    statement: str | None = None
    acknowledged_by_name: str | None = None


class TransactionFieldRead(BaseModel):
    """One editable field, with the provenance the workspace colours it by."""

    name: str
    label: str
    owner: str
    type: str
    value: str | None
    section: str
    # What the machine originally scored for the extracted field behind this one, where there is
    # one. None means nothing was extracted for it and the value was entered by hand.
    source_confidence: float | None = None
    reason_required: bool = False
    is_overridden: bool = False
    original_ai_value: str | None = None
    original_confidence: float | None = None
    override_reason: str | None = None
    overridden_by_name: str | None = None
    overridden_at: datetime | None = None
    options: list[str] = Field(default_factory=list)
    editable: bool = True


class TransactionListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    transaction_code: str
    batch_number: str
    stream: str
    status: str
    commodity_code: str | None
    commodity_name: str | None = None
    quantity_mt: Decimal | None
    price_basis: str | None
    lme_percentage: Decimal | None
    currency: str
    created_at: datetime
    updated_at: datetime
    counterparty: str | None = None
    # The desk's own short form of that name, derived on read rather than stored - see
    # `services/counterparty_codes.py` for why it is not a column.
    counterparty_code: str | None = None
    contract_number: str | None = None
    invoice_status: str | None = None
    value: Decimal | None = None
    # Whole days since the transaction was opened.
    age_days: int = 0
    document_count: int = 0
    failing_rule_count: int = 0
    # Which legs this transaction actually carries. The list reads them to send a row to the desk
    # that owns it rather than assuming every transaction is a purchase.
    has_purchase_leg: bool = False
    has_sales_leg: bool = False
    has_fa_leg: bool = False
    # A joint B2B purchase, and the partner it is shared with. The tag only; no profit split,
    # shared expense or loss allocation is modelled anywhere yet - see PurchaseLeg.is_b2b.
    is_b2b: bool = False
    b2b_partner_name: str | None = None
    # Real from Step 6. Null still means something specific and true: no shipment record exists
    # for this transaction, which is not the same as a shipment that is on schedule.
    shipment_status: str | None = None
    # The worst staleness on any of this transaction's shipments, so the list can show at a
    # glance where nobody has looked - the same figure the shipment dashboard's indicator uses.
    shipment_stale: bool = False
    shipment_count: int = 0


class TransactionList(BaseModel):
    items: list[TransactionListItem]
    page: Page


class StatusEvent(BaseModel):
    occurred_at: datetime
    event_type: str
    summary: str
    actor_name: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MatchCandidateRead(BaseModel):
    transaction_id: UUID
    batch_number: str
    supplier_name: str | None = None
    contract_number: str | None = None
    score: float
    rationale: str


class MatchOutcomeRead(BaseModel):
    outcome: str
    message: str
    transaction_id: UUID | None = None
    batch_number: str | None = None
    score: float | None = None
    method: str | None = None
    candidates: list[MatchCandidateRead] = Field(default_factory=list)
    needs_user_decision: bool = False


class TransactionDetail(TransactionListItem):
    request_id: UUID
    request_code: str | None = None
    match_method: str | None
    match_score: Decimal | None
    match_rationale: str | None
    extracted_commodity_value: str | None
    commodity_needs_review: bool
    submitted_at: datetime | None
    submitted_by_name: str | None = None
    created_by_name: str | None = None
    closed_at: datetime | None
    purchase_leg: PurchaseLegRead | None = None
    # Populated from Step 5. The field was always declared here; nothing about the response shape
    # changed to carry it, which is the point.
    sales_leg: SalesLegRead | None = None
    # Populated from Step 6, and the third leg to arrive without the response shape changing to
    # carry it.
    fa_leg: FaLegRead | None = None
    # The configured FA schema's fields that have no named column, rendered ready for the
    # workspace's Additional FA Fields panel. Empty for every non-FA transaction.
    fa_extra_fields: list[TransactionFieldRead] = Field(default_factory=list)
    # The schema those fields came from, so the panel can render a control per field by its
    # configured type without knowing a single field name.
    fa_field_schema: list[FaFieldSchemaRead] = Field(default_factory=list)
    # Every shipment carrying this batch's cargo, and every container it was loaded into.
    # Named `linked_shipments` rather than `shipments` on purpose: the parent ORM object carries a
    # relationship of that name, and letting pydantic populate this field from it would silently
    # validate the wrong shape instead of the presented one the workspace actually needs.
    linked_shipments: list[LinkedShipmentRead] = Field(default_factory=list)
    containers: list[ContainerRead] = Field(default_factory=list)
    # The three integration jobs this transaction owes the outside world, from Step 7. A small,
    # additive field on an existing response rather than an endpoint of its own: a preparing desk
    # asking "did this reach SAP?" is asking about their transaction, not about a queue.
    integration_jobs: list[IntegrationJobRead] = Field(default_factory=list)
    # True where the caller may open the integration monitor and act on these jobs. Decided
    # server-side from their roles, exactly as every other capability flag here is.
    can_manage_integrations: bool = False
    linked_purchase: LinkedPurchaseContext | None = None
    contract_coverage: ContractCoverageRead | None = None
    generated_drafts: list[GeneratedDraftRead] = Field(default_factory=list)
    # True when BR-07's draft check passes: a draft or original B/L, or a recorded reference.
    can_generate_draft: bool = False
    draft_blocker: str | None = None
    documents: list[DocumentSummary] = Field(default_factory=list)
    rule_evaluations: list[RuleEvaluationRead] = Field(default_factory=list)
    fields: list[TransactionFieldRead] = Field(default_factory=list)
    history: list[StatusEvent] = Field(default_factory=list)
    confidence_threshold: float = 0.75
    can_edit: bool = False
    can_submit: bool = False
    blocking_rules: list[str] = Field(default_factory=list)


class PurchaseTransactionCreate(BaseModel):
    stream: str = "scrap"
    batch_number: str | None = Field(default=None, max_length=32)
    supplier_name: str = Field(min_length=2, max_length=255)
    contract_number: str | None = Field(default=None, max_length=64)
    supplier_invoice_number: str | None = Field(default=None, max_length=64)
    invoice_status: str = "provisional"
    commodity_code: str | None = Field(default=None, max_length=32)
    quantity_mt: Decimal | None = Field(default=None, gt=0)
    price_basis: str = "fixed"
    lme_percentage: Decimal | None = None
    currency: str = Field(default="USD", min_length=3, max_length=3)
    rate: Decimal | None = Field(default=None, ge=0)
    amount: Decimal | None = Field(default=None, ge=0)
    advance_payment_percent: Decimal | None = Field(default=None, ge=0, le=100)
    hedge_date: date | None = None
    hedge_low_price: Decimal | None = Field(default=None, ge=0)
    hedge_high_price: Decimal | None = Field(default=None, ge=0)
    port_of_loading: str | None = Field(default=None, max_length=128)

    @field_validator("stream")
    @classmethod
    def _known_stream(cls, value: str) -> str:
        if value not in BUSINESS_STREAMS:
            raise ValueError(f"Stream must be one of: {', '.join(BUSINESS_STREAMS)}")
        return value

    @field_validator("invoice_status")
    @classmethod
    def _known_invoice_status(cls, value: str) -> str:
        if value not in INVOICE_STATUSES:
            raise ValueError(f"Invoice status must be one of: {', '.join(INVOICE_STATUSES)}")
        return value

    @field_validator("price_basis")
    @classmethod
    def _known_price_basis(cls, value: str) -> str:
        if value not in PRICE_BASES:
            raise ValueError(f"Price basis must be one of: {', '.join(PRICE_BASES)}")
        return value

    @field_validator("currency")
    @classmethod
    def _upper_currency(cls, value: str) -> str:
        return value.strip().upper()


class TransactionFieldChange(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    value: str | None = None
    reason: str | None = None


class TransactionFieldUpdate(BaseModel):
    changes: list[TransactionFieldChange] = Field(min_length=1, max_length=50)


class ToleranceAcknowledgement(BaseModel):
    rule_id: str = Field(min_length=4, max_length=8)
    check_key: str | None = Field(default=None, max_length=48)
    reason: str = Field(min_length=10, max_length=1000)

    @field_validator("reason")
    @classmethod
    def _meaningful(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 10:
            raise ValueError(
                "Give a reason of at least 10 characters; this acknowledgement is on the record."
            )
        return cleaned


class SubmissionResult(BaseModel):
    transaction_id: UUID
    status: str
    submitted_at: datetime | None
    blocking_rules: list[str] = Field(default_factory=list)


class MatchResolution(BaseModel):
    decision: str
    transaction_id: UUID | None = None

    @field_validator("decision")
    @classmethod
    def _known_decision(cls, value: str) -> str:
        if value not in ("confirm", "reject"):
            raise ValueError("Decision must be either 'confirm' or 'reject'.")
        return value


class TransactionStatusVocabulary(BaseModel):
    statuses: list[str] = Field(default_factory=lambda: list(TRANSACTION_STATUSES))
    commodity_codes: list[CommodityCodeRead] = Field(default_factory=list)


class SalesLegCreate(BaseModel):
    """Attaching the sell side to a transaction that has already been identified.

    `acknowledge_no_purchase_leg` is the explicit, visible acknowledgement Section 9.4 requires.
    A sale is almost always of cargo AGFZE has already bought, so attaching a sales leg to a
    transaction with no purchase side is a real decision somebody has to make on the record - the
    server refuses it without this flag, and the audit entry carries it either way.
    """

    customer_name: str = Field(min_length=2, max_length=255)
    territory: str
    sales_contract_no: str = Field(min_length=1, max_length=64)
    payment_condition: str
    contracted_quantity_mt: Decimal | None = Field(default=None, gt=0)
    quantity_mt: Decimal | None = Field(default=None, gt=0)
    sales_invoice_number: str | None = Field(default=None, max_length=64)
    bl_reference: str | None = Field(default=None, max_length=64)
    port_of_discharge: str | None = Field(default=None, max_length=128)
    inland_container_depot: str | None = Field(default=None, max_length=128)
    customer_fixation_status: str = "unfixed"
    fixation_rate: Decimal | None = Field(default=None, ge=0)
    fixation_date: date | None = None
    # The sales-triggering document this leg was raised off, where there was one.
    document_id: UUID | None = None
    acknowledge_no_purchase_leg: bool = False
    acknowledgement_note: str | None = Field(default=None, max_length=1000)

    @field_validator("territory")
    @classmethod
    def _known_territory(cls, value: str) -> str:
        if value not in TERRITORIES:
            raise ValueError(f"Territory must be one of: {', '.join(TERRITORIES)}")
        return value

    @field_validator("payment_condition")
    @classmethod
    def _known_payment_condition(cls, value: str) -> str:
        if value not in PAYMENT_CONDITIONS:
            raise ValueError(f"Payment condition must be one of: {', '.join(PAYMENT_CONDITIONS)}")
        return value

    @field_validator("customer_fixation_status")
    @classmethod
    def _known_fixation_status(cls, value: str) -> str:
        if value not in FIXATION_STATUSES:
            raise ValueError(f"Fixation status must be one of: {', '.join(FIXATION_STATUSES)}")
        return value


class SalesAttachmentResult(BaseModel):
    transaction: TransactionDetail
    attachment: str
    commodity_code_mismatch: bool = False
    commodity_message: str | None = None


class SalesMatchCandidate(MatchCandidateRead):
    pass


class SalesMatchRead(BaseModel):
    """What the platform believes a sales document belongs to, before anything is created."""

    outcome: str
    message: str
    transaction_id: UUID | None = None
    batch_number: str | None = None
    score: float | None = None
    method: str | None = None
    candidates: list[MatchCandidateRead] = Field(default_factory=list)
    needs_user_decision: bool = False


class DraftGenerationRequest(BaseModel):
    document_type: str

    @field_validator("document_type")
    @classmethod
    def _generatable(cls, value: str) -> str:
        if value not in GENERATED_DOCUMENT_TYPES:
            raise ValueError("This platform generates only: " + ", ".join(GENERATED_DOCUMENT_TYPES))
        return value


class DraftGenerationAccepted(BaseModel):
    transaction_id: UUID
    document_type: str
    job_id: UUID


class FaTransactionCreate(BaseModel):
    """Registering an FA transaction by hand.

    Follows the purchase side's standalone-creation pattern rather than the sales side's
    attach-to-an-existing-batch one, and the difference is not an oversight. A sale is the sell
    side of cargo AGFZE already bought, so it attaches to the transaction that cargo already has.
    FA is a structurally separate business line: an FA transaction is not the other side of a
    scrap batch and has nothing to attach to.

    The field list is deliberately the minimal one. Everything beyond it belongs in
    `extra_fields`, keyed by the names the configured schema carries, and is validated against
    that schema before a single value is persisted.
    """

    counterparty_name: str = Field(min_length=2, max_length=255)
    fa_contract_reference: str | None = Field(default=None, max_length=64)
    document_type: str | None = Field(default=None, max_length=64)
    batch_number: str | None = Field(default=None, max_length=32)
    commodity_code: str | None = Field(default=None, max_length=32)
    quantity_mt: Decimal | None = Field(default=None, gt=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    extra_fields: dict[str, str] = Field(default_factory=dict)

    @field_validator("currency")
    @classmethod
    def _upper_currency(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("extra_fields")
    @classmethod
    def _bounded_extras(cls, value: dict[str, str]) -> dict[str, str]:
        # A first, cheap bound. The real gate is the configured schema, applied server-side in
        # the endpoint: a key the schema does not carry is refused rather than stored.
        if len(value) > 50:
            raise ValueError("At most 50 additional FA fields may be supplied at once.")
        return {key: str(item) for key, item in value.items()}


class GraphNodeRead(BaseModel):
    """One node on the trace. Identity and label only - the detail is read from PostgreSQL."""

    id: str
    label: str
    title: str


class GraphEdgeRead(BaseModel):
    source: str
    target: str
    type: str


class TransactionGraph(BaseModel):
    """What one transaction is connected to, as far as the projection knows.

    `available` is False when no graph store is configured or the store could not be reached, and
    the screen is expected to say so rather than render an empty diagram as though the transaction
    were connected to nothing. Those are different claims.
    """

    transaction_id: UUID
    batch_number: str
    available: bool
    nodes: list[GraphNodeRead] = Field(default_factory=list)
    edges: list[GraphEdgeRead] = Field(default_factory=list)
