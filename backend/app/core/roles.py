from __future__ import annotations

from collections.abc import Iterable
from enum import Enum


class PlatformRole(str, Enum):
    APPROVER_HOD = "approver_hod"
    PURCHASE_USER = "purchase_user"
    SALES_USER = "sales_user"
    FA_USER = "fa_user"
    LOGISTICS_USER = "logistics_user"
    FINANCE_USER = "finance_user"
    ADMIN = "admin"
    AUDITOR = "auditor"


ALL_ROLES: tuple[str, ...] = tuple(r.value for r in PlatformRole)

_CANONICAL_ORDER = {role: index for index, role in enumerate(ALL_ROLES)}


def normalise_roles(raw: Iterable[str]) -> list[str]:
    """Keep only known platform roles, de-duplicated, in canonical order."""
    known = {value for value in raw if isinstance(value, str) and value in _CANONICAL_ORDER}
    return sorted(known, key=_CANONICAL_ORDER.__getitem__)


# Which desk owns which leg of a transaction. Reference data about roles, so it lives here rather
# than in any one service: the exception hook reads it to decide whose a case is, and reading a
# map is what keeps that hook free of the leg-by-leg branching it exists to avoid.
DESK_ROLE_BY_LEG: dict[str, str] = {
    "purchase_leg": PlatformRole.PURCHASE_USER.value,
    "sales_leg": PlatformRole.SALES_USER.value,
    "fa_leg": PlatformRole.FA_USER.value,
}
