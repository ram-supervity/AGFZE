"""Builders for the exception and approval fixtures the  suite works against.

Everything is written through the real services - the rule engine opens the cases, the submit
endpoint raises the approval tasks - so the tests exercise the actual hooks rather than a
hand-built row that resembles what they would have produced.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import DocumentType, RuleSeverity
from app.models.governance import RuleExceptionMapping
from app.services.rules import engine as rule_engine
from app.services.rules.registry import RegisteredRule, RuleContext, RuleOutcome
from tests.utils.transactions import (
    contract_values,
    invoice_values,
    make_document,
    make_request,
    make_transaction,
)

SYNTHETIC_RULE_ID = "BR-99"
SYNTHETIC_CHECK_KEY = "synthetic_check"


async def seeded_transaction(
    session: AsyncSession,
    *,
    invoice_overrides: dict | None = None,
    contract_overrides: dict | None = None,
    with_contract: bool = True,
    validate: bool = True,
    invoice_content_hash: str | None = None,
    **transaction_kwargs,
):
    """A transaction with the pack that satisfies every rule, minus whatever is overridden."""
    request = await make_request(session)
    transaction = await make_transaction(session, request=request, **transaction_kwargs)
    await make_document(
        session,
        request,
        values=invoice_values(**(invoice_overrides or {})),
        document_type=DocumentType.INVOICE.value,
        filename="invoice.pdf",
        transaction_id=transaction.id,
        content_hash=invoice_content_hash,
    )
    if with_contract:
        await make_document(
            session,
            request,
            values=contract_values(**(contract_overrides or {})),
            document_type=DocumentType.CONTRACT.value,
            filename="contract.pdf",
            transaction_id=transaction.id,
        )
    if validate:
        await rule_engine.run_validation(session, transaction)
    await session.commit()
    return transaction


async def add_mapping(
    session: AsyncSession,
    *,
    rule_id: str,
    check_key: str | None,
    exception_type: str,
    owner_role: str,
    priority: str = "medium",
) -> RuleExceptionMapping:
    """Register a category for a rule the way a later  would: by adding a row."""
    row = RuleExceptionMapping(
        id=uuid.uuid4(),
        rule_id=rule_id,
        check_key=check_key,
        exception_type=exception_type,
        owner_role=owner_role,
        priority=priority,
        description="Added by the test suite to prove the hook is driven by data.",
        is_active=True,
    )
    session.add(row)
    await session.flush()
    await session.commit()
    return row


@asynccontextmanager
async def synthetic_hard_failing_rule(
    session: AsyncSession,
    *,
    exception_type: str,
    owner_role: str,
    rule_id: str = SYNTHETIC_RULE_ID,
) -> AsyncIterator[str]:
    """A rule that did not exist when the exception hook was written.

    Registering it and giving it a mapping row is the whole of what  5 and 6 will have to do.
    If the hook needed anything else - a branch, a list, an `if` - this context manager could not
    make a case appear, and the test that uses it would fail.
    """
    from app.services.rules.registry import _REGISTRY

    async def evaluate(context: RuleContext) -> list[RuleOutcome]:
        return [
            RuleOutcome(
                rule_id=rule_id,
                check_key=SYNTHETIC_CHECK_KEY,
                passed=False,
                severity=RuleSeverity.HARD.value,
                field_name="synthetic_field",
                expected_value="whatever the mapping says",
                actual_value="a rule the orchestrator has never heard of",
                message="A synthetic rule, hard-failing on purpose.",
            )
        ]

    _REGISTRY[rule_id] = RegisteredRule(
        rule_id=rule_id, evaluator=evaluate, requires_legs=frozenset(), implemented=True
    )
    mapping = await add_mapping(
        session,
        rule_id=rule_id,
        check_key=SYNTHETIC_CHECK_KEY,
        exception_type=exception_type,
        owner_role=owner_role,
    )
    try:
        yield rule_id
    finally:
        _REGISTRY.pop(rule_id, None)
        await session.delete(mapping)
        await session.commit()
