"""The rule-evaluator registry and the context every evaluator is handed.

This is the piece  5 and 6 build on rather than rebuild. An evaluator is a plain function
keyed by rule identifier; the orchestrator looks each one up, decides from the declaration which
legs it needs, and persists whatever it returns. Bringing a rule to life later means registering
a function - never touching the dispatch, the context, or the persistence around it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.configuration import RuleConfiguration
from app.models.enums import DocumentType, RuleSeverity
from app.models.intake import Document
from app.models.transactions import TradeTransaction

# The leg attribute each stream hangs off `TradeTransaction`.  added "sales": "sales_leg"
# and  added "fa": "fa_leg"; the orchestrator reads this map rather than naming a leg
# itself, so no leg-type-specific branch is ever written into the dispatch. Bringing each new leg
# into view for every registered rule was this one line, twice.
LEG_ATTRIBUTES: dict[str, str] = {
    "purchase": "purchase_leg",
    "sales": "sales_leg",
    "fa": "fa_leg",
}

# The legs that carry "our side of a deal with a counterparty", in the order the shared
# evaluators should consult them. BR-02, BR-05 and BR-06 were written about a purchase leg and
# are reused verbatim by the FA stream; what made that possible is asking the context for a
# *concept* rather than for a named column.
COMMERCIAL_LEGS: tuple[str, ...] = ("purchase", "fa")

# The column each leg spells a shared concept with. This is the whole of what a second stream had
# to add to be judged by the existing evaluators: three lines of data, no branch anywhere.
LEG_FIELD_ALIASES: dict[str, dict[str, str]] = {
    "purchase": {
        "counterparty": "supplier_name",
        "contract_reference": "contract_number",
        "invoice_reference": "supplier_invoice_number",
        "amount": "amount",
        "rate": "rate",
    },
    "sales": {
        "counterparty": "customer_name",
        "contract_reference": "sales_contract_no",
        "invoice_reference": "sales_invoice_number",
    },
    "fa": {
        "counterparty": "counterparty_name",
        "contract_reference": "fa_contract_reference",
        # FA has no invoice-number column and no amount or rate column, because AGFZE has not
        # said it needs one. `amount` and `rate` resolve through `FaLeg`'s read-only view over
        # its configured extra fields, so BR-06 can still read them when they are configured and
        # correctly finds nothing when they are not.
        "amount": "amount",
        "rate": "rate",
    },
}

# Which document type carries a transaction's own commercial figures, per stream. Scrap's is the
# supplier invoice; FA's is the single `fa_document` type  anticipated and  gave a
# schema. Structural, not a business rule: it says where to read a number, never what the number
# must be.
VALUE_DOCUMENT_TYPES: dict[str, tuple[str, ...]] = {
    "scrap": (DocumentType.INVOICE.value,),
    "fa": (DocumentType.FA_DOCUMENT.value,),
}


def value_document_types(stream: str | None) -> tuple[str, ...]:
    return VALUE_DOCUMENT_TYPES.get(stream or "", (DocumentType.INVOICE.value,))


class RuleConfigurationResolver:
    """Resolves a threshold for the transaction in front of it.

    The narrowest scope wins: a row scoped to the transaction's commodity beats one scoped only
    to its type, which beats the unscoped default. Nothing falls back to a literal in code - a
    rule with no active configuration reports itself unconfigured and blocks, because silently
    passing a rule nobody configured is worse than failing loudly.
    """

    def __init__(self, rows: list[RuleConfiguration]) -> None:
        self._rows = [row for row in rows if row.is_active]

    def resolve(
        self,
        rule_id: str,
        check_key: str,
        *,
        commodity_code: str | None,
        transaction_type: str | None,
        stream: str | None,
    ) -> RuleConfiguration | None:
        candidates = [
            row
            for row in self._rows
            if row.rule_id == rule_id
            and row.check_key == check_key
            and row.scope_commodity_code in (None, commodity_code)
            and row.scope_transaction_type in (None, transaction_type)
            and row.scope_stream in (None, stream)
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda row: row.specificity)


@dataclass
class RuleContext:
    """Everything an evaluator is allowed to read, assembled once per validation run."""

    session: AsyncSession
    transaction: TradeTransaction
    legs: dict[str, object]
    documents: list[Document]
    # document id -> {field name: value}, for every field the extraction produced.
    document_fields: dict[UUID, dict[str, str]]
    # The contract's own terms, consolidated from the linked contract document.
    contract_terms: dict[str, str]
    # The territory checklist that applies to this transaction's pack, from `DocumentTypeSchema`.
    mandatory_documents: tuple[str, ...]
    territory: str | None
    config: RuleConfigurationResolver
    # The most recent evaluation per (rule, check) before this run, so an acknowledgement made on
    # unchanged data survives a re-validation instead of being silently dropped.
    previous: dict[tuple[str, str | None], object] = field(default_factory=dict)

    def leg(self, name: str) -> object | None:
        return self.legs.get(name)

    def commercial_leg(self) -> object | None:
        """The leg whose own terms the shared evaluators read, whichever stream this is."""
        for name in COMMERCIAL_LEGS:
            leg = self.legs.get(name)
            if leg is not None:
                return leg
        return None

    def leg_value(self, concept: str) -> object | None:
        """One shared concept, read off whichever leg the transaction actually carries.

        Returns None where the present leg has no column for the concept, which is a real answer
        rather than a gap: an FA leg genuinely records no invoice number, and the evaluator that
        asked falls back to what the document said, exactly as it would for a purchase leg that
        had not been filled in yet.
        """
        for name in COMMERCIAL_LEGS:
            leg = self.legs.get(name)
            if leg is None:
                continue
            attribute = LEG_FIELD_ALIASES.get(name, {}).get(concept)
            if attribute is None:
                return None
            return getattr(leg, attribute, None)
        return None

    def latest_value_document(self) -> Document | None:
        """The newest document of whichever type carries this stream's commercial figures."""
        candidates = [
            row
            for document_type in value_document_types(self.transaction.stream)
            for row in self.documents_of_type(document_type)
        ]
        if not candidates:
            return None
        return sorted(candidates, key=lambda row: row.created_at)[-1]

    def documents_of_type(self, document_type: str) -> list[Document]:
        return [row for row in self.documents if row.document_type == document_type]

    def latest_of_type(self, document_type: str) -> Document | None:
        rows = sorted(self.documents_of_type(document_type), key=lambda row: row.created_at)
        return rows[-1] if rows else None

    def fields_of(self, document: Document | None) -> dict[str, str]:
        if document is None:
            return {}
        return self.document_fields.get(document.id, {})

    def threshold(
        self, rule_id: str, check_key: str
    ) -> tuple[Decimal | None, RuleConfiguration | None]:
        row = self.config.resolve(
            rule_id,
            check_key,
            commodity_code=self.transaction.commodity_code,
            transaction_type=self._transaction_type(),
            stream=self.transaction.stream,
        )
        return (row.threshold_value if row else None), row

    def _transaction_type(self) -> str | None:
        """Which desk's leg this transaction actually carries, read generically."""
        present = [name for name, value in self.legs.items() if value is not None]
        return present[0] if len(present) == 1 else None


