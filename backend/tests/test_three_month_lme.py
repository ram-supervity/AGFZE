"""The three-month LME quotation as a price basis of its own.

Discovery names three sales pricing mechanisms, not two: a locked price, a percentage of the LME
cash settlement, and a price struck against the three-month quotation taken ahead of ETD/ETA. Only
the first two were storable, so a three-month deal was recorded as whichever of them it most
resembled and the distinction was lost the moment it was written down.

The thing this file is most careful about is what is *not* implemented. Discovery is equally
explicit that the exchange has no usable feed and that the three-month price is entered by hand
for the day, so this platform holds no daily series to average. It records which quotation a deal
is struck against; it computes no average, because an average of data it does not have would be an
invented price.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.models.enums import LME_LINKED_PRICE_BASES, PRICE_BASES, PriceBasis
from app.services.transaction_service import infer_price_basis


def test_the_vocabulary_carries_all_three_mechanisms():
    assert set(PRICE_BASES) == {"fixed", "lme_percent", "three_month_lme"}
    # Both LME-linked bases are grouped, so a rule comparing a contracted percentage applies to
    # each of them rather than only to the one that happens to be named at the call site.
    assert set(LME_LINKED_PRICE_BASES) == {"lme_percent", "three_month_lme"}
    assert PriceBasis.FIXED.value not in LME_LINKED_PRICE_BASES


@pytest.mark.parametrize(
    "stated",
    [
        "3 month LME less 6%",
        "3-MONTH LME 94%",
        "Three month LME average",
        "3M LME",
    ],
)
def test_a_three_month_quotation_is_read_as_one_however_it_is_written(stated: str):
    """Spacing and hyphenation vary between a supplier in Jebel Ali and a buyer in Ningbo."""
    basis, _ = infer_price_basis({"price_basis": stated})
    assert basis == PriceBasis.THREE_MONTH_LME.value


def test_a_percentage_on_a_three_month_deal_is_still_captured():
    """A "3-month LME less 6%" deal is a three-month deal that also carries a percentage.

    Reading it as a straight percentage of the cash settlement would lose which quotation the
    percentage is taken off, and dropping the percentage would lose the discount. Neither happens.
    """
    basis, percentage = infer_price_basis({"price_basis": "3-month LME 94%"})
    assert basis == PriceBasis.THREE_MONTH_LME.value
    assert percentage == Decimal("94")


def test_the_other_two_mechanisms_are_unchanged():
    assert infer_price_basis({"price_basis": "97% of LME"}) == (
        PriceBasis.LME_PERCENT.value,
        Decimal("97"),
    )
    assert infer_price_basis({"price_basis": "USD 8,450 per MT fixed"}) == (
        PriceBasis.FIXED.value,
        None,
    )
    assert infer_price_basis({}) == (PriceBasis.FIXED.value, None)


def test_the_platform_computes_no_three_month_average_anywhere():
    """The absence is the requirement, so it is asserted rather than assumed.

    The exchange has no usable feed and no daily price series is stored, so an averaged figure
    could only be fabricated. What the platform holds is the basis and the price somebody read off
    the source and entered - never a number it worked out for them.
    """
    import inspect

    from app.services import draft_service, transaction_service

    for module in (transaction_service, draft_service):
        source = inspect.getsource(module)
        for invented in ("mean(", "average(", "/ 90", "three_month_average"):
            assert invented not in source, f"{module.__name__} looks like it averages a price"


def test_the_generated_contract_states_which_quotation_the_price_is_struck_against():
    from app.services.draft_service import _price_terms

    class _Transaction:
        price_basis = PriceBasis.THREE_MONTH_LME.value
        lme_percentage = Decimal("94")
        currency = "USD"
        sales_leg = None
        purchase_leg = None

    assert _price_terms(_Transaction()) == "94% of the 3-month LME quotation"

    class _NoPercentage(_Transaction):
        lme_percentage = None

    # Which quotation is a contractual term, so it is stated even where no percentage was
    # recorded - and no figure is asserted that nobody entered.
    assert _price_terms(_NoPercentage()) == "the 3-month LME quotation"
