"""Local development sample data for the sales, FA, shipment and integration workflows.

One purchase transaction with its supplier pack, ready to be matched against the bill of lading
that sits beside it, plus a second shipment on the same sales contract so the quantity meter has
an aggregate to draw rather than a single figure.

Beside them: an FA transaction carrying only the minimal seeded field set - nothing invented, in
the same discipline the FA module itself follows - and two shipments, one checked minutes ago and
one deliberately last checked three days ago. That second one is what makes the dashboard's
staleness indicator and the exception the sweep opens visible immediately, rather than after
somebody has waited 48 real hours to see whether either works.

From  there is also one batch sitting in `Approval Pending` with a real approval task
against it, so a local environment can be walked through the whole remaining lifecycle in one
sitting: approve it in /approvals, watch its three integration jobs appear, and - with nothing
configured, which is the shipped default - watch all three land honestly in "waiting on a person"
rather than claiming a posting nobody made.

Everything written here is obviously synthetic - the counterparties are named as samples and the
batch prefix is the development one - because sample data that reads like a real deal ends up
being mistaken for one. It refuses to run against a production environment at all.

    make seed-demo
    # or: python -m scripts.seed_sales_demo
"""

from __future__ import annotations

import asyncio
import hashlib
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.db.session import AsyncSessionLocal  # noqa: E402
from app.models.enums import (  # noqa: E402
    ApprovalDecision,
    BusinessStream,
    DocumentSource,
    DocumentType,
    ExceptionCategory,
    ExceptionPriority,
    ExtractionStatus,
    FixationStatus,
    InvoiceStatus,
    MatchMethod,
    PaymentCondition,
    PriceBasis,
    RequestCategory,
    RequestSource,
    RequestStatus,
    ShipmentMilestone,
    ShipmentStatus,
    Territory,
    TransactionStatus,
)
from app.models.governance import ApprovalTask, ExceptionCase  # noqa: E402
from app.models.intake import Document, ExtractedField, Request  # noqa: E402
from app.models.logistics import Container, Shipment  # noqa: E402
from app.models.transactions import (  # noqa: E402
    FaLeg,
    PurchaseLeg,
    SalesLeg,
    TradeTransaction,
)
from app.services.rules import engine as rule_engine  # noqa: E402
from app.services.templates import ensure_template_files  # noqa: E402

SUPPLIER = "Sample Metal Trading LLC (demo)"
CUSTOMER = "Sample Industries Limited (demo)"
PURCHASE_CONTRACT = "DEMO-CT-2026-118"
SALES_CONTRACT = "DEMO-SC-2026-441"
RATE = Decimal("8125.00")

# Two shipments against one sales contract, so the meter has something to sum.
SHIPMENTS = [
    {"batch": "DEMO-I2626-1", "quantity": Decimal("24.500"), "with_sales_leg": True},
    {"batch": "DEMO-I2626-2", "quantity": Decimal("31.250"), "with_sales_leg": True},
    # A third with no sell side yet: this is the one a sales-side test document matches against.
    {"batch": "DEMO-I2626-3", "quantity": Decimal("18.000"), "with_sales_leg": False},
    # A fourth, taken all the way to a pending approval so the integration flow can be walked
    # end to end without first having to prepare a deal by hand.
    {"batch": "DEMO-I2626-4", "quantity": Decimal("27.750"), "with_sales_leg": True},
]

# The batch a sales-side test document is meant to be matched against, so nothing is attached to
# it up front.
NO_SALES_LEG_BATCH = "DEMO-I2626-3"

# The batch that is left waiting on a decision. Approving it in /approvals raises its three
# integration jobs and moves it to Integration Pending.
AWAITING_APPROVAL_BATCH = "DEMO-I2626-4"

CONTRACTED_QUANTITY = Decimal("120.000")

# AGFZE's second business line, seeded with exactly the fields the platform actually configures
# for it. `rate` and `amount` sit in `extra_fields` because no column has been agreed for them -
# which is the whole shape of the FA module in one sample row.
FA_COUNTERPARTY = "Sample Advisory Partners (demo)"
FA_BATCH = "DEMO-FA2626-1"
FA_REFERENCE = "DEMO-FA-2026-0031"

