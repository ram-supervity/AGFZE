"""The rule evaluators.

Five rules could genuinely be judged with the data that existed when this file was written -
BR-02, BR-04, BR-05, BR-06 and BR-13 - and those five are implemented here for real. The rest
were registered too, so the registry was complete and the orchestrator's dispatch never had to
learn about a new rule; each reported itself unevaluated and wrote nothing until the step that
brought its data replaced the body.

BR-07 was the first of those to come to life, beside SL-01 in `sales_evaluators`. BR-03 is the
second, in `logistics_evaluators`. Both modules are imported at the foot of this one, and that
import is the whole of what each had to do - no change here, and none in the orchestrator.

The FA stream, added with those same shipment tables, brought no evaluator of its own at all. The
five below judge an FA transaction exactly as they judge a purchase one, because what changed to
make that work was where they read from, not what they decide: the leg is asked for a *concept*
rather than a named column, and the commercial figures are read from whichever document type the
stream actually carries. Nowhere below does the word "purchase" or "FA" decide an outcome.

Not one threshold in this file is a literal. Every comparison asks the context for its configured
value, and a rule with no active configuration fails loudly rather than passing quietly.
"""

from __future__ import annotations

from decimal import Decimal

from rapidfuzz import fuzz
from sqlalchemy import select

from app.models.enums import LME_LINKED_PRICE_BASES, RuleSeverity
from app.models.intake import Document
from app.services.rules.catalog import CheckKey, RuleId
from app.services.rules.registry import (
    RuleContext,
    RuleOutcome,
    not_applicable,
    register,
)
from app.services.rules.values import (
    format_decimal,
    money,
    percentage_difference,
    to_decimal,
    to_percentage,
)

# The legs these evaluators can judge. Adding "fa" was the entire registration change the second
# business stream required; the bodies below did not learn about it.
COMMERCIAL = frozenset({"purchase", "fa"})


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


# --- BR-02  a business reference must exist -------------------------------------------------


@register(RuleId.BR_02, requires_legs=COMMERCIAL)
async def evaluate_business_reference(context: RuleContext) -> list[RuleOutcome]:
    """The reference the matching service needs before it can match anything at all."""
    threshold, _ = context.threshold(RuleId.BR_02, CheckKey.REFERENCE_PRESENT)
    if threshold is None:
        return [_unconfigured(RuleId.BR_02, CheckKey.REFERENCE_PRESENT)]

    references = {
        "batch_number": context.transaction.batch_number,
        "contract_reference": context.leg_value("contract_reference"),
        "invoice_reference": context.leg_value("invoice_reference"),
    }
    present = {
        name: str(value).strip()
        for name, value in references.items()
        if value is not None and str(value).strip()
    }
    required = int(threshold)
    passed = len(present) >= required

    return [
        RuleOutcome(
            rule_id=RuleId.BR_02,
            check_key=CheckKey.REFERENCE_PRESENT,
            passed=passed,
            severity=RuleSeverity.HARD.value,
            field_name="business_reference",
            expected_value=f"at least {required} of batch, contract or invoice reference",
            actual_value=", ".join(f"{name}={value}" for name, value in present.items()) or "none",
            message=(
                "Business references present: " + ", ".join(sorted(present)) + "."
                if passed
                else "No invoice, contract or batch number is recorded, so this transaction "
                "cannot be identified against a counterparty's paperwork."
            ),
        )
    ]


# --- BR-04  the territory's mandatory document pack -----------------------------------------


def _pack_entry_present(entry: str, documents: list[Document]) -> Document | None:
    """Is this checklist entry evidenced by something actually attached?

    Three signals, strongest first.

    The document's own **kind** is the real answer: it is the classifier reading the face of the
    document and reporting, in the checklist's own vocabulary, what it is. One document may carry
    two kinds, which is how a mill certificate that prints its assay table satisfies both the
    mill test certificate and the chemical analysis entry without an equivalence hard-coded here.

    The **type** covers the entries that are types in their own right - an invoice, a contract.

    The **filename** is the fall-back, kept because it is how a pack whose kinds predate this
    vocabulary still resolves, and because an uploader's hint deserves to count. It is last on
    purpose: a supplier who names a scan `IMG_0042.pdf` is not thereby short of a document, and a
    checklist that could only be satisfied by a helpful filename was never really being checked.
    """
    needle = entry.strip().lower()
    compact = needle.replace("_", "")
    for document in documents:
        if needle in (document.document_kinds or ()):
            return document
        if document.document_type == needle or document.document_type_hint == needle:
            return document
        haystack = document.filename.lower()
        if needle.replace("_", " ") in haystack or compact in haystack.replace(" ", "").replace(
            "_", ""
        ).replace("-", ""):
            return document
    return None


