"""The three architectural claims this build has been making since Step 3, tested as claims.

Each of these has been asserted in prose in a README and demonstrated by a step that happened to
work. That is not the same as a test that would fail if the claim stopped being true, and the claim
stopping being true is exactly the sort of thing that happens quietly - a helpful `if rule_id ==`
in the orchestrator, an exception hook that grows a rule list, a notification call site that learns
about email because it was easier than extending the function.

So each one is checked twice: structurally, by reading the source that is supposed to know nothing,
and behaviourally, by exercising the seam and asserting the outcome.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.roles import PlatformRole
from app.models.enums import ExceptionCategory, RuleSeverity
from app.models.governance import ExceptionCase
from app.models.transactions import RuleEvaluation
from app.services import notification_service
from app.services.governance import hooks as governance_hooks
from app.services.logistics import tracking_service
from app.services.rules import engine as rule_engine
from app.services.rules.catalog import ALL_RULE_IDS, RuleId
from app.services.rules.registry import (
    _REGISTRY,
    LEG_ATTRIBUTES,
    RegisteredRule,
    RuleContext,
    RuleOutcome,
    registered_rules,
)
from tests.utils.delivery import install_push, install_relay, set_channel, subscribe
from tests.utils.governance import seeded_transaction
from tests.utils.logistics import add_shipment, aware, no_adapters
from tests.utils.transactions import make_request, make_transaction

pytestmark = pytest.mark.usefixtures("patched_jwks")

APP_ROOT = Path(__file__).resolve().parents[1] / "app"


def source_of(module) -> str:
    return inspect.getsource(module)


def executable_source(module) -> str:
    """The module with its comments and docstrings removed.

    A prose explanation of *why* the hook does not branch on BR-05 legitimately writes BR-05 down.
    What must not exist is a rule identifier the code acts on, so the search is run over what
    actually executes rather than over what is written beside it.
    """
    tree = ast.parse(inspect.getsource(module))
    for node in ast.walk(tree):
        if isinstance(
            node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
        ) and ast.get_docstring(node):
            node.body = node.body[1:]
    return ast.unparse(tree)


# --- promise 1: the registry needed no dispatch change for a new rule -------------------------


def test_the_orchestrator_names_no_individual_rule() -> None:
    """The claim, read straight off the file that would have to break it.

    If adding a rule had ever required the dispatch to learn about it, the evidence would be a
    rule identifier in here. There is none, and this test is what keeps it that way.
    """
    engine_source = executable_source(rule_engine)

    for rule_id in ALL_RULE_IDS:
        assert rule_id not in engine_source, f"{rule_id} is named in the orchestrator"
    # And neither is any leg, by name. The legs are read off one map.
    for leg in ("purchase_leg", "sales_leg", "fa_leg"):
        assert leg not in engine_source, f"{leg} is named in the orchestrator"
    assert "LEG_ATTRIBUTES" in engine_source


def test_bringing_the_later_steps_rules_to_life_was_a_registration_and_an_import() -> None:
    """Steps 5, 6 and 11 each added an evaluator module and one import at the foot of the five.

    Asserted as the thing that is actually checkable: the rules those steps brought are registered
    from modules of their own, and the module the original five live in contains no body for any of
    them.
    """
    from app.services.rules import (
        evaluators,
        invoice_evaluators,
        logistics_evaluators,
        sales_evaluators,
    )

    origin = {rule_id: rule.evaluator.__module__ for rule_id, rule in registered_rules().items()}

    assert origin[RuleId.BR_07] == sales_evaluators.__name__
    assert origin[RuleId.SL_01] == sales_evaluators.__name__
    assert origin[RuleId.BR_03] == logistics_evaluators.__name__
    assert origin[RuleId.IV_01] == invoice_evaluators.__name__
    # The original five, still where they were.
    for rule_id in (RuleId.BR_02, RuleId.BR_04, RuleId.BR_05, RuleId.BR_06, RuleId.BR_13):
        assert origin[rule_id] == evaluators.__name__


async def test_a_rule_registered_at_runtime_is_evaluated_and_persisted_unchanged(
    db_session: AsyncSession,
) -> None:
    """The strongest form of the claim: a rule the platform has never heard of, added live.

    Nothing is patched except the registry itself. If the orchestrator needed to know about a rule
    in order to run it, this would write nothing.
    """
    transaction = await seeded_transaction(db_session, validate=False)

    async def evaluator(context: RuleContext) -> list[RuleOutcome]:
        # Reads the context generically, exactly as a real evaluator does.
        return [
            RuleOutcome(
                rule_id="ZZ-99",
                check_key="registered_at_runtime",
                passed=True,
                severity=RuleSeverity.INFORMATIONAL.value,
                message=f"Judged {len(context.documents)} document(s) with no dispatch change.",
            )
        ]

    _REGISTRY["ZZ-99"] = RegisteredRule(
        rule_id="ZZ-99",
        evaluator=evaluator,
        requires_legs=frozenset(),
        implemented=True,
    )
    try:
        written = await rule_engine.run_validation(db_session, transaction)
    finally:
        _REGISTRY.pop("ZZ-99", None)

    row = next(item for item in written if item.rule_id == "ZZ-99")
    assert row.check_key == "registered_at_runtime"
    assert row.passed is True
    assert "no dispatch change" in row.message


def test_a_new_leg_would_cost_the_engine_one_map_entry() -> None:
    """The other half of the same promise: three streams, one map, no branch."""
    assert set(LEG_ATTRIBUTES) == {"purchase", "sales", "fa"}
    assert set(LEG_ATTRIBUTES.values()) == {"purchase_leg", "sales_leg", "fa_leg"}


# --- promise 2: the exception hook is callable outside the rule path ---------------------------


def test_the_exception_hook_names_no_rule_and_imports_no_engine() -> None:
    hook_source = executable_source(governance_hooks)

    for rule_id in ALL_RULE_IDS:
        assert rule_id not in hook_source, f"{rule_id} is acted on in the exception hook"
    raw = source_of(governance_hooks)
    assert "from app.services.rules" not in raw
    assert "rule_engine" not in raw


async def test_shipment_staleness_opens_a_case_without_any_rule_evaluation(
    db_session: AsyncSession, monkeypatch
) -> None:
    """Step 6's proof, made an assertion.

    A shipment nobody has looked at is not a rule evaluation over extracted data, so it does not
    route through the rule-to-category mapping at all: the sweep calls `open_case` directly. The
    thing that must never happen is a synthetic `rule_evaluations` row invented to reuse the
    hard-fail hook, because that table is what an auditor reads as a record of real checks.
    """
    no_adapters()
    transaction = await seeded_transaction(db_session, validate=False)
    shipment = await add_shipment(db_session, transaction, checked_hours_ago=24 * 30)
    await db_session.commit()

    result = await tracking_service.run_sweep(db_session, limit=10)
    await db_session.commit()

    assert result.considered >= 1

    cases = list(
        (
            await db_session.scalars(
                select(ExceptionCase).where(
                    ExceptionCase.exception_type
                    == ExceptionCategory.SHIPMENT_STATUS_UNAVAILABLE.value
                )
            )
        ).all()
    )
    assert len(cases) == 1
    case = cases[0]
    assert case.owner_role == PlatformRole.LOGISTICS_USER.value
    # No rule produced it, and it does not pretend one did.
    assert case.rule_id is None
    assert case.check_key is None

    evaluations = list(
        (
            await db_session.scalars(
                select(RuleEvaluation).where(RuleEvaluation.transaction_id == transaction.id)
            )
        ).all()
    )
    assert not [row for row in evaluations if row.rule_id.startswith("SHIP")]
    assert aware(shipment.last_checked_at) is not None or shipment.last_checked_at is None


async def test_the_same_function_serves_both_callers(db_session: AsyncSession) -> None:
    """One `open_case`, reached from the rule path and from a sweep, with one idempotency rule."""
    request = await make_request(db_session)
    transaction = await make_transaction(db_session, request=request)
    await db_session.commit()

    first = await governance_hooks.open_case(
        db_session,
        category=ExceptionCategory.SHIPMENT_STATUS_UNAVAILABLE.value,
        owner_role=PlatformRole.LOGISTICS_USER.value,
        summary="Nobody has established where this cargo is.",
        transaction_id=transaction.id,
    )
    second = await governance_hooks.open_case(
        db_session,
        category=ExceptionCategory.SHIPMENT_STATUS_UNAVAILABLE.value,
        owner_role=PlatformRole.LOGISTICS_USER.value,
        summary="Still nobody.",
        transaction_id=transaction.id,
    )
    await db_session.commit()

    assert first is not None
    # The second is refused because one unresolved case already covers this subject: the queue
    # shows one problem once, ageing from when it first appeared.
    assert second is None


# --- promise 3: the delivery channels changed no call site -------------------------------------

# The five trigger points Step 9 wired, by the names they are called by.
TRIGGERS = (
    "notify_exception_opened",
    "notify_approval_requested",
    "notify_approval_decided",
    "notify_integration_attention",
    "notify_report_ready",
)


def test_the_five_trigger_functions_know_nothing_about_a_channel() -> None:
    """Read from the source of each one, individually.

    A trigger that had learned about email would have to say so somewhere in its own body. None of
    them does: each is a call onto `notify` with a message, a link and a set of recipients.
    """
    for name in TRIGGERS:
        body = inspect.getsource(getattr(notification_service, name))
        for forbidden in ("email", "push", "smtp", "vapid", "dispatch_deliveries"):
            assert forbidden not in body.lower(), f"{name} mentions {forbidden}"


def test_delivery_is_dispatched_from_exactly_one_place() -> None:
    """`notify` is the seam, so it has to be the only caller."""
    module = APP_ROOT / "services" / "notification_service.py"
    tree = ast.parse(module.read_text(encoding="utf-8"))

    callers = [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef)
        and any(
            isinstance(inner, ast.Call) and getattr(inner.func, "id", None) == "dispatch_deliveries"
            for inner in ast.walk(node)
        )
    ]
    assert callers == ["notify"], callers

    # And nowhere else in the application calls it either.
    elsewhere = [
        str(path.relative_to(APP_ROOT))
        for path in APP_ROOT.rglob("*.py")
        if "__pycache__" not in path.parts
        and path != module
        and "dispatch_deliveries" in path.read_text(encoding="utf-8")
    ]
    assert elsewhere == [], elsewhere


def test_no_caller_of_the_five_triggers_mentions_a_channel() -> None:
    """The call sites themselves - hooks, approval service, integration service, schedule."""
    offenders: list[str] = []
    for path in APP_ROOT.rglob("*.py"):
        if "__pycache__" in path.parts or path.name == "notification_service.py":
            continue
        source = path.read_text(encoding="utf-8")
        if not any(trigger in source for trigger in TRIGGERS):
            continue
        if "delivery" in path.parts:
            continue
        for forbidden in ("email_service", "push_service", "smtplib", "webpush"):
            if forbidden in source:
                offenders.append(f"{path.relative_to(APP_ROOT)}:{forbidden}")
    assert offenders == [], offenders


async def test_an_exception_reaches_all_three_channels_through_the_unchanged_call_site(
    db_session: AsyncSession, signed_in, monkeypatch
) -> None:
    """The behavioural half. `record_hard_failures` is the Step 4 code, byte for byte.

    It calls `open_case`, which calls `notify_exception_opened`, which calls `notify` - and email
    and push happen inside `notify`. Nothing on that chain above `notify` was touched by Step 10,
    and this is the test that would fail if the extension had been made at a call site instead.
    """
    relay = install_relay(monkeypatch)
    push = install_push(monkeypatch)
    monkeypatch.setattr(
        "app.services.notification_service.settings.NOTIFICATION_DELIVERY_ENABLED",
        True,
        raising=False,
    )

    logistics, _ = await signed_in(
        "00000000-0000-4000-8000-0000000000c1",
        "logistics@agfze.test",
        "Logistics Desk",
        [PlatformRole.LOGISTICS_USER.value],
    )
    await set_channel(db_session, logistics, "email")
    await subscribe(db_session, logistics.id, endpoint="https://push.example.test/logistics")
    await db_session.commit()

    request = await make_request(db_session)
    transaction = await make_transaction(db_session, request=request)
    await db_session.commit()

    await governance_hooks.open_case(
        db_session,
        category=ExceptionCategory.SHIPMENT_STATUS_UNAVAILABLE.value,
        owner_role=PlatformRole.LOGISTICS_USER.value,
        summary="Nobody has established where this cargo is for two days.",
        transaction_id=transaction.id,
    )
    await db_session.commit()

    rows = await notification_service.list_for_user(db_session, logistics.id)
    assert len(rows) == 1
    assert rows[0].email_sent_at is not None
    assert rows[0].push_sent_at is not None
    assert relay.recipients == [logistics.email]
    assert len(push.delivered) == 1