# Two container numbers, well-formed under ISO 6346 so BR-03's normaliser accepts them.
DEMO_CONTAINERS = ("DEMU7781234", "DEMU7781235")

# How long ago each demo shipment was last checked. The second is past the configured 48-hour
# staleness threshold on purpose, so the indicator and the exception path can both be seen
# immediately rather than two days from now.
RECENT_CHECK_HOURS = 0.5
STALE_CHECK_HOURS = 72

# --- history for the dashboard and the reports () --------------------------------------
#
# The four batches above show the lifecycle. They do not, on their own, make a dashboard worth
# looking at: with nothing behind them the turnaround chart has one point, the automation figure
# is either 0% or 100%, and every ageing band is empty. So a stretch of finished trading is
# seeded behind them.
#
# It is deliberately varied rather than tidy. Some deals went through untouched, some had an
# exception opened and resolved, some fields were corrected by hand and some were not - which is
# what makes the automation percentage, the non-override rate and the turnaround spread land on
# numbers somebody has to actually read rather than on 0 and 100.
HISTORY_COUNT = 14
HISTORY_SPAN_DAYS = 45

# (days before now the deal was decided, hours it took, whether an exception was opened against
# it, how many of its ten extracted fields somebody corrected).
HISTORY: tuple[tuple[int, int, bool, int], ...] = (
    (42, 6, False, 0),
    (39, 9, False, 1),
    (35, 31, True, 3),
    (33, 5, False, 0),
    (30, 14, False, 2),
    (27, 52, True, 4),
    (24, 8, False, 0),
    (21, 11, False, 1),
    (18, 27, True, 2),
    (15, 7, False, 0),
    (12, 19, False, 1),
    (9, 44, True, 3),
    (6, 10, False, 0),
    (3, 16, False, 1),
)

# Three cases left open, one in each ageing band the queue reads, so the exception chart has all
# three bars on the first run rather than after somebody has waited four days.
OPEN_CASE_AGES_HOURS: tuple[tuple[str, str, int], ...] = (
    (ExceptionCategory.LOW_CONFIDENCE.value, "purchase_user", 6),
    (ExceptionCategory.INVOICE_AMOUNT_OUTSIDE_TOLERANCE.value, "finance_user", 30),
    (ExceptionCategory.SHIPMENT_STATUS_UNAVAILABLE.value, "logistics_user", 100),
)


async def _request(session: AsyncSession, category: str) -> Request:
    request = Request(
        request_code=f"DEMO-REQ-{uuid.uuid4().hex[:8].upper()}",
        source=RequestSource.PORTAL.value,
        category=category,
        original_category=category,
        stream="scrap",
        original_stream="scrap",
        status=RequestStatus.EXTRACTED.value,
    )
    session.add(request)
    await session.flush()
    return request


async def _document(
    session: AsyncSession,
    request: Request,
    transaction: TradeTransaction,
    *,
    document_type: str,
    filename: str,
    values: dict[str, str],
    created_at: datetime | None = None,
    # Which of these fields a person corrected. What the non-override rate is computed from, so
    # the sample data can produce a rate that is neither 0% nor a flat 100%.
    overridden: frozenset[str] = frozenset(),
) -> Document:
    body = f"{filename}:{transaction.batch_number}".encode()
    document = Document(
        request_id=request.id,
        transaction_id=transaction.id,
        filename=filename,
        content_type="application/pdf",
        byte_size=len(body),
        document_type=document_type,
        original_document_type=document_type,
        storage_ref=f"documents/source/demo/{uuid.uuid4().hex}.pdf",
        page_image_refs=[],
        content_hash=hashlib.sha256(body).hexdigest(),
        page_count=1,
        extraction_status=ExtractionStatus.COMPLETED.value,
        classification_confidence=0.96,
        source=DocumentSource.UPLOADED.value,
        confirmed_at=created_at or datetime.now(timezone.utc),
        created_at=created_at or datetime.now(timezone.utc),
    )
    session.add(document)
    await session.flush()
    for name, value in values.items():
        corrected = name in overridden
        session.add(
            ExtractedField(
                document_id=document.id,
                field_name=name,
                field_value=value,
                confidence=0.94,
                # Never rewritten by a correction, exactly as the real extraction path leaves it.
                original_ai_value=value,
                original_confidence=0.94,
                is_overridden=corrected,
                override_reason=(
                    "Corrected against the supplier's paperwork (demo)." if corrected else None
                ),
                created_at=created_at or datetime.now(timezone.utc),
            )
        )
    await session.flush()
    return document