@register(RuleId.BR_04)
async def evaluate_mandatory_documents(context: RuleContext) -> list[RuleOutcome]:
    """Read the checklist Step 2 seeded against the territory and check the pack against it."""
    ratio, _ = context.threshold(RuleId.BR_04, CheckKey.DOCUMENT_PACK)
    if ratio is None:
        return [_unconfigured(RuleId.BR_04, CheckKey.DOCUMENT_PACK, "document_pack")]

    checklist = context.mandatory_documents
    if not checklist:
        return [
            RuleOutcome(
                rule_id=RuleId.BR_04,
                check_key=CheckKey.DOCUMENT_PACK,
                passed=True,
                severity=RuleSeverity.HARD.value,
                field_name="document_pack",
                expected_value="no checklist configured",
                actual_value=f"{len(context.documents)} document(s) attached",
                message=(
                    "No mandatory-document checklist is configured for "
                    f"{context.territory or 'this territory'}, so nothing is required beyond what "
                    "is attached."
                ),
            )
        ]

    missing = [
        entry for entry in checklist if _pack_entry_present(entry, context.documents) is None
    ]
    present_count = len(checklist) - len(missing)
    achieved = Decimal(present_count) / Decimal(len(checklist))
    passed = achieved >= ratio

    return [
        RuleOutcome(
            rule_id=RuleId.BR_04,
            check_key=CheckKey.DOCUMENT_PACK,
            passed=passed,
            severity=RuleSeverity.HARD.value,
            field_name="document_pack",
            expected_value=f"{len(checklist)} of {len(checklist)} documents",
            actual_value=f"{present_count} of {len(checklist)} documents",
            message=(
                f"The {context.territory or 'configured'} document pack is complete."
                if passed
                else "The document pack is incomplete. Still missing: "
                + ", ".join(entry.replace("_", " ") for entry in missing)
                + "."
            ),
        )
    ]


# --- BR-05 and BR-06's quantity check -------------------------------------------------------


def _contracted_quantity(context: RuleContext) -> tuple[Decimal | None, str]:
    """What the quantity is judged against, and where that figure came from."""
    contracted = to_decimal(context.contract_terms.get("quantity"))
    if contracted is not None:
        return contracted, "the linked purchase contract"
    return context.transaction.quantity_mt, "the transaction's recorded quantity"


def _invoiced_quantity(context: RuleContext) -> Decimal | None:
    """The quantity the stream's own value document states - an invoice, or an FA document."""
    return to_decimal(context.fields_of(context.latest_value_document()).get("quantity"))


def _quantity_outcome(context: RuleContext, rule_id: str) -> RuleOutcome:
    """The shared quantity comparison.

    Quantity has no self-approval tier, on either rule that checks it: a load that is outside the
    contracted tolerance is a commercial fact somebody has to correct, not a rounding artefact a
    preparer may wave through. That is what separates it from the invoice amount.
    """
    tolerance, _ = context.threshold(rule_id, CheckKey.QUANTITY_TOLERANCE)
    if tolerance is None:
        return _unconfigured(rule_id, CheckKey.QUANTITY_TOLERANCE, "quantity")

    contracted, source = _contracted_quantity(context)
    invoiced = _invoiced_quantity(context)

    if contracted is None or invoiced is None:
        return RuleOutcome(
            rule_id=rule_id,
            check_key=CheckKey.QUANTITY_TOLERANCE,
            passed=False,
            severity=RuleSeverity.HARD.value,
            field_name="quantity",
            expected_value=format_decimal(contracted, suffix=" MT"),
            actual_value=format_decimal(invoiced, suffix=" MT"),
            message=(
                "Quantity cannot be compared: "
                + (
                    "no invoiced quantity has been extracted yet."
                    if invoiced is None
                    else "no contracted quantity is recorded to compare it against."
                )
            ),
        )

    variation = percentage_difference(contracted, invoiced)
    passed = variation is not None and variation <= tolerance
    rendered = format_decimal(variation, suffix="%") if variation is not None else "unmeasurable"

    return RuleOutcome(
        rule_id=rule_id,
        check_key=CheckKey.QUANTITY_TOLERANCE,
        passed=passed,
        severity=RuleSeverity.HARD.value,
        field_name="quantity",
        expected_value=f"{format_decimal(contracted, suffix=' MT')} ±{format_decimal(tolerance)}%",
        actual_value=f"{format_decimal(invoiced, suffix=' MT')} ({rendered})",
        message=(
            f"Invoiced quantity {format_decimal(invoiced, suffix=' MT')} is within "
            f"{format_decimal(tolerance)}% of {format_decimal(contracted, suffix=' MT')} from "
            f"{source} ({rendered} variation)."
            if passed
            else f"Invoiced quantity {format_decimal(invoiced, suffix=' MT')} varies by "
            f"{rendered} from {format_decimal(contracted, suffix=' MT')} on {source}, outside "
            f"the configured {format_decimal(tolerance)}% tolerance. Correct the underlying "
            "figures; a quantity breach cannot be acknowledged."
        ),
    )


