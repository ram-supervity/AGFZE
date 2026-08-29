"""The SAP-side fields discovery named, and the exact line between mapped and guessed.

This file exists because of a specific risk: a payload posted to a real accounting system is the
last place a plausible-looking invented value should first appear. Discovery named ten data points
for the SAP posting. Some were given a mapping outright, some were named without one, and some are
not derivable from anything this platform holds. These tests pin each of those three groups where
it belongs, so a later change that quietly promotes a guess into the payload fails here first.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.enums import (
    IntegrationJobStatus,
    IntegrationTargetSystem,
    InvoiceStatus,
)
from app.models.integration import IntegrationJob
from app.services.integration.payloads import (
    dms_document_reference,
    sap_payload,
)
from tests.utils.integration import approved_transaction

pytestmark = pytest.mark.usefixtures("patched_jwks")


# --- what discovery mapped outright -------------------------------------------------------------


async def test_assignment_carries_the_invoice_number(db_session: AsyncSession) -> None:
    """SAP's Assignment field. A stated mapping, not an inference."""
    transaction = await approved_transaction(db_session, batch_number="I2626-S1")
    transaction.purchase_leg.supplier_invoice_number = "INV-99812"
    await db_session.commit()

    payload = sap_payload(transaction)
    assert payload["sap_posting_reference"]["assignment"] == "INV-99812"


async def test_header_text_carries_the_batch_number(db_session: AsyncSession) -> None:
    """What makes a posting traceable back to this platform at all."""
    transaction = await approved_transaction(db_session, batch_number="I2626-S2")

    payload = sap_payload(transaction)
    assert payload["sap_posting_reference"]["header_text"] == "I2626-S2"


