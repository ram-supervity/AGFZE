"""Turning what a document said into something that can be compared.

Extraction reports strings, because that is what a document contains. Every comparison the rule
engine makes is numeric, and the conversion has to be explicit and lossless: a quantity carries a
unit, an amount may carry a thousands separator, and a price basis states its LME percentage in
prose. Nothing here guesses - a value that cannot be read as a number comes back as None and the
rule that wanted it says so rather than comparing against zero.
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

_NUMBER = re.compile(r"-?\d[\d,\s]*(?:\.\d+)?")
_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*%")

CENTS = Decimal("0.01")


def to_decimal(value: str | Decimal | float | int | None) -> Decimal | None:
    """Read the leading number out of a value, ignoring any currency symbol or unit after it."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int | float):
        return Decimal(str(value))
    match = _NUMBER.search(str(value))
    if match is None:
        return None
    cleaned = match.group(0).replace(",", "").replace(" ", "")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def to_percentage(value: str | Decimal | float | None) -> Decimal | None:
    """Read a percentage, whether written '97%', '97 %' or plainly as 97."""
    if value is None:
        return None
    if not isinstance(value, str):
        return to_decimal(value)
    match = _PERCENT.search(value)
    if match is not None:
        return Decimal(match.group(1))
    return to_decimal(value)


def money(value: Decimal | None) -> Decimal | None:
    """Round to the cent before any comparison.

    The amount rule turns on a one-dollar and a ten-dollar boundary, so the difference either
    side of it has to be a settled figure rather than the tail of a float conversion.
    """
    if value is None:
        return None
    return value.quantize(CENTS, rounding=ROUND_HALF_UP)


def percentage_difference(expected: Decimal, actual: Decimal) -> Decimal | None:
    """How far `actual` sits from `expected`, as a percentage of `expected`."""
    if expected == 0:
        return None
    return (abs(actual - expected) / abs(expected) * Decimal(100)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )


def format_decimal(value: Decimal | None, *, suffix: str = "") -> str | None:
    if value is None:
        return None
    normalised = value.normalize()
    # normalize() renders a whole number in exponent form (1E+2); expand it back out.
    if normalised == normalised.to_integral_value():
        normalised = normalised.quantize(Decimal(1))
    return f"{normalised}{suffix}"