async def _shipment(
    session: AsyncSession, *, batch: str, quantity: Decimal, with_sales_leg: bool
) -> TradeTransaction:
    request = await _request(session, RequestCategory.PURCHASE.value)
    amount = (RATE * quantity).quantize(Decimal("0.01"))

    transaction = TradeTransaction(
        transaction_code=batch,
        batch_number=batch,
        stream="scrap",
        status=TransactionStatus.MATCHED.value,
        commodity_code="CU",
        extracted_commodity_value="Copper Millberry 99.9%",
        quantity_mt=quantity,
        price_basis=PriceBasis.LME_PERCENT.value,
        lme_percentage=Decimal("97.0000"),
        currency="USD",
        request_id=request.id,
        match_method=MatchMethod.MANUAL.value,
        match_rationale="Sample data for local development. Not a real deal.",
        field_overrides={},
    )
    session.add(transaction)
    await session.flush()

    session.add(
        PurchaseLeg(
            transaction_id=transaction.id,
            supplier_name=SUPPLIER,
            supplier_invoice_number=f"DEMO-INV-{batch[-1]}",
            contract_number=PURCHASE_CONTRACT,
            invoice_status=InvoiceStatus.PROVISIONAL.value,
            amount=amount,
            rate=RATE,
            hedge_date=date(2026, 8, 14),
            port_of_loading="Jebel Ali",
        )
    )
    await session.flush()
    await session.refresh(transaction)

    await _document(
        session,
        request,
        transaction,
        document_type=DocumentType.INVOICE.value,
        filename=f"{batch}-supplier-invoice.pdf",
        values={
            "invoice_number": f"DEMO-INV-{batch[-1]}",
            "contract_reference": PURCHASE_CONTRACT,
            "batch_number": batch,
            "supplier_name": SUPPLIER,
            "invoice_status": "provisional",
            "commodity_code": "CU",
            "quantity": f"{quantity} MT",
            "rate": str(RATE),
            "currency": "USD",
            "amount": str(amount),
            "invoice_date": "2026-08-14",
        },
    )
    await _document(
        session,
        request,
        transaction,
        document_type=DocumentType.CONTRACT.value,
        filename=f"{batch}-purchase-contract.pdf",
        values={
            "contract_number": PURCHASE_CONTRACT,
            "buyer": "AGFZE Metals FZE",
            "seller": SUPPLIER,
            "commodity": "Copper Millberry 99.9%",
            "quantity": f"{quantity} MT",
            "rate": str(RATE),
            "price_basis": "97% of LME cash settlement",
            "incoterm": "CIF Nhava Sheva",
            "port_of_loading": "Jebel Ali",
            "port_of_discharge": "Nhava Sheva",
            "payment_terms": "LC at sight",
        },
    )

    if with_sales_leg:
        # An original bill of lading, so BR-07 lets this shipment be submitted as well as drafted.
        await _document(
            session,
            request,
            transaction,
            document_type=DocumentType.BL.value,
            filename=f"{batch}-original-bill-of-lading.pdf",
            values={
                "bl_number": f"DEMO-BL-{batch[-1]}",
                "container_numbers": "DEMU7781234",
                "vessel": "MV Sample Trader / V.214W",
                "port_of_loading": "Jebel Ali",
                "port_of_discharge": "Nhava Sheva",
                "shipper": "AGFZE Metals FZE",
                "consignee": CUSTOMER,
                "contract_reference": SALES_CONTRACT,
                "batch_number": batch,
                "commodity_code": "CU",
                "quantity": f"{quantity} MT",
            },
        )
        session.add(
            SalesLeg(
                transaction_id=transaction.id,
                customer_name=CUSTOMER,
                territory=Territory.INDIA.value,
                sales_contract_no=SALES_CONTRACT,
                contracted_quantity_mt=CONTRACTED_QUANTITY,
                sales_invoice_number=f"DEMO-SI-{batch[-1]}",
                bl_reference=f"DEMO-BL-{batch[-1]}",
                payment_condition=PaymentCondition.CAD.value,
                customer_fixation_status=FixationStatus.UNFIXED.value,
                port_of_discharge="Nhava Sheva",
                inland_container_depot="ICD Tughlakabad",
                extracted_commodity_value="CU",
            )
        )
        await session.flush()
        await session.refresh(transaction)
    else:
        # Left with no sales leg on purpose: this is the batch a sales-side test document is meant
        # to be matched against, so the attachment flow has something real to find.
        transaction.sales_leg = None

    await rule_engine.run_validation(session, transaction)
    return transaction


