"""Short codes for a counterparty's name, derived rather than stored.

Discovery describes two conventions the desk already uses by hand: a customer is abbreviated to
the first three letters of its name ("DongA" becomes "DON"), and a supplier to the first two
letters of each word of its name. Both are written down here as one small function each, called
where a counterparty name is read for display, and nothing more than that.

**Derived, deliberately, and this is the whole design decision.** There is no `Customer` or
`Supplier` master-data table on this platform; a counterparty is a free-text name on
`PurchaseLeg.supplier_name` or `SalesLeg.customer_name`. Storing a generated code in a column
beside the name would create a second source of truth for the same fact - one that goes stale the
moment somebody corrects a misspelt supplier name, and that nothing would notice had gone stale.
Computing it on read cannot drift, costs nothing at this scale, and needs no migration.

That is a reasonable answer for a display abbreviation. It is *not* an answer for a stable
counterparty identifier that survives a name correction, which is what a real master-data table
would give and what a downstream system keying on the code would need. Whether AGFZE wants that
larger thing is recorded in docs/KNOWN-GAPS.md rather than assumed here.
"""

from __future__ import annotations

import re

# Letters only. A supplier name routinely carries a legal suffix in punctuation ("Al-Noor Metals
# L.L.C."), and treating "L.L.C." as three words would produce a code that is mostly the company
# form and none of the company.
_WORD = re.compile(r"[A-Za-z]+")

# The legal-form words that are on the end of most names in this trade and identify none of them.
# Dropped before abbreviating a supplier, so "Emirates Metal Trading LLC" reads as EMMETR rather
# than EMMETRLL. A name that is *only* a legal form keeps it rather than abbreviating to nothing.
_LEGAL_FORMS = frozenset(
    {
        "llc",
        "lc",
        "ltd",
        "limited",
        "inc",
        "incorporated",
        "co",
        "company",
        "corp",
        "corporation",
        "plc",
        "pte",
        "pvt",
        "private",
        "gmbh",
        "bv",
        "nv",
        "sa",
        "srl",
        "spa",
        "ag",
        "fze",
        "fzc",
        "fzco",
        "dmcc",
        "jlt",
        "sarl",
        "kk",
        "pjsc",
        "psc",
    }
)

CUSTOMER_CODE_LENGTH = 3


def _words(name: str | None) -> list[str]:
    # Full stops are stripped before words are found, so a punctuated legal form reads as one word
    # and can be recognised as one. Without this, "L.L.C." is three single-letter words, none of
    # which matches the legal-form list, and "Al-Noor Metals L.L.C." abbreviates to ALNOMELLC -
    # six characters of company and three of company form.
    return _WORD.findall((name or "").replace(".", ""))


def customer_code(name: str | None) -> str | None:
    """First three letters of a customer's name, upper case. "DongA" -> "DON".

    Letters only and across word boundaries, so "A B Metals" gives ABM rather than stopping at a
    space. A name with fewer than three letters returns what there is rather than padding it out
    with characters nobody wrote.
    """
    letters = "".join(_words(name))
    if not letters:
        return None
    return letters[:CUSTOMER_CODE_LENGTH].upper()


def supplier_code(name: str | None) -> str | None:
    """First two letters of each word of a supplier's name, upper case.

    "Emirates Metal Trading LLC" -> "EMMETR". The legal form is dropped first; see `_LEGAL_FORMS`
    for why. A one-letter word contributes its one letter rather than being skipped.
    """
    words = _words(name)
    if not words:
        return None
    meaningful = [word for word in words if word.lower() not in _LEGAL_FORMS]
    # A name that is nothing but a legal form is unusual and is almost certainly a data-entry
    # problem, but returning None for it would be worse than returning what was actually written.
    return "".join(word[:2] for word in (meaningful or words)).upper()


def counterparty_code(name: str | None, *, is_customer: bool) -> str | None:
    """Whichever convention applies to the side of the deal this counterparty sits on."""
    return customer_code(name) if is_customer else supplier_code(name)