@register(RuleId.BR_05, requires_legs=COMMERCIAL)
async def evaluate_quantity_variation(context: RuleContext) -> list[RuleOutcome]:
    # Shipped as ±5%. Discovery also raised ~3.3% as a possible industry standard, but that
    # figure was explicitly unconfirmed, so it is not what is seeded - and because the value is
    # configuration rather than code, adopting it later is a row change, not a release.
    return [_quantity_outcome(context, RuleId.BR_05)]


# --- BR-06  three checks, three different behaviours ----------------------------------------


def _amount_outcome(context: RuleContext) -> RuleOutcome:
    """The invoiced value against the value its own rate and quantity imply.

    Three tiers, and only the middle one is self-approvable: at or under the rounding tolerance
    it passes untouched, between there and the self-approval ceiling the preparing user may
    acknowledge it on the record, and above the ceiling nothing but a correction will clear it.
    """
    rounding, _ = context.threshold(RuleId.BR_06, CheckKey.AMOUNT_ROUNDING)
    ceiling, _ = context.threshold(RuleId.BR_06, CheckKey.AMOUNT_SELF_APPROVAL_LIMIT)
    if rounding is None:
        return _unconfigured(RuleId.BR_06, CheckKey.AMOUNT_ROUNDING, "amount")
    if ceiling is None:
        return _unconfigured(RuleId.BR_06, CheckKey.AMOUNT_SELF_APPROVAL_LIMIT, "amount")

    fields = context.fields_of(context.latest_value_document())

    invoiced = money(to_decimal(fields.get("amount")) or context.leg_value("amount"))
    rate = to_decimal(fields.get("rate")) or context.leg_value("rate")
    quantity = to_decimal(fields.get("quantity")) or context.transaction.quantity_mt

    if invoiced is None or rate is None or quantity is None:
        return RuleOutcome(
            rule_id=RuleId.BR_06,
            check_key=CheckKey.AMOUNT_ROUNDING,
            passed=False,
            severity=RuleSeverity.HARD.value,
            field_name="amount",
            expected_value=None,
            actual_value=format_decimal(invoiced),
            message=(
                "The invoice value cannot be checked: the amount, the rate and the quantity are "
                "not all present."
            ),
        )

    calculated = money(rate * quantity)
    difference = money(abs(invoiced - calculated))
    currency = context.transaction.currency

    if difference <= rounding:
        return RuleOutcome(
            rule_id=RuleId.BR_06,
            check_key=CheckKey.AMOUNT_ROUNDING,
            passed=True,
            severity=RuleSeverity.ACKNOWLEDGEABLE.value,
            field_name="amount",
            expected_value=f"{format_decimal(calculated)} {currency}",
            actual_value=f"{format_decimal(invoiced)} {currency}",
            message=(
                f"Invoiced {format_decimal(invoiced)} {currency} against a calculated "
                f"{format_decimal(calculated)} {currency}; the {format_decimal(difference)} "
                f"{currency} difference is within the {format_decimal(rounding)} {currency} "
                "rounding tolerance."
            ),
        )

    within_self_approval = difference <= ceiling
    return RuleOutcome(
        rule_id=RuleId.BR_06,
        check_key=CheckKey.AMOUNT_ROUNDING,
        passed=False,
        severity=(
            RuleSeverity.ACKNOWLEDGEABLE.value if within_self_approval else RuleSeverity.HARD.value
        ),
        field_name="amount",
        expected_value=f"{format_decimal(calculated)} {currency}",
        actual_value=f"{format_decimal(invoiced)} {currency}",
        message=(
            f"Invoiced {format_decimal(invoiced)} {currency} against a calculated "
            f"{format_decimal(calculated)} {currency} (rate {format_decimal(rate)} x quantity "
            f"{format_decimal(quantity)}). The {format_decimal(difference)} {currency} difference "
            + (
                f"is above the {format_decimal(rounding)} {currency} rounding tolerance but "
                f"within the {format_decimal(ceiling)} {currency} self-approval limit, so you may "
                "acknowledge it with a reason."
                if within_self_approval
                else f"exceeds the {format_decimal(ceiling)} {currency} self-approval limit. It "
                "must be corrected; it cannot be acknowledged."
            )
        ),
    )