async def _fa_transaction(session: AsyncSession) -> TradeTransaction:
    """One FA transaction, carrying only what the seeded FA schema actually defines."""
    request = await _request(session, RequestCategory.FA.value)
    request.stream = BusinessStream.FA.value
    request.original_stream = BusinessStream.FA.value

    transaction = TradeTransaction(
        transaction_code=FA_BATCH,
        batch_number=FA_BATCH,
        stream=BusinessStream.FA.value,
        status=TransactionStatus.MATCHED.value,
        quantity_mt=Decimal("12.000"),
        price_basis=PriceBasis.FIXED.value,
        currency="USD",
        request_id=request.id,
        match_method=MatchMethod.MANUAL.value,
        match_rationale="Sample data for local development. Not a real deal.",
        field_overrides={},
    )
    session.add(transaction)
    await session.flush()

    session.add(
        FaLeg(
            transaction_id=transaction.id,
            counterparty_name=FA_COUNTERPARTY,
            fa_contract_reference=FA_REFERENCE,
            document_type="Advisory fee note",
            # The two base-set fields with no named column, exactly where the commit mechanism
            # puts them. Adding a field to the FA schema would add it here too, with no code
            # change on either side of the wire.
            extra_fields={"rate": "1500.00", "amount": "18000.00"},
        )
    )
    await session.flush()
    await session.refresh(transaction)

    await rule_engine.run_validation(session, transaction)
    return transaction


async def _shipments(session: AsyncSession, transaction: TradeTransaction) -> None:
    """Two shipments on one batch: one checked minutes ago, one three days ago.

    Neither has a carrier adapter behind it, because none ships - so both are exactly what the
    logistics desk will actually be looking at, and the stale one is what the sweep will pick up.
    """
    now = datetime.now(timezone.utc)
    for index, (number, checked_hours, status, milestone) in enumerate(
        (
            (
                DEMO_CONTAINERS[0],
                RECENT_CHECK_HOURS,
                ShipmentStatus.ON_SCHEDULE.value,
                ShipmentMilestone.DEPARTED.value,
            ),
            (
                DEMO_CONTAINERS[1],
                STALE_CHECK_HOURS,
                ShipmentStatus.DELAYED.value,
                ShipmentMilestone.IN_TRANSIT.value,
            ),
        )
    ):
        container = Container(
            transaction_id=transaction.id,
            container_number=number,
            seal_number=f"DEMO-SEAL-{index + 1}",
        )
        session.add(container)
        await session.flush()

        session.add(
            Shipment(
                transaction_id=transaction.id,
                container_id=container.id,
                bl_number=f"DEMO-BL-{transaction.batch_number[-1]}",
                carrier="Sample Line (demo)",
                vessel="MV Sample Trader / V.214W",
                port_of_loading="Jebel Ali",
                port_of_discharge="Nhava Sheva",
                etd=date(2026, 8, 20),
                eta=date(2026, 9, 12),
                status=status,
                current_milestone=milestone,
                last_checked_at=now - timedelta(hours=checked_hours),
                # `manual` on both, because that is how every shipment on this platform is
                # actually kept current until a carrier's terms are agreed.
                last_checked_source="manual",
            )
        )
    await session.flush()


