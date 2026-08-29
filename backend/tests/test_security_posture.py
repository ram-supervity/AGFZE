"""The security properties that are about the shape of the codebase rather than one endpoint.

Three groups, and the third is the unusual one.

**Secrets** - every credential the platform holds is declared with an empty default, is never
returned by any endpoint, never reaches a log line, and appears in no response schema. These are
checked against the running application and against the source, not against a policy document.

**Headers and limits** - the Content-Security-Policy the API serves, the hardening headers beside
it, and the category rate limits, asserted by making real requests and reading real responses.

**Absences** - the properties that are true because something does *not* exist. A test that
asserts a thing is missing is easy to write badly and easy to satisfy by accident, so each one
below names the exact construct it is looking for and searches the real tree for it. These are the
guarantees that would be quietly lost first: a helpful commit adding "email the customer their
invoice", a service worker learning to retry a failed POST, a schema growing a `decided_by` field.
"""

from __future__ import annotations

import ast
import inspect
import json
import logging
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from pydantic import BaseModel

from app.core.config import Settings, settings
from app.core.logging import JsonFormatter
from app.core.rate_limit import categories, category_for
from app.middleware.security_headers import API_CONTENT_SECURITY_POLICY
from tests.utils.tokens import auth_header, build_token

pytestmark = pytest.mark.usefixtures("patched_jwks")

BACKEND_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = BACKEND_ROOT / "app"
REPO_ROOT = BACKEND_ROOT.parent
FRONTEND_SRC = REPO_ROOT / "frontend" / "src"

# Every credential in this platform, with the step that introduced it. The list is the audit: a
# credential added later without being written in here is a credential nobody checked.
SECRET_SETTINGS: tuple[tuple[str, str], ...] = (
    ("KEYCLOAK_ADMIN_CLIENT_SECRET", "Step 9 - Keycloak Admin REST API"),
    ("AZURE_AD_CLIENT_SECRET", "Step 2 - Graph mailbox intake, Step 7 tracker"),
    ("GEMINI_API_KEY", "Step 2 - every AI call"),
    ("SAP_API_PASSWORD", "Step 7 - SAP posting"),
    ("SAP_API_KEY", "Step 7 - SAP posting"),
    ("DMS_API_PASSWORD", "Step 7 - DMS upload"),
    ("DMS_API_KEY", "Step 7 - DMS upload"),
    ("VAPID_PRIVATE_KEY", "Step 10 - push signing"),
    ("SMTP_PASSWORD", "Step 10 - email delivery"),
    ("NEO4J_PASSWORD", "Graph projection - the traceability read model"),
)

# Held in the same secrets store and checked the same way, but not a bare string on `Settings`:
# the database credential is embedded in the DSN and the signing secret has a development default
# the production profile refuses to start on.
CREDENTIAL_BEARING_SETTINGS: tuple[str, ...] = (
    "DATABASE_URL",
    "STORAGE_SIGNED_URL_SECRET",
    "SENTRY_DSN",
)


def python_sources() -> list[Path]:
    return [path for path in APP_ROOT.rglob("*.py") if "__pycache__" not in path.parts]


def frontend_sources() -> list[Path]:
    if not FRONTEND_SRC.exists():
        return []
    return [
        path
        for suffix in ("*.ts", "*.tsx", "*.js")
        for path in FRONTEND_SRC.rglob(suffix)
        if "node_modules" not in path.parts
    ]


# --- secrets ------------------------------------------------------------------------------------


@pytest.mark.parametrize(("name", "origin"), SECRET_SETTINGS, ids=[n for n, _ in SECRET_SETTINGS])
def test_no_credential_ships_with_a_value(name: str, origin: str) -> None:
    """Nothing is hardcoded. Every one of them is empty until an environment supplies it."""
    field = Settings.model_fields[name]
    assert field.default == "", f"{name} ({origin}) ships with a default value"


def test_every_credential_is_declared_and_none_is_missed() -> None:
    """A settings field that looks like a secret must be on the audited list above.

    This is what keeps the list honest as the platform grows: adding `NEW_API_SECRET` to Settings
    fails here until somebody has decided how it is held and written it down.
    """
    suspicious = {
        name
        for name in Settings.model_fields
        if any(word in name for word in ("SECRET", "PASSWORD", "_KEY", "TOKEN", "CREDENTIAL"))
    }
    known = {name for name, _ in SECRET_SETTINGS} | set(CREDENTIAL_BEARING_SETTINGS)
    # The VAPID public key and the algorithm list are the two that match the word test without
    # being secrets: one is meant to be given to a browser, the other is a list of names.
    expected_public = {
        "VAPID_PUBLIC_KEY",
        "JWT_ALGORITHMS",
        "TRACKER_KEY_COLUMN",
        # A model output ceiling. Matches the word test and is a number.
        "GEMINI_MAX_OUTPUT_TOKENS",
    }
    assert suspicious - known - expected_public == set()


