"""AGFZE's second business line, and the claim it exists to test.

The claim is that the engine built in  3 and 4 absorbs a whole second business stream through
configuration. These tests are what makes that claim falsifiable: if `FaLeg` needed a column on the
parent table, if a single evaluator had to be copied, if the exception hook had to learn what an FA
transaction is, or if the workspace had to be taught an FA field name, one of the tests below would
fail.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.configuration import DocumentTypeSchema
from app.models.enums import (
    BusinessStream,
    DocumentType,
    ExceptionCategory,
    RuleSeverity,
)
from app.models.governance import ExceptionCase
from app.models.transactions import FaLeg, TradeTransaction
from app.services import transaction_fields, transaction_service
from app.services.governance import hooks as governance_hooks
from app.services.rules import engine as rule_engine
from app.services.rules.catalog import CheckKey, RuleId
from app.services.rules.registry import RuleConfigurationResolver, registered_rules
from app.services.schema_defaults import FA_DOCUMENT_FIELDS
from tests.utils.logistics import fa_values, make_fa_transaction, make_user
from tests.utils.transactions import make_document, make_request, make_transaction

pytestmark = pytest.mark.usefixtures("patched_jwks")

BASE = "/api/v1/transactions"


async def fa_user(signed_in):
    return await signed_in("fa-1", "fa@agfze.test", "FA User", ["fa_user"])


async def purchase_user(signed_in):
    return await signed_in("buy-1", "buy@agfze.test", "Buyer", ["purchase_user"])


# --- the leg attaches, for the third time, with no change to the parent ------------------------


async def test_the_fa_leg_attaches_with_no_change_to_the_parent_table(
    db_session: AsyncSession,
) -> None:
    """'s design, checked for the third time: the attachment is the child's own key.

    `trade_transactions` carries no `fa_leg_id`, no `stream`-specific column and no nullable
    foreign key waiting for FA to exist. The relationship is expressed entirely by
    `fa_legs.transaction_id`, exactly as `sales_legs` and `purchase_legs` express theirs.
    """
    transaction = await make_fa_transaction(db_session)

    assert transaction.fa_leg is not None
    assert transaction.fa_leg.transaction_id == transaction.id

    parent_columns = {column.name for column in inspect(TradeTransaction).columns}
    assert not any(name.startswith("fa_") for name in parent_columns)
    assert "fa_leg_id" not in parent_columns

    # And the one-to-one is enforced by the database, not by hope.
    leg_columns = inspect(FaLeg).columns
    assert leg_columns["transaction_id"].unique is True


async def test_all_three_legs_hang_off_one_parent_without_colliding(
    db_session: AsyncSession,
) -> None:
    fa = await make_fa_transaction(db_session, batch_number="FA2626-9")
    purchase = await make_transaction(db_session, batch_number="I2626-9")
    await db_session.commit()

    assert (fa.fa_leg, fa.purchase_leg, fa.sales_leg) == (fa.fa_leg, None, None)
    assert purchase.purchase_leg is not None
    assert purchase.fa_leg is None


# --- the seeded schema is minimal, and nothing was invented ------------------------------------


async def test_the_seeded_fa_schema_is_exactly_the_minimal_field_set(
    db_session: AsyncSession,
) -> None:
    """Seven fields, drawn from AGFZE's own material, and not an eighth.

    This test is a guard against the most tempting mistake in the whole : filling in what
    looks like a gap. If somebody adds an FA document type, a mandatory-document list or a
    tolerance the business has not agreed, this fails.
    """
    row = await db_session.scalar(
        select(DocumentTypeSchema).where(
            DocumentTypeSchema.document_type == DocumentType.FA_DOCUMENT.value
        )
    )
    assert row is not None

    names = [field["name"] for field in row.field_schema["fields"]]
    assert names == [
        "counterparty",
        "transaction_reference",
        "quantity",
        "rate",
        "amount",
        "currency",
        "document_type",
    ]
    # No mandatory-document checklist, because no FA document pack has been agreed.
    assert row.mandatory_documents == []
    # And no field asserts that an FA document must contain it.
    assert all(field["required"] is False for field in FA_DOCUMENT_FIELDS)


# --- the extra-fields commit mechanism ----------------------------------------------------------


async def test_commit_fa_values_separates_named_columns_from_schema_driven_extras(
    db_session: AsyncSession,
) -> None:
    """The mechanism that makes "flexible extra fields" real rather than decorative.

    A value with a named column goes to that column. Everything else - including `rate` and
    `amount`, which are in the base set but have no column AGFZE has agreed to - is copied into
    `extra_fields` under its own field name.
    """
    transaction = await make_fa_transaction(
        db_session,
        counterparty_name=None,
        fa_contract_reference=None,
        document_type=None,
        quantity=None,
        extra_fields={},
    )

    written = transaction_service.commit_fa_values(
        transaction,
        transaction.fa_leg,
        fa_values(**{"a_field_configured_later": "some value"}),
    )
    await db_session.commit()

    assert transaction.fa_leg.counterparty_name == "Gulf Financial Advisory Partners"
    assert transaction.fa_leg.fa_contract_reference == "FA-2026-0031"
    assert transaction.fa_leg.document_type == "Advisory fee note"
    # The two base-set fields that belong to the shared parent went there.
    assert transaction.quantity_mt == Decimal("12.000")
    assert transaction.currency == "USD"
    # Everything without a column, base-set or not, is keyed into the structured column.
    assert transaction.fa_leg.extra_fields == {
        "rate": "1500.00",
        "amount": "18000.00",
        "a_field_configured_later": "some value",
    }
    assert "counterparty" not in transaction.fa_leg.extra_fields
    assert set(written) >= {"counterparty", "rate", "a_field_configured_later"}


async def test_a_later_document_adds_detail_and_never_overwrites_it(
    db_session: AsyncSession,
) -> None:
    transaction = await make_fa_transaction(db_session, counterparty_name="Established Name")

    transaction_service.commit_fa_values(
        transaction,
        transaction.fa_leg,
        fa_values(counterparty="A Different Name", rate="9999.00"),
    )
    await db_session.commit()

    assert transaction.fa_leg.counterparty_name == "Established Name"
    # The extra already held a rate, so that is not silently rewritten either.
    assert transaction.fa_leg.extra_fields["rate"] == "1500.00"


async def test_the_extras_the_workspace_offers_come_from_the_configured_schema(
    db_session: AsyncSession,
) -> None:
    """The panel's field list is resolved from configuration, not from a list in the code."""
    transaction = await make_fa_transaction(db_session)

    extras = await transaction_fields.fa_extra_fields(db_session, transaction)
    names = {field.name for field in extras}

    # The base-set fields that have a named column are not offered twice.
    assert names == {"rate", "amount"}
    assert all(field.owner == transaction_fields.FA_EXTRA for field in extras)
    assert all(field.section == transaction_fields.FA_EXTRA_SECTION for field in extras)


