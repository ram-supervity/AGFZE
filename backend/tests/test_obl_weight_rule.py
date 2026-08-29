"""LG-01: the weight an invoice bills for against the weight the bill of lading states.

The rule this file covers exists because BR-05 does not cover it. BR-05 compares the invoice
against the **contract** - what was agreed. LG-01 compares the invoice against the **bill of
lading** - what actually shipped. A load can sit comfortably inside its contractual tolerance and
still be billed for a weight the vessel did not carry, and that difference is money: it is what a
debit or a credit note is raised for.

One test here is a scope guard rather than a behaviour check. LG-01 detects and flags; it does not
generate a debit or a credit note, because raising one is correspondence with a counterparty in a
format nothing in this platform's material specifies.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import DocumentType, RuleSeverity
from app.services.rules import engine as rule_engine
from app.services.rules.catalog import CheckKey, RuleId
from tests.utils.sales import bl_values
from tests.utils.transactions import (
    contract_values,
    invoice_values,
    make_document,
    make_request,
    make_transaction,
)

pytestmark = pytest.mark.usefixtures("patched_jwks")


async def _transaction_with(
    session: AsyncSession,
    *,
    invoiced_quantity: str | None,
    bl_quantity: str | None,
    bl_type: str = DocumentType.BL.value,
    batch_number: str = "I2626-W1",
):
    """An invoice and (optionally) a bill of lading, each stating its own weight."""
    request = await make_request(session)
    transaction = await make_transaction(session, request=request, batch_number=batch_number)
    await make_document(
        session,
        request,
        values=invoice_values(quantity=invoiced_quantity),
        document_type=DocumentType.INVOICE.value,
        filename="invoice.pdf",
        transaction_id=transaction.id,
    )
    await make_document(
        session,
        request,
        values=contract_values(),
        document_type=DocumentType.CONTRACT.value,
        filename="contract.pdf",
        transaction_id=transaction.id,
    )
    if bl_quantity is not None:
        await make_document(
            session,
            request,
            values=bl_values(quantity=bl_quantity, batch_number=batch_number),
            document_type=bl_type,
            filename="bill-of-lading.pdf",
            transaction_id=transaction.id,
        )
    await session.commit()
    return transaction


async def _outcome(session: AsyncSession, transaction):
    written = await rule_engine.run_validation(session, transaction)
    return next(
        row
        for row in written
        if row.rule_id == RuleId.LG_01 and row.check_key == CheckKey.OBL_WEIGHT_VARIANCE
    )


# --- agreement -------------------------------------------------------------------------------------


async def test_matching_weights_pass(db_session: AsyncSession) -> None:
    transaction = await _transaction_with(
        db_session, invoiced_quantity="24.500 MT", bl_quantity="24.500 MT"
    )
    outcome = await _outcome(db_session, transaction)
    assert outcome.passed is True


async def test_a_difference_inside_the_tolerance_passes(db_session: AsyncSession) -> None:
    """24.5 against 24.6 is roughly 0.4%, comfortably inside the seeded 1%."""
    transaction = await _transaction_with(
        db_session, invoiced_quantity="24.600 MT", bl_quantity="24.500 MT"
    )
    outcome = await _outcome(db_session, transaction)
    assert outcome.passed is True


# --- disagreement, in both directions ----------------------------------------------------------------


async def test_an_invoice_heavier_than_the_bill_of_lading_fails_and_names_a_debit_note(
    db_session: AsyncSession,
) -> None:
    """The direction decides which document a person raises, so the message has to say which."""
    transaction = await _transaction_with(
        db_session, invoiced_quantity="26.000 MT", bl_quantity="24.500 MT"
    )
    outcome = await _outcome(db_session, transaction)

    assert outcome.passed is False
    assert outcome.severity == RuleSeverity.ACKNOWLEDGEABLE.value
    assert "debit note" in outcome.message
    assert "credit note" not in outcome.message
    # The actual figures, not a bare "outside tolerance".
    assert "26" in outcome.message and "24.5" in outcome.message


async def test_a_bill_of_lading_heavier_than_the_invoice_fails_and_names_a_credit_note(
    db_session: AsyncSession,
) -> None:
    transaction = await _transaction_with(
        db_session, invoiced_quantity="23.000 MT", bl_quantity="24.500 MT"
    )
    outcome = await _outcome(db_session, transaction)

    assert outcome.passed is False
    assert "credit note" in outcome.message
    assert "debit note" not in outcome.message


async def test_the_rule_is_acknowledgeable_rather_than_blocking(
    db_session: AsyncSession,
) -> None:
    """A real weight difference is a commercial fact to settle, not a data error to correct.

    Blocking on it would strand a correct transaction behind a discrepancy the desk has already
    dealt with by raising a note.
    """
    transaction = await _transaction_with(
        db_session, invoiced_quantity="30.000 MT", bl_quantity="24.500 MT"
    )
    outcome = await _outcome(db_session, transaction)
    assert outcome.severity == RuleSeverity.ACKNOWLEDGEABLE.value
    assert outcome.severity != RuleSeverity.HARD.value


# --- not applicable ------------------------------------------------------------------------------------


async def test_no_bill_of_lading_is_not_a_discrepancy(db_session: AsyncSession) -> None:
    """Most of a transaction's life has no bill of lading yet, and that is ordinary business.

    Reporting it as a failure would fill the logistics queue with the shape of normal work. BR-07
    is the rule that cares whether a bill of lading exists; this one only compares.
    """
    transaction = await _transaction_with(
        db_session, invoiced_quantity="24.500 MT", bl_quantity=None
    )
    outcome = await _outcome(db_session, transaction)

    assert outcome.passed is True
    assert outcome.severity == RuleSeverity.INFORMATIONAL.value
    assert "nothing to compare" in outcome.message


async def test_no_invoiced_weight_is_not_a_discrepancy_either(
    db_session: AsyncSession,
) -> None:
    transaction = await _transaction_with(
        db_session, invoiced_quantity=None, bl_quantity="24.500 MT"
    )
    outcome = await _outcome(db_session, transaction)

    assert outcome.passed is True
    assert outcome.severity == RuleSeverity.INFORMATIONAL.value


async def test_a_final_bill_of_lading_is_preferred_over_a_draft(
    db_session: AsyncSession,
) -> None:
    """A draft's figures are still subject to change; raising a note against one is premature."""
    request = await make_request(db_session)
    transaction = await make_transaction(db_session, request=request, batch_number="I2626-W9")
    await make_document(
        db_session,
        request,
        values=invoice_values(quantity="24.500 MT"),
        document_type=DocumentType.INVOICE.value,
        filename="invoice.pdf",
        transaction_id=transaction.id,
    )
    await make_document(
        db_session,
        request,
        values=contract_values(),
        document_type=DocumentType.CONTRACT.value,
        filename="contract.pdf",
        transaction_id=transaction.id,
    )
    # The draft disagrees wildly; the final one agrees. The final one is what must be read.
    await make_document(
        db_session,
        request,
        values=bl_values(quantity="40.000 MT", batch_number="I2626-W9"),
        document_type=DocumentType.BL_DRAFT.value,
        filename="draft-bl.pdf",
        transaction_id=transaction.id,
    )
    await make_document(
        db_session,
        request,
        values=bl_values(quantity="24.500 MT", batch_number="I2626-W9"),
        document_type=DocumentType.BL.value,
        filename="final-bl.pdf",
        transaction_id=transaction.id,
    )
    await db_session.commit()

    outcome = await _outcome(db_session, transaction)
    assert outcome.passed is True