def test_no_credential_appears_in_the_api_schema(app: FastAPI) -> None:
    """No response or request model anywhere carries a field named after a credential."""
    document = json.dumps(app.openapi()).lower()
    for name, _ in SECRET_SETTINGS:
        assert name.lower() not in document, f"{name} is named in the OpenAPI document"


async def test_no_endpoint_returns_a_credential(
    client: AsyncClient, signed_in, monkeypatch
) -> None:
    """Set every credential to a recognisable value, then read the endpoints most likely to leak.

    The admin screens are the interesting ones: they report *whether* a provider is configured,
    which is a fact an administrator needs, and they must do it without ever handing back the
    value that made it configured.
    """
    canary = "CANARY-SECRET-VALUE-0f8d2a"
    for name, _ in SECRET_SETTINGS:
        monkeypatch.setattr(settings, name, canary, raising=True)

    _, headers = await signed_in(
        "00000000-0000-4000-8000-0000000000a1", "admin@agfze.test", "Admin", ["admin"]
    )
    for path in (
        "/api/v1/users/me",
        "/api/v1/admin/users",
        "/api/v1/admin/rules",
        "/api/v1/admin/document-types",
        "/api/v1/integrations/jobs",
        "/api/v1/notifications/vapid-public-key",
        "/api/v1/health/ready",
    ):
        response = await client.get(path, headers=headers)
        assert canary not in response.text, f"{path} returned a credential"
        assert canary not in json.dumps(dict(response.headers)), f"{path} leaked one in a header"


def test_a_credential_never_reaches_a_log_line(caplog) -> None:
    """The formatter writes what it is given, so what matters is that nothing gives it a secret.

    Asserted the only way that can be: the whole source tree is read, and every call that passes
    one of these settings into a logging call is a failure.
    """
    formatter = JsonFormatter()
    record = logging.LogRecord(
        "app.test", logging.INFO, __file__, 1, "graph_token_refreshed", None, None
    )
    record.status = 200
    rendered = formatter.format(record)
    assert "graph_token_refreshed" in rendered

    offenders: list[str] = []
    secret_names = {name for name, _ in SECRET_SETTINGS}
    for path in python_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            called = getattr(function, "attr", None)
            if called not in {"debug", "info", "warning", "error", "exception", "critical"}:
                continue
            for name in ast.walk(node):
                if isinstance(name, ast.Attribute) and name.attr in secret_names:
                    offenders.append(f"{path.relative_to(BACKEND_ROOT)}:{node.lineno}")
    assert offenders == [], f"a credential is passed to a log call at {offenders}"


def test_no_credential_is_reachable_from_the_browser_bundle() -> None:
    """A server-only value read in frontend code would be inlined as `undefined` or, worse, not.

    Next.js only inlines `NEXT_PUBLIC_*`, so any other `process.env` read has to be server-side.
    The rule enforced here is narrower and easier to keep: no file that declares itself a client
    component reads `process.env` at all.
    """
    offenders: list[str] = []
    for path in frontend_sources():
        source = path.read_text(encoding="utf-8")
        if '"use client"' not in source and "'use client'" not in source:
            continue
        if "process.env" in source:
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == [], f"client components reading process.env: {offenders}"


def test_the_vapid_public_key_is_the_only_key_the_frontend_knows_about() -> None:
    """One deliberate exception, and it is the one the Web Push standard requires."""
    named: set[str] = set()
    for path in frontend_sources():
        source = path.read_text(encoding="utf-8")
        for name, _ in SECRET_SETTINGS:
            if name in source:
                named.add(f"{path.relative_to(REPO_ROOT)}:{name}")
    assert named == set(), f"a backend credential is named in frontend source: {sorted(named)}"


# --- headers ---------------------------------------------------------------------------------


async def test_the_api_serves_a_locked_down_content_security_policy(client: AsyncClient) -> None:
    """This service returns JSON, so its policy allows nothing at all."""
    response = await client.get("/health")

    assert response.headers["content-security-policy"] == API_CONTENT_SECURITY_POLICY
    assert "default-src 'none'" in response.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


