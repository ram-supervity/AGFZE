"""The client wrapper for the graph projection, and the boundary that keeps it a projection.

Two rules are enforced here rather than left to whoever writes the next caller.

**Nothing outside this module writes Cypher.** The three functions below are the whole surface:
upsert a batch of nodes, upsert a batch of relationships, and read one bounded subgraph. There is
no `run(query)`, and there must never be one - a general query function is how an "internal only"
graph store acquires an endpoint that takes a query string from a request.

**The graph is never authoritative.** Every node here is keyed by the relational row's own primary
key and carries only what that row already says. Nothing reads a value back out of the graph to
make a decision; the traversal endpoint returns identifiers and labels for a person to look at, and
the detail behind any of them is read from PostgreSQL as it always was. If the two disagree, the
relational store is right and the projection is stale - which is a rebuild, not an incident.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class GraphUnavailableError(Exception):
    """The graph store could not be reached or refused the request.

    Always caught by the sync worker, which logs it and tries again on the next sweep. A projection
    that is briefly behind is not a fault worth stopping a process over.
    """


@dataclass(frozen=True)
class GraphNode:
    label: str
    key: str
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GraphRelationship:
    start_label: str
    start_key: str
    type: str
    end_label: str
    end_key: str


# Every label and relationship type the projection may contain. Membership is checked before any
# statement is built, because a label or type cannot be a bound parameter in Cypher - it is
# interpolated into the query text, and interpolating an unchecked string into a query is the one
# way this module could become an injection surface.
NODE_LABELS: frozenset[str] = frozenset(
    {
        "EmailMessage",
        "Document",
        "TradeTransaction",
        "PurchaseLeg",
        "SalesLeg",
        "FaLeg",
        "Container",
        "Shipment",
        "Supplier",
        "Customer",
        "ApprovalTask",
        "ExceptionCase",
        "IntegrationJob",
        "DocumentPack",
    }
)

RELATIONSHIP_TYPES: frozenset[str] = frozenset(
    {
        "HAS_ATTACHMENT",
        "EXTRACTED_AS",
        "HAS_PURCHASE_LEG",
        "HAS_SALES_LEG",
        "HAS_FA_LEG",
        "ISSUED_BY",
        "SOLD_TO",
        "HAS_CONTAINER",
        "SHIPPED_UNDER",
        "REQUIRES",
        "HAS_EXCEPTION",
        "COMMITTED_TO",
    }
)


def _check_label(label: str) -> str:
    if label not in NODE_LABELS:
        raise GraphUnavailableError(f"'{label}' is not a node label this projection defines.")
    return label


def _check_type(name: str) -> str:
    if name not in RELATIONSHIP_TYPES:
        raise GraphUnavailableError(f"'{name}' is not a relationship this projection defines.")
    return name


class Neo4jClient:
    """A thin wrapper over the official driver, constructed lazily and once.

    Lazily because a deployment with `GRAPH_SYNC_ENABLED` off - which is every deployment today -
    has no reason to hold a driver, and because building one at import time would make the test
    suite and every management command try to open a connection.
    """

    def __init__(self, driver: Any | None = None) -> None:
        self._driver = driver

    def _get_driver(self) -> Any:
        if self._driver is None:
            if not settings.neo4j_configured:
                raise GraphUnavailableError(
                    "No graph store is configured. Set NEO4J_URI, NEO4J_USER and NEO4J_PASSWORD."
                )
            try:
                from neo4j import AsyncGraphDatabase
            except ImportError as exc:  # pragma: no cover - depends on the install profile
                raise GraphUnavailableError(
                    "The graph projection needs the neo4j driver installed."
                ) from exc
            self._driver = AsyncGraphDatabase.driver(
                settings.NEO4J_URI,
                auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
            )
        return self._driver

    async def _run(self, query: str, **params: Any) -> list[dict[str, Any]]:
        driver = self._get_driver()
        try:
            async with driver.session(database=settings.NEO4J_DATABASE) as session:
                result = await session.run(query, **params)
                return [dict(record) async for record in result]
        except GraphUnavailableError:
            raise
        except Exception as exc:
            # The driver's message can carry the URI and, on an auth failure, enough to identify
            # the credential. It goes to the log; the caller gets the fact and nothing else.
            logger.exception("graph.query_failed")
            raise GraphUnavailableError("The graph store could not be reached.") from exc

    async def upsert_nodes(self, nodes: list[GraphNode]) -> int:
        """MERGE on the relational primary key, then overwrite the properties.

        MERGE rather than CREATE so a sweep that re-reads a row it has already projected updates
        it instead of duplicating it - which is what makes the worker safe to re-run, and what
        makes a full rebuild safe to run over a populated store.
        """
        written = 0
        by_label: dict[str, list[GraphNode]] = {}
        for node in nodes:
            by_label.setdefault(_check_label(node.label), []).append(node)

        for label, rows in by_label.items():
            await self._run(
                f"UNWIND $rows AS row MERGE (n:{label} {{key: row.key}}) SET n += row.properties",
                rows=[{"key": row.key, "properties": row.properties} for row in rows],
            )
            written += len(rows)
        return written

    async def upsert_relationships(self, edges: list[GraphRelationship]) -> int:
        written = 0
        grouped: dict[tuple[str, str, str], list[GraphRelationship]] = {}
        for edge in edges:
            key = (
                _check_label(edge.start_label),
                _check_type(edge.type),
                _check_label(edge.end_label),
            )
            grouped.setdefault(key, []).append(edge)

        for (start, name, end), rows in grouped.items():
            await self._run(
                f"UNWIND $rows AS row "
                f"MATCH (a:{start} {{key: row.start}}), (b:{end} {{key: row.end}}) "
                f"MERGE (a)-[:{name}]->(b)",
                rows=[{"start": row.start_key, "end": row.end_key} for row in rows],
            )
            written += len(rows)
        return written

    async def subgraph(self, transaction_id: str, *, depth: int) -> dict[str, Any]:
        """One transaction and what is reachable from it, to a fixed depth.

        The depth is interpolated because Cypher does not accept a bound parameter inside a
        variable-length pattern. It is coerced to an int and clamped by the caller before it
        arrives here, so what is interpolated is a small integer and never request text.
        """
        bounded = max(1, min(int(depth), MAX_TRAVERSAL_DEPTH))
        rows = await self._run(
            "MATCH (t:TradeTransaction {key: $key}) "
            f"OPTIONAL MATCH path = (t)-[*1..{bounded}]-(related) "
            "WITH t, collect(DISTINCT related) AS nodes, collect(DISTINCT relationships(path)) "
            "AS edges "
            "RETURN t AS root, nodes, edges",
            key=transaction_id,
        )
        return rows[0] if rows else {}

    async def clear(self) -> None:
        """Remove the whole projection. Used only by the rebuild command."""
        await self._run("MATCH (n) DETACH DELETE n")

    async def close(self) -> None:
        if self._driver is not None:
            await self._driver.close()
            self._driver = None


# The furthest a traversal may go. Four hops reaches an email's attachment's transaction's
# shipment, which is the longest question anybody asked for; anything beyond it returns most of
# the graph and is a report rather than a trace.
MAX_TRAVERSAL_DEPTH = 4
DEFAULT_TRAVERSAL_DEPTH = 2

_client: Neo4jClient | None = None


def get_graph_client() -> Neo4jClient:
    global _client
    if _client is None:
        _client = Neo4jClient()
    return _client


def set_graph_client(client: Neo4jClient | None) -> None:
    """Swap the client, for tests and for the rebuild command. Never used by a request path."""
    global _client
    _client = client


# A readable name per label, so a node on the diagram says what it is rather than showing a UUID.
_TITLE_KEYS: dict[str, tuple[str, ...]] = {
    "TradeTransaction": ("batch_number", "transaction_code"),
    "Document": ("filename",),
    "EmailMessage": ("subject",),
    "Container": ("container_number",),
    "Shipment": ("vessel", "carrier", "status"),
    "Supplier": ("name",),
    "Customer": ("name",),
    "ApprovalTask": ("decision",),
    "ExceptionCase": ("exception_type",),
    "IntegrationJob": ("target_system",),
    "DocumentPack": ("filename", "pack_type"),
}


def _title(label: str, properties: dict[str, Any]) -> str:
    for key in _TITLE_KEYS.get(label, ()):
        value = properties.get(key)
        if value:
            return str(value)
    return label


def to_graph_read(transaction: Any, raw: dict[str, Any]) -> Any:
    """Turn a driver result into the API's own shape.

    Imported here rather than at module scope because the schema layer imports nothing from the
    services layer, and reversing that for one function would create an import cycle.
    """
    from app.schemas.transaction import GraphEdgeRead, GraphNodeRead, TransactionGraph

    nodes: dict[str, GraphNodeRead] = {}
    edges: list[GraphEdgeRead] = []

    def add(record: Any) -> str | None:
        properties = dict(record)
        key = properties.get("key")
        if not key:
            return None
        label = next(iter(getattr(record, "labels", ())), "Node")
        nodes.setdefault(
            str(key), GraphNodeRead(id=str(key), label=label, title=_title(label, properties))
        )
        return str(key)

    root = raw.get("root")
    if root is not None:
        add(root)
    for record in raw.get("nodes") or ():
        if record is not None:
            add(record)

    # The driver returns a list of relationship lists, one per path, so the same edge appears
    # once per path that traverses it. De-duplicated on the triple rather than left to the
    # diagram to draw twice.
    seen: set[tuple[str, str, str]] = set()
    for path in raw.get("edges") or ():
        for relationship in path or ():
            start = dict(relationship.start_node).get("key")
            end = dict(relationship.end_node).get("key")
            if not start or not end:
                continue
            triple = (str(start), str(end), relationship.type)
            if triple in seen:
                continue
            seen.add(triple)
            edges.append(GraphEdgeRead(source=str(start), target=str(end), type=relationship.type))

    return TransactionGraph(
        transaction_id=transaction.id,
        batch_number=transaction.batch_number,
        available=True,
        nodes=list(nodes.values()),
        edges=edges,
    )
