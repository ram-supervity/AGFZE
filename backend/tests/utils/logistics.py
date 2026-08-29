"""Builders for the FA and shipment fixtures the  suite works against.

Everything goes in through the real services or straight into the database exactly as they would
leave it, so the tests exercise the actual leg population, the actual BR-03 evaluator and the
actual tracking orchestration rather than mocks that resemble them.

The stand-in carrier adapter here is the one exception, and it is deliberate: the platform ships
no concrete adapter because no carrier's API is specified anywhere in its material. The only way
to prove the orchestration calls one correctly is for the test to register a stand-in, which is
exactly the shape a real adapter would take.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from app.db.base import utcnow
from app.models.enums import (
    BillOfLadingType,
    MatchMethod,
    PriceBasis,
    ShipmentMilestone,
    ShipmentStatus,
    TransactionStatus,
)
from app.models.identity import User
from app.models.logistics import BillOfLading, Container, Shipment
from app.models.transactions import FaLeg, TradeTransaction
from app.services.logistics.adapters import (
    TrackingQuery,
    TrackingResult,
    clear_adapters,
    register_adapter,
)
from tests.utils.transactions import make_request

FA_COUNTERPARTY = "Gulf Financial Advisory Partners"
FA_REFERENCE = "FA-2026-0031"

# What an FA document reads back as: exactly the seven fields the seeded schema carries, and
# nothing else. A fixture that invented an eighth would be inventing FA business content.
FA_DOCUMENT_VALUES: dict[str, str | None] = {
    "counterparty": FA_COUNTERPARTY,
    "transaction_reference": FA_REFERENCE,
    "quantity": "12.000 MT",
    "rate": "1500.00",
    "amount": "18000.00",
    "currency": "USD",
    "document_type": "Advisory fee note",
}

# Two well-formed ISO 6346 container numbers, so the normaliser accepts them and BR-03 has real
# keys to compare.
CONTAINER_A = "MSKU7781234"
CONTAINER_B = "MSKU7781235"


def fa_values(**overrides: Any) -> dict[str, str | None]:
    values = dict(FA_DOCUMENT_VALUES)
    values.update(overrides)
    return values


async def make_fa_transaction(
    session: AsyncSession,
    *,
    batch_number: str = "FA2626-1",
    counterparty_name: str | None = FA_COUNTERPARTY,
    fa_contract_reference: str | None = FA_REFERENCE,
    document_type: str | None = "Advisory fee note",
    quantity: str | None = "12.000",
    extra_fields: dict[str, str] | None = None,
    request=None,
) -> TradeTransaction:
    """A transaction carrying an FA leg and nothing else, written the way the service leaves it."""
    request = request or await make_request(session, category="fa", stream="fa")
    transaction = TradeTransaction(
        transaction_code=batch_number,
        batch_number=batch_number,
        stream="fa",
        status=TransactionStatus.MATCHED.value,
        commodity_code=None,
        quantity_mt=Decimal(quantity) if quantity else None,
        price_basis=PriceBasis.FIXED.value,
        currency="USD",
        request_id=request.id,
        match_method=MatchMethod.MANUAL.value,
        field_overrides={},
    )
    session.add(transaction)
    await session.flush()

    leg = FaLeg(
        transaction_id=transaction.id,
        counterparty_name=counterparty_name,
        fa_contract_reference=fa_contract_reference,
        document_type=document_type,
        # `is not None` rather than a truthiness check: a fixture that deliberately asks for an
        # empty bag must get one, not the default.
        extra_fields=dict(
            extra_fields if extra_fields is not None else {"rate": "1500.00", "amount": "18000.00"}
        ),
    )
    session.add(leg)
    await session.flush()
    transaction.fa_leg = leg
    transaction.purchase_leg = None
    transaction.sales_leg = None
    await session.flush()
    await session.refresh(transaction)
    return transaction


async def add_container(
    session: AsyncSession,
    transaction: TradeTransaction,
    *,
    container_number: str = CONTAINER_A,
    seal_number: str | None = None,
) -> Container:
    container = Container(
        transaction_id=transaction.id,
        container_number=container_number,
        seal_number=seal_number,
    )
    session.add(container)
    await session.flush()
    return container


async def add_shipment(
    session: AsyncSession,
    transaction: TradeTransaction,
    *,
    container: Container | None = None,
    bl_number: str | None = "MAEU-2026-77812",
    carrier: str | None = "Sample Line",
    vessel: str | None = "MV Northern Trader",
    port_of_loading: str | None = "Jebel Ali",
    port_of_discharge: str | None = "Nhava Sheva",
    eta: date | None = None,
    status: str = ShipmentStatus.ON_SCHEDULE.value,
    milestone: str = ShipmentMilestone.LOADED.value,
    checked_hours_ago: float | None = 1.0,
    consecutive_failures: int = 0,
) -> Shipment:
    """A shipment in whatever state the test needs, including a deliberately stale one.

    `checked_hours_ago` is what makes the staleness path testable without waiting 48 real hours:
    the sweep reads `last_checked_at` and nothing else, so moving that timestamp is the whole of
    what it takes to make a shipment genuinely overdue.
    """
    shipment = Shipment(
        transaction_id=transaction.id,
        container_id=container.id if container is not None else None,
        bl_number=bl_number,
        carrier=carrier,
        vessel=vessel,
        port_of_loading=port_of_loading,
        port_of_discharge=port_of_discharge,
        eta=eta,
        status=status,
        current_milestone=milestone,
        consecutive_failures=consecutive_failures,
        last_checked_at=(
            utcnow() - timedelta(hours=checked_hours_ago) if checked_hours_ago is not None else None
        ),
        last_checked_source="manual" if checked_hours_ago is not None else None,
    )
    session.add(shipment)
    await session.flush()
    # Declared loaded and empty rather than left unset, for the reason the services do the same:
    # reading an unloaded collection inside an async session is an error, not a query.
    set_committed_value(shipment, "bills_of_lading", [])
    set_committed_value(shipment, "issues", [])
    set_committed_value(shipment, "container", container)
    return shipment


async def add_bill_of_lading(
    session: AsyncSession,
    shipment: Shipment,
    *,
    bl_type: str = BillOfLadingType.ORIGINAL.value,
    bl_number: str | None = "MAEU-2026-77812",
    received: bool = False,
) -> BillOfLading:
    bill = BillOfLading(
        shipment_id=shipment.id,
        bl_type=bl_type,
        bl_number=bl_number,
        is_original_received=received,
        received_at=utcnow() if received else None,
    )
    session.add(bill)
    await session.flush()
    shipment.bills_of_lading.append(bill)
    return bill


async def make_user(
    session: AsyncSession, *, roles: list[str], name: str = "Logistics User"
) -> User:
    user = User(
        subject_id=f"sub-{uuid.uuid4().hex[:10]}",
        email=f"{uuid.uuid4().hex[:8]}@agfze.test",
        display_name=name,
        roles=roles,
    )
    session.add(user)
    await session.flush()
    return user


class StubCarrierAdapter:
    """A stand-in for the carrier adapter this platform deliberately does not ship.

    It exists only so the orchestration's "attempt a pull" path can be proved to call an adapter,
    read its result and write it through the shared update function. It is not a model of any real
    carrier's API and does not pretend to be one - which is precisely why nothing like it lives in
    the application itself.
    """

    def __init__(
        self,
        *,
        name: str = "stub-carrier",
        result: TrackingResult | None = None,
        handles_all: bool = True,
        raises: bool = False,
    ) -> None:
        self.name = name
        self.result = result or TrackingResult(
            available=True,
            milestone_description="Vessel departure from Jebel Ali",
            eta=date(2026, 9, 12),
            vessel="MV Northern Trader",
            carrier="Sample Line",
        )
        self.handles_all = handles_all
        self.raises = raises
        self.calls: list[TrackingQuery] = []

    def handles(self, query: TrackingQuery) -> bool:
        return self.handles_all

    async def fetch(self, query: TrackingQuery) -> TrackingResult:
        self.calls.append(query)
        if self.raises:
            raise RuntimeError("the carrier's endpoint refused the connection")
        return self.result


def use_adapter(adapter: StubCarrierAdapter) -> StubCarrierAdapter:
    """Register one stand-in adapter and nothing else. Callers must clear it afterwards."""
    clear_adapters()
    register_adapter(adapter)
    return adapter


def no_adapters() -> None:
    """The state every deployment actually ships in."""
    clear_adapters()


def aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