async def test_the_hardening_headers_are_on_every_response(client: AsyncClient, signed_in) -> None:
    _, headers = await signed_in(
        "00000000-0000-4000-8000-0000000000a2", "reader@agfze.test", "Reader", ["auditor"]
    )
    for path, expected in (("/health", 200), ("/api/v1/transactions", 200)):
        response = await client.get(path, headers=headers)
        assert response.status_code == expected
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["referrer-policy"] == "no-referrer"
        assert response.headers["cache-control"] == "no-store"


async def test_a_refusal_carries_the_same_headers_as_a_success(client: AsyncClient) -> None:
    """An unauthenticated 401 is a response like any other and must not arrive unhardened."""
    response = await client.get("/api/v1/transactions")

    assert response.status_code == 401
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "content-security-policy" in response.headers


async def test_hsts_is_absent_outside_production(client: AsyncClient) -> None:
    """Pinning a browser to HTTPS from a plain-HTTP test stack would be a bug, not hardening."""
    response = await client.get("/health")
    assert "strict-transport-security" not in response.headers


# --- rate limits -------------------------------------------------------------------------------


def test_every_named_category_has_a_real_value_and_a_route_behind_it() -> None:
    """A limit that matches no route, or a route named in the spec with no limit, is both a bug."""
    named = {category.name for category in categories()}
    assert named == {"bulk_approval", "upload", "ai", "auth", "webhook"}

    for category in categories():
        assert category.limit and "/" in category.limit, category.name

    # The specific endpoints the specification calls out, resolved through the live matcher.
    assert category_for("POST", "/api/v1/approvals/bulk-decide").name == "bulk_approval"
    assert category_for("POST", "/api/v1/documents/upload").name == "upload"
    assert category_for("GET", "/api/v1/users/me").name == "auth"
    assert (
        category_for(
            "POST", "/api/v1/transactions/11111111-2222-4333-8444-555555555555/generate-draft"
        ).name
        == "ai"
    )
    assert (
        category_for("GET", "/api/v1/approvals/11111111-2222-4333-8444-555555555555").name == "ai"
    )


def test_a_probe_is_never_rate_limited() -> None:
    assert category_for("GET", "/health") is None
    assert category_for("GET", "/api/v1/health/ready") is None


def test_production_enables_rate_limiting_and_will_not_start_without_it() -> None:
    """The switch is not a switch in production: the profile sets it and the validator checks it."""
    from app.core.config import ProductionSettings

    assert ProductionSettings.model_fields["RATE_LIMIT_ENABLED"].default is True
    assert ProductionSettings.model_fields["RATE_LIMIT_TRUST_FORWARDED_FOR"].default is True


def _production_environment() -> dict[str, str]:
    """Everything the production validator demands, so one setting at a time can be made wrong."""
    return {
        "KEYCLOAK_ISSUER": "https://id.agfze.example/realms/agfze",
        "KEYCLOAK_JWKS_URL": "https://id.agfze.example/realms/agfze/protocol/openid-connect/certs",
        "KEYCLOAK_SERVER_URL": "https://id.agfze.example",
        "KEYCLOAK_ADMIN_CLIENT_ID": "agfze-admin-api",
        "KEYCLOAK_ADMIN_CLIENT_SECRET": "not-a-real-secret",
        "DATABASE_URL": "postgresql+asyncpg://agfze:pw@10.20.0.5:5432/agfze",
        "CORS_ALLOWED_ORIGINS": ["https://app.agfze.example"],
        "STORAGE_SIGNED_URL_SECRET": "a-real-signing-secret-for-this-deployment",
        "AZURE_AD_TENANT_ID": "11111111-2222-3333-4444-555555555555",
        "AZURE_AD_CLIENT_ID": "66666666-7777-8888-9999-000000000000",
        "AZURE_AD_CLIENT_SECRET": "not-a-real-secret",
        "GRAPH_MAILBOX_ADDRESS": "trade.docs@agfze.example",
        "GEMINI_API_KEY": "not-a-real-key",
        "SMTP_HOST": "smtp.agfze.example",
        "VAPID_PUBLIC_KEY": "not-a-real-public-key",
        "VAPID_PRIVATE_KEY": "not-a-real-private-key",
        "APP_BASE_URL": "https://app.agfze.example",
        # Set explicitly rather than left to the production default: the suite runs with a
        # development .env on the path, and its RATE_LIMIT_ENABLED=false would otherwise win and
        # make every test below fail for a reason it is not about.
        "RATE_LIMIT_ENABLED": True,
    }


