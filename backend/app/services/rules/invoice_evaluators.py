"""IV-01: how an invoice is dated, judged against the day it is being looked at.

The requirement is one of the oldest in this platform's material and belonged to none of the ten
feature steps, so it lands here. It is registered the way every rule since Step 3 has been - a
function under `@register`, keyed by its own identifier, with its threshold read out of
`rule_configurations` rather than written into this file. The orchestrator, the context and the
persistence are untouched by it, which is the fourth time that claim has been made and the fourth
time it has cost a single import to keep.

What it deliberately does **not** do is block anything. The discovery material proposes rejecting
a future-dated invoice outright and flagging one dated more than three months ago, and says in the
same breath that AGFZE has not confirmed either the tolerance or the approval matrix behind them.
A hard failure on an unconfirmed policy would stop real deals on a rule nobody has agreed, so both
outcomes are `acknowledgeable`: the preparing desk sees the flag, and clears it on its own record
with a stated reason exactly as it clears the invoice amount's middle tier. The day the business
confirms the policy, the threshold is a row somebody edits and the severity is one word here.

The India note is an advisory and nothing more. The local rule it refers to - interest becoming
payable on an overdue payment to a registered small supplier - turns on the counterparty's
registration status and on a payment date this platform does not hold, so no liability figure is
computed and none is implied. The note tells the desk to look; it does not pretend to have looked.
"""

from __future__ import annotations

from datetime import date, datetime

from app.db.base import utcnow
from app.models.enums import RuleSeverity, Territory
from app.services.rules.catalog import CheckKey, RuleId
from app.services.rules.registry import RuleContext, RuleOutcome, not_applicable, register

# The extracted field the date is read from, per document schema. The invoice schema names it
# directly; a stream whose value document carries no date simply has nothing for this rule to
# judge, which the evaluator reports as not applicable rather than as a failure.
INVOICE_DATE_FIELDS: tuple[str, ...] = ("invoice_date", "document_date", "issue_date")

# Formats a date can arrive in. Extraction normalises to YYYY-MM-DD, and these are the shapes a
# corrected value or an older document has actually been seen in. Nothing here guesses between an
# ambiguous day and month: a value that matches none of them is reported as unreadable.
DATE_FORMATS: tuple[str, ...] = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d %b %Y", "%d %B %Y")

INDIA_ADVISORY = (
    "This is an India-territory transaction. Indian payment-term rules can make interest payable "
    "on a late settlement to a registered small or micro supplier, counted from the invoice date. "
    "Check the counterparty's registration and the agreed payment terms before this invoice is "
    "scheduled - this platform states the rule, it does not calculate any liability."
)


def parse_document_date(raw: str | None) -> date | None:
    """Read a date out of an extracted value, or return None because it is not one."""
    text = (raw or "").strip()
    if not text:
        return None
    for pattern in DATE_FORMATS:
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


def months_before(today: date, months: int) -> date:
    """The same day-of-month `months` months earlier, clamped to a month that is short of it."""
    total = today.year * 12 + (today.month - 1) - months
    year, month = divmod(total, 12)
    month += 1
    day = today.day
    while day > 1:
        try:
            return date(year, month, day)
        except ValueError:
            day -= 1
    return date(year, month, 1)


def invoice_date_of(context: RuleContext) -> tuple[date | None, str | None]:
    """The date this transaction's own value document states, and the raw value it stated it as."""
    fields = context.fields_of(context.latest_value_document())
    for name in INVOICE_DATE_FIELDS:
        raw = fields.get(name)
        if raw is not None and str(raw).strip():
            return parse_document_date(str(raw)), str(raw).strip()
    return None, None