@dataclass(frozen=True)
class RuleOutcome:
    """One persistable line of the validation result."""

    rule_id: str
    passed: bool
    message: str
    severity: str = RuleSeverity.HARD.value
    check_key: str | None = None
    field_name: str | None = None
    expected_value: str | None = None
    actual_value: str | None = None
    # A registered rule that cannot yet be judged reports itself unevaluated. Nothing unevaluated
    # is written to `rule_evaluations` or shown to a user as a check, because a row reading
    # "not yet applicable" is noise rather than information.
    applicable: bool = True


def not_applicable(rule_id: str, reason: str) -> list[RuleOutcome]:
    return [
        RuleOutcome(
            rule_id=rule_id,
            passed=True,
            message=reason,
            severity=RuleSeverity.INFORMATIONAL.value,
            applicable=False,
        )
    ]


Evaluator = Callable[[RuleContext], Awaitable[list[RuleOutcome]]]


@dataclass(frozen=True)
class RegisteredRule:
    rule_id: str
    evaluator: Evaluator
    # Legs the rule needs to mean anything. An empty set means it applies to any transaction.
    requires_legs: frozenset[str]
    # False while the rule is registered but the data it needs does not exist yet.
    implemented: bool


_REGISTRY: dict[str, RegisteredRule] = {}


def register(
    rule_id: str,
    *,
    requires_legs: frozenset[str] = frozenset(),
    implemented: bool = True,
) -> Callable[[Evaluator], Evaluator]:
    def decorate(evaluator: Evaluator) -> Evaluator:
        _REGISTRY[rule_id] = RegisteredRule(
            rule_id=rule_id,
            evaluator=evaluator,
            requires_legs=requires_legs,
            implemented=implemented,
        )
        return evaluator

    return decorate


def registered_rules() -> dict[str, RegisteredRule]:
    return dict(_REGISTRY)


def get_rule(rule_id: str) -> RegisteredRule | None:
    return _REGISTRY.get(rule_id)