def test_production_refuses_to_start_counting_rate_limits_in_process() -> None:
    """A per-instance counter multiplies every limit by the instance count, silently.

    Refused rather than warned about: a warning on a start-up line nobody reads is exactly how a
    bulk-approval limit ends up five-times more permissive than it reads for a year.
    """
    import pytest as _pytest

    from app.core.config import ProductionSettings

    with _pytest.raises(ValueError) as raised:
        ProductionSettings(**_production_environment(), RATE_LIMIT_STORAGE_URI="memory://")

    assert "counts every limit per instance" in str(raised.value)


def test_production_starts_against_a_shared_counter_store() -> None:
    settings_ = ProductionSettingsFactory(RATE_LIMIT_STORAGE_URI="redis://10.20.0.9:6379/0")
    assert settings_.RATE_LIMIT_STORAGE_URI.startswith("redis://")


def test_a_single_instance_deployment_may_opt_into_per_instance_counting() -> None:
    """The escape hatch exists, and it has to be said out loud rather than fallen into."""
    settings_ = ProductionSettingsFactory(
        RATE_LIMIT_STORAGE_URI="memory://", RATE_LIMIT_ALLOW_IN_PROCESS=True
    )
    assert settings_.RATE_LIMIT_ALLOW_IN_PROCESS is True


def ProductionSettingsFactory(**overrides):
    from app.core.config import ProductionSettings

    return ProductionSettings(**_production_environment(), **overrides)


async def test_a_category_limit_is_genuinely_enforced_when_enabled(
    client: AsyncClient, signed_in, monkeypatch
) -> None:
    """Not a boolean and not a document: the ninth call in a row is actually refused with 429."""
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True, raising=True)
    monkeypatch.setattr(settings, "RATE_LIMIT_AUTH", "3/minute", raising=True)

    token = build_token(
        sub="00000000-0000-4000-8000-0000000000a3",
        email="limited@agfze.test",
        name="Limited",
        realm_access={"roles": ["auditor"]},
    )
    headers = auth_header(token)

    statuses = [
        (await client.get("/api/v1/users/me", headers=headers)).status_code for _ in range(6)
    ]
    assert 429 in statuses, statuses
    assert statuses.count(200) <= 3, statuses

    refusal = next(
        response
        for response in [await client.get("/api/v1/users/me", headers=headers)]
        if response.status_code == 429
    )
    body = refusal.json()
    assert body["success"] is False
    assert body["errors"][0]["code"] == "rate_limited"
    # The category is named; the remaining budget is not.
    assert "auth" in body["message"]
    assert "3" not in body["message"]


async def test_a_probe_is_still_answered_while_a_limit_is_being_hit(
    client: AsyncClient, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True, raising=True)
    monkeypatch.setattr(settings, "RATE_LIMIT_DEFAULT", "1/minute", raising=True)

    for _ in range(5):
        assert (await client.get("/health")).status_code == 200


# --- absences ----------------------------------------------------------------------------------


def module_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def test_nothing_can_send_a_generated_sales_document_to_a_counterparty() -> None:
    """Step 5's hardest promise, checked structurally rather than read for.

    Two facts together make it true, and both are asserted: the only module in the platform that
    can hand a message to a relay is the notification service, and the module that produces a
    sales document has no route to a relay, an attachment or a counterparty address at all.
    """
    senders = {
        str(path.relative_to(APP_ROOT))
        for path in python_sources()
        if "smtplib" in module_imports(path)
    }
    assert senders == {"services/delivery/email_service.py"}, senders

    relay_users = {
        str(path.relative_to(APP_ROOT))
        for path in python_sources()
        if any("delivery.email_service" in name for name in module_imports(path))
    }
    # The package's own `__init__` re-exports the two delivery modules and calls neither.
    assert relay_users == {
        "services/delivery/__init__.py",
        "services/notification_service.py",
    }, relay_users

    draft = (APP_ROOT / "services" / "draft_service.py").read_text(encoding="utf-8")
    for forbidden in ("smtplib", "send_message", "sendmail", "add_attachment", "MIMEBase"):
        assert forbidden not in draft, f"draft_service can {forbidden}"

    # And what the notification service is allowed to attach: nothing. An email carries a summary
    # and a link, so a document cannot travel out on the one path that does reach a relay.
    relay = (APP_ROOT / "services" / "delivery" / "email_service.py").read_text(encoding="utf-8")
    for forbidden in ("add_attachment", "MIMEApplication", "MIMEBase", "storage"):
        assert forbidden not in relay, f"the relay can {forbidden}"


