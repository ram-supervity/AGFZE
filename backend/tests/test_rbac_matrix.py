"""The role matrix, run in full against every endpoint the application exposes.

Not a spot check. The table below names every route the router tree carries, together with the
roles that may reach it, and the tests walk it exhaustively: for each endpoint, every one of the
eight platform roles is signed in and made to call it, and the outcome is asserted in both
directions - an authorised role must not be refused, and an unauthorised one must receive a real
403 from the server.

Two properties matter more than any individual row.

**Coverage is enforced, not intended.** `test_every_route_is_in_the_matrix` reads the routes off
the live application and fails if one is missing from the table. An endpoint added later cannot
quietly escape this file by not being written into it.

**A 403 has to come from the server.** Every unauthorised call is made with a real signed token
carrying a real role, against a real dependency. Nothing here inspects a frontend, and no row
passes because a screen would have hidden a button.

Where an authorised call is expected to fail for some other reason - a UUID that names nothing, a
body the schema rejects - the assertion is only that the status is *not* 403 and not 401. That is
the whole of what an authorisation test should assert: whether the caller got past the gate.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.core.roles import ALL_ROLES, PlatformRole

pytestmark = pytest.mark.usefixtures("patched_jwks")

PREFIX = "/api/v1"
ANY_ID = "11111111-2222-4333-8444-555555555555"

# Every signed-in account, whatever it holds.
EVERYONE = frozenset(ALL_ROLES)

PURCHASE = PlatformRole.PURCHASE_USER.value
SALES = PlatformRole.SALES_USER.value
FA = PlatformRole.FA_USER.value
LOGISTICS = PlatformRole.LOGISTICS_USER.value
FINANCE = PlatformRole.FINANCE_USER.value
APPROVER = PlatformRole.APPROVER_HOD.value
ADMIN = PlatformRole.ADMIN.value
AUDITOR = PlatformRole.AUDITOR.value

DESKS = frozenset({PURCHASE, SALES, FA, LOGISTICS, ADMIN})
PREPARING = frozenset({PURCHASE, SALES, FA, ADMIN})
EXCEPTION_WORKERS = frozenset({PURCHASE, SALES, FA, LOGISTICS, FINANCE, ADMIN})


@dataclass(frozen=True)
class Endpoint:
    method: str
    path: str
    allowed: frozenset[str]
    body: dict | None = None
    # Routes that are deliberately reachable without a token at all.
    anonymous: bool = False
    notes: str = ""
    query: dict[str, str] = field(default_factory=dict)

    @property
    def key(self) -> tuple[str, str]:
        return (self.method.upper(), self.path)

    @property
    def refused(self) -> frozenset[str]:
        return EVERYONE - self.allowed


# The matrix. One row per route, in router order.
MATRIX: tuple[Endpoint, ...] = (
    # --- health and internal ------------------------------------------------------------------
    Endpoint("GET", "/health", EVERYONE, anonymous=True, notes="liveness probe, no database"),
    Endpoint("GET", "/health/ready", EVERYONE, anonymous=True, notes="readiness probe"),
    Endpoint(
        "GET",
        f"{PREFIX}/health",
        EVERYONE,
        anonymous=True,
        notes="the same probes, also mounted under the versioned prefix",
    ),
    Endpoint("GET", f"{PREFIX}/health/ready", EVERYONE, anonymous=True),
    Endpoint(
        "GET",
        "/internal/files/{key:path}",
        EVERYONE,
        anonymous=True,
        notes="authorised by an HMAC-signed, expiring URL rather than by a role",
    ),
    Endpoint(
        "POST",
        f"{PREFIX}/graph/notifications",
        EVERYONE,
        anonymous=True,
        notes="authenticated by Graph's own clientState secret, compared in constant time",
    ),
    # --- identity and self-service --------------------------------------------------------------
    Endpoint("GET", f"{PREFIX}/users/me", EVERYONE),
    Endpoint(
        "PATCH",
        f"{PREFIX}/users/me/preferences",
        EVERYONE,
        body={"notification_channel": "in_app"},
    ),
    # Marking the first-login walkthrough as seen. Open to everybody signed in, and self-only in
    # the strongest sense: the request carries no body at all, so there is nothing to point
    # somewhere else even in a crafted one.
    Endpoint("POST", f"{PREFIX}/users/me/onboarding-complete", EVERYONE, body={}),
    Endpoint("GET", f"{PREFIX}/notifications", EVERYONE),
    Endpoint("POST", f"{PREFIX}/notifications/mark-all-read", EVERYONE, body={}),
    Endpoint("GET", f"{PREFIX}/notifications/vapid-public-key", EVERYONE),
    Endpoint(
        "POST",
        f"{PREFIX}/notifications/push-subscribe",
        EVERYONE,
        body={
            "endpoint": "https://push.example.test/subscription/abc",
            "keys": {"p256dh": "a" * 32, "auth": "b" * 16},
        },
    ),
    Endpoint("DELETE", f"{PREFIX}/notifications/push-subscribe", EVERYONE),
    Endpoint("GET", f"{PREFIX}/jobs/{ANY_ID}/status", EVERYONE),
    # --- intake ----------------------------------------------------------------------------------
    Endpoint("GET", f"{PREFIX}/requests", EVERYONE),
    Endpoint("GET", f"{PREFIX}/requests/{ANY_ID}", EVERYONE),
    Endpoint(
        "PATCH",
        f"{PREFIX}/requests/{ANY_ID}/category",
        DESKS,
        body={"category": "purchase", "reason": "Reclassified during the matrix run."},
    ),
    # Replying on the thread a request arrived on. Reading is open to everybody signed in, on the
    # same transparency principle as the request itself; composing, sending and withdrawing are
    # the desks'. The approver is deliberately outside that set, exactly as they are for the
    # category correction: they review and sign off, and are not the corresponding party.
    Endpoint("GET", f"{PREFIX}/requests/{ANY_ID}/replies", EVERYONE),
    Endpoint(
        "POST",
        f"{PREFIX}/requests/{ANY_ID}/replies",
        DESKS,
        body={"message": "Confirming the booking against your reference, per the matrix run."},
    ),
    Endpoint(
        "POST",
        f"{PREFIX}/requests/{ANY_ID}/replies/{ANY_ID}/send",
        DESKS,
        notes="the one route on this platform that puts a message into somebody else's inbox",
    ),
    Endpoint(
        "POST",
        f"{PREFIX}/requests/{ANY_ID}/replies/{ANY_ID}/withdraw",
        DESKS,
    ),
    Endpoint("POST", f"{PREFIX}/documents/upload", DESKS, body={}),
    Endpoint("GET", f"{PREFIX}/documents", EVERYONE),
    Endpoint("GET", f"{PREFIX}/documents/{ANY_ID}", EVERYONE),
    Endpoint(
        "PATCH",
        f"{PREFIX}/documents/{ANY_ID}/fields",
        DESKS,
        body={"fields": [{"field_name": "invoice_number", "field_value": "INV-1"}]},
    ),
    Endpoint(
        "POST",
        f"{PREFIX}/documents/{ANY_ID}/reclassify",
        DESKS,
        body={"document_type": "invoice", "reason": "Matrix run."},
    ),
    Endpoint("POST", f"{PREFIX}/documents/{ANY_ID}/confirm", DESKS, body={}),
    Endpoint("GET", f"{PREFIX}/documents/{ANY_ID}/match", EVERYONE),
    Endpoint(
        "POST",
        f"{PREFIX}/documents/{ANY_ID}/match",
        frozenset({PURCHASE, ADMIN}),
        body={"decision": "reject"},
    ),
    # --- transactions -----------------------------------------------------------------------------
    Endpoint("GET", f"{PREFIX}/transactions/commodity-codes", EVERYONE),
    Endpoint("GET", f"{PREFIX}/transactions/fa/schema", EVERYONE),
    Endpoint("GET", f"{PREFIX}/transactions", EVERYONE),
    Endpoint("GET", f"{PREFIX}/transactions/{ANY_ID}", EVERYONE),
    # The traceability read. Same audience as the detail it belongs to, and scoped the same way:
    # the transaction is loaded through the detail endpoint's own visibility check before the
    # projection is consulted at all.
    Endpoint("GET", f"{PREFIX}/transactions/{ANY_ID}/graph", EVERYONE),
    Endpoint(
        "POST",
        f"{PREFIX}/transactions",
        frozenset({PURCHASE, ADMIN}),
        body={"document_ids": [ANY_ID]},
    ),
    Endpoint("POST", f"{PREFIX}/transactions/fa", frozenset({FA, ADMIN}), body={}),
    Endpoint(
        "POST",
        f"{PREFIX}/transactions/{ANY_ID}/sales-leg",
        frozenset({SALES, ADMIN}),
        body={},
    ),
    Endpoint(
        "POST",
        f"{PREFIX}/transactions/{ANY_ID}/generate-draft",
        frozenset({SALES, ADMIN}),
        body={"document_type": "sales_invoice"},
    ),
    Endpoint("PATCH", f"{PREFIX}/transactions/{ANY_ID}/fields", PREPARING, body={"fields": []}),
    Endpoint(
        "POST",
        f"{PREFIX}/transactions/{ANY_ID}/acknowledge-tolerance",
        PREPARING,
        body={"rule_id": "BR-06", "reason": "Within the agreed rounding on the pro-forma."},
    ),
    Endpoint("POST", f"{PREFIX}/transactions/{ANY_ID}/submit", PREPARING, body={}),
    # --- shipments ---------------------------------------------------------------------------------
    Endpoint("GET", f"{PREFIX}/shipments", EVERYONE),
    Endpoint(
        "POST",
        f"{PREFIX}/shipments",
        frozenset({LOGISTICS, ADMIN}),
        body={"transaction_id": ANY_ID},
    ),
    Endpoint("GET", f"{PREFIX}/shipments/{ANY_ID}", EVERYONE),
    Endpoint(
        "POST", f"{PREFIX}/shipments/{ANY_ID}/refresh", frozenset({LOGISTICS, ADMIN}), body={}
    ),
    Endpoint("PATCH", f"{PREFIX}/shipments/{ANY_ID}", frozenset({LOGISTICS, ADMIN}), body={}),
    Endpoint(
        "POST",
        f"{PREFIX}/shipments/{ANY_ID}/issues",
        frozenset({LOGISTICS, ADMIN}),
        body={"issue_type": "delay", "description": "Matrix run."},
    ),
    # --- governance -----------------------------------------------------------------------------
    Endpoint("GET", f"{PREFIX}/exceptions", EVERYONE),
    Endpoint("GET", f"{PREFIX}/exceptions/{ANY_ID}", EVERYONE),
    Endpoint(
        "POST",
        f"{PREFIX}/exceptions/{ANY_ID}/resolve",
        EXCEPTION_WORKERS,
        body={"resolution": "corrected", "reason": "Corrected during the matrix run."},
    ),
    Endpoint("GET", f"{PREFIX}/approvals", EVERYONE),
    Endpoint("GET", f"{PREFIX}/approvals/{ANY_ID}", EVERYONE),
    Endpoint(
        "POST",
        f"{PREFIX}/approvals/{ANY_ID}/decide",
        frozenset({APPROVER, ADMIN}),
        body={"decision": "approved"},
    ),
    Endpoint(
        "POST",
        f"{PREFIX}/approvals/bulk-decide",
        frozenset({APPROVER, ADMIN}),
        body={"approval_ids": [ANY_ID]},
    ),
    # --- integration hub -----------------------------------------------------------------------
    Endpoint("GET", f"{PREFIX}/integrations/jobs", frozenset({ADMIN})),
    Endpoint("GET", f"{PREFIX}/integrations/jobs/{ANY_ID}", frozenset({ADMIN})),
    Endpoint("POST", f"{PREFIX}/integrations/jobs/{ANY_ID}/retry", frozenset({ADMIN}), body={}),
    Endpoint(
        "POST",
        f"{PREFIX}/integrations/jobs/{ANY_ID}/complete-manual",
        frozenset({ADMIN}),
        body={"reference": "SAP-1", "note": "Posted by hand during the matrix run."},
    ),
    # --- analytics and reporting -----------------------------------------------------------------
    Endpoint("GET", f"{PREFIX}/dashboards/summary", EVERYONE),
    Endpoint("GET", f"{PREFIX}/dashboards/kpis", EVERYONE),
    Endpoint("GET", f"{PREFIX}/reports", EVERYONE),
    Endpoint(
        "POST",
        f"{PREFIX}/reports",
        frozenset({ADMIN, APPROVER}),
        body={"report_type": "adhoc", "output_format": "pdf", "days": 7},
    ),
    Endpoint("GET", f"{PREFIX}/reports/{ANY_ID}", EVERYONE),
    # --- administration and the audit trail --------------------------------------------------------
    Endpoint("GET", f"{PREFIX}/admin/rules", frozenset({ADMIN})),
    Endpoint(
        "PATCH",
        f"{PREFIX}/admin/rules/{ANY_ID}",
        frozenset({ADMIN}),
        body={"threshold_value": "5.0", "change_reason": "Matrix run, reason recorded."},
    ),
    Endpoint("GET", f"{PREFIX}/admin/document-types", frozenset({ADMIN})),
    Endpoint(
        "PATCH",
        f"{PREFIX}/admin/document-types/{ANY_ID}",
        frozenset({ADMIN}),
        body={"change_reason": "Matrix run, reason recorded."},
    ),
    Endpoint("GET", f"{PREFIX}/admin/users", frozenset({ADMIN})),
    Endpoint(
        "PATCH",
        f"{PREFIX}/admin/users",
        frozenset({ADMIN}),
        body={
            "user_id": ANY_ID,
            "roles": ["purchase_user"],
            "change_reason": "Matrix run, reason recorded.",
        },
    ),
    Endpoint("GET", f"{PREFIX}/admin/report-distribution", frozenset({ADMIN})),
    Endpoint(
        "POST",
        f"{PREFIX}/admin/report-distribution",
        frozenset({ADMIN}),
        body={
            "report_type": "daily",
            "recipient_roles": ["finance_user"],
            "channel": "in_app",
            "change_reason": "Matrix run, reason recorded.",
        },
    ),
    Endpoint(
        "PATCH",
        f"{PREFIX}/admin/report-distribution/{ANY_ID}",
        frozenset({ADMIN}),
        body={
            "report_type": "daily",
            "recipient_roles": ["finance_user"],
            "channel": "in_app",
            "change_reason": "Matrix run, reason recorded.",
        },
    ),
    Endpoint("GET", f"{PREFIX}/admin/report-templates", frozenset({ADMIN})),
    Endpoint(
        "PATCH",
        f"{PREFIX}/admin/report-templates/{ANY_ID}",
        frozenset({ADMIN}),
        body={"change_reason": "Matrix run, reason recorded."},
    ),
    Endpoint("GET", f"{PREFIX}/audit", frozenset({ADMIN, AUDITOR})),
    Endpoint("GET", f"{PREFIX}/audit/export", frozenset({ADMIN, AUDITOR})),
)

MATRIX_BY_KEY = {row.key: row for row in MATRIX}

# Routes FastAPI mounts that are not this platform's endpoints: the interactive documentation and
# the OpenAPI document, both of which are switched off entirely in production.
FRAMEWORK_PATHS = frozenset({"/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"})

# The writes that are open to every authenticated account on purpose, because each one can only
# ever touch the caller's own row. They are self-only in the query rather than in the routing,
# which is the stronger of the two: there is no account identifier in any of their bodies for a
# crafted request to point somewhere else.
SELF_ONLY_WRITES = frozenset(
    {
        f"{PREFIX}/users/me/preferences",
        f"{PREFIX}/users/me/onboarding-complete",
        f"{PREFIX}/notifications/mark-all-read",
        f"{PREFIX}/notifications/push-subscribe",
    }
)

# `liveness` carries a second decorator so /health and /health/ trailing-slash both answer. The
# duplicate is not a separate endpoint and has nothing of its own to authorise.
ALIAS_PATHS = frozenset({"/health/", f"{PREFIX}/health/"})


def _walk(routes, prefix: str = ""):
    """Every (method, path) the router tree carries, prefixes included.

    Written against both shapes FastAPI has used. Newer versions keep an included router nested
    behind a placeholder carrying its prefix; older ones copy each route in flat with the prefix
    already applied. Reading the live tree either way is the point - a matrix checked against a
    hand-kept list of endpoints proves only that the list agrees with itself.
    """
    for route in routes:
        nested = getattr(getattr(route, "original_router", None), "routes", None)
        if nested is not None:
            context = getattr(route, "include_context", None)
            yield from _walk(nested, prefix + (getattr(context, "prefix", "") or ""))
            continue
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if not path or not methods:
            continue
        for method in methods:
            yield method, f"{prefix}{path}"


def application_routes(app: FastAPI) -> set[tuple[str, str]]:
    return {
        (method, path)
        for method, path in _walk(app.routes)
        if method not in {"HEAD", "OPTIONS"}
        and path not in FRAMEWORK_PATHS
        and path not in ALIAS_PATHS
    }


def matrix_route_keys() -> set[tuple[str, str]]:
    """The matrix, expressed the way FastAPI names its routes, so the two can be compared."""
    keys: set[tuple[str, str]] = set()
    for row in MATRIX:
        keys.add((row.method.upper(), row.path))
    return keys


async def account(signed_in, role: str):
    """One signed-in account holding exactly one role, provisioned on first call."""
    subject = f"00000000-0000-4000-8000-{abs(hash(role)) % 10**12:012d}"
    return await signed_in(subject, f"{role}@agfze.test", role.replace("_", " ").title(), [role])


async def call(client: AsyncClient, row: Endpoint, headers: dict[str, str] | None):
    path = row.path.replace("{key:path}", "unsigned/object/key")
    request = {"headers": headers or {}}
    if row.body is not None and row.method.upper() in {"POST", "PATCH", "PUT"}:
        request["json"] = row.body
    if row.query:
        request["params"] = row.query
    return await client.request(row.method, path, **request)


# --- coverage --------------------------------------------------------------------------------


def test_every_route_is_in_the_matrix(app: FastAPI) -> None:
    """The matrix is complete against the running application, not against a memory of it.

    Compared on the parameterised shape, so `/transactions/{transaction_id}` and the matrix's
    concrete identifier are recognised as the same route. Both directions are asserted: a route
    with no row is an endpoint nobody checked, and a row with no route is a check that has quietly
    stopped testing anything.
    """
    live = {(method, _shape(path)) for method, path in application_routes(app)}
    declared = {(method, _shape(path)) for method, path in matrix_route_keys()}

    assert live - declared == set(), (
        f"These routes exist but are not in the RBAC matrix: {sorted(live - declared)}"
    )
    assert declared - live == set(), (
        f"These matrix rows name routes that no longer exist: {sorted(declared - live)}"
    )


def _shape(path: str) -> str:
    """A path with every identifier, named or literal, collapsed to a single placeholder."""
    parts = []
    for segment in path.split("/"):
        if (segment.startswith("{") and segment.endswith("}")) or segment == ANY_ID:
            parts.append("{}")
        else:
            parts.append(segment)
    return "/".join(parts)


def test_the_matrix_names_only_known_roles() -> None:
    for row in MATRIX:
        assert row.allowed <= EVERYONE, row.path


# --- the matrix itself -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "row", [row for row in MATRIX if not row.anonymous], ids=lambda row: f"{row.method} {row.path}"
)
async def test_an_unauthorised_role_is_refused_by_the_server(
    row: Endpoint, client: AsyncClient, signed_in
) -> None:
    """403, from the dependency layer, for every role the endpoint does not grant."""
    for role in sorted(row.refused):
        _, headers = await account(signed_in, role)
        response = await call(client, row, headers)
        assert response.status_code == 403, (
            f"{row.method} {row.path} answered {response.status_code} to {role}, "
            "which must not reach it"
        )
        payload = response.json()
        assert payload["success"] is False
        # The refusal says nothing about what is behind the door.
        assert "role" in payload["message"].lower()


@pytest.mark.parametrize(
    "row", [row for row in MATRIX if not row.anonymous], ids=lambda row: f"{row.method} {row.path}"
)
async def test_an_authorised_role_gets_past_the_gate(
    row: Endpoint, client: AsyncClient, signed_in
) -> None:
    """Every granted role reaches the handler.

    What happens next is not this test's business: an identifier that names nothing answers 404,
    an intentionally thin body answers 422, and both are the handler doing its job. Only 401 and
    403 would mean the gate refused somebody it should have let through.
    """
    for role in sorted(row.allowed):
        _, headers = await account(signed_in, role)
        response = await call(client, row, headers)
        assert response.status_code not in {401, 403}, (
            f"{row.method} {row.path} refused {role}, which it is supposed to allow "
            f"({response.status_code}: {response.text[:200]})"
        )


@pytest.mark.parametrize(
    "row", [row for row in MATRIX if not row.anonymous], ids=lambda row: f"{row.method} {row.path}"
)
async def test_no_endpoint_answers_without_a_token(row: Endpoint, client: AsyncClient) -> None:
    """401 with no bearer token, on everything that is not deliberately anonymous."""
    response = await call(client, row, None)
    assert response.status_code == 401, f"{row.method} {row.path} answered {response.status_code}"


@pytest.mark.parametrize(
    "row", [row for row in MATRIX if not row.anonymous], ids=lambda row: f"{row.method} {row.path}"
)
async def test_no_endpoint_accepts_a_token_carrying_no_platform_role(
    row: Endpoint, client: AsyncClient, signed_in
) -> None:
    """An account provisioned from a valid token with no mapped role reaches no write endpoint.

    A read is a different question and is answered by the matrix above; this asserts the narrower
    thing, that holding a verified token is never on its own enough to change anything.
    """
    if row.method.upper() == "GET":
        pytest.skip("reads are governed by the matrix, not by this narrower claim")
    if row.path in SELF_ONLY_WRITES:
        pytest.skip("a self-only write governs itself; see the assertion below")
    _, headers = await signed_in(
        "00000000-0000-4000-8000-999999999999", "noroles@agfze.test", "No Roles", []
    )
    response = await call(client, row, headers)
    assert response.status_code == 403


@pytest.mark.parametrize("path", sorted(SELF_ONLY_WRITES))
async def test_a_self_only_write_needs_no_role_and_reaches_only_the_caller(
    path: str, client: AsyncClient, signed_in, db_session
) -> None:
    """The four writes that are deliberately open to any account, and why that is correct.

    A preference, a read receipt and a browser's push subscription belong to the person making
    the request and to nobody else. Gating them on a desk role would mean an auditor could not
    mark their own notification as read. They are safe not because a role is checked but because
    the row is chosen by the verified token subject and by nothing a client can supply - so this
    asserts the property that actually holds: a caller with no role at all gets through, and what
    they touch is their own record.
    """
    row = next(item for item in MATRIX if item.path == path and item.method != "GET")
    user, headers = await signed_in(
        "00000000-0000-4000-8000-888888888888", "selfonly@agfze.test", "Self Only", []
    )
    response = await call(client, row, headers)
    assert response.status_code == 200, response.text

    # Nothing in any of these bodies names an account, so there is no other account to reach.
    assert row.body is None or not {"user_id", "email", "roles"} & set(row.body)
    await db_session.refresh(user)
    assert user.roles == []


def test_the_anonymous_routes_are_exactly_the_ones_that_should_be() -> None:
    """A short, deliberately hard-to-extend list.

    Two probes an orchestrator polls, the same probes under the versioned prefix, one signed-URL
    file route, and one webhook authenticated by a shared secret. Anything else appearing here
    would be an endpoint somebody made reachable without a token.
    """
    assert {row.path for row in MATRIX if row.anonymous} == {
        "/health",
        "/health/ready",
        f"{PREFIX}/health",
        f"{PREFIX}/health/ready",
        "/internal/files/{key:path}",
        f"{PREFIX}/graph/notifications",
    }


async def test_the_signed_url_route_refuses_an_unsigned_request(client: AsyncClient) -> None:
    """It takes no token, so its signature has to be the whole of its protection."""
    response = await client.get(f"/internal/files/{uuid.uuid4()}.pdf")
    # Refused before anything is read. 422 because the signature and expiry are required query
    # parameters, 404 once they are present but wrong - the point is that no object is served and
    # neither answer distinguishes a key that exists from one that does not.
    assert response.status_code in {404, 422}
    assert response.headers.get("content-type", "").startswith("application/json")

    signed_but_forged = await client.get(
        f"/internal/files/{uuid.uuid4()}.pdf",
        params={"expires": "99999999999", "signature": "0" * 64},
    )
    assert signed_but_forged.status_code == 404


async def test_the_graph_webhook_ignores_a_notification_with_the_wrong_secret(
    client: AsyncClient,
) -> None:
    response = await client.post(
        f"{PREFIX}/graph/notifications",
        json={
            "value": [
                {
                    "subscriptionId": "sub-1",
                    "clientState": "not-the-configured-secret",
                    "resource": "users/x/messages/y",
                    "changeType": "created",
                }
            ]
        },
    )
    # Accepted and discarded: Graph retries anything it is not acknowledged on, and a forged
    # notification must not become a retry loop. What matters is that nothing was ingested.
    assert response.status_code in {200, 202}