async def test_the_panel_grows_the_moment_configuration_adds_a_field(
    db_session: AsyncSession,
) -> None:
    """The "no frontend code change" promise, proved on the side of the wire that decides it.

    A field is added to the stored schema - which is what the  admin screen will do - and it
    becomes an editable, correctable, audited field with no code change anywhere.
    """
    transaction = await make_fa_transaction(db_session)
    row = await db_session.scalar(
        select(DocumentTypeSchema).where(
            DocumentTypeSchema.document_type == DocumentType.FA_DOCUMENT.value
        )
    )
    row.field_schema = {
        "fields": [
            *row.field_schema["fields"],
            {
                "name": "fa_service_period",
                "label": "Service period",
                "type": "date",
                "required": False,
                "tolerance": None,
                "section": "Identification",
                "description": "Only ever configured by a test.",
            },
        ]
    }
    await db_session.commit()

    try:
        extras = await transaction_fields.fa_extra_fields(db_session, transaction)
        added = next(field for field in extras if field.name == "fa_service_period")
        assert added.label == "Service period"
        # And its configured type decides the control the workspace renders.
        assert added.type == "date"
    finally:
        row.field_schema = {"fields": FA_DOCUMENT_FIELDS}
        await db_session.commit()


async def test_an_extra_field_the_schema_does_not_carry_cannot_be_written(
    db_session: AsyncSession,
) -> None:
    """`extra_fields` is a validated, correctable field - never a place to post arbitrary JSON."""
    transaction = await make_fa_transaction(db_session)
    user = await make_user(db_session, roles=["fa_user"], name="FA User")

    with pytest.raises(Exception) as raised:
        await transaction_fields.apply_corrections(
            db_session,
            transaction,
            [("not_in_the_schema", "anything at all", None)],
            user=user,
            audit_event_type="transaction.field_corrected",
        )
    assert "not an editable field" in str(raised.value)


