"""Transaction creation, batch numbering, commodity resolution and the list query."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from rapidfuzz import fuzz
from sqlalchemy import Select, exc, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload
from sqlalchemy.orm.attributes import set_committed_value

from app.core.config import settings
from app.core.errors import ConflictError, NotFoundError
from app.core.roles import PlatformRole
from app.db.base import utcnow
from app.models.enums import (
    BusinessStream,
    InvoiceStatus,
    MatchMethod,
    PriceBasis,
    RequestCategory,
    RequestSource,
    TransactionStatus,
)
from app.models.identity import User
from app.models.intake import Document
from app.models.transactions import (
    BatchSequence,
    CommodityCode,
    FaLeg,
    PurchaseLeg,
    TradeTransaction,
)
from app.services import request_service
from app.services.rules.defaults import COMMODITY_ALIASES
from app.services.rules.values import to_decimal, to_percentage

# The financial year runs April to March, so a batch raised in August 2026 belongs to FY 2026-27
# and carries the suffix 26. Stated assumption, recorded here rather than left implicit.
FINANCIAL_YEAR_START_MONTH = 4

# Where a batch sequence starts when a prefix is seen for the first time.
SEQUENCE_START = 1
# How many times the allocator will step past a number some other record already holds.
MAX_ALLOCATION_ATTEMPTS = 50

# A commodity name has to look like the seeded grade to be accepted as it. Below this the value
# is kept verbatim and the transaction is flagged, never quietly coerced to the nearest grade.
COMMODITY_NAME_MATCH_FLOOR = 90.0


class AuditEvent:
    TRANSACTION_CREATED = "transaction.created"
    FA_LEG_ATTACHED = "transaction.fa_leg_attached"
    TRANSACTION_MATCHED = "transaction.matched"
    TRANSACTION_SUPERSEDED = "transaction.leg_superseded"
    TRANSACTION_FIELD_CORRECTED = "transaction.field_corrected"
    TRANSACTION_TOLERANCE_ACKNOWLEDGED = "transaction.tolerance_acknowledged"
    TRANSACTION_SUBMITTED = "transaction.submitted"
    TRANSACTION_SUBMISSION_BLOCKED = "transaction.submission_blocked"
    TRANSACTION_VALIDATED = "transaction.validated"
    TRANSACTION_DOCUMENT_LINKED = "transaction.document_linked"
    TRANSACTION_COMMODITY_UNRESOLVED = "transaction.commodity_unresolved"
    CONTAINER_RECORDED = "transaction.container_recorded"


def financial_year_suffix(moment: datetime | None = None) -> str:
    moment = moment or datetime.now(timezone.utc)
    year = moment.year if moment.month >= FINANCIAL_YEAR_START_MONTH else moment.year - 1
    return f"{year % 100:02d}"


def batch_prefix(moment: datetime | None = None) -> str:
    """`I` + the financial year's last two digits + the two-digit company code.

    A single default company code, deliberately: routing between SAP company codes (2000 for the
    UAE entity, 3010 for Singapore) only becomes a real decision once there is an SAP posting to
    route, which is Step 7's problem and not this step's.
    """
    company = f"{settings.BATCH_COMPANY_CODE:>2.2}".replace(" ", "0")
    return f"I{financial_year_suffix(moment)}{company}"


async def _increment_sequence(session: AsyncSession, prefix: str) -> int:
    """Take the next value off the counter in one atomic statement.

    A single `UPDATE ... RETURNING` rather than a read followed by a write: two callers that read
    the same value would both propose the same batch, and no amount of care afterwards recovers
    from that. The database serialises the increment, and every caller walks away with a number
    nobody else was given.
    """
    bump = (
        update(BatchSequence)
        .where(BatchSequence.prefix == prefix)
        .values(next_value=BatchSequence.next_value + 1, updated_at=utcnow())
        .returning(BatchSequence.next_value)
        .execution_options(synchronize_session=False)
    )

    allocated = (await session.execute(bump)).scalar_one_or_none()
    if allocated is not None:
        return int(allocated) - 1

    # First use of this prefix. The insert runs inside a savepoint so losing the race to create
    # the counter row costs the savepoint and not the caller's whole transaction.
    try:
        async with session.begin_nested():
            session.add(BatchSequence(prefix=prefix, next_value=SEQUENCE_START + 1))
            await session.flush()
        return SEQUENCE_START
    except exc.IntegrityError:
        allocated = (await session.execute(bump)).scalar_one_or_none()
        if allocated is None:
            raise ConflictError(
                "The batch sequence could not be allocated; please retry."
            ) from None
        return int(allocated) - 1


async def next_batch_number(session: AsyncSession, *, moment: datetime | None = None) -> str:
    """Allocate the next unused batch number for the current financial year and company code.

    Never a read-max-then-add-one. The counter is incremented atomically, and the allocated
    number is then checked against the transactions that already exist, because a supplier is
    free to quote a batch reference of their own that happens to collide with one the sequence
    has not reached yet. The unique index on `batch_number` is the backstop behind both.
    """
    prefix = batch_prefix(moment)
    for _ in range(MAX_ALLOCATION_ATTEMPTS):
        candidate = f"{prefix}-{await _increment_sequence(session, prefix)}"
        taken = await session.scalar(
            select(TradeTransaction.id).where(TradeTransaction.batch_number == candidate)
        )
        if taken is None:
            return candidate
    raise ConflictError("A free batch number could not be allocated; please retry.")


async def resolve_commodity(session: AsyncSession, raw: str | None) -> tuple[str | None, bool]:
    """Map what the document said onto a seeded grade.

    Returns the resolved code and whether the value needs a person to look at it. An unrecognised
    grade is never silently dropped and never silently coerced: it is kept verbatim on the
    transaction and flagged, because a wrong grade misprices the whole deal.
    """
    value = (raw or "").strip()
    if not value:
        return None, False

    active = select(CommodityCode).where(CommodityCode.is_active.is_(True))
    codes = list((await session.scalars(active)).all())
    upper = value.upper()

    for row in codes:
        if row.code.upper() == upper:
            return row.code, False

    aliased = COMMODITY_ALIASES.get(upper)
    if aliased and any(row.code == aliased for row in codes):
        return aliased, False

    # A descriptive grade ("Copper Millberry 99.9%") still resolves when it clearly names one of
    # the seeded metals; anything weaker than that is left for a person.
    scored = [
        (fuzz.partial_ratio(row.display_name.lower(), value.lower()), row.code) for row in codes
    ]
    best_score, best_code = max(scored, default=(0.0, None))
    if best_code is not None and best_score >= COMMODITY_NAME_MATCH_FLOOR:
        return best_code, False

    return None, True


def infer_invoice_status(values: dict[str, str | None], document: Document | None) -> str:
    """Provisional until something actually says final.

    A batch is normally invoiced twice, and treating an unlabelled invoice as final would let the
    first document freeze a price that is not fixed yet.
    """
    stated = (values.get("invoice_status") or "").strip().lower()
    if stated.startswith("final"):
        return InvoiceStatus.FINAL.value
    if stated.startswith("provisional") or stated.startswith("prov"):
        return InvoiceStatus.PROVISIONAL.value

    haystack = " ".join(
        part
        for part in (
            values.get("invoice_number"),
            document.filename if document else None,
        )
        if part
    ).lower()
    if "final" in haystack:
        return InvoiceStatus.FINAL.value
    return InvoiceStatus.PROVISIONAL.value


# How the three-month quotation is written on the documents this platform reads. Matched on the
# normalised text - spacing and hyphenation vary between a supplier in Jebel Ali and a buyer in
# Ningbo, and the phrase itself does not.
THREE_MONTH_MARKERS: tuple[str, ...] = ("3 month", "3month", "three month", "3m lme", "3-m lme")


def infer_price_basis(values: dict[str, str | None]) -> tuple[str, Decimal | None]:
    """Which of the three mechanisms this deal is priced on, read off the stated basis.

    A three-month quotation is recognised ahead of a plain percentage because the two are not
    alternatives: "3-month LME less 6%" is a three-month deal that also carries a percentage, and
    reading it as a straight percentage of the cash settlement would lose which quotation the
    percentage is taken off. The percentage is kept either way, so nothing that used to be
    captured stops being captured.
    """
    basis_text = values.get("price_basis") or ""
    normalised = " ".join(basis_text.lower().replace("-", " ").split())
    percentage = to_percentage(basis_text) if "%" in basis_text else None
    if any(marker.replace("-", " ") in normalised for marker in THREE_MONTH_MARKERS):
        return PriceBasis.THREE_MONTH_LME.value, percentage
    if percentage is not None:
        return PriceBasis.LME_PERCENT.value, percentage
    return PriceBasis.FIXED.value, None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    return None


# The FA base fields that have a named column somewhere, and where each one goes. Every other
# field the configured schema carries - including `rate` and `amount`, which AGFZE has not asked
# for columns of - is copied into `fa_legs.extra_fields` by `commit_fa_values` below.
#
# This map, and not a list of "FA fields", is what makes the flexible-field promise real: adding
# a field to the FA schema adds it to `extra_fields`, to the workspace panel and to the audit
# trail, with no entry here and no code change anywhere.
FA_LEG_COLUMNS: dict[str, str] = {
    "counterparty": "counterparty_name",
    "transaction_reference": "fa_contract_reference",
    "document_type": "document_type",
}

# Fields of the FA base set that belong to the shared parent rather than to the leg. Quantity and
# currency are facts about the batch, not about one desk's view of it, and they already have
# columns there that every stream reads.
FA_TRANSACTION_COLUMNS: dict[str, str] = {
    "quantity": "quantity_mt",
    "currency": "currency",
}


def commit_fa_values(
    transaction: TradeTransaction,
    leg: FaLeg,
    values: dict[str, str | None],
    *,
    overwrite: bool = False,
) -> dict[str, str]:
    """Write a confirmed document's field values onto the FA leg, wherever each one belongs.

    This is the mechanism Section 8 asks to be made explicit, generalised. `PurchaseLeg` and
    `SalesLeg` have always been populated this way - the matching service reads the confirmed,
    confidence-tracked extracted values and fills the leg's columns from them - but they could
    only ever be filled into columns somebody had already decided to create. FA cannot work that
    way, because nobody has decided yet.

    So the split is by *where a home exists*, not by a hardcoded field list: a value with a named
    column is written there, and everything else is copied into `extra_fields` keyed by its own
    field name. Returns what actually moved, for the audit entry.
    """
    written: dict[str, str] = {}

    for field_name, attribute in FA_LEG_COLUMNS.items():
        value = (values.get(field_name) or "").strip()
        if not value:
            continue
        if overwrite or getattr(leg, attribute, None) in (None, ""):
            setattr(leg, attribute, value)
            written[field_name] = value

    for field_name, attribute in FA_TRANSACTION_COLUMNS.items():
        raw = (values.get(field_name) or "").strip()
        if not raw:
            continue
        if attribute == "quantity_mt":
            quantity = to_decimal(raw)
            if quantity is not None and (overwrite or transaction.quantity_mt is None):
                transaction.quantity_mt = quantity
                written[field_name] = str(quantity)
            continue
        if overwrite or not getattr(transaction, attribute, None):
            setattr(transaction, attribute, raw.upper()[:3] if attribute == "currency" else raw)
            written[field_name] = raw

    handled = set(FA_LEG_COLUMNS) | set(FA_TRANSACTION_COLUMNS)
    extras = dict(leg.extra_fields or {})
    for field_name, raw in values.items():
        if field_name in handled:
            continue
        value = (raw or "").strip()
        if not value:
            continue
        if not overwrite and extras.get(field_name) not in (None, ""):
            continue
        extras[field_name] = value
        written[field_name] = value
    leg.extra_fields = extras
    leg.updated_at = utcnow()
    return written


def _mark_empty_collections(transaction: TradeTransaction) -> None:
    """Declare the new transaction's container and shipment collections loaded and empty.

    `set_committed_value` rather than a plain assignment, and the difference matters. Assigning to
    a collection on a row that has already been flushed makes SQLAlchemy load the collection it is
    replacing so it can compute the change - which is a query, issued from inside a flush, in an
    async session, where it raises rather than runs. This states the same fact without asking a
    question whose answer is already known: a transaction created a moment ago has neither.
    """
    set_committed_value(transaction, "containers", [])
    set_committed_value(transaction, "shipments", [])


async def create_transaction(
    session: AsyncSession,
    *,
    request_id: UUID,
    stream: str,
    batch_number: str | None,
    values: dict[str, str | None],
    match_method: str,
    match_score: float | None = None,
    match_rationale: str | None = None,
    created_by_id: UUID | None = None,
    document: Document | None = None,
) -> TradeTransaction:
    """Create a transaction and the leg its stream calls for, from whatever is actually known.

    Which leg is decided by the stream and by nothing else. The FA branch is four lines because
    that is genuinely all a second business line needed: the same parent row, the same batch
    numbering, the same commodity resolution, the same price basis, and a leg of its own.
    """
    number = (batch_number or "").strip() or await next_batch_number(session)

    commodity_code, needs_review = await resolve_commodity(session, values.get("commodity_code"))
    price_basis, lme = infer_price_basis(values)

    transaction = TradeTransaction(
        transaction_code=number,
        batch_number=number,
        stream=stream,
        status=TransactionStatus.MATCHED.value,
        commodity_code=commodity_code,
        extracted_commodity_value=(values.get("commodity_code") or None),
        commodity_needs_review=needs_review,
        quantity_mt=to_decimal(values.get("quantity")),
        price_basis=price_basis,
        lme_percentage=lme,
        currency=(values.get("currency") or "USD").strip().upper()[:3] or "USD",
        request_id=request_id,
        match_method=match_method,
        match_score=Decimal(str(round(match_score, 2))) if match_score is not None else None,
        match_rationale=match_rationale,
        created_by_id=created_by_id,
        field_overrides={},
    )
    session.add(transaction)
    await session.flush()

    if stream == BusinessStream.FA.value:
        fa_leg = FaLeg(transaction_id=transaction.id, extra_fields={})
        session.add(fa_leg)
        await session.flush()
        transaction.fa_leg = fa_leg
        commit_fa_values(transaction, fa_leg, values)
        # Stated explicitly for the same reason the sales leg is below: an object nothing has
        # queried has unset relationships, and an unset relationship read inside an async request
        # is a lazy load, which is an error rather than a query.
        transaction.purchase_leg = None
        transaction.sales_leg = None
        _mark_empty_collections(transaction)
        await session.flush()
        return transaction

    leg = PurchaseLeg(
        transaction_id=transaction.id,
        supplier_name=(values.get("supplier_name") or values.get("seller") or None),
        supplier_invoice_number=(values.get("invoice_number") or None),
        contract_number=(values.get("contract_number") or values.get("contract_reference") or None),
        invoice_status=infer_invoice_status(values, document),
        amount=to_decimal(values.get("amount")),
        rate=to_decimal(values.get("rate")),
        advance_payment_percent=to_percentage(values.get("advance_payment_percent")),
        hedge_date=_parse_date(values.get("hedge_date")),
        hedge_low_price=to_decimal(values.get("hedge_low_price")),
        hedge_high_price=to_decimal(values.get("hedge_high_price")),
        port_of_loading=(values.get("port_of_loading") or None),
    )
    session.add(leg)
    await session.flush()
    transaction.purchase_leg = leg
    # Stated explicitly rather than left unloaded. A transaction created here is a live object
    # nothing has queried, so an unset relationship would be lazily loaded the first time the
    # rule engine reads the leg map - and a lazy load inside an async request is an error, not a
    # query. A newly opened purchase transaction genuinely has no sales or FA leg, no container
    # and no shipment, and this says so.
    transaction.sales_leg = None
    transaction.fa_leg = None
    _mark_empty_collections(transaction)
    return transaction


async def create_manual_transaction(
    session: AsyncSession,
    *,
    user: User,
    stream: str,
    batch_number: str | None,
    values: dict[str, str | None],
) -> TradeTransaction:
    """Register a deal that never arrived by email.

    A synthetic portal request is issued first so BR-01 holds exactly as it does for an
    email-triggered transaction: the traceability is real, not waived because the trigger differs.
    """
    request = await request_service.create_request(
        session, source=RequestSource.PORTAL, created_by_id=user.id, stream=stream
    )
    # The category follows the stream rather than being assumed to be purchase. An FA request
    # filed under "purchase" would land its low-confidence cases on the buying desk.
    category = (
        RequestCategory.FA.value
        if stream == BusinessStream.FA.value
        else RequestCategory.PURCHASE.value
    )
    request.category = category
    request.original_category = request.original_category or category

    return await create_transaction(
        session,
        request_id=request.id,
        stream=stream,
        batch_number=batch_number,
        values=values,
        match_method=MatchMethod.MANUAL.value,
        match_rationale="Registered by hand; no email or document triggered this transaction.",
        created_by_id=user.id,
    )


async def get_transaction(session: AsyncSession, transaction_id: UUID) -> TradeTransaction:
    transaction = await session.scalar(
        select(TradeTransaction)
        .where(TradeTransaction.id == transaction_id)
        .options(
            selectinload(TradeTransaction.purchase_leg),
            selectinload(TradeTransaction.sales_leg),
            selectinload(TradeTransaction.fa_leg),
            selectinload(TradeTransaction.commodity),
        )
    )
    if transaction is None:
        raise NotFoundError("Transaction not found.")
    return transaction


EVERY_STREAM = frozenset({BusinessStream.SCRAP.value, BusinessStream.FA.value})

# Which streams a role may read. Every role in the matrix reads across both streams at this
# stage; the map exists so Steps 5 and 6 narrow visibility in one place, and so the restriction
# lives in the query rather than in whether a button was rendered.
ROLE_STREAM_VISIBILITY: dict[str, frozenset[str]] = {
    PlatformRole.PURCHASE_USER.value: EVERY_STREAM,
    PlatformRole.SALES_USER.value: EVERY_STREAM,
    PlatformRole.FA_USER.value: EVERY_STREAM,
    PlatformRole.LOGISTICS_USER.value: EVERY_STREAM,
    PlatformRole.FINANCE_USER.value: EVERY_STREAM,
    PlatformRole.APPROVER_HOD.value: EVERY_STREAM,
    PlatformRole.ADMIN.value: EVERY_STREAM,
    PlatformRole.AUDITOR.value: EVERY_STREAM,
}


def visible_streams(user: User) -> frozenset[str]:
    granted: set[str] = set()
    for role in user.roles or ():
        granted |= ROLE_STREAM_VISIBILITY.get(role, frozenset())
    return frozenset(granted)


def apply_visibility(statement: Select, user: User) -> Select:
    """Constrain a query to what the caller's roles actually permit, at the query layer.

    An account holding no recognised platform role reaches nothing at all, rather than falling
    through to an unfiltered query.
    """
    streams = visible_streams(user)
    if not streams:
        return statement.where(TradeTransaction.id.is_(None))
    return statement.where(TradeTransaction.stream.in_(sorted(streams)))


def list_query(
    *,
    stream: str | None = None,
    status: str | None = None,
    commodity_code: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    search: str | None = None,
    deal_type: str | None = None,
) -> Select[tuple[TradeTransaction]]:
    statement = select(TradeTransaction)
    if stream:
        statement = statement.where(TradeTransaction.stream == stream)
    if status:
        statement = statement.where(TradeTransaction.status == status)
    if commodity_code:
        statement = statement.where(TradeTransaction.commodity_code == commodity_code)
    if date_from:
        statement = statement.where(TradeTransaction.created_at >= date_from)
    if date_to:
        statement = statement.where(TradeTransaction.created_at <= date_to)
    if deal_type in ("b2b", "standard"):
        # An EXISTS over an alias, rather than a join, and both halves of that matter.
        #
        # A join would be wrong because the search filter below already joins `purchase_legs`, and
        # joining the same table twice in one statement is an error rather than a narrower result.
        #
        # The alias is what makes the EXISTS safe alongside that join. Against the bare mapped
        # class, SQLAlchemy auto-correlates the subquery to the enclosing query's FROM: once the
        # search filter has put `purchase_legs` there, the subquery loses its own FROM entirely and
        # the statement fails. An alias is a different selectable, so there is nothing to correlate
        # away and the two filters compose.
        #
        # A transaction with no purchase leg - a sales-only or an FA one - genuinely has no B2B
        # status, so it is correctly absent from both sides of this filter rather than being swept
        # into "standard" by a NULL.
        b2b_leg = aliased(PurchaseLeg)
        statement = statement.where(
            select(b2b_leg.id)
            .where(
                b2b_leg.transaction_id == TradeTransaction.id,
                b2b_leg.is_b2b.is_(deal_type == "b2b"),
            )
            .exists()
        )
    if search:
        term = f"%{search.strip().lower()}%"
        statement = (
            statement.outerjoin(PurchaseLeg, PurchaseLeg.transaction_id == TradeTransaction.id)
            .outerjoin(FaLeg, FaLeg.transaction_id == TradeTransaction.id)
            .where(
                or_(
                    func.lower(TradeTransaction.batch_number).like(term),
                    func.lower(TradeTransaction.transaction_code).like(term),
                    func.lower(func.coalesce(PurchaseLeg.contract_number, "")).like(term),
                    func.lower(func.coalesce(PurchaseLeg.supplier_name, "")).like(term),
                    func.lower(func.coalesce(PurchaseLeg.supplier_invoice_number, "")).like(term),
                    # The FA leg searches on the same two concepts under its own column names,
                    # so one search box covers both streams.
                    func.lower(func.coalesce(FaLeg.counterparty_name, "")).like(term),
                    func.lower(func.coalesce(FaLeg.fa_contract_reference, "")).like(term),
                )
            )
            .distinct()
        )
    return statement


SORTABLE = {
    "created_at": TradeTransaction.created_at,
    "updated_at": TradeTransaction.updated_at,
    "batch_number": TradeTransaction.batch_number,
    "status": TradeTransaction.status,
    "quantity_mt": TradeTransaction.quantity_mt,
}


def apply_sort(statement: Select, sort_by: str, direction: str) -> Select:
    column = SORTABLE.get(sort_by, TradeTransaction.created_at)
    return statement.order_by(column.asc() if direction == "asc" else column.desc())