def _contracted_price(context: RuleContext) -> tuple[Decimal | None, Decimal | None]:
    """The rate and LME percentage the contract actually states."""
    terms = context.contract_terms
    contracted_rate = to_decimal(terms.get("rate"))
    lme = to_percentage(terms.get("price_basis"))
    return contracted_rate, lme


def _rate_outcome(context: RuleContext) -> RuleOutcome:
    """Price is a negotiated term, so it is compared exactly.

    The tolerance is still read from configuration rather than assumed to be zero - it is seeded
    at zero, which is the business rule, but it stays a row somebody can see and reason about.
    """
    tolerance, _ = context.threshold(RuleId.BR_06, CheckKey.RATE_TOLERANCE)
    if tolerance is None:
        return _unconfigured(RuleId.BR_06, CheckKey.RATE_TOLERANCE, "rate")

    leg_rate = context.leg_value("rate")
    contracted_rate, contracted_lme = _contracted_price(context)
    invoice_rate = to_decimal(context.fields_of(context.latest_value_document()).get("rate"))

    # Both LME-linked bases, not only the plain percentage. A "3-month LME less 6%" deal carries
    # a percentage exactly as a cash-settlement one does, and re-classifying it must not quietly
    # drop it out of the comparison it was already subject to.
    if context.transaction.price_basis in LME_LINKED_PRICE_BASES and contracted_lme is not None:
        expected: Decimal | None = contracted_lme
        actual: Decimal | None = context.transaction.lme_percentage
        field_name = "lme_percentage"
        unit = "%"
        source = "the linked purchase contract's price basis"
    else:
        expected = contracted_rate if contracted_rate is not None else leg_rate
        actual = invoice_rate if invoice_rate is not None else leg_rate
        field_name = "rate"
        unit = f" {context.transaction.currency}"
        source = (
            "the linked contract"
            if contracted_rate is not None
            else "the rate recorded on this transaction's leg"
        )

    if expected is None or actual is None:
        return RuleOutcome(
            rule_id=RuleId.BR_06,
            check_key=CheckKey.RATE_TOLERANCE,
            passed=False,
            severity=RuleSeverity.HARD.value,
            field_name=field_name,
            expected_value=format_decimal(expected, suffix=unit),
            actual_value=format_decimal(actual, suffix=unit),
            message=(
                "The price cannot be checked: there is no agreed figure to compare the invoiced "
                "one against."
            ),
        )

    difference = abs(actual - expected)
    passed = difference <= tolerance

    return RuleOutcome(
        rule_id=RuleId.BR_06,
        check_key=CheckKey.RATE_TOLERANCE,
        passed=passed,
        # Never acknowledgeable, at any size. A price difference is a different deal, not a
        # rounding artefact, so the tiered treatment the amount gets does not apply here.
        severity=RuleSeverity.HARD.value,
        field_name=field_name,
        expected_value=format_decimal(expected, suffix=unit),
        actual_value=format_decimal(actual, suffix=unit),
        message=(
            f"The price matches {source} exactly at {format_decimal(expected, suffix=unit)}."
            if passed
            else f"The price is {format_decimal(actual, suffix=unit)} against "
            f"{format_decimal(expected, suffix=unit)} on {source}. Price is a negotiated term and "
            "must match exactly; correct the figures rather than acknowledging the difference."
        ),
    )


@register(RuleId.BR_06, requires_legs=COMMERCIAL)
async def evaluate_invoice_agreement(context: RuleContext) -> list[RuleOutcome]:
    """Three checks that share a rule number and share nothing else."""
    return [
        _amount_outcome(context),
        _quantity_outcome(context, RuleId.BR_06),
        _rate_outcome(context),
    ]


# --- BR-13  a repeated document links, never duplicates -------------------------------------


