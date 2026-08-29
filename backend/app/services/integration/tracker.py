"""The tracker synchronisation: a real client, against a target nobody has named yet.

This adapter is not built like the SAP and DMS ones, and the difference is the point of the whole
. Microsoft Graph's Excel API is documented, this platform has authenticated against Graph
since , and the write itself is completely specified - so the client is real, complete
working code that extends the existing Graph service rather than a second one built beside it.

What is genuinely unknown is only *which* workbook, sheet, table and columns AGFZE wants written
to. That is configuration, and an unconfigured deployment gets the same honest
`awaiting_manual_action` an unconfigured SAP job gets: the figures are prepared and shown to a
person, and nothing is written into a spreadsheet nobody named.

The write is row-level throughout - locate the row for the batch, patch it, or append one - so a
person with the tracker open in Excel at the same moment is never overwritten.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.enums import IntegrationTargetSystem
from app.models.integration import IntegrationJob
from app.models.transactions import TradeTransaction
from app.services.graph_service import (
    GraphError,
    TrackerNotConfiguredError,
    get_graph_client,
)
from app.services.integration.adapters import IntegrationOutcome
from app.services.integration.payloads import tracker_fields

logger = get_logger(__name__)

MANUAL_INSTRUCTION = (
    "No tracker workbook is configured on this deployment, so nothing has been written to any "
    "spreadsheet. The figures below are this transaction's own, ready to be entered into the "
    "tracker by hand. Confirm the entry here once it is done, with the row or file reference you "
    "used."
)

# The reasons that are worth another automatic attempt. A throttled or unreachable Graph is a
# transient condition; a workbook whose columns do not match the configured mapping is not going
# to start matching on its own, and four more attempts would only delay the exception.
TRANSIENT_GRAPH_REASONS: frozenset[str] = frozenset(
    {"transport", "authentication", "http_429", "http_500", "http_502", "http_503", "http_504"}
)


class TrackerAdapter:
    target_system = IntegrationTargetSystem.TRACKER.value

    @property
    def configured(self) -> bool:
        return settings.tracker_configured

    async def run(
        self, session: AsyncSession, job: IntegrationJob, transaction: TradeTransaction
    ) -> IntegrationOutcome:
        fields = tracker_fields(transaction)
        if not self.configured:
            return IntegrationOutcome.awaiting_manual_action(
                MANUAL_INSTRUCTION,
                payload={"tracker_row": fields},
                reason="tracker_not_configured",
            )

        try:
            result = await get_graph_client().upsert_tracker_row(fields)
        except TrackerNotConfiguredError:
            # Configuration that passed the flag check but not the client's own. Still not a
            # failure: there is nothing to retry and a person can enter the row today.
            return IntegrationOutcome.awaiting_manual_action(
                MANUAL_INSTRUCTION, payload={"tracker_row": fields}, reason="tracker_incomplete"
            )
        except GraphError as exc:
            return IntegrationOutcome.failed(
                f"The tracker workbook could not be updated ({exc.reason}).",
                retryable=exc.reason in TRANSIENT_GRAPH_REASONS,
                reason=exc.reason,
            )

        reference = (
            f"{settings.TRACKER_TABLE_NAME}!row {result.row_index}"
            if settings.TRACKER_TABLE_NAME
            else f"row {result.row_index}"
        )
        logger.info(
            "tracker_row_written",
            extra={
                "transaction_id": str(transaction.id),
                "row_index": result.row_index,
                "action": result.action,
            },
        )
        return IntegrationOutcome.succeeded(
            reference,
            action=result.action,
            row_index=result.row_index,
            columns_written=result.columns_written,
        )
