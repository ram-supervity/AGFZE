"""The thirteen governing business rules, plus the sales module's own, as identifiers and prose.

This module is deliberately data only. It names every rule the platform recognises and says what
each one means; whether a rule can actually be evaluated yet, and how, belongs to the evaluator
registered against it. A later step that brings the data a rule needs registers a real evaluator
under the same identifier and changes nothing here.

SL-01 is the one entry that is not one of the thirteen. It is a genuinely new requirement of the
sales module - the only check in the platform that reads across transactions - so it is named in
its own namespace rather than appended to a numbering it does not belong to.
"""

from __future__ import annotations

from dataclasses import dataclass


class RuleId:
    BR_01 = "BR-01"
    BR_02 = "BR-02"
    BR_03 = "BR-03"
    BR_04 = "BR-04"
    BR_05 = "BR-05"
    BR_06 = "BR-06"
    BR_07 = "BR-07"
    BR_08 = "BR-08"
    BR_09 = "BR-09"
    BR_10 = "BR-10"
    BR_11 = "BR-11"
    BR_12 = "BR-12"
    BR_13 = "BR-13"
    # Outside the BR-01..13 numbering on purpose. The thirteen governing rules were written
    # about a single transaction; this one is a genuinely new requirement of the sales module and
    # is the only rule in the platform that reads across transactions, so it carries its own
    # namespace rather than being smuggled in as a fourteenth "BR".
    SL_01 = "SL-01"
    # The same reasoning, for the same reason, a second time. Invoice dating was named in this
    # platform's original discovery material and never belonged to the thirteen governing rules,
    # so it is registered in its own namespace rather than appended to a numbering it is not part
    # of. The policy behind it - how far back a supplier may date an invoice, and who signs off a
    # backdated one - is explicitly unconfirmed by AGFZE, which is why the evaluator flags and
    # never blocks.
    IV_01 = "IV-01"
    # A third time, and the same reasoning again. The weight a bill of lading states against the
    # weight the invoice bills for was named in discovery as the trigger for a debit or a credit
    # note, and is not one of the thirteen governing rules - which compare the invoice against the
    # *contract*, never against the shipping document. It carries its own namespace rather than
    # being appended to a numbering it is not part of.
    LG_01 = "LG-01"


@dataclass(frozen=True)
class RuleDefinition:
    rule_id: str
    title: str
    statement: str


RULE_CATALOG: tuple[RuleDefinition, ...] = (
    RuleDefinition(
        RuleId.BR_01,
        "Unique request traceability",
        "Every transaction traces back to exactly one request identifier.",
    ),
    RuleDefinition(
        RuleId.BR_02,
        "Business reference present",
        "A business reference - invoice, contract or batch number - must exist before a document "
        "can be matched to a transaction.",
    ),
    RuleDefinition(
        RuleId.BR_03,
        "Container number agreement",
        "The container number must agree across the document pack before the transaction is "
        "committed, and a container may not sit on two unrelated transactions.",
    ),
    RuleDefinition(
        RuleId.BR_04,
        "Mandatory document pack",
        "Every document the destination territory requires must be present.",
    ),
    RuleDefinition(
        RuleId.BR_05,
        "Quantity variation",
        "Quantity may vary from the contracted figure only within the configured tolerance.",
    ),
    RuleDefinition(
        RuleId.BR_06,
        "Invoice value agreement",
        "Invoiced value, rate and quantity must agree with the contracted terms, or fall inside "
        "the tolerance configured for each.",
    ),
    RuleDefinition(
        RuleId.BR_07,
        "Sales document preparation",
        "Sales document preparation may begin from an OBL or draft bill of lading; final posting "
        "waits for shipping validation.",
    ),
    RuleDefinition(
        RuleId.BR_08,
        "Failure routing",
        "A failed check routes the transaction to an exception queue for a person to resolve.",
    ),
    RuleDefinition(
        RuleId.BR_09,
        "Portal is primary",
        "The portal is the system of record; trackers are synchronised only after validation.",
    ),
    RuleDefinition(
        RuleId.BR_10,
        "No commit without approval",
        "Nothing is committed to SAP or the DMS without a recorded approval.",
    ),
    RuleDefinition(
        RuleId.BR_11,
        "AI provenance retained",
        "Every AI output retains its confidence, its evidence and the history of any override.",
    ),
    RuleDefinition(
        RuleId.BR_12,
        "Actions are audited",
        "Every governance-relevant action is written to the append-only audit trail.",
    ),
    RuleDefinition(
        RuleId.BR_13,
        "Repeated documents link, never duplicate",
        "A document received again links to the transaction it already belongs to rather than "
        "creating a second one.",
    ),
    RuleDefinition(
        RuleId.IV_01,
        "Invoice dating",
        "An invoice dated further in the past than the configured window, or dated in the "
        "future, is flagged for the preparing desk to accept or correct.",
    ),
    RuleDefinition(
        RuleId.SL_01,
        "Sales contract quantity coverage",
        "Everything invoiced against one sales contract number, summed across every shipment, "
        "must stay within the quantity that contract actually covers.",
    ),
    RuleDefinition(
        RuleId.LG_01,
        "Invoiced weight against the bill of lading",
        "The weight an invoice bills for and the weight the bill of lading states must agree "
        "within the configured tolerance. A difference beyond it is what a debit or a credit "
        "note is raised for, and is flagged for a person rather than settled by the platform.",
    ),
)

