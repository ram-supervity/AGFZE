"""The seam every downstream posting goes through, and the only three outcomes it may report.

`IntegrationOutcome` is the point of this module. An adapter returns exactly one of three things
and cannot express anything else:

* it posted, and here is the reference the receiving system gave back;
* it tried and the attempt failed, and here is why;
* it is not configured to post at all, so here is everything a person needs to finish the job
  themselves.

There is no fourth constructor, no default, and no way to build a `succeeded` outcome without an
adapter having actually succeeded. That is deliberate: the single most damaging thing this module
could do is report a posting that never happened, and the type system is the cheapest place to
make that impossible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.integration import IntegrationJob
from app.models.transactions import TradeTransaction


class OutcomeKind(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    AWAITING_MANUAL_ACTION = "awaiting_manual_action"


@dataclass(frozen=True)
class IntegrationOutcome:
    kind: OutcomeKind
    external_reference: str | None = None
    failure_reason: str | None = None
    # Whether a failure is worth another automatic attempt. A timeout is; a payload the receiving
    # system rejected as invalid is not, and retrying it four more times would only produce four
    # more identical rejections and a slower exception.
    retryable: bool = True
    # What a person has to do, and the data they need in front of them to do it. Populated only
    # on the manual path.
    manual_instruction: str | None = None
    prepared_payload: dict[str, Any] | None = None
    # Anything worth putting on the audit trail about how this attempt went.
    detail: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def succeeded(cls, external_reference: str, **detail: Any) -> IntegrationOutcome:
        return cls(
            kind=OutcomeKind.SUCCEEDED,
            external_reference=external_reference,
            detail=detail,
        )

    @classmethod
    def failed(cls, message: str, *, retryable: bool = True, **detail: Any) -> IntegrationOutcome:
        """`message` is what a person reads on the job; `detail` is what the audit trail keeps.

        The parameter is deliberately not called `reason`: every adapter passes a `reason=` code
        into `detail`, and a positional name that collided with it would silently swallow one of
        the two.
        """
        return cls(
            kind=OutcomeKind.FAILED, failure_reason=message, retryable=retryable, detail=detail
        )

    @classmethod
    def awaiting_manual_action(
        cls,
        instruction: str,
        *,
        payload: dict[str, Any] | None = None,
        **detail: Any,
    ) -> IntegrationOutcome:
        return cls(
            kind=OutcomeKind.AWAITING_MANUAL_ACTION,
            manual_instruction=instruction,
            prepared_payload=payload,
            detail=detail,
        )


@runtime_checkable
class IntegrationAdapter(Protocol):
    """One target system's posting.

    `configured` is what decides which path the run takes, and it is a property of the deployment
    rather than of the transaction: either this installation has been given a real endpoint to
    call or it has not.
    """

    target_system: str

    @property
    def configured(self) -> bool: ...

    async def run(
        self, session: AsyncSession, job: IntegrationJob, transaction: TradeTransaction
    ) -> IntegrationOutcome: ...
