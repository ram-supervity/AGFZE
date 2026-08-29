"""The sales module's evaluators: BR-07 for real, and SL-01.

Both are registered against 's registry through the same `@register` decorator every other
evaluator uses. Nothing in the orchestrator, the context or the persistence changed to accept
them - the dispatch walks the registry, sees two more entries, and calls them. That was the
promise the registry was built on, and this file is where it is collected on.

SL-01 is the only rule in the platform that reads outside the transaction it was handed. That is
deliberate and unavoidable: a sales contract is fulfilled across several shipments, so whether
more has been invoiced than was agreed is a question about the contract, not about any one
shipment, and answering it from a single transaction would always answer it wrong.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.enums import (
    DRAFT_BL_DOCUMENT_TYPES,
    FINAL_BILL_OF_LADING_TYPES,
    FINAL_BL_DOCUMENT_TYPES,
    RuleSeverity,
)
from app.models.logistics import BillOfLading, Shipment
from app.models.transactions import SalesLeg, TradeTransaction
from app.services.rules.catalog import CheckKey, RuleId
from app.services.rules.registry import RuleContext, RuleOutcome, register
from app.services.rules.values import format_decimal

SALES = frozenset({"sales"})


def _unconfigured(rule_id: str, check_key: str, field_name: str | None = None) -> RuleOutcome:
    return RuleOutcome(
        rule_id=rule_id,
        check_key=check_key,
        passed=False,
        severity=RuleSeverity.HARD.value,
        field_name=field_name,
        message=(
            f"{rule_id} has no active configuration for '{check_key}'. The rule cannot be "
            "evaluated until an administrator configures its threshold."
        ),
    )


# --- BR-07  a draft starts the paperwork, a final bill of lading finishes it -------------------


def _bl_documents(context: RuleContext, types: tuple[str, ...]) -> list:
    return [row for row in context.documents if row.document_type in types]


async def linked_bills_of_lading(context: RuleContext) -> list[BillOfLading]:
    """Every bill-of-lading record on any shipment of this transaction.

     gave BR-07 a purpose-built entity to ask. Before it existed the rule had to infer the
    answer from a document's classified type, which is a looser thing entirely: it says what a
    file looked like, not whether the original has physically arrived at the desk.
    """
    return list(
        (
            await context.session.scalars(
                select(BillOfLading)
                .join(Shipment, Shipment.id == BillOfLading.shipment_id)
                .where(Shipment.transaction_id == context.transaction.id)
                .order_by(BillOfLading.created_at)
            )
        ).all()
    )


@register(RuleId.BR_07, requires_legs=SALES)
async def evaluate_sales_document_readiness(context: RuleContext) -> list[RuleOutcome]:
    """Two checks, because BR-07 draws exactly one distinction and it matters twice.

    Preparing a draft is permitted from a draft bill of lading - that is the whole point of a
    draft B/L, and holding the paperwork until the original arrives is what the desk does today
    on paper and wants to stop doing. Submitting is not: a transaction reaching the approval
    queue is a transaction somebody is about to sign off, and it may not do that on a document
    that is still marked draft.

    The submission check asks the `BillOfLading` record from  onwards, which is a stronger
    question than the one it used to ask. "A file classified as a B/L is attached" is not the
    same fact as "the original is in hand", and only the second one is what submission waits for.
    """
    leg = context.leg("sales")
    drafts = _bl_documents(context, DRAFT_BL_DOCUMENT_TYPES)
    finals = _bl_documents(context, FINAL_BL_DOCUMENT_TYPES)
    reference = (getattr(leg, "bl_reference", None) or "").strip()
    bills = await linked_bills_of_lading(context)
    received = [
        bill
        for bill in bills
        if bill.is_original_received and bill.bl_type in FINAL_BILL_OF_LADING_TYPES
    ]

    # A recorded B/L reference counts for the draft check on its own: the desk routinely has the
    # number from the carrier before any document reaches the platform, and that is precisely the
    # point at which drafting is supposed to start.
    draft_evidence = bool(drafts) or bool(finals) or bool(reference) or bool(bills)
    draft_sources = [row.filename for row in (*drafts, *finals)]
    if bills and not draft_sources:
        draft_sources = [f"{bill.bl_type} B/L {bill.bl_number or 'on file'}" for bill in bills]
    if reference and not draft_sources:
        draft_sources = [f"B/L reference {reference}"]

    draft_check = RuleOutcome(
        rule_id=RuleId.BR_07,
        check_key=CheckKey.DRAFT_BL_PRESENT,
        passed=draft_evidence,
        # Never self-approvable. Drafting from nothing at all is not a tolerance question.
        severity=RuleSeverity.HARD.value,
        field_name="bl_reference",
        expected_value="a draft or original bill of lading, or a recorded B/L reference",
        actual_value=", ".join(draft_sources) or "none",
        message=(
            "A bill of lading is on file for this shipment, so a draft sales document may be "
            "prepared from it."
            if draft_evidence
            else "BR-07: no bill of lading - draft or original - and no B/L reference is "
            "recorded, so there is nothing to prepare a sales document against yet."
        ),
    )

    return [draft_check, _final_bl_outcome(bills, received, finals, drafts)]


def _final_bl_outcome(
    bills: list[BillOfLading],
    received: list[BillOfLading],
    finals: list,
    drafts: list,
) -> RuleOutcome:
    """Whether a final bill of lading is genuinely in hand, from the record that actually knows.

    The bill-of-lading record is the authority wherever one exists: `is_original_received` is a
    statement somebody made about a piece of paper on their desk, and it is the thing submission
    is supposed to wait for. The document-type distinction the rule used before it existed stays
    as the supporting signal, and is what the check falls back to for a transaction whose
    shipment has not been recorded yet - it is looser, but it is not nothing.
    """
    if bills:
        passed = bool(received)
        return RuleOutcome(
            rule_id=RuleId.BR_07,
            check_key=CheckKey.FINAL_BL_PRESENT,
            passed=passed,
            severity=RuleSeverity.HARD.value,
            field_name="bill_of_lading",
            expected_value="an original or seaway bill of lading recorded as received",
            actual_value=(
                ", ".join(f"{bill.bl_type} {bill.bl_number or 'B/L'} received" for bill in received)
                if received
                else ", ".join(
                    f"{bill.bl_type} {bill.bl_number or 'B/L'} not yet received" for bill in bills
                )
            ),
            message=(
                "The original bill of lading is recorded as received against this shipment, so "
                "this transaction may be submitted."
                if passed
                else "BR-07: this shipment's bill of lading is on record but has not been marked "
                "as received. Submission waits for the original itself, not for a draft or a "
                "number - mark it received on the shipment once it is physically in hand."
            ),
        )

    return RuleOutcome(
        rule_id=RuleId.BR_07,
        check_key=CheckKey.FINAL_BL_PRESENT,
        passed=bool(finals),
        severity=RuleSeverity.HARD.value,
        field_name="bill_of_lading",
        expected_value="an original (non-draft) bill of lading or shipping document",
        actual_value=(
            ", ".join(row.filename for row in finals)
            if finals
            else (
                f"{len(drafts)} draft bill(s) of lading only"
                if drafts
                else "no bill of lading attached"
            )
        ),
        message=(
            "An original bill of lading is attached, and no shipment record contradicts it, so "
            "this transaction may be submitted."
            if finals
            else "BR-07: a final bill of lading is required before submission. A draft is enough "
            "to generate and review a draft sales document, but not to put this transaction in "
            "front of an approver."
        ),
    )


def draft_generation_permitted(evaluations: list) -> tuple[bool, str | None]:
    """Read BR-07's draft check off a set of evaluations, without re-deriving it.

    The draft-generation endpoint asks this rather than looking for a document itself, so the
    gate the user is shown and the gate the server applies are the same evaluated row.
    """
    for row in evaluations:
        if row.rule_id == RuleId.BR_07 and row.check_key == CheckKey.DRAFT_BL_PRESENT:
            return bool(row.passed), None if row.passed else row.message
    return False, (
        "BR-07 has not been evaluated for this transaction yet, so draft generation is held "
        "until it has been."
    )


# --- SL-01  what has been invoiced against this contract, in total ----------------------------


@dataclass(frozen=True)
class ContractCoverage:
    """The aggregate position of one sales contract number, across every shipment on it."""

    contract_no: str
    contracted_quantity: Decimal | None
    invoiced_quantity: Decimal
    shipment_count: int

    @property
    def state(self) -> str:
        if self.contracted_quantity is None:
            return "unknown"
        if self.invoiced_quantity > self.contracted_quantity:
            return "exceeded"
        if self.invoiced_quantity == self.contracted_quantity:
            return "complete"
        return "partial"

    @property
    def remaining(self) -> Decimal | None:
        if self.contracted_quantity is None:
            return None
        return self.contracted_quantity - self.invoiced_quantity

    @property
    def ratio(self) -> float:
        if not self.contracted_quantity:
            return 0.0
        return float(self.invoiced_quantity / self.contracted_quantity)


async def sibling_transactions(session: AsyncSession, contract_no: str) -> list[TradeTransaction]:
    """Every transaction whose sales leg quotes this contract number, in batch order."""
    rows = (
        await session.scalars(
            select(TradeTransaction)
            .join(SalesLeg, SalesLeg.transaction_id == TradeTransaction.id)
            .where(SalesLeg.sales_contract_no == contract_no)
            .options(
                selectinload(TradeTransaction.sales_leg),
                selectinload(TradeTransaction.purchase_leg),
            )
            .order_by(TradeTransaction.created_at)
        )
    ).all()
    return list(rows)


async def contract_coverage(session: AsyncSession, contract_no: str) -> ContractCoverage:
    """Sum what every shipment on this contract carries, and read what the contract covers.

    The contracted total is expected to be the same on every leg quoting the number. Where the
    legs disagree - which is a data problem somebody has to fix - the largest recorded figure is
    used, because using the smallest would manufacture an over-shipment out of a typo.
    """
    rows = await sibling_transactions(session, contract_no)
    invoiced = sum((row.quantity_mt for row in rows if row.quantity_mt is not None), Decimal("0"))
    contracted = [
        row.sales_leg.contracted_quantity_mt
        for row in rows
        if row.sales_leg is not None and row.sales_leg.contracted_quantity_mt is not None
    ]
    return ContractCoverage(
        contract_no=contract_no,
        contracted_quantity=max(contracted) if contracted else None,
        invoiced_quantity=invoiced,
        shipment_count=len(rows),
    )


def coverage_outcome(
    coverage: ContractCoverage, tolerance: Decimal, *, contract_no: str | None
) -> RuleOutcome:
    """Turn an aggregate position into the one row SL-01 records for this transaction.

    Three states, and only one of them is a failure. A contract that is part-shipped is the
    normal, expected condition of a live sales contract and must never open an exception - a
    queue that fills up with "this contract has more shipments to come" is a queue nobody reads.
    """
    if not contract_no:
        return RuleOutcome(
            rule_id=RuleId.SL_01,
            check_key=CheckKey.CONTRACT_QUANTITY_COVERAGE,
            passed=False,
            severity=RuleSeverity.HARD.value,
            field_name="sales_contract_no",
            expected_value="a sales contract number",
            actual_value="none",
            message=(
                "SL-01: no sales contract number is recorded on this leg, so what has been "
                "invoiced cannot be checked against what was contracted."
            ),
        )

    contracted = coverage.contracted_quantity
    invoiced = coverage.invoiced_quantity
    shipments = coverage.shipment_count
    spread = f"{shipments} shipment{'' if shipments == 1 else 's'}"

    if contracted is None:
        return RuleOutcome(
            rule_id=RuleId.SL_01,
            check_key=CheckKey.CONTRACT_QUANTITY_COVERAGE,
            passed=False,
            severity=RuleSeverity.HARD.value,
            field_name="contracted_quantity_mt",
            expected_value="the total quantity sales contract " + contract_no + " covers",
            actual_value=f"{format_decimal(invoiced, suffix=' MT')} invoiced over {spread}",
            message=(
                f"SL-01: no contracted quantity is recorded for sales contract {contract_no}, so "
                "there is nothing to check the invoiced total against. Record it on this leg."
            ),
        )

    allowance = contracted + (contracted * tolerance / Decimal(100))
    excess = invoiced - contracted
    expected = f"{format_decimal(contracted, suffix=' MT')} contracted" + (
        f" (+{format_decimal(tolerance)}% permitted)" if tolerance > 0 else ""
    )
    actual = f"{format_decimal(invoiced, suffix=' MT')} invoiced over {spread}"

    if invoiced > allowance:
        return RuleOutcome(
            rule_id=RuleId.SL_01,
            check_key=CheckKey.CONTRACT_QUANTITY_COVERAGE,
            passed=False,
            # Hard, at any size. More has been sold than was agreed; that is a commercial fact
            # somebody has to settle with the customer, not a rounding artefact to wave through.
            severity=RuleSeverity.HARD.value,
            field_name="contracted_quantity_mt",
            expected_value=expected,
            actual_value=actual,
            message=(
                f"SL-01: {format_decimal(invoiced, suffix=' MT')} has now been invoiced across "
                f"{spread} against sales contract {contract_no}, which covers "
                f"{format_decimal(contracted, suffix=' MT')}. That is "
                f"{format_decimal(excess, suffix=' MT')} more than was ever contracted."
            ),
        )

    if invoiced == contracted:
        return RuleOutcome(
            rule_id=RuleId.SL_01,
            check_key=CheckKey.CONTRACT_QUANTITY_COVERAGE,
            passed=True,
            severity=RuleSeverity.HARD.value,
            field_name="contracted_quantity_mt",
            expected_value=expected,
            actual_value=actual,
            message=(
                f"Sales contract {contract_no} is fully shipped: "
                f"{format_decimal(invoiced, suffix=' MT')} invoiced across {spread}, exactly the "
                "contracted quantity."
            ),
        )

    # Under the contracted total. Normal, expected, and deliberately not an exception.
    return RuleOutcome(
        rule_id=RuleId.SL_01,
        check_key=CheckKey.CONTRACT_QUANTITY_COVERAGE,
        passed=True,
        severity=RuleSeverity.INFORMATIONAL.value,
        field_name="contracted_quantity_mt",
        expected_value=expected,
        actual_value=actual,
        message=(
            f"Sales contract {contract_no} is part-shipped: "
            f"{format_decimal(invoiced, suffix=' MT')} invoiced across {spread}, with "
            f"{format_decimal(coverage.remaining, suffix=' MT')} still to ship. Nothing is "
            "outstanding here - further shipments against this contract are expected."
        ),
    )


async def evaluate_coverage_for(
    session: AsyncSession, transaction: TradeTransaction, tolerance: Decimal
) -> tuple[RuleOutcome, ContractCoverage | None]:
    """SL-01's whole judgement for one transaction, reusable outside a validation run.

    The sibling propagation calls this directly, which is why it does not take a `RuleContext`:
    re-checking one rule on a neighbouring transaction must not rebuild that transaction's entire
    context and must not re-run any other rule against it.
    """
    leg = transaction.sales_leg
    contract_no = (getattr(leg, "sales_contract_no", None) or "").strip()
    if not contract_no:
        return coverage_outcome(
            ContractCoverage("", None, Decimal("0"), 0), tolerance, contract_no=None
        ), None
    coverage = await contract_coverage(session, contract_no)
    return coverage_outcome(coverage, tolerance, contract_no=contract_no), coverage


@register(RuleId.SL_01, requires_legs=SALES)
async def evaluate_contract_quantity_coverage(context: RuleContext) -> list[RuleOutcome]:
    """Has more been invoiced against this sales contract than the contract actually covers?"""
    tolerance, _ = context.threshold(RuleId.SL_01, CheckKey.CONTRACT_QUANTITY_COVERAGE)
    if tolerance is None:
        return [
            _unconfigured(
                RuleId.SL_01, CheckKey.CONTRACT_QUANTITY_COVERAGE, "contracted_quantity_mt"
            )
        ]

    outcome, _ = await evaluate_coverage_for(context.session, context.transaction, tolerance)
    return [outcome]
