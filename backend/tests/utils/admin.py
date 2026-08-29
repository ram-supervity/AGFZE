"""Helpers for the  suite: a fake Keycloak Admin API, and signed-in administrators.

The fake is a real object satisfying the same interface `app.api.v1.admin` calls, installed
through the module's own swap point rather than by monkeypatching a method onto the live client.
It records what it was asked to do, so a test can assert on the *ordering* that matters most in
this : Keycloak first, local record second.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.roles import normalise_roles
from app.services import keycloak_admin


@dataclass
class FakeKeycloakAdminClient:
    """Stands in for the Admin REST API.

    `fail_with` is what makes the important test possible: an instance that refuses every call
    the way an unreachable or refusing Keycloak would, so the suite can prove that a failed call
    leaves this platform's own record completely unchanged.
    """

    roles_by_user: dict[str, list[str]] = field(default_factory=dict)
    fail_with: Exception | None = None
    calls: list[tuple[str, str, tuple[str, ...]]] = field(default_factory=list)
    known_ids: set[str] = field(default_factory=set)

    async def find_user_id(self, *, subject_id: str, email: str) -> str:
        if self.fail_with is not None:
            raise self.fail_with
        self.calls.append(("find_user_id", subject_id, ()))
        if self.known_ids and subject_id not in self.known_ids:
            raise keycloak_admin.KeycloakUserNotFoundError(reason="not_found")
        return subject_id

    async def current_platform_roles(self, keycloak_user_id: str) -> list[str]:
        if self.fail_with is not None:
            raise self.fail_with
        return normalise_roles(self.roles_by_user.get(keycloak_user_id, []))

    async def set_platform_roles(
        self, keycloak_user_id: str, roles: list[str]
    ) -> tuple[list[str], list[str]]:
        if self.fail_with is not None:
            raise self.fail_with
        wanted = set(normalise_roles(roles))
        held = set(await self.current_platform_roles(keycloak_user_id))
        added = normalise_roles(wanted - held)
        removed = normalise_roles(held - wanted)
        self.roles_by_user[keycloak_user_id] = normalise_roles(wanted)
        self.calls.append(("set_platform_roles", keycloak_user_id, tuple(sorted(wanted))))
        return added, removed

    async def aclose(self) -> None:
        return None


def install_fake_client(client: FakeKeycloakAdminClient) -> FakeKeycloakAdminClient:
    keycloak_admin.set_keycloak_admin_client(client)  # type: ignore[arg-type]
    return client


def restore_client() -> None:
    keycloak_admin.set_keycloak_admin_client(None)


async def admin_user(signed_in):
    return await signed_in(
        "0a1b2c3d-0000-4000-8000-0000000009a1",
        "sofia.admin@agfze.ae",
        "Sofia Lindqvist",
        ["admin"],
    )


async def auditor_user(signed_in):
    return await signed_in(
        "0a1b2c3d-0000-4000-8000-0000000009a2",
        "kenji.auditor@agfze.ae",
        "Kenji Watanabe",
        ["auditor"],
    )


async def purchase_user(signed_in):
    return await signed_in(
        "0a1b2c3d-0000-4000-8000-0000000009a3",
        "marco.purchase@agfze.ae",
        "Marco Bellini",
        ["purchase_user"],
    )


async def approver_user(signed_in):
    return await signed_in(
        "0a1b2c3d-0000-4000-8000-0000000009a4",
        "rania.hod@agfze.ae",
        "Rania Haddad",
        ["approver_hod"],
    )