async def test_a_configured_extra_is_corrected_through_the_ordinary_path(
    db_session: AsyncSession,
) -> None:
    transaction = await make_fa_transaction(db_session)
    user = await make_user(db_session, roles=["fa_user"], name="FA User")

    recorded = await transaction_fields.apply_corrections(
        db_session,
        transaction,
        # A reason, because nothing was extracted for this field and the platform gates a
        # correction on what the machine originally scored - which here is nothing at all.
        [("rate", "1600.00", "Corrected against the counterparty's fee note.")],
        user=user,
        audit_event_type="transaction.field_corrected",
    )
    await db_session.commit()

    assert [item["field"] for item in recorded] == ["rate"]
    assert transaction.fa_leg.extra_fields["rate"] == "1600.00"
    # The same provenance record every other correctable field gets.
    assert transaction.field_overrides["fa_extra.rate"]["previous_value"] == "1500.00"


# --- the configuration lookup distinguishes the two streams ------------------------------------


async def test_the_configuration_lookup_distinguishes_fa_from_scrap(
    db_session: AsyncSession,
) -> None:
    """FA resolves to its own row; scrap resolves to the unscoped platform default.

    The two currently carry the same number, because AGFZE has confirmed no FA figure and this
     is instructed not to invent one. What matters is that they are separately addressable:
    the day the business decides FA's tolerance, it is a row change on a row that already exists.
    """
    from app.models.configuration import RuleConfiguration

    resolver = RuleConfigurationResolver(
        list((await db_session.scalars(select(RuleConfiguration))).all())
    )

    scrap = resolver.resolve(
        RuleId.BR_05,
        CheckKey.QUANTITY_TOLERANCE,
        commodity_code=None,
        transaction_type="purchase",
        stream=BusinessStream.SCRAP.value,
    )
    fa = resolver.resolve(
        RuleId.BR_05,
        CheckKey.QUANTITY_TOLERANCE,
        commodity_code=None,
        transaction_type="fa",
        stream=BusinessStream.FA.value,
    )

    assert scrap is not None and fa is not None
    assert scrap.id != fa.id
    assert scrap.scope_stream is None
    assert fa.scope_stream == BusinessStream.FA.value
    assert fa.threshold_value == scrap.threshold_value
    assert "placeholder" in (fa.change_reason or "").lower()


async def test_an_fa_scoped_row_wins_over_the_unscoped_default_once_it_differs(
    db_session: AsyncSession,
) -> None:
    from app.models.configuration import RuleConfiguration

    fa_row = await db_session.scalar(
        select(RuleConfiguration).where(
            RuleConfiguration.rule_id == RuleId.BR_05,
            RuleConfiguration.check_key == CheckKey.QUANTITY_TOLERANCE,
            RuleConfiguration.scope_stream == BusinessStream.FA.value,
        )
    )
    original = fa_row.threshold_value
    fa_row.threshold_value = Decimal("1.5")
    await db_session.commit()

    try:
        resolver = RuleConfigurationResolver(
            list((await db_session.scalars(select(RuleConfiguration))).all())
        )
        resolved = resolver.resolve(
            RuleId.BR_05,
            CheckKey.QUANTITY_TOLERANCE,
            commodity_code=None,
            transaction_type="fa",
            stream=BusinessStream.FA.value,
        )
        assert resolved.threshold_value == Decimal("1.5")
    finally:
        fa_row.threshold_value = original
        await db_session.commit()


# --- the evaluators are reused, not duplicated --------------------------------------------------