async def _awaiting_approval(session: AsyncSession, transaction: TradeTransaction) -> None:
    """Put one demo batch in front of the approver, with a real task rather than a status alone.

    Written the way the submit endpoint leaves it - `Approval Pending`, submitted at a real
    moment, one pending `ApprovalTask` - so approving it in the UI runs the genuine decision path
    and, from there, the genuine integration path. Nothing here creates an integration job:
    that is the approval's act, and seeding one would be exactly the fabricated posting this
    module refuses to make.
    """
    transaction.status = TransactionStatus.APPROVAL_PENDING.value
    transaction.submitted_at = datetime.now(timezone.utc)
    session.add(
        ApprovalTask(
            transaction_id=transaction.id,
            approver_role="approver_hod",
            requested_at=datetime.now(timezone.utc),
            decision=ApprovalDecision.PENDING.value,
        )
    )
    await session.flush()


async def _history(session: AsyncSession) -> tuple[int, int]:
    """A stretch of finished trading behind the demo batches, so every KPI has something to say.

    Written straight into the same tables the dashboard queries - transactions, requests,
    documents, extracted fields, approval tasks and exception cases - because that is the only
    place any figure on this platform comes from. There is no summary row to seed and nowhere to
    put one.
    """
    now = datetime.now(timezone.utc)
    exception_free = 0

    for index, (days_ago, hours_taken, had_exception, corrected) in enumerate(HISTORY, start=1):
        batch = f"DEMO-H2626-{index:02d}"
        decided_at = now - timedelta(days=days_ago)
        opened_at = decided_at - timedelta(hours=hours_taken)
        quantity = Decimal("20.000") + Decimal(index)
        amount = (RATE * quantity).quantize(Decimal("0.01"))

        request = await _request(session, RequestCategory.PURCHASE.value)
        request.created_at = opened_at

        transaction = TradeTransaction(
            transaction_code=batch,
            batch_number=batch,
            stream="scrap" if index % 4 else "fa",
            # Most historic deals are fully posted; a few stopped at Approved, which is what an
            # honest Integration Pending column looks like on a real board.
            status=(
                TransactionStatus.COMMITTED.value
                if index % 5
                else TransactionStatus.INTEGRATION_PENDING.value
            ),
            commodity_code="CU",
            extracted_commodity_value="Copper Millberry 99.9%",
            quantity_mt=quantity,
            price_basis=PriceBasis.FIXED.value,
            currency="USD",
            request_id=request.id,
            match_method=MatchMethod.BATCH_NUMBER.value,
            match_rationale="Sample history for local development. Not a real deal.",
            field_overrides={},
            created_at=opened_at,
            submitted_at=decided_at - timedelta(hours=1),
        )
        session.add(transaction)
        await session.flush()

        session.add(
            PurchaseLeg(
                transaction_id=transaction.id,
                supplier_name=SUPPLIER,
                supplier_invoice_number=f"DEMO-HINV-{index:02d}",
                contract_number=PURCHASE_CONTRACT,
                invoice_status=InvoiceStatus.FINAL.value,
                amount=amount,
                rate=RATE,
                port_of_loading="Jebel Ali",
            )
        )

        # Ten extracted fields per deal, a stated number of them corrected by hand. This is what
        # the non-override rate is computed from, and why it lands somewhere between 0 and 100.
        await _document(
            session,
            request,
            transaction,
            document_type=DocumentType.INVOICE.value,
            filename=f"{batch}-supplier-invoice.pdf",
            values={f"field_{position}": f"value {position}" for position in range(10)},
            created_at=opened_at,
            overridden=frozenset(f"field_{position}" for position in range(corrected)),
        )

        session.add(
            ApprovalTask(
                transaction_id=transaction.id,
                approver_role="approver_hod",
                requested_at=decided_at - timedelta(hours=1),
                decision=ApprovalDecision.APPROVED.value,
                decided_at=decided_at,
            )
        )

        if had_exception:
            # Opened and resolved. It still counts against the automation percentage, because the
            # measure is whether a person had to  in - not whether anything is open now.
            session.add(
                ExceptionCase(
                    transaction_id=transaction.id,
                    exception_type=ExceptionCategory.QUANTITY_VARIATION_OUTSIDE_TOLERANCE.value,
                    owner_role="purchase_user",
                    priority=ExceptionPriority.MEDIUM.value,
                    summary="Invoiced quantity varied from the contracted figure (demo).",
                    opened_at=opened_at + timedelta(hours=2),
                    resolved_at=decided_at - timedelta(hours=2),
                    resolution_note="Corrected against the weighbridge certificate (demo).",
                )
            )
        else:
            exception_free += 1
        await session.flush()

    for exception_type, owner_role, age_hours in OPEN_CASE_AGES_HOURS:
        session.add(
            ExceptionCase(
                exception_type=exception_type,
                owner_role=owner_role,
                priority=ExceptionPriority.MEDIUM.value,
                summary="Left open by the sample data so the ageing bands are visible (demo).",
                opened_at=now - timedelta(hours=age_hours),
            )
        )
    await session.flush()
    return len(HISTORY), exception_free


