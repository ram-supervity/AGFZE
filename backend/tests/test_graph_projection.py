"""The Neo4j projection: what it holds, what it refuses to hold, and what it never becomes.

Every test here runs against a fake driver. That is not a compromise - a real Neo4j in CI would
test the driver rather than this code, and the properties worth defending are all properties of
this module: that the projection is derived and never authoritative, that a store being absent or
unreachable changes no behaviour anywhere, and that there is no path from a request to a Cypher
string.

The last of those is the one that would matter most if it were ever wrong, so it is asserted
directly against the module's own source rather than through its behaviour.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services import graph_sync_worker, neo4j_service
from app.services.neo4j_service import (
    GraphNode,
    GraphRelationship,
    GraphUnavailableError,
    Neo4jClient,
)
from tests.utils.governance import seeded_transaction

pytestmark = pytest.mark.usefixtures("patched_jwks")


class FakeSession:
    def __init__(self, store: FakeDriver) -> None:
        self._store = store

    async def __aenter__(self) -> FakeSession:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def run(self, query: str, **params: object):
        if self._store.fail:
            raise RuntimeError("bolt://graph.internal:7687 refused the connection")
        self._store.queries.append((query, params))

        rows = self._store.rows

        class _Result:
            def __aiter__(self):
                async def _iterate():
                    for row in rows:
                        yield row

                return _iterate()

        return _Result()


class FakeDriver:
    def __init__(self) -> None:
        self.queries: list[tuple[str, dict]] = []
        self.rows: list[dict] = []
        self.fail = False

    def session(self, **_kwargs: object) -> FakeSession:
        return FakeSession(self)

    async def close(self) -> None:
        return None


@pytest.fixture
def driver() -> FakeDriver:
    return FakeDriver()


@pytest.fixture
def graph_client(driver: FakeDriver) -> Neo4jClient:
    """Named to stay clear of conftest's `client`, which is the HTTP one every API test uses."""
    return Neo4jClient(driver=driver)


# --- what the projection is allowed to contain ----------------------------------------------------


async def test_a_label_outside_the_declared_set_is_refused(graph_client: Neo4jClient) -> None:
    """A label cannot be a bound parameter in Cypher - it is interpolated into the query text.

    Checking membership before the statement is built is the whole of what stops this module
    becoming an injection surface, so it is asserted rather than assumed.
    """
    with pytest.raises(GraphUnavailableError):
        await graph_client.upsert_nodes([GraphNode("DROP DATABASE", "x", {})])


async def test_a_relationship_outside_the_declared_set_is_refused(
    graph_client: Neo4jClient,
) -> None:
    with pytest.raises(GraphUnavailableError):
        await graph_client.upsert_relationships(
            [GraphRelationship("TradeTransaction", "a", "SOMETHING_INVENTED", "Document", "b")]
        )


async def test_nodes_are_merged_on_the_relational_key_rather_than_created(
    graph_client: Neo4jClient, driver: FakeDriver
) -> None:
    """MERGE is what makes the worker safe to re-run and a rebuild safe over a populated store."""
    await graph_client.upsert_nodes([GraphNode("Document", "doc-1", {"filename": "invoice.pdf"})])

    query, params = driver.queries[0]
    assert "MERGE (n:Document {key: row.key})" in query
    assert "CREATE" not in query
    assert params["rows"] == [{"key": "doc-1", "properties": {"filename": "invoice.pdf"}}]


async def test_a_traversal_depth_is_clamped_before_it_reaches_the_driver(
    graph_client: Neo4jClient, driver: FakeDriver
) -> None:
    """The depth is interpolated because Cypher will not bind it, so its bound has to be real."""
    await graph_client.subgraph("tx-1", depth=99)

    query, _params = driver.queries[0]
    assert f"[*1..{neo4j_service.MAX_TRAVERSAL_DEPTH}]" in query