@register(RuleId.BR_13)
async def evaluate_duplicate_handling(context: RuleContext) -> list[RuleOutcome]:
    """Confirm that nothing byte-identical to this pack sits on a competing transaction."""
    threshold, _ = context.threshold(RuleId.BR_13, CheckKey.DUPLICATE_CONTENT)
    if threshold is None:
        return [_unconfigured(RuleId.BR_13, CheckKey.DUPLICATE_CONTENT, "content_hash")]

    hashes = {document.content_hash for document in context.documents}
    if not hashes:
        return [
            RuleOutcome(
                rule_id=RuleId.BR_13,
                check_key=CheckKey.DUPLICATE_CONTENT,
                passed=True,
                severity=RuleSeverity.HARD.value,
                field_name="content_hash",
                expected_value="no competing copy",
                actual_value="no documents attached",
                message="No document is attached yet, so nothing can have been duplicated.",
            )
        ]

    elsewhere = (
        await context.session.scalars(
            select(Document).where(
                Document.content_hash.in_(hashes),
                Document.transaction_id.is_not(None),
                Document.transaction_id != context.transaction.id,
            )
        )
    ).all()

    passed = not elsewhere
    return [
        RuleOutcome(
            rule_id=RuleId.BR_13,
            check_key=CheckKey.DUPLICATE_CONTENT,
            passed=passed,
            severity=RuleSeverity.HARD.value,
            field_name="content_hash",
            expected_value="no competing copy",
            actual_value=(
                "none" if passed else ", ".join(sorted({row.filename for row in elsewhere}))
            ),
            message=(
                f"All {len(hashes)} attached document(s) belong to this transaction alone."
                if passed
                else "A byte-identical copy of an attached document is linked to a different "
                "transaction. One of the two links is wrong and must be resolved before this "
                "transaction goes forward."
            ),
        )
    ]


# --- registered, not yet evaluable ----------------------------------------------------------
#
# Each of these is a real entry in the registry with a real evaluator signature. None of them
# writes a row or shows a user a check, because none of them can be judged with the data that
# exists yet. The step that brings that data replaces the body and touches nothing else.


@register(RuleId.BR_01, implemented=False)
async def evaluate_request_traceability(context: RuleContext) -> list[RuleOutcome]:
    # Structurally guaranteed rather than checked: `trade_transactions.request_id` is a
    # non-nullable foreign key, so a transaction that traces to no request cannot be stored.
    return not_applicable(
        RuleId.BR_01,
        "Guaranteed by the schema: every transaction carries a mandatory request reference.",
    )


@register(RuleId.BR_08, implemented=False)
async def evaluate_failure_routing(context: RuleContext) -> list[RuleOutcome]:
    # Satisfied generically rather than evaluated, and by real code: every hard-severity failure
    # any rule above produces is routed to the exception queue by `governance.hooks`, which reads
    # the outcomes and opens a case against the configured owner. A rule of its own here would be
    # a second, narrower implementation of routing that already happens for all of them.
    return not_applicable(
        RuleId.BR_08,
        "Enforced generically: every hard failure is routed to the exception queue by the "
        "governance hook, whichever rule produced it.",
    )


@register(RuleId.BR_09, implemented=False)
async def evaluate_portal_primacy(context: RuleContext) -> list[RuleOutcome]:
    return not_applicable(
        RuleId.BR_09,
        "An architectural principle, enforced structurally rather than evaluated: the tracker is "
        "written only from an approved transaction, by the integration hub, and nothing reads a "
        "tracker back into this platform.",
    )


@register(RuleId.BR_10, implemented=False)
async def evaluate_commit_gate(context: RuleContext) -> list[RuleOutcome]:
    # Still enforced structurally rather than evaluated, and now by a real gate: integration
    # jobs are created only where a recorded approval put the transaction into `Approved`, and a
    # transaction reaches `Committed` only once all three of them are genuinely resolved. There
    # is no code path from an undecided transaction to a posting for a rule to guard.
    return not_applicable(
        RuleId.BR_10,
        "An architectural principle: a posting can only be raised by a recorded approval "
        "decision, so there is no unapproved commit path to gate.",
    )


@register(RuleId.BR_11, implemented=False)
async def evaluate_ai_provenance(context: RuleContext) -> list[RuleOutcome]:
    # Satisfied by construction: `extracted_fields` keeps the original AI value and confidence on
    # every override, and `trade_transactions.field_overrides` does the same for this layer.
    return not_applicable(
        RuleId.BR_11, "Guaranteed by the storage design of every correctable value."
    )


@register(RuleId.BR_12, implemented=False)
async def evaluate_audit_coverage(context: RuleContext) -> list[RuleOutcome]:
    return not_applicable(
        RuleId.BR_12, "Guaranteed by construction: every governance action writes an audit event."
    )


def similarity(left: str, right: str) -> float:
    """Deterministic text similarity. Not an AI call, and deliberately nowhere near one."""
    return float(fuzz.token_set_ratio(left, right))


# Registering the sales, shipment and invoice-dating modules' evaluators. The import is the
# entire integration: BR-07's real body, SL-01, BR-03 and IV-01 land in the same registry, keyed
# the same way, and the orchestrator walks them without knowing any of them exists.
from app.services.rules import (  # noqa: E402,F401
    invoice_evaluators,
    logistics_evaluators,
    sales_evaluators,
)
