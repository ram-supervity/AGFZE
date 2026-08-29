"""Classification against synthetic provider responses.

`_generate_raw` is the single seam through which the AI service reaches a model. Replacing it
with a payload the test wrote is what proves the parsing, the confidence handling and the
failure routing without a live key or live quota - and proves that a malformed response is a
routed failure, never a crash and never a value silently coerced into shape.
"""

from __future__ import annotations

import json

import pytest

from app.core.config import settings
from app.models.enums import DocumentType
from app.services import classification_service
from app.services.gemini_service import (
    DATA_BLOCK_CLOSE,
    DATA_BLOCK_OPEN,
    AIProviderNotConfiguredError,
    AIServiceError,
    generate_structured,
    get_provider,
    reset_provider_cache,
    wrap_source_data,
)
from tests.utils.fixtures import classification_response, document_classification_response


@pytest.fixture
def model_reply(monkeypatch: pytest.MonkeyPatch):
    """Answer the next model call with an exact payload, and capture the prompt it was sent."""
    captured: dict[str, object] = {}

    def _install(payload: str | Exception) -> dict[str, object]:
        async def _raw(prompt, response_schema, images):
            captured["prompt"] = prompt
            captured["schema"] = response_schema
            captured["images"] = images
            if isinstance(payload, Exception):
                raise payload
            return payload

        monkeypatch.setattr("app.services.gemini_service._generate_raw", _raw)
        return captured

    return _install


async def test_a_valid_response_is_parsed_into_the_expected_schema(model_reply) -> None:
    captured = model_reply(classification_response("purchase", 0.93, "scrap"))

    outcome = await classification_service.classify_request(
        subject="Purchase confirmation - Copper Millberry 24.5MT",
        body="Please find our confirmation for 24.5 MT.",
        sender="desk@broker.example",
    )

    assert outcome.category == "purchase"
    assert outcome.confidence == pytest.approx(0.93)
    assert outcome.stream == "scrap"
    assert outcome.rationale
    assert outcome.needs_review is False
    assert outcome.error is None
    # The mail is handed over as a delimited data block, marked as data and not instruction.
    prompt = str(captured["prompt"])
    assert DATA_BLOCK_OPEN in prompt and DATA_BLOCK_CLOSE in prompt


async def test_a_low_confidence_answer_is_routed_to_human_review(model_reply) -> None:
    below = settings.CONFIDENCE_THRESHOLD_DEFAULT - 0.2
    model_reply(classification_response("follow_up", below, None))

    outcome = await classification_service.classify_request(
        subject="Any update?", body="Chasing the earlier mail.", sender="desk@broker.example"
    )

    assert outcome.category == "follow_up"
    assert outcome.needs_review is True
    assert outcome.error is None


@pytest.mark.parametrize(
    "payload",
    [
        "this is not json at all",
        "[]",
        json.dumps({"confidence": 0.9}),
        json.dumps({"category": "not_a_category", "confidence": 0.9, "rationale": "x"}),
        json.dumps({"category": "purchase", "confidence": 4.2, "rationale": "x"}),
        json.dumps({"category": "purchase", "confidence": 0.9, "rationale": ""}),
    ],
)
async def test_a_malformed_response_becomes_a_review_flag_not_a_crash(
    model_reply, payload: str
) -> None:
    model_reply(payload)

    outcome = await classification_service.classify_request(
        subject="Anything", body="Anything", sender="desk@broker.example"
    )

    # Nothing is coerced into shape: the answer is discarded and a person is asked.
    assert outcome.category is None
    assert outcome.confidence is None
    assert outcome.needs_review is True
    assert outcome.error in {"malformed_response", "schema_invalid"}


async def test_a_provider_failure_is_reported_without_leaking_its_detail(model_reply) -> None:
    model_reply(RuntimeError("429 quota exceeded for project 1234 key AIzaSyLEAKED"))

    outcome = await classification_service.classify_request(
        subject="Anything", body="Anything", sender="desk@broker.example"
    )

    assert outcome.needs_review is True
    assert outcome.error == "provider_error"
    assert outcome.rationale is None


async def test_the_schema_validation_failure_surfaces_as_a_typed_error(model_reply) -> None:
    from pydantic import BaseModel

    class Shape(BaseModel):
        value: int

    model_reply(json.dumps({"value": "not an integer"}))

    with pytest.raises(AIServiceError) as caught:
        await generate_structured(
            prompt="anything",
            response_schema={"type": "object"},
            model=Shape,
            purpose="test",
        )
    assert caught.value.reason == "schema_invalid"
    assert caught.value.status_code == 503


async def test_document_classification_parses_type_and_territory(model_reply) -> None:
    model_reply(document_classification_response("invoice", 0.95, "india"))

    outcome = await classification_service.classify_document(
        filename="invoice.pdf", text="COMMERCIAL INVOICE\nInvoice Number: INV-2026-0451"
    )

    assert outcome.document_type == "invoice"
    assert outcome.territory == "india"
    assert outcome.needs_review is False


async def test_an_unidentifiable_document_always_asks_for_a_person(model_reply) -> None:
    model_reply(document_classification_response(DocumentType.UNKNOWN.value, 0.99, None))

    outcome = await classification_service.classify_document(filename="scan.pdf", text="")

    assert outcome.document_type == DocumentType.UNKNOWN.value
    assert outcome.needs_review is True


def test_source_data_is_delimited_and_truncated_rather_than_sent_whole() -> None:
    wrapped = wrap_source_data("document text", "x" * 500, limit=100)
    assert wrapped.startswith(DATA_BLOCK_OPEN)
    assert wrapped.rstrip().endswith(DATA_BLOCK_CLOSE)
    assert "[truncated at 100 characters]" in wrapped


async def test_a_missing_api_key_fails_loudly_and_is_never_faked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_provider_cache()
    monkeypatch.setattr("app.services.gemini_service.settings.GEMINI_API_KEY", "")
    provider = get_provider()
    with pytest.raises(AIProviderNotConfiguredError):
        await provider.client()
    reset_provider_cache()


async def test_the_vertex_extension_point_refuses_rather_than_pretending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_provider_cache()
    monkeypatch.setattr("app.services.gemini_service.settings.AI_PROVIDER", "vertex_ai")
    with pytest.raises(AIProviderNotConfiguredError):
        await get_provider().generate(prompt="x", response_schema={}, images=None)
    reset_provider_cache()