async def test_there_is_no_general_query_function_on_the_client() -> None:
    """The property that keeps an internal read model from acquiring an ad-hoc query endpoint.

    If a `run`/`query`/`execute` ever becomes public here, the next  is somebody passing it a
    string from a request. Deleting this test is the deliberate act that would have to precede it.
    """
    public = {name for name in dir(Neo4jClient) if not name.startswith("_")}
    assert public == {"upsert_nodes", "upsert_relationships", "subgraph", "clear", "close"}


# --- what the sync worker projects ------------------------------------------------------------------


async def test_a_transaction_projects_its_legs_and_its_counterparties(
    db_session: AsyncSession,
) -> None:
    transaction = await seeded_transaction(db_session, batch_number="I2626-G1")
    transaction.purchase_leg.supplier_name = "Emirates Metal Trading LLC"
    await db_session.commit()

    nodes, edges = graph_sync_worker.project_transaction(transaction)
    labels = {node.label for node in nodes}

    assert "TradeTransaction" in labels
    assert "PurchaseLeg" in labels
    assert "Supplier" in labels
    assert any(edge.type == "ISSUED_BY" for edge in edges)
    assert any(edge.type == "HAS_PURCHASE_LEG" for edge in edges)

    supplier = next(node for node in nodes if node.label == "Supplier")
    # The same short code the transaction list shows, from the same function.
    assert supplier.properties["code"] == "EMMETR"


async def test_a_projected_node_carries_no_commercial_figures(
    db_session: AsyncSession,
) -> None:
    """Copying the money in would make the projection look like a place to read it from.

    It is a derived read model that can lag or be rebuilt at any moment. Every value it holds is
    an identifier or a label; the figures are read from PostgreSQL, always.
    """
    transaction = await seeded_transaction(db_session, batch_number="I2626-G2")
    nodes, _edges = graph_sync_worker.project_transaction(transaction)

    for node in nodes:
        for forbidden in ("amount", "rate", "value", "price", "quantity"):
            assert forbidden not in node.properties, (
                f"{node.label} carries '{forbidden}'. The projection is not a place to read a "
                "figure from - see the module docstring."
            )


async def test_the_sweep_writes_nodes_before_the_relationships_that_need_them(
    db_session: AsyncSession, graph_client: Neo4jClient, driver: FakeDriver
) -> None:
    """An edge MATCHes both ends, so projecting it first silently writes nothing at all."""
    await seeded_transaction(db_session, batch_number="I2626-G3")
    await db_session.commit()

    result = await graph_sync_worker.sync_once(db_session, graph_client, since=None, limit=100)

    assert result.considered > 0
    assert result.nodes > 0
    merges = [query for query, _ in driver.queries]
    first_edge = next(i for i, q in enumerate(merges) if "MERGE (a)-[:" in q)
    assert any("MERGE (n:" in q for q in merges[:first_edge])


async def test_the_sweep_advances_its_watermark(
    db_session: AsyncSession, graph_client: Neo4jClient
) -> None:
    await seeded_transaction(db_session, batch_number="I2626-G4")
    await db_session.commit()

    first = await graph_sync_worker.sync_once(db_session, graph_client, since=None, limit=100)
    assert first.watermark is not None

    # Nothing has changed since, so a second sweep from that watermark projects nothing.
    second = await graph_sync_worker.sync_once(
        db_session, graph_client, since=first.watermark, limit=100
    )
    assert second.considered == 0


async def test_an_unreachable_store_raises_the_modules_own_error_without_leaking_the_uri(
    db_session: AsyncSession, graph_client: Neo4jClient, driver: FakeDriver
) -> None:
    """The driver's message carries the bolt URI and, on an auth failure, more than that."""
    await seeded_transaction(db_session, batch_number="I2626-G5")
    await db_session.commit()
    driver.fail = True

    with pytest.raises(GraphUnavailableError) as raised:
        await graph_sync_worker.sync_once(db_session, graph_client, since=None, limit=100)

    assert "bolt://" not in str(raised.value)
    assert "graph.internal" not in str(raised.value)


# --- the endpoint ---------------------------------------------------------------------------------