RULE_BY_ID: dict[str, RuleDefinition] = {rule.rule_id: rule for rule in RULE_CATALOG}
ALL_RULE_IDS: tuple[str, ...] = tuple(rule.rule_id for rule in RULE_CATALOG)


class CheckKey:
    """Names for the individual checks a rule carries when it carries more than one.

    BR-06 is the reason this exists: it is three genuinely different comparisons with three
    different behaviours, and collapsing them into one pass/fail would hide which one failed.
    """

    REFERENCE_PRESENT = "reference_present"
    CONTRACT_MATCH_THRESHOLD = "contract_match_threshold"
    SUPPLIER_MATCH_THRESHOLD = "supplier_match_threshold"
    SUGGESTION_FLOOR = "suggestion_floor"
    DOCUMENT_PACK = "document_pack"
    QUANTITY_TOLERANCE = "quantity_tolerance"
    AMOUNT_ROUNDING = "amount_rounding"
    AMOUNT_SELF_APPROVAL_LIMIT = "amount_self_approval_limit"
    RATE_TOLERANCE = "rate_tolerance"
    DUPLICATE_CONTENT = "duplicate_content"
    DUPLICATE_SIMILARITY = "duplicate_similarity"
    # BR-07 carries two checks because it draws one distinction: a draft bill of lading is enough
    # to start preparing a sales document, and only a final one lets the transaction be submitted.
    DRAFT_BL_PRESENT = "draft_bl_present"
    FINAL_BL_PRESENT = "final_bl_present"
    # SL-01's single check: the summed invoiced quantity against the contracted total.
    CONTRACT_QUANTITY_COVERAGE = "contract_quantity_coverage"
    # IV-01's checks. The window is how far back an invoice may be dated before it is flagged;
    # the advisory carries no threshold at all, because it states a local rule rather than
    # measuring anything.
    INVOICE_DATE_WINDOW = "invoice_date_window"
    INDIA_PAYMENT_TERMS_ADVISORY = "india_payment_terms_advisory"
    # LG-01's single check: the invoiced weight against the weight the bill of lading states.
    # Expressed as a percentage rather than an absolute tonnage because a tolerable difference on
    # a 25 MT container and on a 2,000 MT parcel are not the same number.
    OBL_WEIGHT_VARIANCE = "obl_weight_variance"
    # BR-03's single check: how many *other* transactions may hold a container this one quotes.
    # A batch spanning several containers of its own is not what this counts.
    CONTAINER_CROSS_TRANSACTION = "container_cross_transaction"