async def test_business_area_is_configured_rather_than_written_into_the_code(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """1070 is AGFZE's, and a second entity must not need a code change to post."""
    transaction = await approved_transaction(db_session, batch_number="I2626-S3")

    assert sap_payload(transaction)["sap_posting_reference"]["business_area"] == "1070"

    monkeypatch.setattr(settings, "SAP_BUSINESS_AREA", "2080")
    assert sap_payload(transaction)["sap_posting_reference"]["business_area"] == "2080"


# --- what is named but deliberately unmapped ------------------------------------------------------


async def test_reference_keys_and_house_bank_are_absent_rather_than_guessed(
    db_session: AsyncSession,
) -> None:
    """The most important assertion in this file.

    Discovery named Reference Key 1, Reference Key 2 and House Bank as fields the posting carries,
    and mapped none of them to a value. A plausible-looking guess in an accounting document is
    worse than a gap, because the gap is visible to whoever completes the posting and the guess is
    not. If AGFZE later supplies the mapping, this test is deleted in the same change that adds
    the fields - deliberately, rather than by a change that happens to make it pass.
    """
    transaction = await approved_transaction(db_session, batch_number="I2626-S4")
    reference = sap_payload(transaction)["sap_posting_reference"]

    for invented in ("reference_key_1", "reference_key_2", "house_bank"):
        assert invented not in reference, (
            f"{invented} appeared in the SAP payload. No source document maps it to a value - "
            "see docs/KNOWN-GAPS.md before filling it in."
        )


async def test_no_company_code_is_chosen_when_none_is_configured(
    db_session: AsyncSession,
) -> None:
    """AGFZE routes between 2000 (UAE) and 3010 (Singapore) and nothing says which deal is which."""
    transaction = await approved_transaction(db_session, batch_number="I2626-S5")
    assert "company_code" not in sap_payload(transaction)["trade_contract"]


# --- the posting pattern ---------------------------------------------------------------------------


async def test_a_final_invoice_is_named_as_an_invoice_verification_posting(
    db_session: AsyncSession,
) -> None:
    transaction = await approved_transaction(db_session, batch_number="I2626-S6")
    transaction.purchase_leg.supplier_invoice_number = "INV-100"
    transaction.purchase_leg.invoice_status = InvoiceStatus.FINAL.value
    await db_session.commit()

    reference = sap_payload(transaction)["sap_posting_reference"]
    assert reference["posting_pattern"] == "invoice_verification"


async def test_a_provisional_invoice_names_no_posting_pattern(
    db_session: AsyncSession,
) -> None:
    """It is priced again before it is final, so naming it would name a superseded document."""
    transaction = await approved_transaction(db_session, batch_number="I2626-S7")
    transaction.purchase_leg.supplier_invoice_number = "INV-101"
    transaction.purchase_leg.invoice_status = InvoiceStatus.PROVISIONAL.value
    await db_session.commit()

    reference = sap_payload(transaction)["sap_posting_reference"]
    assert "posting_pattern" not in reference


async def test_no_goods_receipt_or_payment_clearing_pattern_is_ever_derived(
    db_session: AsyncSession,
) -> None:
    """A guard on the two T-codes this platform cannot honestly source.

    A goods receipt is posted against physical receipt into stock, which this platform tracks as
    shipment milestones rather than as a receipt event. F-53/F-58 clear a payment, and payment
    confirmation lives in SAP - the platform does not know a payment happened, which is the same
    reason the `Closed` transaction state has no code path setting it.
    """
    transaction = await approved_transaction(db_session, batch_number="I2626-S8")
    transaction.purchase_leg.supplier_invoice_number = "INV-102"
    transaction.purchase_leg.invoice_status = InvoiceStatus.FINAL.value
    await db_session.commit()

    pattern = sap_payload(transaction)["sap_posting_reference"].get("posting_pattern")
    assert pattern not in ("goods_receipt", "payment_clearing", "f-53", "f-58", "grn")


# --- the DMS document number, and its non-blocking rule ---------------------------------------------


async def test_the_dms_reference_is_included_once_the_filing_has_succeeded(
    db_session: AsyncSession,
) -> None:
    transaction = await approved_transaction(db_session, batch_number="I2626-S9")
    db_session.add(
        IntegrationJob(
            transaction_id=transaction.id,
            target_system=IntegrationTargetSystem.DMS.value,
            status=IntegrationJobStatus.SUCCEEDED.value,
            external_reference="DMS-55501",
        )
    )
    await db_session.commit()

    reference = await dms_document_reference(db_session, transaction)
    assert reference == "DMS-55501"
    payload = sap_payload(transaction, dms_document_number=reference)
    assert payload["sap_posting_reference"]["dms_document_number"] == "DMS-55501"


async def test_a_pack_filed_by_hand_counts_exactly_as_an_automated_upload_does(
    db_session: AsyncSession,
) -> None:
    """A person who filed the pack and recorded the reference produced the same fact."""
    transaction = await approved_transaction(db_session, batch_number="I2626-S10")
    db_session.add(
        IntegrationJob(
            transaction_id=transaction.id,
            target_system=IntegrationTargetSystem.DMS.value,
            status=IntegrationJobStatus.AWAITING_MANUAL_ACTION.value,
            completed_manually=True,
            external_reference="DMS-55502",
        )
    )
    await db_session.commit()

    assert await dms_document_reference(db_session, transaction) == "DMS-55502"


async def test_an_unresolved_dms_filing_leaves_the_field_out_rather_than_waiting(
    db_session: AsyncSession,
) -> None:
    """The whole point of the opportunistic rule: SAP never blocks on another target system."""
    transaction = await approved_transaction(db_session, batch_number="I2626-S11")
    db_session.add(
        IntegrationJob(
            transaction_id=transaction.id,
            target_system=IntegrationTargetSystem.DMS.value,
            status=IntegrationJobStatus.AWAITING_MANUAL_ACTION.value,
            completed_manually=False,
        )
    )
    await db_session.commit()

    assert await dms_document_reference(db_session, transaction) is None
    payload = sap_payload(transaction, dms_document_number=None)
    assert "dms_document_number" not in payload["sap_posting_reference"]


async def test_no_dms_job_at_all_is_not_an_error(db_session: AsyncSession) -> None:
    transaction = await approved_transaction(db_session, batch_number="I2626-S12")
    assert await dms_document_reference(db_session, transaction) is None


async def test_a_failed_dms_filing_contributes_no_reference(
    db_session: AsyncSession,
) -> None:
    transaction = await approved_transaction(db_session, batch_number="I2626-S13")
    db_session.add(
        IntegrationJob(
            transaction_id=transaction.id,
            target_system=IntegrationTargetSystem.DMS.value,
            status=IntegrationJobStatus.FAILED.value,
            external_reference="DMS-PARTIAL",
        )
    )
    await db_session.commit()

    assert await dms_document_reference(db_session, transaction) is None


# --- the payload still says what it is --------------------------------------------------------------


async def test_the_platform_field_names_are_still_declared_as_this_platforms_own(
    db_session: AsyncSession,
) -> None:
    """The posting-reference section is the one exception, and everything else is unchanged."""
    transaction = await approved_transaction(db_session, batch_number="I2626-S14")
    payload = sap_payload(transaction)

    assert payload["schema"] == "agfze.platform.v1"
    assert "trade_contract" in payload
    assert "deal_price_record" in payload