def _window_outcome(invoice_date: date, *, today: date, months: int, raw: str) -> RuleOutcome:
    earliest = months_before(today, months)
    window = f"between {earliest.isoformat()} and {today.isoformat()}"

    if invoice_date > today:
        return RuleOutcome(
            rule_id=RuleId.IV_01,
            check_key=CheckKey.INVOICE_DATE_WINDOW,
            passed=False,
            # Flagged, never blocked. AGFZE has not confirmed what a future-dated invoice should
            # cost a transaction, and stopping a live deal on an unconfirmed policy is worse than
            # putting the fact in front of the person preparing it.
            severity=RuleSeverity.ACKNOWLEDGEABLE.value,
            field_name="invoice_date",
            expected_value=window,
            actual_value=raw,
            message=(
                f"IV-01: the invoice is dated {invoice_date.isoformat()}, which is in the future. "
                "Check the date against the document before this transaction goes forward, or "
                "accept it with a reason. AGFZE has not confirmed a policy for a future-dated "
                "invoice, so this is a flag rather than a block."
            ),
        )

    if invoice_date < earliest:
        age_days = (today - invoice_date).days
        return RuleOutcome(
            rule_id=RuleId.IV_01,
            check_key=CheckKey.INVOICE_DATE_WINDOW,
            passed=False,
            severity=RuleSeverity.ACKNOWLEDGEABLE.value,
            field_name="invoice_date",
            expected_value=window,
            actual_value=f"{raw} ({age_days} days old)",
            message=(
                f"IV-01: the invoice is dated {invoice_date.isoformat()}, {age_days} days ago, "
                f"which is further back than the configured {months}-month window. Confirm the "
                "date is right and accept it with a reason, or correct it. The exact tolerance "
                "and the approval matrix for a backdated invoice are not yet confirmed by the "
                "business, so this is a flag rather than a block."
            ),
        )

    return RuleOutcome(
        rule_id=RuleId.IV_01,
        check_key=CheckKey.INVOICE_DATE_WINDOW,
        passed=True,
        severity=RuleSeverity.ACKNOWLEDGEABLE.value,
        field_name="invoice_date",
        expected_value=window,
        actual_value=raw,
        message=(
            f"The invoice is dated {invoice_date.isoformat()}, inside the configured "
            f"{months}-month window."
        ),
    )


def _india_advisory(invoice_date: date) -> RuleOutcome:
    return RuleOutcome(
        rule_id=RuleId.IV_01,
        check_key=CheckKey.INDIA_PAYMENT_TERMS_ADVISORY,
        # Never a failure and never a gate. An advisory that could block something would stop
        # being an advisory.
        passed=True,
        severity=RuleSeverity.INFORMATIONAL.value,
        field_name="invoice_date",
        expected_value="advisory only - no calculation is performed",
        actual_value=invoice_date.isoformat(),
        message=INDIA_ADVISORY,
    )


@register(RuleId.IV_01)
async def evaluate_invoice_dating(context: RuleContext) -> list[RuleOutcome]:
    """Flag an invoice dated too far back or in the future, and note India's payment-term rule."""
    months_value, _ = context.threshold(RuleId.IV_01, CheckKey.INVOICE_DATE_WINDOW)
    if months_value is None:
        return [
            RuleOutcome(
                rule_id=RuleId.IV_01,
                check_key=CheckKey.INVOICE_DATE_WINDOW,
                passed=False,
                # Unconfigured is still only a flag for this rule. Every other evaluator hard-
                # fails on a missing threshold because the check it guards is a confirmed business
                # rule; this one is not, so an administrator having deactivated its row must not
                # be able to stop a desk from working.
                severity=RuleSeverity.ACKNOWLEDGEABLE.value,
                field_name="invoice_date",
                message=(
                    f"IV-01 has no active configuration for '{CheckKey.INVOICE_DATE_WINDOW}', so "
                    "the invoice date cannot be checked against a window. An administrator can "
                    "set one on the rules screen."
                ),
            )
        ]

    invoice_date, raw = invoice_date_of(context)
    if raw is None:
        return not_applicable(
            RuleId.IV_01,
            "No invoice date has been extracted for this transaction yet, so there is nothing to "
            "date-check.",
        )

    if invoice_date is None:
        return [
            RuleOutcome(
                rule_id=RuleId.IV_01,
                check_key=CheckKey.INVOICE_DATE_WINDOW,
                passed=False,
                severity=RuleSeverity.ACKNOWLEDGEABLE.value,
                field_name="invoice_date",
                expected_value="a readable calendar date",
                actual_value=raw,
                message=(
                    f"IV-01: '{raw}' could not be read as a date, so the invoice's age cannot be "
                    "checked. Correct it on the document, or accept the check with a reason."
                ),
            )
        ]

    today = utcnow().date()
    # Whole months. A fractional row is truncated rather than refused: half a month is not a
    # window anybody means, and refusing the transaction over it would be the block this rule
    # exists not to be.
    months = max(0, int(months_value))
    outcomes = [_window_outcome(invoice_date, today=today, months=months, raw=raw)]
    if (context.territory or "").strip().lower() == Territory.INDIA.value:
        outcomes.append(_india_advisory(invoice_date))
    return outcomes