async def seed() -> None:
    if settings.is_production:
        raise SystemExit("Refusing to write sample data into a production environment.")

    ensure_template_files()

    async with AsyncSessionLocal() as session:
        existing = await session.scalar(
            select(TradeTransaction).where(TradeTransaction.batch_number == SHIPMENTS[0]["batch"])
        )
        if existing is not None:
            print("Sample data is already present; nothing was written.")
            return

        first: TradeTransaction | None = None
        for shipment in SHIPMENTS:
            transaction = await _shipment(
                session,
                batch=str(shipment["batch"]),
                quantity=Decimal(str(shipment["quantity"])),
                with_sales_leg=bool(shipment["with_sales_leg"]),
            )
            first = first or transaction
            print(
                f"  {transaction.batch_number}: "
                f"{'purchase + sales' if shipment['with_sales_leg'] else 'purchase only'}"
            )
            if transaction.batch_number == AWAITING_APPROVAL_BATCH:
                await _awaiting_approval(session, transaction)
                print(
                    f"  {transaction.batch_number}: submitted and waiting on a decision, ready "
                    "for the integration flow"
                )

        if first is not None:
            await _shipments(session, first)
            print(
                f"  {first.batch_number}: two containers and two shipments, one of them last "
                f"checked {STALE_CHECK_HOURS} hours ago"
            )

        fa = await _fa_transaction(session)
        print(f"  {fa.batch_number}: FA, minimal seeded field set only")

        decided, exception_free = await _history(session)
        print(
            f"  {decided} historic batches over the last {HISTORY_SPAN_DAYS} days, "
            f"{exception_free} of them approved with no exception ever opened"
        )

        await session.commit()

    print(
        f"\nSales contract {SALES_CONTRACT} covers {CONTRACTED_QUANTITY} MT across "
        f"{sum(1 for row in SHIPMENTS if row['with_sales_leg'])} shipments so far.\n"
        f"Batch {NO_SALES_LEG_BATCH} has no sales leg: attach one to it from "
        "/transactions/new.\n"
        f"Batch {FA_BATCH} is the FA sample. It carries the seeded FA fields and nothing else.\n"
        f"One demo shipment was last checked {STALE_CHECK_HOURS} hours ago, past the configured "
        "48-hour threshold, so /shipments shows its staleness indicator immediately and the "
        "tracking sweep will open a Logistics-owned exception against it on its next pass.\n"
        f"Batch {AWAITING_APPROVAL_BATCH} is waiting on a decision. Approve it in /approvals and "
        "its three integration jobs appear at once - with no tracker, SAP or DMS configured, all "
        "three land in 'waiting on a person', which is the honest outcome and not a failure. "
        "Confirm them in /admin/integrations to walk the batch through to Committed.\n"
        f"{HISTORY_COUNT} historic batches sit behind them, decided over the last "
        f"{HISTORY_SPAN_DAYS} days with turnarounds from 5 to 52 hours, some of them corrected "
        "by hand and some not. That is what gives /dashboard and /analytics a real turnaround "
        "curve, an automation percentage that is neither 0 nor 100, and all three exception "
        "ageing bands populated on the first run.\n"
        "No report is generated by this script. The daily and monthly reports are produced by "
        "the scheduled sweep once the backend has been running past their configured times, and "
        "anything else is asked for in /reports/builder. Nothing is ever sent anywhere."
    )


if __name__ == "__main__":
    asyncio.run(seed())
