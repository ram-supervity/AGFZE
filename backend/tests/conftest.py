"""Test bootstrap for the backend suite.

PostgreSQL is the real target: `make test-backend` and CI point TEST_DATABASE_URL at the
`agfze_test` database created by the compose stack, which is the engine the application actually
ships on. When TEST_DATABASE_URL is unset the suite falls back to a disposable SQLite file in the
system temp directory so a container-less checkout can still run it; that file is deleted and rebuilt from scratch
at the start of every session and carries no meaning between runs.

Either way the schema comes from Alembic. A schema built straight off the model metadata would
only prove the models agree with themselves, and would say nothing about whether the migrations
that run against a real database are correct.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from collections.abc import AsyncIterator, Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from alembic.config import Config
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import bindparam, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from alembic import command

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# Settings are resolved once, at import time, so the environment has to be final before anything
# under app.* is imported. That is why the first-party imports sit below this block.
os.environ["ENV"] = "testing"
# The fallback lives in the OS temp directory rather than the source tree: it is disposable by
# definition, and ./var is a mount point in the container image, so writing there depends on which
# uid happens to be running.
_SQLITE_FALLBACK = f"sqlite+aiosqlite:///{Path(tempfile.gettempdir()) / 'agfze-test.db'}"
# An empty value counts as unset: `TEST_DATABASE_URL=` in a shell or a compose file means "no
# database was chosen", not "migrate against the empty string".
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "").strip() or _SQLITE_FALLBACK
os.environ["TEST_DATABASE_URL"] = TEST_DATABASE_URL
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ.setdefault("KEYCLOAK_ISSUER", "https://keycloak.test/realms/agfze")
os.environ.setdefault(
    "KEYCLOAK_JWKS_URL", "https://keycloak.test/realms/agfze/protocol/openid-connect/certs"
)
# Graph and Gemini credentials are deliberately absent: the suite proves the intake logic against
# mocked boundaries, and must keep passing on a machine that has neither. What is set here is only
# the non-secret configuration the code reads to build a URL or pick a threshold.
os.environ.setdefault("AZURE_AD_TENANT_ID", "11111111-2222-3333-4444-555555555555")
os.environ.setdefault("AZURE_AD_CLIENT_ID", "66666666-7777-8888-9999-000000000000")
os.environ.setdefault("AZURE_AD_CLIENT_SECRET", "test-client-secret-not-a-real-credential")
os.environ.setdefault("GRAPH_MAILBOX_ADDRESS", "trade.docs@agfze.test")
os.environ.setdefault("GRAPH_POLL_ENABLED", "false")
os.environ.setdefault("GRAPH_WEBHOOK_CLIENT_STATE", "test-client-state")
os.environ.setdefault("CONFIDENCE_THRESHOLD_DEFAULT", "0.75")

from app.core.security import TokenError, jwks_client  # noqa: E402
from app.db.session import get_session  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import Base, User  # noqa: E402
from app.services.storage.factory import get_storage_service  # noqa: E402
from app.services.storage.local import LocalFileSystemStorage  # noqa: E402
from tests.utils.tokens import (  # noqa: E402
    JWKS,
    auth_header,
    build_token,
)


def _sqlite_file(url: str) -> Path | None:
    """The on-disk file behind a SQLite URL, or None for any other dialect or :memory:."""
    if not url.startswith("sqlite"):
        return None
    _, _, location = url.partition(":///")
    if not location or location.startswith(":memory:"):
        return None
    return Path(location)


def _alembic_config() -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    # ConfigParser treats '%' as interpolation, and URL-encoded credentials contain it.
    config.set_main_option("sqlalchemy.url", TEST_DATABASE_URL.replace("%", "%%"))
    return config


def _run_off_loop(func: Any, *args: Any) -> Any:
    """alembic/env.py drives an async engine on an event loop of its own, so keep it off ours.

    Also used by the seeded-configuration snapshot, which is session-scoped and so cannot borrow
    the function-scoped event loop the tests themselves run on.
    """
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(func, *args).result()


@pytest.fixture(scope="session", autouse=True)
def database_schema() -> None:
    sqlite_file = _sqlite_file(TEST_DATABASE_URL)
    if sqlite_file is None:
        _run_off_loop(command.downgrade, _alembic_config(), "base")
    else:
        sqlite_file.parent.mkdir(parents=True, exist_ok=True)
        sqlite_file.unlink(missing_ok=True)
    _run_off_loop(command.upgrade, _alembic_config(), "head")


@pytest.fixture
async def db_engine(database_schema: None) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    try:
        yield engine
    finally:
        await engine.dispose()


# Reference data written by a migration, not by a test. Wiping it between tests would leave the
# database in a state the application can never actually be in: every schema lookup would fail,
# and every rule would report itself unconfigured, against tables that are seeded on every real
# deployment.
SEEDED_TABLES = frozenset(
    {
        "document_type_schemas",
        "commodity_codes",
        "rule_configurations",
        # The rule-to-exception mapping is reference data on exactly the same footing: wiping it
        # would leave the engine unable to categorise any failure, which is a state no real
        # deployment can be in.
        "rule_exception_mappings",
    }
)


# The seeded tables are preserved between tests, but they are no longer read-only: Step 9 makes
# `rule_configurations` and `document_type_schemas` genuinely editable, so a test that exercises
# an admin edit changes reference data every later test reads. These are the columns such an edit
# can move, per table; everything else on those rows is identity and is never written.
EDITABLE_SEEDED_COLUMNS: dict[str, tuple[str, ...]] = {
    "rule_configurations": (
        "threshold_value",
        "threshold_unit",
        "description",
        "is_active",
        "change_reason",
        "changed_by_id",
    ),
    "document_type_schemas": (
        "field_schema",
        "mandatory_documents",
        "change_reason",
        "changed_by_id",
    ),
}


async def _read_seeded_configuration() -> dict[str, list[dict[str, Any]]]:
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    try:
        snapshot: dict[str, list[dict[str, Any]]] = {}
        async with engine.connect() as connection:
            for name, columns in EDITABLE_SEEDED_COLUMNS.items():
                table = Base.metadata.tables[name]
                selected = [table.c.id, *(table.c[column] for column in columns)]
                rows = await connection.execute(select(*selected))
                snapshot[name] = [dict(row._mapping) for row in rows]
        return snapshot
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def seeded_configuration(database_schema: None) -> dict[str, list[dict[str, Any]]]:
    """The configuration exactly as the migrations wrote it, read once before any test runs.

    Taken at session scope on purpose: snapshotting per test would capture whatever the previous
    test left behind, which is the drift this exists to undo. Read on its own event loop in a
    worker thread, the same way the Alembic run above is, because a session-scoped fixture cannot
    borrow the function-scoped loop the tests themselves run on.
    """
    return _run_off_loop(lambda: asyncio.run(_read_seeded_configuration()))


@pytest.fixture(autouse=True)
async def clean_tables(
    db_engine: AsyncEngine, seeded_configuration: dict[str, list[dict[str, Any]]]
) -> None:
    async with db_engine.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            if table.name in SEEDED_TABLES:
                continue
            await connection.execute(table.delete())

        # Put the editable reference data back the way the migrations left it. Rows a test added
        # go; rows a test changed are restored. Without this, one admin test's threshold edit
        # would silently become every later test's configuration.
        #
        # Only rows that actually differ are rewritten, which for almost every test in the suite
        # means nothing is written at all. That is not only cheaper: rewriting an unchanged row on
        # PostgreSQL produces a new row version and moves it in physical order, and a query
        # without an ORDER BY would start returning a different row of a multi-row set for no
        # reason a reader could see.
        for name, seeded in seeded_configuration.items():
            if not seeded:
                continue
            table = Base.metadata.tables[name]
            columns = EDITABLE_SEEDED_COLUMNS[name]

            await connection.execute(
                table.delete().where(table.c.id.notin_([row["id"] for row in seeded]))
            )
            live = {
                row.id: row._mapping
                for row in await connection.execute(
                    select(table.c.id, *(table.c[column] for column in columns))
                )
            }
            drifted = [
                {"row_id": row["id"], **{column: row[column] for column in columns}}
                for row in seeded
                if row["id"] not in live
                or any(live[row["id"]][column] != row[column] for column in columns)
            ]
            if drifted:
                await connection.execute(
                    table.update()
                    .where(table.c.id == bindparam("row_id"))
                    .values({column: bindparam(column) for column in columns}),
                    drifted,
                )


@pytest.fixture(autouse=True)
async def background_task_isolation():
    """Wait for any background work a test started, then release the engine it ran on.

    Draft generation and report generation both run as real `asyncio` tasks on their own sessions,
    taken from the application's own engine rather than from the test engine - which is exactly
    how they run in production and exactly why the suite has to tidy up after them. A task still
    holding a connection when its event loop closes leaves that connection orphaned in the shared
    pool, and the next test to draw it gets a failure that has nothing to do with what it is
    testing.
    """
    yield
    from app.db import session as db_session_module
    from app.services import draft_service
    from app.services.analytics import report_service

    pending = [
        task
        for source in (draft_service._BACKGROUND_TASKS, report_service._BACKGROUND_TASKS)
        for task in list(source)
    ]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    await db_session_module.engine.dispose()


@pytest.fixture(autouse=True)
def dashboard_cache_isolation():
    """The aggregate cache is process-global, so it has to be emptied between tests.

    Left alone it would do exactly what it is designed to do - serve one test's figures to the
    next - and a suite that proved its KPIs against a neighbour's cached payload would prove
    nothing at all.
    """
    from app.services.analytics.cache import dashboard_cache

    dashboard_cache().clear()
    yield
    dashboard_cache().clear()


@pytest.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """A session on its own connection, independent of the one the API uses.

    Tests commit (or roll back) before handing control back to the HTTP client: on the SQLite
    fallback an open read transaction blocks the application's writer, and on PostgreSQL it would
    hold a snapshot taken before the request ran.
    """
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session


@pytest.fixture
def app(db_engine: AsyncEngine) -> Iterator[FastAPI]:
    application = create_app()
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)

    async def _session_override() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    application.dependency_overrides[get_session] = _session_override
    yield application
    application.dependency_overrides.clear()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http_client:
        yield http_client


@pytest.fixture
def patched_jwks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Serve the test key set locally. Signature and claim verification still run for real."""

    async def _get_key(kid: str) -> dict[str, str]:
        for jwk in JWKS["keys"]:
            if jwk["kid"] == kid:
                return jwk
        raise TokenError("Signing key is not published by the identity provider.")

    monkeypatch.setattr(jwks_client, "get_key", _get_key)


