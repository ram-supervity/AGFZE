"""The editable surface of a transaction, and what correcting it costs.

Every field a person can change here declares which extracted field it came from. That is what
lets the workspace colour it by the confidence the machine originally reported, and what makes
the reason gate on a correction the same gate the document review screen applies - decided by
what the model first scored, not by the value currently on screen.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AuthorizationError, BadRequestError, ConflictError
from app.core.roles import PlatformRole
from app.db.base import utcnow
from app.models.enums import (
    FIXATION_STATUSES,
    INVOICE_STATUSES,
    PAYMENT_CONDITIONS,
    PRICE_BASES,
    TERRITORIES,
    DocumentType,
    FixationStatus,
    TransactionStatus,
)
from app.models.identity import User
from app.models.intake import Document
from app.models.transactions import TradeTransaction
from app.services import extraction_service, transaction_service
from app.services.audit_service import ActorType, record_audit_event
from app.services.rules import engine as rule_engine
from app.services.rules.engine import extracted_field_confidence

TRANSACTION = "transaction"
PURCHASE_LEG = "purchase_leg"
SALES_LEG = "sales_leg"
FA_LEG = "fa_leg"
# The FA leg's configured extras, which have no column of their own and live in
# `fa_legs.extra_fields`. A separate owner rather than a flag on `FA_LEG`, because where a value
# is written is genuinely different and the writer has to know.
FA_EXTRA = "fa_extra"


@dataclass(frozen=True)
class EditableField:
    name: str
    label: str
    owner: str
    attribute: str
    type: str
    section: str
    # The extracted field this value was read from, where it was read from one at all.
    source_field: str | None = None
    options: tuple[str, ...] = ()


PURCHASE_FIELDS: tuple[EditableField, ...] = (
    EditableField(
        "supplier_name",
        "Supplier",
        PURCHASE_LEG,
        "supplier_name",
        "string",
        "Counterparty",
        source_field="supplier_name",
    ),
    EditableField(
        "contract_number",
        "Contract number",
        PURCHASE_LEG,
        "contract_number",
        "string",
        "Counterparty",
        source_field="contract_reference",
    ),
    EditableField(
        "supplier_invoice_number",
        "Supplier invoice number",
        PURCHASE_LEG,
        "supplier_invoice_number",
        "string",
        "Counterparty",
        source_field="invoice_number",
    ),
    EditableField(
        "invoice_status",
        "Invoice status",
        PURCHASE_LEG,
        "invoice_status",
        "enum",
        "Counterparty",
        source_field="invoice_status",
        options=tuple(INVOICE_STATUSES),
    ),
    EditableField(
        "commodity_code",
        "Commodity code",
        TRANSACTION,
        "commodity_code",
        "commodity",
        "Goods",
        source_field="commodity_code",
    ),
    EditableField(
        "quantity_mt",
        "Quantity (MT)",
        TRANSACTION,
        "quantity_mt",
        "number",
        "Goods",
        source_field="quantity",
    ),
    EditableField(
        "price_basis",
        "Price basis",
        TRANSACTION,
        "price_basis",
        "enum",
        "Commercials",
        options=tuple(PRICE_BASES),
    ),
    EditableField(
        "lme_percentage",
        "LME percentage",
        TRANSACTION,
        "lme_percentage",
        "number",
        "Commercials",
    ),
    EditableField(
        "rate",
        "Rate",
        PURCHASE_LEG,
        "rate",
        "number",
        "Commercials",
        source_field="rate",
    ),
    EditableField(
        "amount",
        "Invoice amount",
        PURCHASE_LEG,
        "amount",
        "number",
        "Commercials",
        source_field="amount",
    ),
    EditableField(
        "currency",
        "Currency",
        TRANSACTION,
        "currency",
        "string",
        "Commercials",
        source_field="currency",
    ),
    EditableField(
        "advance_payment_percent",
        "Advance payment %",
        PURCHASE_LEG,
        "advance_payment_percent",
        "number",
        "Commercials",
    ),
    EditableField(
        "hedge_date",
        "Hedge / fixation date",
        PURCHASE_LEG,
        "hedge_date",
        "date",
        "Commercials",
    ),
    # The hedging day's range. Corrected in by hand like the hedge date beside them: no document
    # this platform receives states where the exchange went that day, so there is nothing to
    # extract them from - the desk reads them off the exchange and records them.
    EditableField(
        "hedge_low_price",
        "Hedge day low (LLME)",
        PURCHASE_LEG,
        "hedge_low_price",
        "number",
        "Commercials",
    ),
    EditableField(
        "hedge_high_price",
        "Hedge day high",
        PURCHASE_LEG,
        "hedge_high_price",
        "number",
        "Commercials",
    ),
    EditableField(
        "port_of_loading",
        "Port of loading",
        PURCHASE_LEG,
        "port_of_loading",
        "string",
        "Shipment",
        source_field="port_of_loading",
    ),
    # The B2B tag, and the partner it names. Editable here rather than set at extraction because
    # nothing in a supplier's invoice says whether AGFZE is doing the deal jointly - that is
    # commercial context the desk holds and the document does not, so it is corrected in like any
    # other field, with the same reason gate and the same provenance record.
    #
    # No profit split, shared expense or loss allocation is editable, because none of them is
    # modelled. See PurchaseLeg.is_b2b for why, and docs/KNOWN-GAPS.md for what AGFZE has to
    # confirm before they could be.
    EditableField(
        "is_b2b",
        "B2B deal",
        PURCHASE_LEG,
        "is_b2b",
        "boolean",
        "Commercials",
    ),
    EditableField(
        "b2b_partner_name",
        "B2B partner",
        PURCHASE_LEG,
        "b2b_partner_name",
        "string",
        "Commercials",
    ),
)

# The sell side's editable surface, added in Step 5. Everything about how a correction behaves -
# the reason gate, the provenance record, the synchronous re-validation - is inherited from the
# machinery above rather than reimplemented, which is why recording a price fixation is a field
# correction through the existing endpoint and not a second endpoint that resembles one.
SALES_FIELDS: tuple[EditableField, ...] = (
    EditableField(
        "customer_name",
        "Customer",
        SALES_LEG,
        "customer_name",
        "string",
        "Customer",
        source_field="consignee",
    ),
    EditableField(
        "territory",
        "Destination territory",
        SALES_LEG,
        "territory",
        "enum",
        "Customer",
        options=tuple(TERRITORIES),
    ),
    EditableField(
        "sales_contract_no",
        "Sales contract number",
        SALES_LEG,
        "sales_contract_no",
        "string",
        "Customer",
        source_field="contract_reference",
    ),
    EditableField(
        "contracted_quantity_mt",
        "Contracted quantity (MT, whole contract)",
        SALES_LEG,
        "contracted_quantity_mt",
        "number",
        "Customer",
    ),
    EditableField(
        "sales_invoice_number",
        "Sales invoice number",
        SALES_LEG,
        "sales_invoice_number",
        "string",
        "Customer",
    ),
    EditableField(
        "payment_condition",
        "Payment condition",
        SALES_LEG,
        "payment_condition",
        "enum",
        "Sales commercials",
        options=tuple(PAYMENT_CONDITIONS),
    ),
    EditableField(
        "customer_fixation_status",
        "Customer price fixation",
        SALES_LEG,
        "customer_fixation_status",
        "enum",
        "Sales commercials",
        options=tuple(FIXATION_STATUSES),
    ),
    EditableField(
        "fixation_rate",
        "Fixation rate",
        SALES_LEG,
        "fixation_rate",
        "number",
        "Sales commercials",
    ),
    EditableField(
        "fixation_date",
        "Fixation date",
        SALES_LEG,
        "fixation_date",
        "date",
        "Sales commercials",
    ),
    EditableField(
        "bl_reference",
        "Bill of lading reference",
        SALES_LEG,
        "bl_reference",
        "string",
        "Sales shipment",
        source_field="bl_number",
    ),
    EditableField(
        "port_of_discharge",
        "Port of discharge",
        SALES_LEG,
        "port_of_discharge",
        "string",
        "Sales shipment",
        source_field="port_of_discharge",
    ),
    EditableField(
        "inland_container_depot",
        "Inland container depot",
        SALES_LEG,
        "inland_container_depot",
        "string",
        "Sales shipment",
    ),
)

# The FA leg's three named columns. Deliberately three: AGFZE's material names a counterparty, a
# reference and a document type, and nothing else about FA has been agreed. Everything else the
# configured schema carries is an extra, resolved from that schema at request time rather than
# listed here - which is why this tuple does not grow when the business adds a field.
FA_FIELDS: tuple[EditableField, ...] = (
    EditableField(
        "counterparty_name",
        "Counterparty",
        FA_LEG,
        "counterparty_name",
        "string",
        "Counterparty",
        source_field="counterparty",
    ),
    EditableField(
        "fa_contract_reference",
        "FA contract / transaction reference",
        FA_LEG,
        "fa_contract_reference",
        "string",
        "Counterparty",
        source_field="transaction_reference",
    ),
    EditableField(
        "fa_document_type",
        "FA document type",
        FA_LEG,
        "document_type",
        "string",
        "Counterparty",
        source_field="document_type",
    ),
)

ALL_FIELDS: tuple[EditableField, ...] = PURCHASE_FIELDS + SALES_FIELDS + FA_FIELDS

# The section the schema-driven FA extras are grouped under, and the heading the workspace's
# "Additional FA Fields" panel picks them out by.
FA_EXTRA_SECTION = "Additional FA fields"

# How a configured schema field's type maps onto an editable field's input type. Anything the
# schema calls something this map does not know renders as a plain string, which is the safe
# reading of a type nobody has taught the platform yet.
SCHEMA_INPUT_TYPES: dict[str, str] = {
    "string": "string",
    "number": "number",
    "currency": "number",
    "quantity": "number",
    "date": "date",
}

FIELDS_BY_NAME: dict[str, EditableField] = {item.name: item for item in ALL_FIELDS}

# Which leg a role may correct. A purchase user does not restate the customer's terms and a sales
# user does not restate the supplier's; both share the fields that belong to the batch itself.
# Admin carries every owner. This narrows what `apply_corrections` will write and is enforced
# server-side, never by whether a control was rendered.
OWNERS_BY_ROLE: dict[str, frozenset[str]] = {
    PlatformRole.PURCHASE_USER.value: frozenset({TRANSACTION, PURCHASE_LEG}),
    PlatformRole.SALES_USER.value: frozenset({TRANSACTION, SALES_LEG}),
    PlatformRole.FA_USER.value: frozenset({TRANSACTION, FA_LEG, FA_EXTRA}),
    PlatformRole.ADMIN.value: frozenset({TRANSACTION, PURCHASE_LEG, SALES_LEG, FA_LEG, FA_EXTRA}),
}


def owners_for(roles: object) -> frozenset[str]:
    granted: set[str] = set()
    for role in roles or ():
        granted |= OWNERS_BY_ROLE.get(role, frozenset())
    return frozenset(granted)


# Which leg each owner needs the transaction to carry before its fields mean anything.
LEG_FOR_OWNER: dict[str, str] = {
    PURCHASE_LEG: "purchase_leg",
    SALES_LEG: "sales_leg",
    FA_LEG: "fa_leg",
    FA_EXTRA: "fa_leg",
}


def fields_for(transaction: TradeTransaction) -> tuple[EditableField, ...]:
    """The named fields this transaction carries: a leg it does not have contributes none."""
    return tuple(
        item
        for item in ALL_FIELDS
        if item.owner not in LEG_FOR_OWNER
        or getattr(transaction, LEG_FOR_OWNER[item.owner], None) is not None
    )


def _schema_extra_field(definition: object) -> EditableField:
    """One configured FA schema field, as an editable field bound to `extra_fields`."""
    return EditableField(
        name=definition.name,
        label=definition.label,
        owner=FA_EXTRA,
        attribute=definition.name,
        type=SCHEMA_INPUT_TYPES.get(definition.type, "string"),
        section=FA_EXTRA_SECTION,
        source_field=definition.name,
    )


async def fa_extra_fields(
    session: AsyncSession, transaction: TradeTransaction
) -> tuple[EditableField, ...]:
    """The FA fields configuration has added that have no column of their own.

    Resolved from `document_type_schemas` on every request, which is what makes the flexible-field
    promise real rather than decorative: a field added to the FA schema becomes editable, audited
    and rendered without a line changing here, in the API, or in the workspace component. It is
    also what makes writing to `extra_fields` safe - a name that is not in the configured schema
    is not an editable field at all, so arbitrary JSON has no way in.
    """
    if transaction.fa_leg is None:
        return ()
    try:
        schema = await extraction_service.select_schema(
            session, document_type=DocumentType.FA_DOCUMENT.value, territory=None
        )
    except extraction_service.SchemaNotConfiguredError:
        # No FA schema configured is a real state, not an error: the leg keeps whatever it has and
        # nothing extra is offered for editing.
        return ()
    mapped = set(transaction_service.FA_LEG_COLUMNS) | set(
        transaction_service.FA_TRANSACTION_COLUMNS
    )
    return tuple(
        _schema_extra_field(definition)
        for definition in schema.fields
        if definition.name not in mapped
    )


async def editable_fields(
    session: AsyncSession, transaction: TradeTransaction
) -> tuple[EditableField, ...]:
    """Every field a person may correct on this transaction, named columns and FA extras alike."""
    return fields_for(transaction) + await fa_extra_fields(session, transaction)


def _target(transaction: TradeTransaction, field: EditableField) -> object | None:
    if field.owner == TRANSACTION:
        return transaction
    if field.owner == SALES_LEG:
        return transaction.sales_leg
    if field.owner in (FA_LEG, FA_EXTRA):
        return transaction.fa_leg
    return transaction.purchase_leg


def read_value(transaction: TradeTransaction, field: EditableField) -> str | None:
    holder = _target(transaction, field)
    if holder is None:
        return None
    if field.owner == FA_EXTRA:
        raw = (getattr(holder, "extra_fields", None) or {}).get(field.attribute)
        return None if raw is None else str(raw)
    value = getattr(holder, field.attribute, None)
    if value is None:
        return None
    if isinstance(value, bool):
        # Before the Decimal and date branches, and before `str(value)`, because bool is an int
        # subclass in Python and would otherwise render as "True" rather than as the "yes"/"no"
        # the boolean coercion above reads back.
        return "yes" if value else "no"
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, date | datetime):
        return value.isoformat()[:10]
    return str(value)


def coerce(field: EditableField, raw: str | None) -> object | None:
    cleaned = (raw or "").strip()
    if not cleaned:
        return None
    if field.type == "number":
        try:
            return Decimal(cleaned.replace(",", ""))
        except InvalidOperation as exc:
            raise BadRequestError(f"{field.label} must be a number.", code="invalid_value") from exc
    if field.type == "date":
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                return datetime.strptime(cleaned, fmt).date()
            except ValueError:
                continue
        raise BadRequestError(
            f"{field.label} must be a date, for example 2026-08-23.", code="invalid_value"
        )
    if field.type == "boolean":
        # Spelled out rather than truthy. "0" and "no" are both meant as false by whoever typed
        # them, and a coercion that treated any non-empty string as true would turn a correction
        # into its opposite - which on a flag that changes how a deal is read is not a small bug.
        lowered = cleaned.lower()
        if lowered in ("true", "yes", "y", "1"):
            return True
        if lowered in ("false", "no", "n", "0"):
            return False
        raise BadRequestError(f"{field.label} must be yes or no.", code="invalid_value")
    if field.type == "enum" and cleaned not in field.options:
        raise BadRequestError(
            f"{field.label} must be one of: {', '.join(field.options)}.", code="invalid_value"
        )
    return cleaned


async def provenance(
    session: AsyncSession,
    transaction: TradeTransaction,
    documents: list[Document],
    *,
    fields: tuple[EditableField, ...] | None = None,
) -> dict[str, float | None]:
    """The original machine confidence behind every field that came from an extraction.

    Takes the field set rather than always walking `ALL_FIELDS`, so the FA extras resolved from
    configuration are coloured by the same confidence, and gated by the same reason rule, as a
    field somebody wrote a column for.
    """
    document_ids = [document.id for document in documents]
    scores: dict[str, float | None] = {}
    for field in fields if fields is not None else ALL_FIELDS:
        if field.source_field is None:
            scores[field.name] = None
            continue
        scores[field.name] = await extracted_field_confidence(
            session, document_ids, field.source_field
        )
    return scores


def reason_required(confidence: float | None, *, was_extracted: bool) -> bool:
    """A value the machine was unsure of needs a stated reason before it is changed.

    A field that never came from an extraction at all - an advance percentage somebody types in -
    is not gated: there is no machine reading to disagree with.
    """
    if not was_extracted:
        return False
    return confidence is None or confidence < settings.CONFIDENCE_THRESHOLD_DEFAULT


def apply_change(
    transaction: TradeTransaction,
    field: EditableField,
    raw: str | None,
    *,
    reason: str | None,
    confidence: float | None,
    user: User,
) -> dict[str, object] | None:
    """Write one corrected value and record what it replaced. Returns None when nothing moved."""
    holder = _target(transaction, field)
    if holder is None:
        raise BadRequestError(
            f"{field.label} belongs to a leg this transaction does not have.",
            code="leg_missing",
        )

    previous = read_value(transaction, field)
    value = coerce(field, raw)
    _write_value(holder, field, value)
    rendered = read_value(transaction, field)
    if rendered == previous:
        return None

    key = f"{field.owner}.{field.name}"
    history = dict(transaction.field_overrides or {})
    entry = dict(history.get(key) or {})
    # Written once, on the first correction, and never rewritten - the same guarantee
    # `extracted_fields.original_ai_value` gives at the document layer.
    if "original_ai_value" not in entry:
        entry["original_ai_value"] = previous
        entry["original_confidence"] = confidence
    entry.update(
        {
            "previous_value": previous,
            "value": rendered,
            "reason": (reason or "").strip() or None,
            "overridden_by_id": str(user.id),
            "overridden_by_name": user.display_name,
            "overridden_at": utcnow().isoformat(),
        }
    )
    history[key] = entry
    transaction.field_overrides = history

    return {
        "field": field.name,
        "owner": field.owner,
        "previous_value": previous,
        "new_value": rendered,
        "original_ai_value": entry.get("original_ai_value"),
        "original_confidence": entry.get("original_confidence"),
        "reason": entry.get("reason"),
    }


def _write_value(holder: object, field: EditableField, value: object | None) -> None:
    """Put one coerced value where its owner keeps it.

    Every owner but `FA_EXTRA` is a column. `FA_EXTRA` is a key in a JSON column, rebound rather
    than mutated in place so SQLAlchemy sees the change, and holding only strings so what comes
    back out is what a schema-driven form put in.
    """
    if field.owner != FA_EXTRA:
        setattr(holder, field.attribute, value)
        return
    extras = dict(getattr(holder, "extra_fields", None) or {})
    if value is None:
        extras.pop(field.attribute, None)
    else:
        extras[field.attribute] = str(value)
    holder.extra_fields = extras
    holder.updated_at = utcnow()


def _settle_fixation(transaction: TradeTransaction, recorded: list[dict[str, object]]) -> None:
    """Keep the fixation status honest against the rate and date recorded beside it."""
    leg = transaction.sales_leg
    if leg is None:
        return
    touched = {item["field"] for item in recorded}
    if not touched & {"fixation_rate", "fixation_date", "customer_fixation_status"}:
        return
    if leg.fixation_rate is not None and leg.fixation_date is not None:
        leg.customer_fixation_status = FixationStatus.FIXED.value
    elif "customer_fixation_status" not in touched:
        leg.customer_fixation_status = FixationStatus.UNFIXED.value
    leg.updated_at = utcnow()


def fixation_recorded(recorded: list[dict[str, object]]) -> bool:
    """Whether this set of corrections is a price fixation, for the audit entry behind it."""
    return bool(
        {item["field"] for item in recorded}
        & {"fixation_rate", "fixation_date", "customer_fixation_status"}
    )


def fa_extra_recorded(recorded: list[dict[str, object]]) -> bool:
    """Whether this set of corrections touched the FA leg's configured extra fields."""
    return any(item["owner"] == FA_EXTRA for item in recorded)


