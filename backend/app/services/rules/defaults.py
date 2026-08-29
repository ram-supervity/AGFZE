"""The reference data and default rule configuration shipped with the platform.

Both lists are data, not behaviour. The migration writes them; the engine reads whatever the
tables hold at call time. Changing a threshold once  has an editing screen is a row change
with a mandatory reason attached, and needs no release.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.models.enums import BusinessStream
from app.services.rules.catalog import CheckKey, RuleId

SEED_CHANGE_REASON = "Platform default shipped with the transaction and rule engine module."

# The six grades the desk actually trades. `AL` is commonly written ALU on supplier paperwork,
# which the commodity resolver treats as an alias rather than an unknown code.
COMMODITY_CODES: list[dict[str, Any]] = [
    {"code": "CU", "display_name": "Copper", "is_active": True},
    {"code": "AL", "display_name": "Aluminum", "is_active": True},
    {"code": "CUZNS", "display_name": "Brass", "is_active": True},
    {"code": "MIX", "display_name": "Mixed metal scrap", "is_active": True},
    {"code": "HMS", "display_name": "Heavy Melting Steel", "is_active": True},
    {"code": "TIP", "display_name": "Other", "is_active": True},
]

COMMODITY_ALIASES: dict[str, str] = {
    "ALU": "AL",
    "ALUMINIUM": "AL",
    "ALUMINUM": "AL",
    "COPPER": "CU",
    "BRASS": "CUZNS",
    "MIXED": "MIX",
    "OTHER": "TIP",
}


def _row(
    rule_id: str,
    check_key: str,
    value: str,
    unit: str,
    description: str,
    *,
    stream: str | None = None,
    change_reason: str = SEED_CHANGE_REASON,
) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "check_key": check_key,
        "scope_commodity_code": None,
        "scope_transaction_type": None,
        "scope_stream": stream,
        "threshold_value": Decimal(value),
        "threshold_unit": unit,
        "description": description,
        "is_active": True,
        "change_reason": change_reason,
    }


def default_rule_configurations() -> list[dict[str, Any]]:
    """The unscoped defaults for every rule this  evaluates for real.

    Every row is scoped to nothing, which makes it the fall-back the resolver lands on when no
    narrower row exists. A commodity-specific override is added as a second row beside its
    default, never by editing the default out from under the transactions it already governs.
    """
    return [
        _row(
            RuleId.BR_02,
            CheckKey.REFERENCE_PRESENT,
            "1",
            "count",
            "How many of batch number, contract number and supplier invoice number must be "
            "present before a transaction can be matched and validated.",
        ),
        _row(
            RuleId.BR_02,
            CheckKey.CONTRACT_MATCH_THRESHOLD,
            "92",
            "score",
            "Minimum rapidfuzz partial_ratio between two contract references for them to be "
            "treated as the same contract.",
        ),
        _row(
            RuleId.BR_02,
            CheckKey.SUPPLIER_MATCH_THRESHOLD,
            "90",
            "score",
            "Minimum rapidfuzz token_sort_ratio between two supplier names for them to be "
            "treated as the same counterparty.",
        ),
        _row(
            RuleId.BR_02,
            CheckKey.SUGGESTION_FLOOR,
            "80",
            "score",
            "Below this composite score a candidate is not offered at all; between it and the "
            "auto-link thresholds the candidate is put to a person to confirm or reject.",
        ),
        _row(
            RuleId.BR_04,
            CheckKey.DOCUMENT_PACK,
            "1.0",
            "ratio",
            "Proportion of the territory's mandatory-document checklist that must be present. "
            "1.0 means the pack must be complete.",
        ),
        _row(
            RuleId.BR_05,
            CheckKey.QUANTITY_TOLERANCE,
            "5.0",
            "percent",
            "Permitted variation between contracted and invoiced quantity. Discovery also "
            "raised roughly 3.3% as a possible industry standard, but that figure was "
            "explicitly unconfirmed, so ±5% is what ships.",
        ),
        _row(
            RuleId.BR_06,
            CheckKey.AMOUNT_ROUNDING,
            "1.00",
            "currency",
            "Difference between the invoiced and the calculated value that passes without any "
            "user action at all.",
        ),
        _row(
            RuleId.BR_06,
            CheckKey.AMOUNT_SELF_APPROVAL_LIMIT,
            "10.00",
            "currency",
            "Ceiling on the difference a preparing user may acknowledge on their own record. "
            "Above it the transaction is blocked until the figures are corrected.",
        ),
        _row(
            RuleId.BR_06,
            CheckKey.QUANTITY_TOLERANCE,
            "5.0",
            "percent",
            "Quantity tolerance applied to the invoice agreement check. Quantity has no "
            "self-approval tier, unlike the invoice amount.",
        ),
        _row(
            RuleId.BR_06,
            CheckKey.RATE_TOLERANCE,
            "0",
            "currency",
            "Permitted difference between the contracted and the invoiced price. Zero: price is "
            "a negotiated term, not a measurement, so any difference is a hard failure.",
        ),
        _row(
            RuleId.BR_13,
            CheckKey.DUPLICATE_CONTENT,
            "1",
            "count",
            "How many byte-identical copies of a document may sit on a competing transaction. "
            "One means the copy must link to the transaction that already holds it.",
        ),
        _row(
            RuleId.BR_13,
            CheckKey.DUPLICATE_SIMILARITY,
            "97",
            "score",
            "Minimum rapidfuzz token_set_ratio between two documents' extracted content for the "
            "later one to be treated as a repeat of the earlier.",
        ),
    ]


def sales_rule_configurations() -> list[dict[str, Any]]:
    """The defaults the sales module brings with it. A separate list, deliberately.

    `default_rule_configurations` is what the  migration wrote and must keep writing
    unchanged; appending to it would make that migration insert rows the  migration then
    inserts again, against a unique constraint. New rules ship their own list.
    """
    return [
        _row(
            RuleId.SL_01,
            CheckKey.CONTRACT_QUANTITY_COVERAGE,
            "0",
            "percent",
            "How far the summed invoiced quantity across every shipment on one sales contract "
            "may exceed the quantity that contract covers. Zero: a contract states the quantity "
            "that was agreed, and invoicing past it is a commercial breach rather than a "
            "measurement variance. A customer who genuinely permits an overage gets a scoped row "
            "beside this default, not an edit to it.",
        ),
    ]


INVOICE_DATE_SEED_CHANGE_REASON = (
    "Platform default shipped with the invoice-dating rule. Three months is the figure this "
    "platform's discovery material proposes; AGFZE has not confirmed it, nor the approval matrix "
    "for a backdated invoice, which is exactly why the rule flags rather than blocks."
)


def invoice_date_rule_configurations() -> list[dict[str, Any]]:
    """IV-01's one threshold, in the same table every other threshold already lives in.

    A separate list for the same reason every previous 's is separate: each migration has to
    keep writing exactly what it wrote, and the unique constraint on (rule, check, scope) would
    reject a second insert of the same row.

    `count` rather than a unit of its own, because the check constraint on `threshold_unit` admits
    percent, currency, count, ratio and score - and widening a constraint every screen already
    reads correctly, for one row, would be a schema change made for cosmetics. The description
    says what is being counted.
    """
    return [
        _row(
            RuleId.IV_01,
            CheckKey.INVOICE_DATE_WINDOW,
            "3",
            "count",
            "Calendar months. How far in the past an invoice may be dated before the transaction "
            "is flagged for the preparing desk to accept with a reason or correct. A future-dated "
            "invoice is flagged whatever this value is. Deliberately a flag and never a block: "
            "the business has not confirmed the tolerance or who signs off a backdated invoice.",
            change_reason=INVOICE_DATE_SEED_CHANGE_REASON,
        ),
    ]


FA_SEED_CHANGE_REASON = (
    "FA-scoped placeholder shipped with the FA module. AGFZE has not confirmed an FA-specific "
    "figure for this check, so the row deliberately carries the same value the platform default "
    "carries. It exists as a separate, stream-scoped row precisely so the business can change "
    "FA's figure without touching the scrap stream's, the moment they decide what it should be."
)

# What the FA rows are placeholders *for*. Each pairs a check with the platform default it
# currently repeats, so the seeded list cannot drift away from the defaults it is meant to mirror.
_FA_PLACEHOLDER_CHECKS: tuple[tuple[str, str], ...] = (
    (RuleId.BR_02, CheckKey.REFERENCE_PRESENT),
    (RuleId.BR_02, CheckKey.CONTRACT_MATCH_THRESHOLD),
    (RuleId.BR_02, CheckKey.SUPPLIER_MATCH_THRESHOLD),
    (RuleId.BR_02, CheckKey.SUGGESTION_FLOOR),
    (RuleId.BR_04, CheckKey.DOCUMENT_PACK),
    (RuleId.BR_05, CheckKey.QUANTITY_TOLERANCE),
    (RuleId.BR_06, CheckKey.AMOUNT_ROUNDING),
    (RuleId.BR_06, CheckKey.AMOUNT_SELF_APPROVAL_LIMIT),
    (RuleId.BR_06, CheckKey.QUANTITY_TOLERANCE),
    (RuleId.BR_06, CheckKey.RATE_TOLERANCE),
    (RuleId.BR_13, CheckKey.DUPLICATE_CONTENT),
    (RuleId.BR_13, CheckKey.DUPLICATE_SIMILARITY),
)


def fa_rule_configurations() -> list[dict[str, Any]]:
    """The FA stream's own defaults: the same checks, scoped to `fa`, at the same values.

    This is the shape of the whole FA extension in one function. Not one new rule, not one new
    threshold and not one invented number - the second business line is governed by exactly the
    checks the first one is, through rows rather than code.

    Every value is copied from the platform default rather than chosen, because AGFZE's material
    gives no FA figure and this  is instructed not to invent one. Copying it is not a no-op:
    it gives FA a row of its own to change later, which an unscoped default shared with the scrap
    stream could never be.
    """
    defaults = {(row["rule_id"], row["check_key"]): row for row in default_rule_configurations()}
    rows: list[dict[str, Any]] = []
    for rule_id, check_key in _FA_PLACEHOLDER_CHECKS:
        source = defaults[(rule_id, check_key)]
        rows.append(
            _row(
                rule_id,
                check_key,
                str(source["threshold_value"]),
                str(source["threshold_unit"]),
                f"FA stream placeholder, currently equal to the platform default. "
                f"{source['description']}",
                stream=BusinessStream.FA.value,
                change_reason=FA_SEED_CHANGE_REASON,
            )
        )
    return rows


SHIPMENT_SEED_CHANGE_REASON = "Platform default shipped with the shipment tracking module."


def shipment_rule_configurations() -> list[dict[str, Any]]:
    """BR-03's threshold, in the table every other rule already reads from.

    One row, and the value is the whole rule in a number: a container may sit on zero other
    transactions. It is configuration rather than a literal for the same reason every other
    threshold is - so an administrator can see what the check compares against, and change it
    with a reason attached rather than through a release.
    """
    return [
        _row(
            RuleId.BR_03,
            CheckKey.CONTAINER_CROSS_TRANSACTION,
            "0",
            "count",
            "How many *other*, unrelated transactions a container number quoted on this one may "
            "already belong to. Zero: one physical box is one deal's cargo, and finding it on a "
            "second transaction is a strong signal that something was matched wrongly. This "
            "never counts the containers of the transaction being checked, so a batch loaded "
            "into several boxes is not what it measures.",
            change_reason=SHIPMENT_SEED_CHANGE_REASON,
        ),
    ]


# LG-01's seed. A separate list from every list above it, for the reason each of those is separate:
# a shipped migration has to keep writing exactly what it wrote, and the unique constraint on
# (rule, check, scope) rejects a second insert of the same row.
OBL_WEIGHT_SEED_CHANGE_REASON = (
    "Seeded with LG-01. The figure is this platform's own cautious starting point and is NOT "
    "confirmed by AGFZE. Discovery named the invoice-versus-bill-of-lading weight difference as "
    "the trigger for a debit or a credit note without ever naming the difference that triggers "
    "one, so 1% is chosen to sit below the 5% BR-05 allows against the contract - a load can be "
    "contractually fine and still be billed for a weight the vessel did not carry, which is the "
    "whole reason this rule is separate from BR-05."
)


def obl_weight_rule_configurations() -> list[dict[str, Any]]:
    """LG-01's one threshold."""
    return [
        _row(
            RuleId.LG_01,
            CheckKey.OBL_WEIGHT_VARIANCE,
            "1.0",
            "percent",
            "Permitted difference between the weight an invoice bills for and the weight the "
            "bill of lading states. Beyond it the transaction is flagged for a person, who "
            "raises a debit note (invoice heavier) or a credit note (bill of lading heavier). "
            "The platform never raises either itself.",
            change_reason=OBL_WEIGHT_SEED_CHANGE_REASON,
        ),
    ]