@pytest.fixture(autouse=True)
def storage_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LocalFileSystemStorage:
    """A fresh storage root per test, so no document survives into the next one."""
    storage = LocalFileSystemStorage(
        str(tmp_path / "storage"),
        signing_secret="intake-test-signing-secret",
        base_url="http://testserver/internal/files",
        default_ttl_seconds=900,
    )
    get_storage_service.cache_clear()
    # Every consumer binds the factory by name at import time, so each binding is replaced
    # rather than only the one in the factory module.
    for module in (
        "app.services.storage.factory",
        "app.services.storage",
        "app.services.document_service",
        "app.services.draft_service",
        "app.services.analytics.report_service",
        "app.services.integration.document_packs",
        "app.services.integration.dms",
        "app.services.email_ingestion",
        "app.services.mailbox_worker",
        "app.api.v1.documents",
        "app.api.v1.requests",
        "app.api.v1.transactions",
        "app.api.internal.files",
    ):
        monkeypatch.setattr(f"{module}.get_storage_service", lambda: storage, raising=True)
    return storage


@pytest.fixture
async def signed_in(client: AsyncClient, db_session: AsyncSession):
    """Provision an account with the requested roles and hand back the row and its header."""

    async def _provision(
        subject_id: str,
        email: str,
        name: str,
        roles: list[str],
    ) -> tuple[User, dict[str, str]]:
        token = build_token(sub=subject_id, email=email, name=name, realm_access={"roles": roles})
        headers = auth_header(token)
        response = await client.get("/api/v1/users/me", headers=headers)
        assert response.status_code == 200, response.text

        user = (await db_session.scalars(select(User).where(User.subject_id == subject_id))).one()
        await db_session.commit()
        return user, headers

    return _provision