async def purchase_user(signed_in):
    return await signed_in(
        "0a1b2c3d-0000-4000-8000-00000000a001",
        "purchase.graph@agfze.ae",
        "Ana Ferreira",
        ["purchase_user"],
    )


async def test_the_trace_says_it_is_unavailable_rather_than_showing_an_empty_diagram(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    """No store configured is the shipped state, and "unavailable" and "unconnected" differ.

    Rendering an empty graph would tell somebody this transaction is connected to nothing, which
    is a claim about their deal rather than about the deployment.
    """
    _user, headers = await purchase_user(signed_in)
    transaction = await seeded_transaction(db_session, batch_number="I2626-G6")
    await db_session.commit()

    response = await client.get(f"/api/v1/transactions/{transaction.id}/graph", headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()["data"]
    assert body["available"] is False
    assert body["nodes"] == []
    assert "no graph projection is configured" in response.json()["message"].lower()


async def test_the_trace_is_scoped_by_the_same_rules_as_the_transaction_itself(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    """Access is decided against PostgreSQL. The projection carries no permissions of its own.

    A caller who cannot see the transaction is refused before the graph is consulted at all, so
    there is no version of this where the read model becomes a way around the scoping.
    """
    _user, headers = await purchase_user(signed_in)
    missing = "11111111-2222-4333-8444-555555555555"

    response = await client.get(f"/api/v1/transactions/{missing}/graph", headers=headers)
    assert response.status_code == 404


async def test_the_traversal_depth_is_bounded_by_the_schema(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    _user, headers = await purchase_user(signed_in)
    transaction = await seeded_transaction(db_session, batch_number="I2626-G7")
    await db_session.commit()

    too_deep = await client.get(
        f"/api/v1/transactions/{transaction.id}/graph?depth=99", headers=headers
    )
    assert too_deep.status_code == 422

    fine = await client.get(f"/api/v1/transactions/{transaction.id}/graph?depth=2", headers=headers)
    assert fine.status_code == 200


async def test_the_endpoint_takes_no_query_text_of_any_kind() -> None:
    """There is no Cypher on this path, and there must never be one.

    An internal read model acquires an arbitrary-query surface exactly once: when somebody adds a
    convenient parameter to the one endpoint that reads it.
    """
    from app.api.v1 import transactions

    route = next(
        r for r in transactions.router.routes if str(r.path).endswith("/{transaction_id}/graph")
    )
    parameters = set(
        route.dependant.query_params and [p.name for p in route.dependant.query_params]
    )
    assert parameters == {"depth"}


# --- the shipped state ------------------------------------------------------------------------------


def test_the_projection_is_off_and_unconfigured_by_default() -> None:
    from app.core.config import Settings

    assert Settings.model_fields["GRAPH_SYNC_ENABLED"].default is False
    assert Settings.model_fields["NEO4J_URI"].default == ""
    assert settings.neo4j_configured is False


def test_the_worker_will_not_run_without_both_a_flag_and_a_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "GRAPH_SYNC_ENABLED", True)
    monkeypatch.setattr(settings, "ENV", "production")
    # Enabled but unconfigured is an intention, not a deployment.
    assert graph_sync_worker.should_run() is False


def test_the_graph_store_name_is_not_confusable_with_microsoft_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`graph_configured` already means the mailbox API, and the two must stay independent.

    Two properties a letter apart meaning different integrations is how somebody eventually gates
    the mailbox poller on Neo4j being reachable. Asserted by moving one and checking the other
    does not follow, rather than by reading their names.
    """
    monkeypatch.setattr(settings, "NEO4J_URI", "bolt://graph.internal:7687")
    monkeypatch.setattr(settings, "NEO4J_USER", "neo4j")
    monkeypatch.setattr(settings, "NEO4J_PASSWORD", "not-a-real-password")
    assert settings.neo4j_configured is True

    # Configuring the graph store must not make the mailbox look configured, or the other way.
    monkeypatch.setattr(settings, "AZURE_AD_CLIENT_SECRET", "")
    assert settings.graph_configured is False
    assert settings.neo4j_configured is True