# --- routing, and the scope limit ------------------------------------------------------------------------


async def test_a_failure_routes_to_the_logistics_desk_through_the_unmodified_hook(
    db_session: AsyncSession,
) -> None:
    """The rule is routed by a table row, not by a branch anybody added to the hook."""
    from app.services.governance.categories import obl_weight_rule_exception_mappings

    mapping = obl_weight_rule_exception_mappings()[0]
    assert mapping["rule_id"] == RuleId.LG_01
    assert mapping["check_key"] == CheckKey.OBL_WEIGHT_VARIANCE
    assert mapping["owner_role"] == "logistics_user"


def test_the_platform_never_generates_a_debit_or_credit_note_itself() -> None:
    """A scope guard, and the most important assertion in this file.

    Raising a debit or a credit note is correspondence that commits AGFZE to a financial claim
    against a counterparty, in a document format nothing in this platform's material specifies.
    LG-01 flags the discrepancy for a person; it must not quietly grow into a generator. If AGFZE
    confirms the format, generating it goes through the existing reviewed-draft path in
    `draft_service` - and this test is deleted in the same change, deliberately.
    """
    from app.models.enums import DocumentType as DocTypes

    generated = {value.value for value in DocTypes}
    for invented in ("debit_note", "credit_note", "draft_debit_note", "draft_credit_note"):
        assert invented not in generated, (
            f"{invented} became a generatable document type. LG-01 flags a weight discrepancy "
            "for a person; see docs/KNOWN-GAPS.md before generating one."
        )