async def test_the_shared_evaluators_judge_an_fa_transaction(
    db_session: AsyncSession,
) -> None:
    """BR-02, BR-04, BR-05, BR-06 and BR-13 run against an FA leg they were never written for.

    Not a copy of them, not an FA-specific variant: the same registered functions, reached through
    the same registry, differing only in which leg the context handed them.
    """
    request = await make_request(db_session, category="fa", stream="fa")
    transaction = await make_fa_transaction(db_session, request=request)
    await make_document(
        db_session,
        request,
        values=fa_values(),
        document_type=DocumentType.FA_DOCUMENT.value,
        filename="fa-fee-note.pdf",
        transaction_id=transaction.id,
    )

    written = await rule_engine.run_validation(db_session, transaction)
    await db_session.commit()

    recorded = {row.rule_id for row in written}
    assert {
        RuleId.BR_02,
        RuleId.BR_04,
        RuleId.BR_05,
        RuleId.BR_06,
        RuleId.BR_13,
    } <= recorded
    # And the sales rules stay out of it, because this transaction carries no sales leg.
    assert RuleId.BR_07 not in recorded
    assert RuleId.SL_01 not in recorded


def test_no_fa_specific_evaluator_was_ever_registered() -> None:
    """The registry holds fourteen rules and not a fifteenth called FA-something."""
    assert not any(rule_id.upper().startswith("FA") for rule_id in registered_rules())


# --- the exception owner is decided by the leg, not by a hardcoded desk -------------------------


def test_the_owner_role_is_decided_by_the_leg_that_is_present() -> None:
    """The generalisation Section 9.3 asks for, checked directly.

    The mapping rows say `purchase_user` because they were written when purchase was the only
    stream. That default is honoured where the transaction has a purchase leg and substituted
    where it does not - by inspecting the legs, never by naming a stream.
    """

    class _Stub:
        purchase_leg = None
        sales_leg = None
        fa_leg = None

    purchase_only = _Stub()
    purchase_only.purchase_leg = object()
    fa_only = _Stub()
    fa_only.fa_leg = object()
    sales_only = _Stub()
    sales_only.sales_leg = object()
    both = _Stub()
    both.purchase_leg = object()
    both.sales_leg = object()

    assert governance_hooks.owner_role_for(purchase_only, "purchase_user") == "purchase_user"
    assert governance_hooks.owner_role_for(fa_only, "purchase_user") == "fa_user"
    assert governance_hooks.owner_role_for(sales_only, "purchase_user") == "sales_user"
    # A transaction that genuinely has the named desk's leg keeps that desk, even beside another.
    assert governance_hooks.owner_role_for(both, "purchase_user") == "purchase_user"
    # And a non-desk owner is never substituted: an invoice-value case is Finance's regardless.
    assert governance_hooks.owner_role_for(fa_only, "finance_user") == "finance_user"


async def test_an_fa_hard_failure_opens_a_case_owned_by_the_fa_desk(
    db_session: AsyncSession,
) -> None:
    """End to end, through the real hook and the real mapping table.

    BR-02's mapping row names `purchase_user`. The case this FA transaction opens is owned by
    `fa_user`, and nothing was added to the hook, the mapping table or the rule to make that so.
    """
    transaction = await make_fa_transaction(db_session, fa_contract_reference=None, batch_number="")
    await db_session.commit()

    await rule_engine.run_validation(db_session, transaction)
    await db_session.commit()

    cases = list(
        (
            await db_session.scalars(
                select(ExceptionCase).where(ExceptionCase.transaction_id == transaction.id)
            )
        ).all()
    )
    unmatched = [
        case for case in cases if case.exception_type == ExceptionCategory.UNMATCHED_REFERENCE.value
    ]
    assert unmatched, [case.exception_type for case in cases]
    assert unmatched[0].owner_role == "fa_user"
    assert unmatched[0].rule_id == RuleId.BR_02


# --- the API surface ------------------------------------------------------------------------------


FA_BODY = {
    "counterparty_name": "Gulf Financial Advisory Partners",
    "fa_contract_reference": "FA-2026-0044",
    "document_type": "Advisory fee note",
    "quantity_mt": "12.000",
    "currency": "USD",
    "extra_fields": {"rate": "1500.00", "amount": "18000.00"},
}


