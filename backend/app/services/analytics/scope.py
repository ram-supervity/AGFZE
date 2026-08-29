"""What one account's dashboard is allowed to count, expressed as query constraints.

The distinction this module exists to hold is between *hiding a widget* and *scoping a query*.
Every function in :mod:`app.services.analytics.kpis` takes a :class:`DashboardScope` and applies
it with a `WHERE` clause before any `GROUP BY` runs, so a Sales User's exception tile is not a
full-platform count with the Purchase rows painted out - it is a count that never saw them.

The scope is derived from three things that already exist and are already the platform's answer
to "who may see what":

* the stream visibility map  put in `transaction_service`, so a role's streams are decided
  in one place rather than in two that can drift;
* the exception matrix  put in `governance.categories`, so a desk's categories are exactly
  the ones it can actually work;
* the three cross-cutting roles - Admin, Approver/HOD and Auditor - whose whole function is to
  see across the desks, and which are named here rather than inferred.

An account holding no recognised platform role scopes to nothing at all and every figure it is
shown is a real, honest zero, rather than falling through to an unfiltered query.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.roles import PlatformRole
from app.models.identity import User
from app.services.governance.categories import CATEGORY_CATALOG
from app.services.transaction_service import visible_streams

# The roles whose function is oversight across every desk. Named, never inferred from the absence
# of a desk role: an account with an unrecognised role must scope to nothing, not to everything.
CROSS_CUTTING_ROLES: frozenset[str] = frozenset(
    {
        PlatformRole.ADMIN.value,
        PlatformRole.APPROVER_HOD.value,
        PlatformRole.AUDITOR.value,
    }
)

# Which desk's dashboard leads with which panel. Section 5 of the brief, as data: the Logistics
# desk opens on cargo, Finance on the invoice-value exceptions that are finally theirs to work,
# and the HOD on the approval queue and the automation KPIs. Nothing is hidden by it - it decides
# the order the panels appear in, and the queries above it decide what they may contain.
EMPHASIS_BY_ROLE: dict[str, str] = {
    PlatformRole.LOGISTICS_USER.value: "shipments",
    PlatformRole.FINANCE_USER.value: "exceptions",
    PlatformRole.APPROVER_HOD.value: "approvals",
    PlatformRole.ADMIN.value: "integrations",
    PlatformRole.AUDITOR.value: "automation",
    PlatformRole.PURCHASE_USER.value: "transactions",
    PlatformRole.SALES_USER.value: "transactions",
    PlatformRole.FA_USER.value: "transactions",
}

# Which role decides the emphasis when an account holds several. The oversight roles win, because
# somebody who is both a buyer and the department head opens this screen to sign things off.
EMPHASIS_PRIORITY: tuple[str, ...] = (
    PlatformRole.APPROVER_HOD.value,
    PlatformRole.ADMIN.value,
    PlatformRole.AUDITOR.value,
    PlatformRole.LOGISTICS_USER.value,
    PlatformRole.FINANCE_USER.value,
    PlatformRole.PURCHASE_USER.value,
    PlatformRole.SALES_USER.value,
    PlatformRole.FA_USER.value,
)


def categories_for_roles(roles: frozenset[str]) -> frozenset[str]:
    """Every exception category these roles may actually work, from the matrix itself."""
    if roles & CROSS_CUTTING_ROLES:
        return frozenset(row.category for row in CATEGORY_CATALOG)
    return frozenset(
        row.category
        for row in CATEGORY_CATALOG
        if row.owner_role in roles or roles & set(row.shared_with)
    )


@dataclass(frozen=True)
class DashboardScope:
    """The constraints one account's aggregates run under. Immutable, and cacheable by key."""

    streams: frozenset[str]
    exception_categories: frozenset[str]
    # True only for the three oversight roles. It decides whether the integration and automation
    # panels are computed at all - not whether they are rendered.
    cross_cutting: bool
    emphasis: str
    roles: frozenset[str]
    # True once a caller has asked for one stream explicitly. It changes one thing only: an
    # exception case that is attached to no transaction has no stream to be in, so it belongs in
    # an unfiltered view of the queue and does not belong in a view of one business line.
    stream_explicit: bool = False

    @property
    def empty(self) -> bool:
        """An account that may reach nothing. Every figure it is shown is a genuine zero."""
        return not self.streams

    @property
    def sorted_streams(self) -> list[str]:
        return sorted(self.streams)

    @property
    def sorted_categories(self) -> list[str]:
        return sorted(self.exception_categories)

    def narrowed_to(self, stream: str | None) -> DashboardScope:
        """Apply a caller-supplied stream filter without ever widening what the roles permit."""
        if not stream or stream == "both":
            return self
        return DashboardScope(
            streams=self.streams & frozenset({stream}),
            exception_categories=self.exception_categories,
            cross_cutting=self.cross_cutting,
            emphasis=self.emphasis,
            roles=self.roles,
            stream_explicit=True,
        )

    def cache_key(self) -> str:
        """Two accounts with identical permissions share a cache entry; nobody else ever does."""
        return "|".join(
            (
                ",".join(self.sorted_streams),
                ",".join(self.sorted_categories),
                "x" if self.cross_cutting else "-",
                "s" if self.stream_explicit else "-",
            )
        )


def scope_for(user: User) -> DashboardScope:
    roles = frozenset(user.roles or ())
    return DashboardScope(
        streams=visible_streams(user),
        exception_categories=categories_for_roles(roles),
        cross_cutting=bool(roles & CROSS_CUTTING_ROLES),
        emphasis=_emphasis(roles),
        roles=roles,
    )


def _emphasis(roles: frozenset[str]) -> str:
    """Which panel this account's dashboard leads with, by the priority above."""
    for role in EMPHASIS_PRIORITY:
        if role in roles:
            return EMPHASIS_BY_ROLE[role]
    return "transactions"
