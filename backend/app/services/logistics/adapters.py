"""The carrier-tracking adapter seam, and deliberately nothing behind it.

Every other external system this platform talks to was named, documented and reachable before a
client was written for it: a Microsoft Graph mailbox, a Gemini endpoint. Carrier tracking is not
like that. Access is negotiated carrier by carrier, none of those negotiations has concluded, and
no carrier's API is specified anywhere in this platform's material.

So this module defines the shape of an adapter and the registry the orchestration walks, and
ships **no concrete adapter at all**. That is not an omission waiting to be filled in with a
plausible-looking client for whichever line springs to mind: a client written against an interface
nobody has published would fail on first contact with the real thing, and would meanwhile make
the platform look as though it had an integration it does not have.

What ships instead is a registry that is legitimately empty, orchestration that handles empty
correctly, and a manual path that is not a fallback but the way almost every shipment will
actually be tracked. When a carrier's terms are agreed, implementing `fetch` against them and
calling `register_adapter` is the whole of the work; nothing above this file changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol, runtime_checkable

from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class TrackingQuery:
    """What an adapter is given to look a shipment up by.

    Both references, because carriers differ on which one they will answer to, and the caller
    should not have to know which. An adapter that needs neither ignores both.
    """

    container_number: str | None = None
    bl_number: str | None = None
    carrier: str | None = None


@dataclass(frozen=True)
class TrackingResult:
    """What an adapter came back with.

    `available` is the whole point of the type. An adapter that cannot answer says so explicitly
    and gives a reason; it never returns a blank result that reads, downstream, like a shipment
    which is genuinely nowhere. The distinction between "the carrier says it has not moved" and
    "we could not ask the carrier" is the difference between a quiet shipment and a broken
    integration, and only one of those should age into an exception.
    """

    available: bool
    # The carrier's own words for where the cargo is, unparsed. Turning this into the platform's
    # fixed milestone vocabulary is the orchestrator's job, not the adapter's.
    milestone_description: str | None = None
    # A milestone the adapter is confident enough to state directly, where it has a structured
    # feed rather than prose. Skips the parsing  entirely when present.
    milestone: str | None = None
    status: str | None = None
    eta: date | None = None
    etd: date | None = None
    vessel: str | None = None
    carrier: str | None = None
    port_of_discharge: str | None = None
    # Why nothing came back. Recorded on the shipment and shown to the logistics desk verbatim,
    # because "the carrier's portal rejected our credentials" and "this container is not one of
    # theirs" call for different actions.
    unavailable_reason: str | None = None

    @classmethod
    def unavailable(cls, reason: str) -> TrackingResult:
        return cls(available=False, unavailable_reason=reason)


@runtime_checkable
class CarrierAdapter(Protocol):
    """One carrier's tracking source.

    `name` identifies it on the audit trail, so a status a person is looking at can always be
    traced to whichever source produced it. `handles` lets an adapter decline a shipment that is
    not its carrier's without the orchestrator needing to know the mapping.
    """

    name: str

    def handles(self, query: TrackingQuery) -> bool: ...

    async def fetch(self, query: TrackingQuery) -> TrackingResult: ...


_ADAPTERS: dict[str, CarrierAdapter] = {}


def register_adapter(adapter: CarrierAdapter) -> None:
    """Make one carrier's adapter live. The only integration  there is."""
    _ADAPTERS[adapter.name] = adapter
    logger.info("carrier_adapter_registered", extra={"adapter": adapter.name})


def unregister_adapter(name: str) -> None:
    _ADAPTERS.pop(name, None)


def registered_adapters() -> tuple[CarrierAdapter, ...]:
    """Every registered adapter. Empty on every deployment that ships today, and correctly so."""
    return tuple(_ADAPTERS.values())


def adapters_for(query: TrackingQuery) -> tuple[CarrierAdapter, ...]:
    """The adapters that will admit to handling this shipment, in registration order."""
    return tuple(adapter for adapter in _ADAPTERS.values() if adapter.handles(query))


def clear_adapters() -> None:
    """Used by the test suite, which registers a stand-in to prove the orchestration calls one."""
    _ADAPTERS.clear()
