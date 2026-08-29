"""The desk's own short forms of a counterparty's name.

Two conventions, both taken from discovery: a customer abbreviates to the first three letters of
its name, a supplier to the first two letters of each word. The worked example discovery gives -
"DongA" becoming "DON" - is asserted directly, because an abbreviation convention that does not
reproduce the one example anybody wrote down is not the convention.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.counterparty_codes import (
    counterparty_code,
    customer_code,
    supplier_code,
)
from tests.utils.governance import seeded_transaction

pytestmark = pytest.mark.usefixtures("patched_jwks")


# --- the conventions themselves --------------------------------------------------------------


def test_the_worked_example_from_discovery() -> None:
    """The one example anybody actually wrote down."""
    assert customer_code("DongA") == "DON"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("DongA", "DON"),
        ("Dongkuk Steel", "DON"),
        ("Hyundai", "HYU"),
        # Letters only, and across word boundaries - a space must not stop it short.
        ("A B Metals", "ABM"),
        # Shorter than three letters returns what there is rather than padding it out.
        ("Li", "LI"),
    ],
)
def test_a_customer_abbreviates_to_three_letters(name: str, expected: str) -> None:
    assert customer_code(name) == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Emirates Metal Trading", "EMMETR"),
        # The legal form identifies no company and is dropped.
        ("Emirates Metal Trading LLC", "EMMETR"),
        # Including when it is written with full stops, which is the common case.
        ("Al-Noor Metals L.L.C.", "ALNOME"),
        ("Gulf Recycling FZE", "GURE"),
        ("Sing Metals Pte Ltd", "SIME"),
        # A one-letter word contributes its letter rather than being skipped.
        ("A B Metals", "ABME"),
    ],
)
def test_a_supplier_abbreviates_to_two_letters_per_word(name: str, expected: str) -> None:
    assert supplier_code(name) == expected


def test_a_name_that_is_only_a_legal_form_keeps_what_was_written() -> None:
    """Almost certainly a data-entry problem, and returning nothing would hide it."""
    assert supplier_code("Pte Ltd") == "PTLT"


@pytest.mark.parametrize("name", [None, "", "   ", "---", "123"])
def test_a_name_with_no_letters_has_no_code(name: str | None) -> None:
    """Never a guess and never an empty string pretending to be a code."""
    assert customer_code(name) is None
    assert supplier_code(name) is None


def test_the_side_of_the_deal_selects_the_convention() -> None:
    assert counterparty_code("Emirates Metal Trading", is_customer=False) == "EMMETR"
    assert counterparty_code("Emirates Metal Trading", is_customer=True) == "EMI"


# --- where it is actually used ----------------------------------------------------------------


async def test_the_transaction_list_carries_the_code_beside_the_name(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    _user, headers = await signed_in(
        "0a1b2c3d-0000-4000-8000-00000000c001",
        "purchase.codes@agfze.ae",
        "Leila Haddad",
        ["purchase_user"],
    )
    transaction = await seeded_transaction(db_session, batch_number="I2626-C1")
    transaction.purchase_leg.supplier_name = "Emirates Metal Trading LLC"
    await db_session.commit()

    response = await client.get("/api/v1/transactions", headers=headers)
    assert response.status_code == 200, response.text
    row = next(
        item
        for item in response.json()["data"]["items"]
        if item["batch_number"] == transaction.batch_number
    )
    assert row["counterparty"] == "Emirates Metal Trading LLC"
    assert row["counterparty_code"] == "EMMETR"


async def test_the_code_follows_a_corrected_name_rather_than_going_stale(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    """The reason it is derived rather than stored, asserted as behaviour.

    A stored code would keep the old value after somebody fixed a misspelt supplier name, and
    nothing on the platform would notice it had gone stale.
    """
    _user, headers = await signed_in(
        "0a1b2c3d-0000-4000-8000-00000000c002",
        "purchase.codes2@agfze.ae",
        "Omar Said",
        ["purchase_user"],
    )
    transaction = await seeded_transaction(db_session, batch_number="I2626-C2")
    # Recorded with the trading arm's name missing, which is the shape of correction that actually
    # changes the abbreviation - a misspelling inside a word would not.
    transaction.purchase_leg.supplier_name = "Emirates Metal"
    await db_session.commit()

    async def code_now() -> str | None:
        response = await client.get("/api/v1/transactions", headers=headers)
        row = next(
            item
            for item in response.json()["data"]["items"]
            if item["batch_number"] == transaction.batch_number
        )
        return row["counterparty_code"]

    assert await code_now() == "EMME"

    transaction.purchase_leg.supplier_name = "Emirates Metal Trading"
    await db_session.commit()

    assert await code_now() == "EMMETR"


async def test_a_transaction_with_no_counterparty_name_has_no_code(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    _user, headers = await signed_in(
        "0a1b2c3d-0000-4000-8000-00000000c003",
        "purchase.codes3@agfze.ae",
        "Sara Nasser",
        ["purchase_user"],
    )
    transaction = await seeded_transaction(db_session, batch_number="I2626-C3")
    transaction.purchase_leg.supplier_name = None
    await db_session.commit()

    response = await client.get("/api/v1/transactions", headers=headers)
    row = next(
        item
        for item in response.json()["data"]["items"]
        if item["batch_number"] == transaction.batch_number
    )
    assert row["counterparty_code"] is None
