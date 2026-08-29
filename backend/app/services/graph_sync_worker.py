"""Keeps the graph projection current with the relational store, and never the other way round.

A watermark sweep, modelled on the three workers beside it. Every tick it reads the rows that
changed since it last looked, turns them into nodes and relationships, and upserts them. It writes
nothing back to PostgreSQL and reads nothing out of the graph, so a projection that is behind, or
absent entirely, cannot affect a single decision the platform makes.

Two properties are worth stating because they are what make this safe to run at all.

**Idempotent.** Every write is a MERGE on the relational row's own primary key, so re-projecting a
row updates it rather than duplicating it. That is what lets the worker overlap its own previous
sweep harmlessly, and what lets `rebuild` run over a populated store.

**Failure is not an incident.** Neo4j being unreachable produces a logged warning and another
attempt on the next tick. The worker never raises out of its loop, because a stale read model is
not worth stopping a process for.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import AsyncSessionLocal
from app.models.governance import ApprovalTask, ExceptionCase
from app.models.intake import Document, EmailMessage
from app.models.integration import DocumentPack, IntegrationJob
from app.models.logistics import Container, Shipment
from app.models.transactions import TradeTransaction
from app.services.counterparty_codes import customer_code, supplier_code
from app.services.neo4j_service import (
    GraphNode,
    GraphRelationship,
    GraphUnavailableError,
    Neo4jClient,
    get_graph_client,
)

logger = get_logger(__name__)


@dataclass
class SyncResult:
    nodes: int = 0
    relationships: int = 0
    considered: int = 0
    watermark: datetime | None = None
    failures: list[str] = field(default_factory=list)


def _text(value: object | None) -> str | None:
    return str(value) if value is not None else None


def _counterparty_nodes(
    transaction: TradeTransaction,
) -> tuple[list[GraphNode], list[GraphRelationship]]:
    """Supplier and Customer nodes, derived from the leg name fields.

    There is no counterparty table on this platform, so these nodes are keyed by the name itself.
    That has a consequence worth knowing rather than discovering: correct a misspelt supplier and
    the projection gains a second node, because a different name is a different key. The relational
    store is unaffected, and a rebuild collapses it. See docs/KNOWN-GAPS.md on counterparty
    master data - this is the same gap seen from a different angle.
    """
    nodes: list[GraphNode] = []
    edges: list[GraphRelationship] = []
    key = str(transaction.id)

    purchase = transaction.purchase_leg
    if purchase is not None and purchase.supplier_name:
        name = purchase.supplier_name.strip()
        nodes.append(GraphNode("Supplier", name, {"name": name, "code": supplier_code(name) or ""}))
        edges.append(GraphRelationship("TradeTransaction", key, "ISSUED_BY", "Supplier", name))

    sales = transaction.sales_leg
    if sales is not None and sales.customer_name:
        name = sales.customer_name.strip()
        nodes.append(GraphNode("Customer", name, {"name": name, "code": customer_code(name) or ""}))
        edges.append(GraphRelationship("TradeTransaction", key, "SOLD_TO", "Customer", name))

    return nodes, edges


def project_transaction(
    transaction: TradeTransaction,
) -> tuple[list[GraphNode], list[GraphRelationship]]:
    """One transaction, its legs and its counterparties, as nodes and edges.

    Properties are deliberately thin: an identifier, a status, and whatever a person needs to read
    a node on a diagram. Copying the commercial figures in would make the projection look like a
    place to read them from, which is exactly what it must not become.
    """
    key = str(transaction.id)
    nodes = [
        GraphNode(
            "TradeTransaction",
            key,
            {
                "batch_number": transaction.batch_number,
                "transaction_code": transaction.transaction_code,
                "stream": transaction.stream,
                "status": transaction.status,
            },
        )
    ]
    edges: list[GraphRelationship] = []

    for label, relationship, leg in (
        ("PurchaseLeg", "HAS_PURCHASE_LEG", transaction.purchase_leg),
        ("SalesLeg", "HAS_SALES_LEG", transaction.sales_leg),
        ("FaLeg", "HAS_FA_LEG", getattr(transaction, "fa_leg", None)),
    ):
        if leg is None:
            continue
        nodes.append(GraphNode(label, str(leg.id), {"transaction_id": key}))
        edges.append(GraphRelationship("TradeTransaction", key, relationship, label, str(leg.id)))

    counterparties, counterparty_edges = _counterparty_nodes(transaction)
    return nodes + counterparties, edges + counterparty_edges


def project_document(document: Document) -> tuple[list[GraphNode], list[GraphRelationship]]:
    key = str(document.id)
    nodes = [
        GraphNode(
            "Document",
            key,
            {
                "filename": document.filename,
                "document_type": document.document_type or "unknown",
                "extraction_status": document.extraction_status,
            },
        )
    ]
    edges: list[GraphRelationship] = []
    if document.transaction_id is not None:
        edges.append(
            GraphRelationship(
                "TradeTransaction", str(document.transaction_id), "EXTRACTED_AS", "Document", key
            )
        )
    return nodes, edges


def project_email(message: EmailMessage) -> tuple[list[GraphNode], list[GraphRelationship]]:
    key = str(message.id)
    return (
        [
            GraphNode(
                "EmailMessage",
                key,
                {
                    "subject": message.subject or "",
                    "sender": message.sender_address or "",
                    "received_at": _text(message.received_at) or "",
                },
            )
        ],
        [],
    )


def project_container(container: Container) -> tuple[list[GraphNode], list[GraphRelationship]]:
    key = str(container.id)
    nodes = [GraphNode("Container", key, {"container_number": container.container_number or ""})]
    edges = [
        GraphRelationship(
            "TradeTransaction",
            str(container.transaction_id),
            "HAS_CONTAINER",
            "Container",
            key,
        )
    ]
    return nodes, edges


def project_shipment(shipment: Shipment) -> tuple[list[GraphNode], list[GraphRelationship]]:
    key = str(shipment.id)
    nodes = [
        GraphNode(
            "Shipment",
            key,
            {
                "status": shipment.status,
                "carrier": shipment.carrier or "",
                "vessel": shipment.vessel or "",
            },
        )
    ]
    edges = [
        GraphRelationship(
            "TradeTransaction", str(shipment.transaction_id), "SHIPPED_UNDER", "Shipment", key
        )
    ]
    return nodes, edges


def project_approval(task: ApprovalTask) -> tuple[list[GraphNode], list[GraphRelationship]]:
    key = str(task.id)
    nodes = [GraphNode("ApprovalTask", key, {"decision": task.decision})]
    edges = [
        GraphRelationship(
            "TradeTransaction", str(task.transaction_id), "REQUIRES", "ApprovalTask", key
        )
    ]
    return nodes, edges


def project_exception(case: ExceptionCase) -> tuple[list[GraphNode], list[GraphRelationship]]:
    key = str(case.id)
    nodes = [
        GraphNode(
            "ExceptionCase",
            key,
            {"exception_type": case.exception_type, "status": case.status},
        )
    ]
    edges: list[GraphRelationship] = []
    if case.transaction_id is not None:
        edges.append(
            GraphRelationship(
                "TradeTransaction",
                str(case.transaction_id),
                "HAS_EXCEPTION",
                "ExceptionCase",
                key,
            )
        )
    return nodes, edges


def project_integration_job(job: IntegrationJob) -> tuple[list[GraphNode], list[GraphRelationship]]:
    key = str(job.id)
    nodes = [
        GraphNode(
            "IntegrationJob",
            key,
            {
                "target_system": job.target_system,
                "status": job.status,
                "external_reference": job.external_reference or "",
            },
        )
    ]
    edges = [
        GraphRelationship(
            "TradeTransaction", str(job.transaction_id), "COMMITTED_TO", "IntegrationJob", key
        )
    ]
    return nodes, edges


def project_document_pack(pack: DocumentPack) -> tuple[list[GraphNode], list[GraphRelationship]]:
    key = str(pack.id)
    nodes = [
        GraphNode("DocumentPack", key, {"pack_type": pack.pack_type, "filename": pack.filename})
    ]
    edges = [
        GraphRelationship(
            "TradeTransaction", str(pack.transaction_id), "HAS_ATTACHMENT", "DocumentPack", key
        )
    ]
    return nodes, edges


# Each entry is one relational table, the column its watermark is read from, and the function that
# turns a row into nodes and edges. Adding a table to the projection is a row here and a function
# above; the sweep below learns nothing about any of them.
PROJECTIONS = (
    (TradeTransaction, TradeTransaction.updated_at, project_transaction),
    (Document, Document.created_at, project_document),
    # `ingested_at` rather than `created_at`: an email row records when the platform took it off
    # the mailbox, and that is the only timestamp it carries.
    (EmailMessage, EmailMessage.ingested_at, project_email),
    (Container, Container.created_at, project_container),
    (Shipment, Shipment.updated_at, project_shipment),
    (ApprovalTask, ApprovalTask.updated_at, project_approval),
    (ExceptionCase, ExceptionCase.updated_at, project_exception),
    (IntegrationJob, IntegrationJob.updated_at, project_integration_job),
    # A pack is written once and never edited, so when it was generated is its watermark.
    (DocumentPack, DocumentPack.generated_at, project_document_pack),
)

# Loaded eagerly for the transaction projection, because reading a leg off an un-loaded
# relationship inside an async session is a lazy load, which is an error rather than a query.
TRANSACTION_OPTIONS = (
    selectinload(TradeTransaction.purchase_leg),
    selectinload(TradeTransaction.sales_leg),
    selectinload(TradeTransaction.fa_leg),
)


async def sync_once(
    session: AsyncSession,
    client: Neo4jClient,
    *,
    since: datetime | None,
    limit: int,
) -> SyncResult:
    """Project every row that changed since the watermark. Returns what was written."""
    result = SyncResult(watermark=since)
    nodes: list[GraphNode] = []
    edges: list[GraphRelationship] = []
    newest = since

    for model, column, project in PROJECTIONS:
        statement = select(model).order_by(column).limit(limit)
        if since is not None:
            statement = statement.where(column > since)
        if model is TradeTransaction:
            statement = statement.options(*TRANSACTION_OPTIONS)

        for row in (await session.scalars(statement)).all():
            result.considered += 1
            row_nodes, row_edges = project(row)
            nodes.extend(row_nodes)
            edges.extend(row_edges)
            stamp = getattr(row, column.key, None)
            if stamp is not None and (newest is None or stamp > newest):
                newest = stamp

    if not nodes:
        return result

    result.nodes = await client.upsert_nodes(nodes)
    # Relationships after nodes, always: an edge MATCHes both ends, so projecting it before its
    # nodes exist silently writes nothing rather than failing.
    result.relationships = await client.upsert_relationships(edges)
    result.watermark = newest
    return result


async def rebuild(client: Neo4jClient | None = None) -> SyncResult:
    """Drop the projection and rebuild it from the relational store.

    The projection is derived, so this is always safe and is the answer to any question about
    whether the graph is correct: throw it away and build it again. Nothing else on the platform
    reads it, so nothing is unavailable while it runs.
    """
    graph = client or get_graph_client()
    await graph.clear()
    async with AsyncSessionLocal() as session:
        total = SyncResult()
        watermark: datetime | None = None
        # Paged by watermark rather than by offset, so a rebuild over a large table does not
        # re-read rows it has already projected.
        while True:
            batch = await sync_once(
                session, graph, since=watermark, limit=max(1, settings.GRAPH_SYNC_BATCH_SIZE)
            )
            if batch.considered == 0:
                break
            total.considered += batch.considered
            total.nodes += batch.nodes
            total.relationships += batch.relationships
            if batch.watermark == watermark:
                break
            watermark = batch.watermark
        total.watermark = watermark
        return total


async def run_worker(stop: asyncio.Event) -> None:
    interval = max(30, settings.GRAPH_SYNC_INTERVAL_SECONDS)
    client = get_graph_client()
    watermark: datetime | None = None
    logger.info("graph_sync_worker_started", extra={"interval_seconds": interval})

    while not stop.is_set():
        try:
            async with AsyncSessionLocal() as session:
                result = await sync_once(
                    session,
                    client,
                    since=watermark,
                    limit=max(1, settings.GRAPH_SYNC_BATCH_SIZE),
                )
            if result.considered:
                watermark = result.watermark
                logger.info(
                    "graph_sync_complete",
                    extra={
                        "considered": result.considered,
                        "nodes": result.nodes,
                        "relationships": result.relationships,
                    },
                )
        except GraphUnavailableError:
            # Expected, and not an incident. The watermark is deliberately not advanced, so the
            # rows this sweep could not project are picked up by the next one.
            logger.warning("graph_sync_store_unavailable")
        except Exception:
            logger.exception("graph_sync_iteration_failed")

        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            continue
    logger.info("graph_sync_worker_stopped")


def should_run() -> bool:
    """Enabled, configured, and not under the test harness. All three, and never only the flag."""
    return settings.GRAPH_SYNC_ENABLED and settings.neo4j_configured and not settings.is_testing
