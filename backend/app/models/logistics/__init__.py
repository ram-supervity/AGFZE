"""Shipment and logistics models - added in .

Four tables, one parent. `Container` and `Shipment` attach to `TradeTransaction` through their
own foreign keys, so the parent table was not altered to carry them, exactly as no leg required
altering it. `BillOfLading` and `ShipmentIssue` hang off the shipment.
"""

from app.models.logistics.shipments import (
    BillOfLading,
    Container,
    Shipment,
    ShipmentIssue,
)

__all__ = ["BillOfLading", "Container", "Shipment", "ShipmentIssue"]
