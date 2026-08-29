"""BR-03, real at last.

The rule sat in the registry from Step 3 reporting itself unevaluable, because there was no
`Container` table for it to read. There is one now, and this is the body that replaces the
placeholder. Nothing in the orchestrator, the context or the persistence changed to accept it -
registering it is the whole of the integration, for the third time.

What BR-03 actually asks is narrower than "the container numbers agree", and the difference is
the entire point of the rule. A batch legitimately spans several containers; that is normal
loading, not a discrepancy, and flagging it would fill the logistics queue with the shape of
ordinary business. What is not normal is one physical box appearing on two unrelated
transactions, because a container can only be one deal's cargo - so that, and only that, is what
hard-fails here.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from app.models.enums import DocumentType, RuleSeverity
from app.models.logistics import Container
from app.models.transactions import TradeTransaction
from app.services.rules.catalog import CheckKey, RuleId
from app.services.rules.registry import RuleContext, RuleOutcome, register
from app.services.rules.values import format_decimal, percentage_difference, to_decimal

# The extracted fields a container number is reported in, across every document schema the
# platform seeds. Read as a list rather than a single field because a bill of lading names every
# box on the shipment in one comma-separated value.
CONTAINER_FIELD_NAMES: tuple[str, ...] = (
    "container_numbers",
    "container_or_bl_reference",
    "container_number",
)


def normalise_container_number(raw: str | None) -> str | None:
    """A container number as ISO 6346 writes it: eleven characters, no spaces, upper case.

    Returns None for anything that is not one. The invoice schema's field is a *container or
    B/L* reference, so it frequently holds a bill-of-lading number instead, and treating that as
    a container would have BR-03 compare two things that are not the same kind of thing.
    """
    cleaned = "".join((raw or "").split()).upper().replace("-", "")
    if len(cleaned) != 11:
        return None
    if not cleaned[:4].isalpha() or not cleaned[4:].isdigit():
        return None
    return cleaned


def container_numbers_in(value: str | None) -> list[str]:
    """Every container number in one extracted value, which may list several."""
    parts = (value or "").replace(";", ",").split(",")
    found = [normalise_container_number(part) for part in parts]
    return [number for number in found if number is not None]


async def quoted_container_numbers(context: RuleContext) -> list[str]:
    """Every container this transaction is associated with, from its records and its documents.

    Both sources on purpose. The `Container` rows are what the matching service created, and the
    documents are what has arrived since; a number that appears on a newly linked bill of lading
    but has not been turned into a row yet is still a number this rule has to check.

    The rows are queried rather than read off the transaction's relationship. A transaction the
    caller assembled itself - which the matching path does, and which the tests do - has that
    collection unloaded, and reading it would be a query issued from wherever the evaluator
    happens to be called rather than an explicit one here.
    """
    numbers: list[str] = []
    recorded = (
        await context.session.scalars(
            select(Container.container_number).where(
                Container.transaction_id == context.transaction.id
            )
        )
    ).all()
    for raw in recorded:
        number = normalise_container_number(raw)
        if number is not None:
            numbers.append(number)
    for values in context.document_fields.values():
        for field_name in CONTAINER_FIELD_NAMES:
            numbers.extend(container_numbers_in(values.get(field_name)))
    # De-duplicated, order preserved, so the message reads in the order the documents do.
    return list(dict.fromkeys(numbers))


@register(RuleId.BR_03)
async def evaluate_container_agreement(context: RuleContext) -> list[RuleOutcome]:
    """Is any container on this transaction already claimed by a different, unrelated one?"""
    allowance, _ = context.threshold(RuleId.BR_03, CheckKey.CONTAINER_CROSS_TRANSACTION)
    if allowance is None:
        return [
            RuleOutcome(
                rule_id=RuleId.BR_03,
                check_key=CheckKey.CONTAINER_CROSS_TRANSACTION,
                passed=False,
                severity=RuleSeverity.HARD.value,
                field_name="container_number",
                message=(
                    "BR-03 has no active configuration for "
                    f"'{CheckKey.CONTAINER_CROSS_TRANSACTION}'. The rule cannot be evaluated "
                    "until an administrator configures its threshold."
                ),
            )
        ]

    numbers = await quoted_container_numbers(context)
    if not numbers:
        return [
            RuleOutcome(
                rule_id=RuleId.BR_03,
                check_key=CheckKey.CONTAINER_CROSS_TRANSACTION,
                passed=True,
                severity=RuleSeverity.HARD.value,
                field_name="container_number",
                expected_value="no container claimed by another transaction",
                actual_value="no container number recorded yet",
                message=(
                    "No container number has been recorded or extracted for this transaction "
                    "yet, so there is nothing whose ownership could be in dispute."
                ),
            )
        ]

    rows = (
        await context.session.execute(
            select(Container.container_number, TradeTransaction.batch_number)
            .join(TradeTransaction, TradeTransaction.id == Container.transaction_id)
            .where(
                Container.container_number.in_(numbers),
                Container.transaction_id != context.transaction.id,
            )
        )
    ).all()
    # One entry per container, naming the batch that already holds it.
    elsewhere: dict[str, str] = dict(rows)

    passed = len(elsewhere) <= int(allowance)
    spread = f"{len(numbers)} container{'' if len(numbers) == 1 else 's'}"

    return [
        RuleOutcome(
            rule_id=RuleId.BR_03,
            check_key=CheckKey.CONTAINER_CROSS_TRANSACTION,
            passed=passed,
            # Hard, and never acknowledgeable. If this box belongs to another deal then either
            # this transaction or that one has the wrong cargo on it, and no amount of accepting
            # the discrepancy makes the two records right.
            severity=RuleSeverity.HARD.value,
            field_name="container_number",
            expected_value=(
                f"at most {int(allowance)} other transaction(s) holding any of these containers"
            ),
            actual_value=(
                ", ".join(
                    f"{number} on batch {batch}" for number, batch in sorted(elsewhere.items())
                )
                if elsewhere
                else f"{spread}, none held elsewhere"
            ),
            message=(
                f"{spread} recorded against this batch, and none of them is associated with any "
                "other transaction. A batch loaded into more than one container is normal and is "
                "not what this rule looks for."
                if passed
                else "BR-03: "
                + ", ".join(
                    f"container {number} is already associated with batch {batch}"
                    for number, batch in sorted(elsewhere.items())
                )
                + ". One physical container cannot be two deals' cargo, so one of the two links "
                "is wrong. Check which transaction this document really belongs to before going "
                "any further."
            ),
        )
    ]


# --- LG-01: the invoiced weight against the weight the bill of lading states ---------------------
#
# Not a restatement of BR-05, and the difference is what makes it worth having. BR-05 compares the
# invoice against the **contract** - what was agreed. This compares the invoice against the **bill
# of lading** - what actually shipped. A load can sit comfortably inside its contractual tolerance
# and still be billed for more or less than the vessel carried, and that discrepancy is money:
# discovery named it as exactly the trigger for raising a debit note (invoice heavier than the OBL)
# or a credit note (OBL heavier than the invoice).
#
# **Scope limit, stated here because it is the most likely thing to be misread.** This rule detects
# and flags. It does **not** generate a debit or credit note. Raising one is an act of external
# correspondence with a counterparty, in a document format nothing in this platform's material
# specifies, and a platform that generated one automatically would be committing AGFZE to a
# financial claim no person had read. The moment AGFZE confirms the format, generating it is the
# existing `draft_service`/template path - reviewed draft first, person second - and not a new
# mechanism. See docs/KNOWN-GAPS.md.
#
# Severity is `acknowledgeable` rather than `hard`, deliberately. A genuine weight difference is a
# real commercial fact that a person resolves with a note to the counterparty; it is not a data
# error to be corrected before the transaction may proceed, and blocking on it would strand a
# correct transaction behind a discrepancy the desk has already dealt with.

BL_DOCUMENT_TYPES: tuple[str, ...] = (DocumentType.BL.value, DocumentType.BL_DRAFT.value)


def bill_of_lading_quantity(context: RuleContext) -> tuple[Decimal | None, str | None]:
    """The shipped weight, from the most recent bill of lading this transaction carries.

    A final bill of lading is preferred over a draft whenever one exists, because a draft's figures
    are still subject to change and comparing money against a provisional weight would raise notes
    that the final document then contradicts. Within one type, the most recently received wins,
    matching how every other rule here resolves a document that arrived twice.
    """
    for document_type in BL_DOCUMENT_TYPES:
        document = context.latest_of_type(document_type)
        if document is None:
            continue
        quantity = to_decimal(context.fields_of(document).get("quantity"))
        if quantity is not None:
            return quantity, document_type
    return None, None


@register(RuleId.LG_01)
async def evaluate_invoiced_weight_against_bill_of_lading(
    context: RuleContext,
) -> list[RuleOutcome]:
    """Does what was billed agree with what shipped?"""
    tolerance, _ = context.threshold(RuleId.LG_01, CheckKey.OBL_WEIGHT_VARIANCE)
    if tolerance is None:
        return [
            RuleOutcome(
                rule_id=RuleId.LG_01,
                check_key=CheckKey.OBL_WEIGHT_VARIANCE,
                passed=False,
                severity=RuleSeverity.ACKNOWLEDGEABLE.value,
                field_name="quantity",
                message=(
                    "The tolerable difference between the invoiced weight and the bill of "
                    "lading's weight is not configured, so this check cannot be made."
                ),
            )
        ]

    invoiced = to_decimal(context.fields_of(context.latest_value_document()).get("quantity"))
    shipped, source = bill_of_lading_quantity(context)

    # Not applicable rather than failing. A transaction whose bill of lading has not arrived yet -
    # which is most of a transaction's life - has nothing to disagree with, and reporting that as a
    # discrepancy would fill the logistics queue with the shape of ordinary business. BR-07 is the
    # rule that cares whether a bill of lading exists at all; this one only compares.
    if invoiced is None or shipped is None:
        return [
            RuleOutcome(
                rule_id=RuleId.LG_01,
                check_key=CheckKey.OBL_WEIGHT_VARIANCE,
                passed=True,
                severity=RuleSeverity.INFORMATIONAL.value,
                field_name="quantity",
                message=(
                    "No bill of lading weight has been extracted yet, so there is nothing to "
                    "compare the invoiced weight against."
                    if shipped is None
                    else "No invoiced weight has been extracted yet, so there is nothing to "
                    "compare against the bill of lading."
                ),
            )
        ]

    variation = percentage_difference(shipped, invoiced)
    passed = variation is not None and variation <= tolerance
    rendered = format_decimal(variation, suffix="%") if variation is not None else "unmeasurable"
    label = "final bill of lading" if source == DocumentType.BL.value else "draft bill of lading"

    if passed:
        message = (
            f"Invoiced weight {format_decimal(invoiced, suffix=' MT')} agrees with the "
            f"{label}'s {format_decimal(shipped, suffix=' MT')} "
            f"({rendered} difference, within {format_decimal(tolerance)}%)."
        )
    else:
        # Directional, because the direction decides which document a person raises. Said in the
        # message rather than left to the reader to work out from two numbers.
        note = "debit note" if invoiced > shipped else "credit note"
        heavier = "more than" if invoiced > shipped else "less than"
        message = (
            f"The invoice bills for {format_decimal(invoiced, suffix=' MT')}, which is {heavier} "
            f"the {format_decimal(shipped, suffix=' MT')} the {label} states "
            f"({rendered} difference, above the {format_decimal(tolerance)}% tolerance). "
            f"A {note} is the usual correction. Accept this with a reason if the difference is "
            "already settled with the counterparty."
        )

    return [
        RuleOutcome(
            rule_id=RuleId.LG_01,
            check_key=CheckKey.OBL_WEIGHT_VARIANCE,
            passed=passed,
            severity=RuleSeverity.ACKNOWLEDGEABLE.value,
            field_name="quantity",
            expected_value=(
                f"{format_decimal(shipped, suffix=' MT')} ±{format_decimal(tolerance)}%"
            ),
            actual_value=f"{format_decimal(invoiced, suffix=' MT')} ({rendered})",
            message=message,
        )
    ]