async def test_an_fa_user_registers_a_transaction_standalone(
    client: AsyncClient, signed_in
) -> None:
    """FA follows purchase's standalone pattern, not sales' attach-to-an-existing-batch one."""
    _, headers = await fa_user(signed_in)

    response = await client.post(f"{BASE}/fa", headers=headers, json=FA_BODY)

    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert data["stream"] == "fa"
    assert data["has_fa_leg"] is True
    assert data["has_purchase_leg"] is False
    assert data["fa_leg"]["counterparty_name"] == FA_BODY["counterparty_name"]
    assert data["fa_leg"]["extra_fields"]["rate"] == "1500.00"
    # A batch number was allocated by the same sequence the purchase side uses.
    assert data["batch_number"]


async def test_the_workspace_is_handed_the_schema_rather_than_a_field_list(
    client: AsyncClient, signed_in
) -> None:
    """What makes the Additional FA Fields panel schema-driven on the frontend."""
    _, headers = await fa_user(signed_in)

    created = await client.post(f"{BASE}/fa", headers=headers, json=FA_BODY)
    data = created.json()["data"]

    assert {row["name"] for row in data["fa_field_schema"]} == {"rate", "amount"}
    assert {row["name"] for row in data["fa_extra_fields"]} == {"rate", "amount"}
    assert all(row["owner"] == "fa_extra" for row in data["fa_extra_fields"])
    # Every entry carries the type the panel renders its control from.
    assert all(row["type"] for row in data["fa_field_schema"])


async def test_an_unconfigured_extra_field_is_refused_at_the_endpoint(
    client: AsyncClient, signed_in
) -> None:
    _, headers = await fa_user(signed_in)

    response = await client.post(
        f"{BASE}/fa",
        headers=headers,
        json={**FA_BODY, "extra_fields": {"invented_field": "x"}},
    )

    assert response.status_code == 409, response.text
    assert response.json()["errors"][0]["code"] == "fa_field_not_configured"


async def test_the_purchase_desk_may_not_register_an_fa_transaction(
    client: AsyncClient, signed_in
) -> None:
    _, headers = await purchase_user(signed_in)

    response = await client.post(f"{BASE}/fa", headers=headers, json=FA_BODY)

    assert response.status_code == 403, response.text


async def test_an_fa_transaction_is_corrected_and_submitted_through_the_existing_endpoints(
    client: AsyncClient, signed_in
) -> None:
    """The endpoints Section 10 says needed no code change, exercised against FA to prove it."""
    _, headers = await fa_user(signed_in)
    created = await client.post(f"{BASE}/fa", headers=headers, json=FA_BODY)
    transaction_id = created.json()["data"]["id"]

    corrected = await client.patch(
        f"{BASE}/{transaction_id}/fields",
        headers=headers,
        json={
            "changes": [
                {
                    "name": "counterparty_name",
                    "value": "Renamed Counterparty",
                    "reason": "The counterparty's registered name changed.",
                }
            ]
        },
    )
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["data"]["fa_leg"]["counterparty_name"] == "Renamed Counterparty"

    listed = await client.get(f"{BASE}?stream=fa", headers=headers)
    assert listed.status_code == 200
    rows = listed.json()["data"]["items"]
    assert any(row["id"] == transaction_id and row["has_fa_leg"] for row in rows)


async def test_a_hard_failure_on_an_fa_transaction_blocks_its_submission(
    client: AsyncClient, signed_in
) -> None:
    _, headers = await fa_user(signed_in)
    created = await client.post(
        f"{BASE}/fa",
        headers=headers,
        json={**FA_BODY, "extra_fields": {}},
    )
    transaction_id = created.json()["data"]["id"]

    response = await client.post(f"{BASE}/{transaction_id}/submit", headers=headers)

    # BR-06 cannot check a value it has no rate or amount for, and says so rather than passing.
    assert response.status_code == 409, response.text
    assert response.json()["errors"]
    assert any(detail["code"] == "rule_failed" for detail in response.json()["errors"])


async def test_every_fa_rule_evaluation_names_a_severity_the_platform_knows(
    db_session: AsyncSession,
) -> None:
    transaction = await make_fa_transaction(db_session)
    written = await rule_engine.run_validation(db_session, transaction)
    await db_session.commit()

    assert written
    assert all(row.severity in {value.value for value in RuleSeverity} for row in written)
