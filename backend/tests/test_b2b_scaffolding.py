"""The B2B tag on a purchase, and the exact limit of what it claims.

Discovery described a joint B2B purchase model with a negotiated profit split, shared expenses and
a loss borne by one side. Only one part of that is unambiguous enough to build: whether a deal is
B2B at all, and who the partner is. These tests cover that part, and one of them exists purely to
fail if somebody later adds a profit-split column without a confirmed specification behind it.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.transactions import PurchaseLeg, TradeTransaction
from app.services import transaction_fields
from tests.utils.governance import seeded_transaction

pytestmark = pytest.mark.usefixtures("patched_jwks")

TRANSACTIONS = "/api/v1/transactions"


async def purchase_user(signed_in):
    return await signed_in(
        "0a1b2c3d-0000-4000-8000-00000000b001",
        "purchase.b2b@agfze.ae",
        "Nadia Farouk",
        ["purchase_user"],
    )


# --- the tag itself ------------------------------------------------------------------------------


async def test_a_purchase_is_not_b2b_unless_somebody_says_so(
    db_session: AsyncSession,
) -> None:
    """False is the true value for every deal, not a convenient default."""
    transaction = await seeded_transaction(db_session, batch_number="I2626-B1")
    assert transaction.purchase_leg.is_b2b is False
    assert transaction.purchase_leg.b2b_partner_name is None


async def test_a_desk_can_tag_a_deal_b2b_and_name_the_partner(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    """Through the ordinary field-correction endpoint, with its reason gate, not a second one.

    Nothing in a supplier's invoice says whether AGFZE is doing a deal jointly - it is commercial
    context the desk holds - so it is corrected in like any other field rather than extracted.
    """
    _user, headers = await purchase_user(signed_in)
    transaction = await seeded_transaction(db_session, batch_number="I2626-B2")

    response = await client.patch(
        f"{TRANSACTIONS}/{transaction.id}/fields",
        headers=headers,
        json={
            "changes": [
                {
                    "name": "is_b2b",
                    "value": "yes",
                    "reason": "Confirmed with the desk that this is a joint deal.",
                },
                {
                    "name": "b2b_partner_name",
                    "value": "Meridian Metals",
                    "reason": "The partner on this joint deal, per the desk.",
                },
            ]
        },
    )
    assert response.status_code == 200, response.text

    await db_session.refresh(transaction.purchase_leg)
    assert transaction.purchase_leg.is_b2b is True
    assert transaction.purchase_leg.b2b_partner_name == "Meridian Metals"


async def test_the_tag_can_be_taken_off_again(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    """ "no" has to mean False rather than "a non-empty string, therefore true"."""
    _user, headers = await purchase_user(signed_in)
    transaction = await seeded_transaction(db_session, batch_number="I2626-B3")
    transaction.purchase_leg.is_b2b = True
    await db_session.commit()

    response = await client.patch(
        f"{TRANSACTIONS}/{transaction.id}/fields",
        headers=headers,
        json={
            "changes": [
                {
                    "name": "is_b2b",
                    "value": "no",
                    "reason": "Tagged B2B in error; an ordinary purchase after all.",
                }
            ]
        },
    )
    assert response.status_code == 200, response.text

    await db_session.refresh(transaction.purchase_leg)
    assert transaction.purchase_leg.is_b2b is False


async def test_a_value_that_is_neither_yes_nor_no_is_refused(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    _user, headers = await purchase_user(signed_in)
    transaction = await seeded_transaction(db_session, batch_number="I2626-B4")

    response = await client.patch(
        f"{TRANSACTIONS}/{transaction.id}/fields",
        headers=headers,
        json={
            "changes": [
                {
                    "name": "is_b2b",
                    "value": "perhaps",
                    "reason": "Trying a value that is neither a yes nor a no.",
                }
            ]
        },
    )
    assert response.status_code == 400
    assert response.json()["errors"][0]["code"] == "invalid_value"


def test_a_boolean_field_reads_back_as_yes_or_no_rather_than_python_repr() -> None:
    """bool is an int subclass, so a careless read path would render "True" and coerce back wrong.

    Round-tripped rather than merely rendered: what `read_value` produces has to be something
    `coerce` accepts, or the workspace would show a value the same endpoint then refuses.
    """
    field = next(item for item in transaction_fields.PURCHASE_FIELDS if item.name == "is_b2b")
    transaction = TradeTransaction(purchase_leg=PurchaseLeg(is_b2b=True))

    assert transaction_fields.read_value(transaction, field) == "yes"
    assert transaction_fields.coerce(field, "yes") is True

    transaction.purchase_leg.is_b2b = False
    assert transaction_fields.read_value(transaction, field) == "no"
    assert transaction_fields.coerce(field, "no") is False


# --- the filter -----------------------------------------------------------------------------------


async def test_the_list_filters_to_b2b_deals_only(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    _user, headers = await purchase_user(signed_in)
    b2b = await seeded_transaction(db_session, batch_number="I2626-B5")
    ordinary = await seeded_transaction(db_session, batch_number="I2626-B6")
    b2b.purchase_leg.is_b2b = True
    b2b.purchase_leg.b2b_partner_name = "Meridian Metals"
    await db_session.commit()

    response = await client.get(f"{TRANSACTIONS}?deal_type=b2b", headers=headers)
    assert response.status_code == 200, response.text
    batches = [row["batch_number"] for row in response.json()["data"]["items"]]
    assert batches == [b2b.batch_number]
    assert ordinary.batch_number not in batches

    row = response.json()["data"]["items"][0]
    assert row["is_b2b"] is True
    assert row["b2b_partner_name"] == "Meridian Metals"


async def test_the_list_filters_to_standard_deals_only(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    _user, headers = await purchase_user(signed_in)
    b2b = await seeded_transaction(db_session, batch_number="I2626-B7")
    ordinary = await seeded_transaction(db_session, batch_number="I2626-B8")
    b2b.purchase_leg.is_b2b = True
    await db_session.commit()

    response = await client.get(f"{TRANSACTIONS}?deal_type=standard", headers=headers)
    assert response.status_code == 200, response.text
    batches = [row["batch_number"] for row in response.json()["data"]["items"]]
    assert batches == [ordinary.batch_number]


async def test_no_deal_type_filter_returns_both(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    _user, headers = await purchase_user(signed_in)
    b2b = await seeded_transaction(db_session, batch_number="I2626-B9")
    ordinary = await seeded_transaction(db_session, batch_number="I2626-B10")
    b2b.purchase_leg.is_b2b = True
    await db_session.commit()

    response = await client.get(TRANSACTIONS, headers=headers)
    assert response.status_code == 200
    batches = {row["batch_number"] for row in response.json()["data"]["items"]}
    assert {b2b.batch_number, ordinary.batch_number} <= batches


async def test_the_filter_combines_with_search_rather_than_joining_twice(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    """Both filters read `purchase_legs`. An EXISTS is what stops that being a duplicate join."""
    _user, headers = await purchase_user(signed_in)
    wanted = await seeded_transaction(db_session, batch_number="I2626-B11")
    other = await seeded_transaction(db_session, batch_number="I2626-B12")
    wanted.purchase_leg.is_b2b = True
    wanted.purchase_leg.supplier_name = "Meridian Metals"
    other.purchase_leg.is_b2b = True
    other.purchase_leg.supplier_name = "Someone Else"
    await db_session.commit()

    response = await client.get(f"{TRANSACTIONS}?deal_type=b2b&search=meridian", headers=headers)
    assert response.status_code == 200, response.text
    batches = [row["batch_number"] for row in response.json()["data"]["items"]]
    assert batches == [wanted.batch_number]


async def test_an_unknown_deal_type_is_refused_rather_than_ignored(
    client: AsyncClient, db_session: AsyncSession, signed_in
) -> None:
    _user, headers = await purchase_user(signed_in)
    response = await client.get(f"{TRANSACTIONS}?deal_type=joint_venture", headers=headers)
    assert response.status_code == 422


# --- the scope limit ------------------------------------------------------------------------------


def test_no_profit_split_or_expense_sharing_is_modelled_anywhere() -> None:
    """A guard, not a description.

    Discovery gave illustrative profit splits (50/50, 60/40, 65/35) and no rule for choosing
    between them, no mechanism for capturing a shared expense and no definition of a borne loss.
    Any column matching these names would therefore be a guess with a schema around it, and this
    test is what makes adding one a deliberate act rather than a quiet one. If AGFZE confirms the
    real shape, delete this test in the same change that adds the columns.
    """
    columns = set(PurchaseLeg.__table__.columns.keys())
    for invented in (
        "profit_share_percent",
        "profit_split",
        "partner_share_percent",
        "shared_expenses",
        "expense_share_percent",
        "loss_allocation",
    ):
        assert invented not in columns, (
            f"{invented} was added to purchase_legs. No source document specifies it - see "
            "docs/KNOWN-GAPS.md on the B2B workflow before modelling it."
        )