def override_entry(transaction: TradeTransaction, field: EditableField) -> dict[str, object]:
    return dict((transaction.field_overrides or {}).get(f"{field.owner}.{field.name}") or {})


def parse_uuid(value: str | None) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


# The one state in which a transaction's figures are frozen: an approver is being asked to sign
# what is on the screen, and it cannot move underneath them. `Approved` is frozen for the same
# reason in reverse - it has already been signed.
LOCKED_STATUSES = frozenset(
    {TransactionStatus.APPROVAL_PENDING.value, TransactionStatus.APPROVED.value}
)

MIN_CORRECTION_REASON = 5


async def apply_corrections(
    session: AsyncSession,
    transaction: TradeTransaction,
    changes: list[tuple[str, str | None, str | None]],
    *,
    user: User,
    audit_event_type: str,
    audit_context: dict[str, object] | None = None,
    allowed_owners: frozenset[str] | None = None,
) -> list[dict[str, object]]:
    """Correct fields, audit what moved, and re-run validation. The single path for both callers.

    Both `PATCH /transactions/{id}/fields` and the exception queue's inline correction come
    through here, so a value corrected while resolving an exception is subject to exactly the same
    reason gate, the same provenance record and the same synchronous re-validation as one
    corrected in the workspace. There is no second correction mechanism to drift from this one.

    `allowed_owners` narrows which legs the caller may write. The transaction workspace passes
    what the caller's roles actually grant, so a sales user cannot restate the supplier's terms
    through the same endpoint that lets them record a fixation. Left unset - as the exception
    queue's inline correction leaves it - nothing is narrowed, and the behaviour is exactly what
    it was before the sales leg existed.
    """
    if transaction.status in LOCKED_STATUSES:
        raise ConflictError(
            "This transaction is awaiting approval or already approved, so its fields can no "
            "longer be corrected."
        )

    documents = list(
        (
            await session.scalars(select(Document).where(Document.transaction_id == transaction.id))
        ).all()
    )
    available = await editable_fields(session, transaction)
    by_name = {item.name: item for item in available}
    confidences = await provenance(session, transaction, documents, fields=available)
    recorded: list[dict[str, object]] = []

    for name, value, reason in changes:
        # Resolved against what this transaction actually offers, never against a global list.
        # For an FA extra that is the configured schema, which is exactly the validation
        # discipline Section 13 asks for: a name the schema does not carry is refused here rather
        # than written into the JSON column unchecked.
        field = by_name.get(name)
        if field is None:
            raise ConflictError(f"'{name}' is not an editable field of this transaction.")
        if allowed_owners is not None and field.owner not in allowed_owners:
            raise AuthorizationError(
                f"{field.label} belongs to the "
                f"{field.owner.replace('_', ' ')}, which your role does not correct."
            )

        confidence = confidences.get(field.name)
        if (
            reason_required(confidence, was_extracted=field.source_field is not None)
            and len((reason or "").strip()) < MIN_CORRECTION_REASON
        ):
            raise ConflictError(
                f"{field.label} was extracted below the confidence threshold, so a reason of at "
                f"least {MIN_CORRECTION_REASON} characters is required for the correction."
            )

        change = apply_change(
            transaction, field, value, reason=reason, confidence=confidence, user=user
        )
        if change is not None:
            recorded.append(change)

    if recorded:
        # A fixation is not just three changed fields, so the one field that says the customer has
        # fixed carries the whole set with it: recording a rate or a date without moving the
        # status would leave a "fixed" price the platform still reports as unfixed.
        _settle_fixation(transaction, recorded)
        # Commodity is reference data, so a corrected grade is re-resolved rather than trusted.
        # `apply_change` has already put what the person typed into `commodity_code`, which is a
        # foreign key onto the seeded grades, and the resolution below issues a query. Autoflush
        # is held off across it so an unrecognised grade reaches `commodity_needs_review` - the
        # documented outcome - instead of being flushed against the constraint first.
        if any(item["field"] == "commodity_code" for item in recorded):
            stated = transaction.commodity_code
            with session.no_autoflush:
                resolved, needs_review = await transaction_service.resolve_commodity(
                    session, stated
                )
            transaction.extracted_commodity_value = stated
            transaction.commodity_code = resolved
            transaction.commodity_needs_review = needs_review
        transaction.updated_at = utcnow()
        await record_audit_event(
            session,
            event_type=audit_event_type,
            entity_type="trade_transaction",
            entity_id=transaction.id,
            actor_id=user.id,
            actor_type=ActorType.USER,
            metadata={
                "batch_number": transaction.batch_number,
                "changes": recorded,
                **(audit_context or {}),
            },
        )

    # Synchronous, always: whoever corrected a figure has to see what it did to the checks before
    # they decide anything else, and a queued job would hand them a stale panel.
    await rule_engine.run_validation(session, transaction)
    return recorded
