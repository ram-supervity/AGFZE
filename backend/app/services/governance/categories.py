"""The exception matrix as reference data, and the default rule-to-category mapping it seeds.

Two separate things live here, and the difference matters.

The catalog is a description: ten categories, who owns each, and - stated honestly - whether the
platform can produce one yet. It is what the queue renders its ten tabs from, so the structure was
complete from the start and needed no restructuring when Step 6 gave two of the dormant three
their producing code, and the integration hub in Step 7 gave the last one - the integration
failure - its own. Every category the queue renders now has code behind it that can genuinely
raise it.

The mapping is behaviour, expressed as rows. It is what actually decides which category a failing
rule opens. The engine never asks "is this BR-04?"; it asks the table what this rule means. A
later step brings its own rules to life by inserting rows, and touches no orchestration code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.roles import PlatformRole
from app.models.enums import ExceptionCategory, ExceptionPriority
from app.services.rules.catalog import CheckKey, RuleId


@dataclass(frozen=True)
class CategoryDefinition:
    category: str
    label: str
    owner_role: str
    # The desks the matrix names, where more than one may work the category.
    shared_with: tuple[str, ...]
    # False while nothing in the platform can produce this category yet. Registered so the queue
    # is structurally complete; deliberately not faked into producing rows.
    triggerable: bool
    description: str
    dormant_reason: str | None = None


CATEGORY_CATALOG: tuple[CategoryDefinition, ...] = (
    CategoryDefinition(
        ExceptionCategory.MISSING_MANDATORY_DOCUMENT.value,
        "Missing mandatory document",
        PlatformRole.PURCHASE_USER.value,
        # The selling desk joins from Step 5: BR-07's missing final bill of lading is a missing
        # mandatory document, and it is Sales who chases the carrier for it. The FA desk joins
        # from Step 6 for the plainest reason: an FA transaction can fail BR-04 too, and a case
        # owned by a desk that cannot open it is a case nobody works.
        (
            PlatformRole.FINANCE_USER.value,
            PlatformRole.SALES_USER.value,
            PlatformRole.FA_USER.value,
        ),
        True,
        "The destination territory's document checklist is not complete for this batch, or a "
        "document a rule requires before the transaction can go forward is not on file.",
    ),
    CategoryDefinition(
        ExceptionCategory.MISMATCHED_CONTAINER_NUMBER.value,
        "Mismatched container number",
        PlatformRole.LOGISTICS_USER.value,
        # The desks that prepare the transactions raise it, and are the ones who can say which
        # of the two competing links is the wrong one.
        (
            PlatformRole.PURCHASE_USER.value,
            PlatformRole.SALES_USER.value,
            PlatformRole.FA_USER.value,
        ),
        True,
        "A container quoted on this transaction is already associated with a different, "
        "unrelated one. Real from the shipment module onwards, and deliberately never raised "
        "for a batch that simply spans more than one container.",
    ),
    CategoryDefinition(
        ExceptionCategory.INVOICE_AMOUNT_OUTSIDE_TOLERANCE.value,
        "Invoice amount outside tolerance",
        PlatformRole.FINANCE_USER.value,
        (PlatformRole.PURCHASE_USER.value, PlatformRole.FA_USER.value),
        True,
        "The invoiced value or price is outside what the contracted terms allow. A difference "
        "small enough to be self-approved never reaches this queue: it is acknowledged in the "
        "transaction workspace instead.",
    ),
    CategoryDefinition(
        ExceptionCategory.QUANTITY_VARIATION_OUTSIDE_TOLERANCE.value,
        "Quantity variation outside tolerance",
        PlatformRole.PURCHASE_USER.value,
        # Shared with the selling desk and the approver from Step 5: SL-01 can put a
        # quantity breach in here that the buying desk cannot settle on its own, because it is
        # the customer's contract that has been over-invoiced.
        (
            PlatformRole.SALES_USER.value,
            PlatformRole.APPROVER_HOD.value,
            PlatformRole.FA_USER.value,
        ),
        True,
        "The invoiced quantity varies from the contracted figure by more than the configured "
        "tolerance, on either side of the deal. Quantity has no self-approval tier at any size.",
    ),
    CategoryDefinition(
        ExceptionCategory.UNMATCHED_REFERENCE.value,
        "Unmatched contract or batch reference",
        PlatformRole.PURCHASE_USER.value,
        (PlatformRole.SALES_USER.value, PlatformRole.FA_USER.value),
        True,
        "No usable invoice, contract or batch reference is recorded, so the deal cannot be tied "
        "to a counterparty's paperwork. Every desk that prepares a transaction can land here, "
        "and the case is owned by whichever one actually carries the leg.",
    ),
    CategoryDefinition(
        ExceptionCategory.LOW_CONFIDENCE.value,
        "Low OCR / AI confidence",
        PlatformRole.PURCHASE_USER.value,
        (
            PlatformRole.SALES_USER.value,
            PlatformRole.FA_USER.value,
            PlatformRole.LOGISTICS_USER.value,
        ),
        True,
        "The machine was not confident enough about what a document says. The owner is whoever "
        "is already carrying the request the document arrived on.",
    ),
    CategoryDefinition(
        ExceptionCategory.DUPLICATE_DOCUMENT.value,
        "Duplicate or repeated document",
        PlatformRole.ADMIN.value,
        (),
        True,
        "A repeated document was linked rather than duplicated, which is the correct behaviour. "
        "The case exists so the link is visible and auditable, not because anything is broken.",
    ),
    CategoryDefinition(
        ExceptionCategory.SHIPMENT_STATUS_UNAVAILABLE.value,
        "Shipment status unavailable or delayed",
        PlatformRole.LOGISTICS_USER.value,
        (),
        True,
        "Nobody has established where this cargo is for longer than the configured threshold "
        "allows, or the attempts to find out have failed repeatedly. Real from the shipment "
        "module onwards, and raised whether the silence came from an unreachable carrier or "
        "from nobody having typed anything in.",
    ),
    CategoryDefinition(
        ExceptionCategory.APPROVAL_NOT_RECEIVED.value,
        "Approval not received",
        PlatformRole.APPROVER_HOD.value,
        (),
        True,
        "A transaction has waited for a decision longer than the configured threshold allows.",
    ),
    CategoryDefinition(
        ExceptionCategory.INTEGRATION_FAILURE.value,
        "SAP / DMS / integration failure",
        PlatformRole.ADMIN.value,
        (),
        True,
        "A downstream system rejected or failed to accept a posting, and every automatic "
        "attempt has been used up. Real from the integration hub onwards, and deliberately not "
        "raised for a posting that is simply waiting on a person - that is an honest state of "
        "the job, not a failure of anything.",
    ),
)

CATEGORY_BY_NAME: dict[str, CategoryDefinition] = {row.category: row for row in CATEGORY_CATALOG}
ALL_CATEGORIES: tuple[str, ...] = tuple(row.category for row in CATEGORY_CATALOG)


def desks_for(category: str) -> frozenset[str]:
    """Every desk role the matrix lets work this category, plus Admin, who works all of them."""
    definition = CATEGORY_BY_NAME.get(category)
    if definition is None:
        return frozenset({PlatformRole.ADMIN.value})
    return frozenset({definition.owner_role, *definition.shared_with, PlatformRole.ADMIN.value})


def _mapping(
    rule_id: str,
    check_key: str | None,
    category: str,
    owner_role: str,
    priority: str,
    description: str,
) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "check_key": check_key,
        "exception_type": category,
        "owner_role": owner_role,
        "priority": priority,
        "description": description,
        "is_active": True,
    }


def default_rule_exception_mappings() -> list[dict[str, Any]]:
    """One row per check this step's engine can genuinely hard-fail on.

    BR-06 carries three rows because it carries three genuinely different checks: an amount
    problem is Finance's, a quantity problem is the buying desk's, and the two must not land in
    the same tab. BR-02 and BR-13 map at rule level because each carries one meaning.
    """
    return [
        _mapping(
            RuleId.BR_02,
            CheckKey.REFERENCE_PRESENT,
            ExceptionCategory.UNMATCHED_REFERENCE.value,
            PlatformRole.PURCHASE_USER.value,
            ExceptionPriority.HIGH.value,
            "A transaction with no business reference cannot be tied to a counterparty's "
            "paperwork at all, so it blocks everything behind it.",
        ),
        _mapping(
            RuleId.BR_04,
            CheckKey.DOCUMENT_PACK,
            ExceptionCategory.MISSING_MANDATORY_DOCUMENT.value,
            PlatformRole.PURCHASE_USER.value,
            ExceptionPriority.HIGH.value,
            "The territory's mandatory document checklist is incomplete; the buying desk chases "
            "the missing paperwork.",
        ),
        _mapping(
            RuleId.BR_05,
            CheckKey.QUANTITY_TOLERANCE,
            ExceptionCategory.QUANTITY_VARIATION_OUTSIDE_TOLERANCE.value,
            PlatformRole.PURCHASE_USER.value,
            ExceptionPriority.MEDIUM.value,
            "Invoiced quantity is outside the contracted tolerance.",
        ),
        _mapping(
            RuleId.BR_06,
            CheckKey.AMOUNT_ROUNDING,
            ExceptionCategory.INVOICE_AMOUNT_OUTSIDE_TOLERANCE.value,
            PlatformRole.FINANCE_USER.value,
            ExceptionPriority.HIGH.value,
            "The invoiced value is beyond the ceiling a preparing user may accept on their own, "
            "so it becomes Finance's to settle with the buying desk.",
        ),
        _mapping(
            RuleId.BR_06,
            CheckKey.QUANTITY_TOLERANCE,
            ExceptionCategory.QUANTITY_VARIATION_OUTSIDE_TOLERANCE.value,
            PlatformRole.PURCHASE_USER.value,
            ExceptionPriority.MEDIUM.value,
            "The quantity behind the invoice agreement check is outside tolerance; that is the "
            "buying desk's problem, not Finance's.",
        ),
        _mapping(
            RuleId.BR_06,
            CheckKey.RATE_TOLERANCE,
            ExceptionCategory.INVOICE_AMOUNT_OUTSIDE_TOLERANCE.value,
            PlatformRole.FINANCE_USER.value,
            ExceptionPriority.HIGH.value,
            "Price is a negotiated term, so any difference from the contract is an invoice-value "
            "exception rather than a measurement one.",
        ),
        _mapping(
            RuleId.BR_13,
            CheckKey.DUPLICATE_CONTENT,
            ExceptionCategory.DUPLICATE_DOCUMENT.value,
            PlatformRole.ADMIN.value,
            ExceptionPriority.LOW.value,
            "A byte-identical document sits on a competing transaction. Raised for system and "
            "process visibility; the automatic link is already the correct handling.",
        ),
    ]


def sales_rule_exception_mappings() -> list[dict[str, Any]]:
    """The rows the sales module adds, and the whole of what it had to do to route its failures.

    Two rows. No branch, no list of rule identifiers, no change to the hook that reads this table
    and no change to the orchestrator that calls it. That is what Step 4's mapping table was
    built for, and adding these two is the proof it works.

    Kept apart from `default_rule_exception_mappings` for the same reason the sales rule
    configurations are: that function is what the Step 4 migration writes, and it has to keep
    writing exactly what it wrote.
    """
    return [
        _mapping(
            RuleId.SL_01,
            CheckKey.CONTRACT_QUANTITY_COVERAGE,
            ExceptionCategory.QUANTITY_VARIATION_OUTSIDE_TOLERANCE.value,
            PlatformRole.SALES_USER.value,
            ExceptionPriority.HIGH.value,
            "More has been invoiced against this sales contract, summed across every shipment on "
            "it, than the contract covers. The selling desk owns it, with the buying desk and the "
            "approver alongside, because settling it is a conversation with the customer.",
        ),
        _mapping(
            RuleId.BR_07,
            CheckKey.FINAL_BL_PRESENT,
            ExceptionCategory.MISSING_MANDATORY_DOCUMENT.value,
            PlatformRole.SALES_USER.value,
            ExceptionPriority.MEDIUM.value,
            "The transaction has no original bill of lading, so it cannot be submitted. The "
            "selling desk chases the carrier or the freight forwarder for it.",
        ),
    ]


def shipment_rule_exception_mappings() -> list[dict[str, Any]]:
    """The one row the shipment module adds, and again the whole of what routing it required.

    BR-03's failure is a container that belongs to two deals. It is logistics' to untangle - they
    are the people with the carrier's manifest - with the preparing desks alongside them, because
    only they can say which transaction the paperwork really belonged to.

    The shipment-staleness case has no row here on purpose. It is not a rule evaluation on
    extracted data, so it does not route through the rule-to-category mapping at all: the sweep
    calls the exception-creation function directly, with the same category vocabulary and the
    same queue. Inventing a synthetic rule to give it a mapping row would be fabricating an
    evaluation that never happened.
    """
    return [
        _mapping(
            RuleId.BR_03,
            CheckKey.CONTAINER_CROSS_TRANSACTION,
            ExceptionCategory.MISMATCHED_CONTAINER_NUMBER.value,
            PlatformRole.LOGISTICS_USER.value,
            ExceptionPriority.HIGH.value,
            "A container on this transaction is already associated with a different one. One of "
            "the two links is wrong, and logistics holds the carrier's manifest that settles it.",
        ),
    ]


def draft_bl_rule_exception_mapping() -> list[dict[str, Any]]:
    """BR-07's other half, which has been a hard failure with nobody's name on it.

    BR-07 carries two checks. `final_bl_present` has routed to the sales desk since Step 5;
    `draft_bl_present` never got a row, so a transaction failing it produced a blocking failure,
    an `exception_mapping_missing` warning in the log, and no case for anyone to work - against
    the governing document's plain requirement that *every* exception have an accountable owner,
    reason, age, priority and next action, and against BR-08's requirement that a missing
    document reach the queue at all.

    Nothing about the routing had to be invented to close it. It is the same rule, about the same
    document, at the same desk as the sibling check already mapped beside it, and the exception
    matrix routes a missing mandatory document to the desk that owns the transaction. So:
    the missing-document category, the sales desk.

    Priority is the one judgement here, and it is `low` rather than the sibling's `medium` on
    purpose. `final_bl_present` blocks a submission; this one only blocks *preparing a draft*
    ahead of the paperwork arriving, which is a normal early state on a live deal rather than
    something going wrong. Ranking it alongside a stalled submission would push genuinely stuck
    work down the queue behind cargo that is simply still in transit.
    """
    return [
        _mapping(
            RuleId.BR_07,
            CheckKey.DRAFT_BL_PRESENT,
            ExceptionCategory.MISSING_MANDATORY_DOCUMENT.value,
            PlatformRole.SALES_USER.value,
            ExceptionPriority.LOW.value,
            "No bill of lading - draft or original - and no B/L reference is recorded, so no "
            "sales document can be prepared against this cargo yet. The sales desk chases the "
            "reference from the carrier or the shipper; it clears itself the moment one arrives.",
        ),
    ]


def purchase_bundle_rule_exception_mappings() -> list[dict[str, Any]]:
    """PR-01's two routing rows, and the whole of what routing its failures required.

    Both belong to the buying desk, because both are answered by going back to the supplier: a
    missing weight slip is chased, and a contract that turned up on an intake is filed against
    the deal it actually belongs to. Neither is a finance or a logistics question.

    The purity failure is `unmatched_reference` rather than a category of its own: a document on
    a purchase intake that a purchase intake never carries is, precisely, a document nobody has
    established the deal for.
    """
    return [
        _mapping(
            RuleId.PR_01,
            CheckKey.PURCHASE_BUNDLE_COMPLETE,
            ExceptionCategory.MISSING_MANDATORY_DOCUMENT.value,
            PlatformRole.PURCHASE_USER.value,
            ExceptionPriority.HIGH.value,
            "A purchase deal arrives as three documents - the supplier's invoice, the packing "
            "list and the weight slip. One of them has not arrived, so nothing is generated for "
            "this deal and no Loading Sheet row is written until it does.",
        ),
        _mapping(
            RuleId.PR_01,
            CheckKey.PURCHASE_BUNDLE_PURITY,
            ExceptionCategory.UNMATCHED_REFERENCE.value,
            PlatformRole.PURCHASE_USER.value,
            ExceptionPriority.MEDIUM.value,
            "Something a purchase bundle never carries arrived on a purchase intake. The "
            "purchase contract in particular is written by this platform out of the confirmed "
            "figures, so one received inbound belongs to another deal or is a draft come back "
            "round, and a person establishes which.",
        ),
    ]


def obl_weight_rule_exception_mappings() -> list[dict[str, Any]]:
    """LG-01's single routing row, and the whole of what routing its failures required.

    One row. No branch in the hook that reads this table, and none in the orchestrator that calls
    it - the third rule added since Step 4 to need nothing but a row here.

    The logistics desk owns it rather than the buying desk, because resolving a weight difference
    starts with the shipping documents and the carrier, not with the supplier's invoice.
    """
    return [
        _mapping(
            RuleId.LG_01,
            CheckKey.OBL_WEIGHT_VARIANCE,
            ExceptionCategory.QUANTITY_VARIATION_OUTSIDE_TOLERANCE.value,
            PlatformRole.LOGISTICS_USER.value,
            ExceptionPriority.MEDIUM.value,
            "The weight billed and the weight shipped disagree beyond tolerance. The logistics "
            "desk establishes which figure is right from the shipping documents, and the "
            "difference is settled with a debit or a credit note - which a person raises, not "
            "this platform.",
        ),
    ]
