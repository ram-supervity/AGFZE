"""Rebuild the graph projection from the relational store, from scratch.

    python -m scripts.rebuild_graph

The projection is derived, so this is always safe and is the answer to any question about whether
the graph is correct: throw it away and build it again. Nothing on the platform reads it, so
nothing is unavailable while this runs, and running it twice costs time rather than correctness.

It refuses to start when no store is configured, rather than reporting that it rebuilt an empty
projection successfully.
"""

from __future__ import annotations

import asyncio
import sys

from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.services import graph_sync_worker

logger = get_logger(__name__)


async def main() -> int:
    configure_logging()
    if not settings.neo4j_configured:
        print(
            "No graph store is configured. Set NEO4J_URI, NEO4J_USER and NEO4J_PASSWORD before "
            "rebuilding.",
            file=sys.stderr,
        )
        return 1

    print(f"Rebuilding the graph projection at {settings.NEO4J_URI} …")
    result = await graph_sync_worker.rebuild()
    print(
        f"Done. {result.considered} rows projected as {result.nodes} nodes and "
        f"{result.relationships} relationships."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