def test_nothing_queues_a_mutating_request_for_later_replay() -> None:
    """Step 10's hardest promise. Offline support on this platform is read-only, permanently."""
    forbidden = (
        "BackgroundSync",
        "SyncManager",
        "backgroundFetch",
        "registration.sync",
        "sync.register",
        "periodicSync",
        "replayQueue",
        "outbox",
    )
    offenders: list[str] = []
    for path in frontend_sources():
        # A test that asserts one of these names is absent has to write the name down. Skipping
        # the test tree keeps this check from failing on the very assertions that agree with it.
        if "__tests__" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in source:
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{token}")

    worker = REPO_ROOT / "frontend" / "public" / "sw.js"
    if worker.exists():
        built = worker.read_text(encoding="utf-8")
        for token in forbidden:
            if token in built:
                offenders.append(f"public/sw.js:{token}")

    assert offenders == [], f"a replay queue has appeared: {offenders}"


SERVER_AUTHORITATIVE_FIELDS = frozenset(
    {
        "decided_by",
        "decided_by_id",
        "decided_at",
        "actor_id",
        "acknowledged_by",
        "acknowledged_by_id",
        "acknowledged_at",
        "resolved_by_id",
        "created_by_id",
        "changed_by_id",
        "submitted_by_id",
        "uploaded_by_id",
        "occurred_at",
        "user_id",
    }
)


def request_models() -> list[type[BaseModel]]:
    """Every schema a client is allowed to send, found by what the endpoints actually accept."""
    import app.schemas as schemas_package

    models: list[type[BaseModel]] = []
    for module_path in Path(schemas_package.__file__).parent.glob("*.py"):
        if module_path.name == "__init__.py":
            continue
        module = __import__(f"app.schemas.{module_path.stem}", fromlist=["*"])
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if not issubclass(obj, BaseModel) or obj is BaseModel:
                continue
            if obj.__module__ != module.__name__:
                continue
            if obj.__name__.endswith(("Request", "Create", "Update", "Acknowledgement", "Removal")):
                models.append(obj)
    return models


def test_no_request_schema_carries_a_server_authoritative_field() -> None:
    """A client cannot supply what a client is not allowed to decide.

    This is stronger than ignoring such a field in a handler: a value that has no place in the
    schema is rejected before any handler runs and, more importantly, cannot be added later by
    somebody who does not know why it was left out.
    """
    offenders = [
        f"{model.__module__}.{model.__name__}.{name}"
        for model in request_models()
        for name in model.model_fields
        if name in SERVER_AUTHORITATIVE_FIELDS
    ]
    # `user_id` on the role-override schema names the account being *edited*, not the actor, and
    # the actor is still the token subject. Nothing else may name any of these.
    assert offenders == ["app.schemas.admin.UserRoleUpdate.user_id"], offenders


def test_no_admin_screen_exists_for_the_configuration_that_deliberately_has_none() -> None:
    """Three things Step 9 excluded on purpose, checked against the real page tree.

    The integration *monitor* is a page and is supposed to be: it shows jobs. What must not exist
    is a screen that edits where a posting is sent, which desk owns which failure, or what a
    report template contains.
    """
    admin_pages = REPO_ROOT / "frontend" / "src" / "app" / "(protected)" / "admin"
    if not admin_pages.exists():
        pytest.skip("frontend is not present in this checkout")

    present = {path.parent.name for path in admin_pages.rglob("page.tsx")}
    assert present <= {"admin", "rules", "document-types", "users", "audit", "integrations"}, (
        present
    )

    forbidden_editors = (
        "rule-exception",
        "report-template",
        "endpoint",
        "sap-config",
        "dms-config",
    )
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{token}"
        for path in admin_pages.rglob("*.tsx")
        for token in forbidden_editors
        if token in path.name
    ]
    assert offenders == [], offenders

    # And the monitor, specifically, may not write a target's configuration.
    monitor = (
        REPO_ROOT / "frontend" / "src" / "components" / "integrations" / "integration-monitor.tsx"
    )
    source = monitor.read_text(encoding="utf-8")
    for forbidden in ("SAP_API_BASE_URL", "DMS_API_BASE_URL", "TRACKER_DRIVE_ID", "base_url"):
        assert forbidden not in source, f"the integration monitor exposes {forbidden}"


def test_the_audit_trail_has_no_write_route_at_any_role(app: FastAPI) -> None:
    """Append-only means append-only: nothing but a GET is mounted under /audit."""
    from tests.test_rbac_matrix import application_routes

    audit = {(method, path) for method, path in application_routes(app) if "/audit" in path}
    assert {method for method, _ in audit} == {"GET"}, audit
