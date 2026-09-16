"""Missing response fields remain actionable without exposing exception payloads."""

import traceback

import httpx
import pytest

from engineering_team.config import Settings
from engineering_team.contracts.enums import AgentRole
from engineering_team.contracts.models import ProductSpecification
from engineering_team.llm.cloud import CloudModelRuntime
from engineering_team.models.context import ContextEnvelope


def _candidate() -> ProductSpecification:
    return ProductSpecification(
        objective="Add health endpoint", actors=["operator"],
        business_rules=["Return healthy"], constraints=["Keep compatibility"],
        acceptance_criteria=["GET health returns 200"], nfrs=["Deterministic"],
        ambiguities=[], assumptions=[], source_requirement="Add health endpoint",
    )


def _envelope() -> ContextEnvelope:
    return ContextEnvelope(
        agent=AgentRole.PRODUCT, current_task="classify requirement",
        state_projection={"requirement": "Add health endpoint"},
        rag_evidence=[], tool_results=[], remediation_feedback=None,
        output_schema="", allowed_tools=[], model_profile="CLOUD_FALLBACK",
        projection_fingerprint="fixture-fingerprint",
    )


def _settings(**overrides: object) -> Settings:
    return Settings(
        cloud_enabled=True, local_first=False, gemini_api_key="fixture-key",
        gemini_api_key_2=None, mistral_api_key=None, open_router_api_key=None,
        x_kiro_api_key=None, vyce_ai_api_key=None, token_forge_api_key=None, nvidia_api_key=None,
        kilo_api_key=None, cohere_api_key=None, cloudflare_worker_ai_api=None,
        **{"groq_api_key": None, **overrides},
    )


@pytest.mark.parametrize(("body", "missing"), [
    ({}, "candidates"),
    ({"candidates": [{}]}, "content"),
    ({"candidates": [{"content": {}}]}, "parts"),
    ({"candidates": [{"content": {"parts": [{}]}}]}, "text"),
])
def test_missing_response_field_is_named_without_response_values(body, missing) -> None:
    body["private"] = "private-provider-value"
    with httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json=body)
    )) as client:
        runtime = CloudModelRuntime(_settings(), client=client, primary=True)
        with pytest.raises(RuntimeError, match=f"KeyError: missing response field '{missing}'") as raised:
            runtime.invoke_artifact(AgentRole.PRODUCT, _envelope(), _candidate())
    assert runtime.attempts[-1].error == str(raised.value)
    assert runtime.attempts[-1].error_category == "invalid_response"
    assert runtime.attempts[-1].retryable is True
    assert "private-provider-value" not in str(raised.value)


@pytest.mark.parametrize("key", [
    "sk-" + "a" * 40,
    "Authorization: Bearer private-provider-value",
    "private-provider-value\n" * 1000,
    ("private-provider-value",),
], ids=["token", "header", "oversized", "non-string"])
def test_untrusted_keyerror_arguments_are_suppressed_even_in_tracebacks(key) -> None:
    def fail(_: httpx.Request) -> httpx.Response:
        raise KeyError(key)

    with httpx.Client(transport=httpx.MockTransport(fail)) as client:
        runtime = CloudModelRuntime(_settings(), client=client, primary=True)
        with pytest.raises(RuntimeError) as raised:
            runtime.invoke_artifact(AgentRole.PRODUCT, _envelope(), _candidate())
    assert str(raised.value) == "CLOUD_FALLBACK_UNAVAILABLE: KeyError: missing response field [REDACTED]"
    assert len(runtime.attempts[-1].error) < 150
    rendered = "".join(traceback.format_exception(raised.value))
    assert "private-provider-value" not in rendered
    assert "sk-" + "a" * 40 not in rendered


def test_missing_field_still_falls_back_to_next_provider() -> None:
    candidate = _candidate()

    def reply(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.groq.com":
            return httpx.Response(200, json={"private": "private-provider-value"})
        return httpx.Response(200, json={"candidates": [{"content": {
            "parts": [{"text": candidate.model_dump_json()}],
        }}]})

    with httpx.Client(transport=httpx.MockTransport(reply)) as client:
        runtime = CloudModelRuntime(
            _settings(groq_api_key="fixture-key"), client=client, primary=True,
        )
        artifact, info = runtime.invoke_artifact(AgentRole.PRODUCT, _envelope(), candidate)
    assert artifact == candidate
    assert info.structured_output_success is True
    assert [attempt.provider for attempt in runtime.attempts] == ["groq", "google"]
    assert runtime.attempts[0].error == "CLOUD_FALLBACK_UNAVAILABLE: KeyError: missing response field 'choices'"


def test_sensitive_keyerror_does_not_leak_when_later_provider_fails() -> None:
    def reply(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.groq.com":
            raise KeyError("private-provider-value")
        return httpx.Response(401, json={})

    with httpx.Client(transport=httpx.MockTransport(reply)) as client:
        runtime = CloudModelRuntime(
            _settings(groq_api_key="fixture-key"), client=client, primary=True,
        )
        with pytest.raises(RuntimeError, match="authentication") as raised:
            runtime.invoke_artifact(AgentRole.PRODUCT, _envelope(), _candidate())
    rendered = "".join(traceback.format_exception(raised.value))
    assert "KeyError: 'private-provider-value'" not in rendered
    assert [attempt.provider for attempt in runtime.attempts] == ["groq", "google"]


@pytest.mark.parametrize(("code", "category"), [
    (502, "provider_unavailable"), (429, "rate_limit"), (400, "request_rejected"),
])
def test_provider_error_in_a_success_body_is_reported_by_its_code_only(code, category) -> None:
    """OpenRouter relays upstream failures as HTTP 200 with an error object.

    Observed 2026-09-16: 'Upstream error from Nvidia: Service temporarily
    overloaded', code 502, reported as a missing 'choices' field.
    """
    body = {"id": "gen-1", "error": {
        "message": "private-provider-value overloaded", "code": code,
        "metadata": {"raw": "private-provider-value"},
    }}
    with httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json=body)
    )) as client:
        settings = Settings(
            cloud_enabled=True, local_first=False, gemini_api_key=None, gemini_api_key_2=None,
            mistral_api_key=None, groq_api_key=None, open_router_api_key="fixture-key",
            cloud_chain_product="openrouter:nvidia/nemotron-3-super-120b-a12b:free",
        )
        runtime = CloudModelRuntime(settings, client=client, primary=True)
        with pytest.raises(RuntimeError, match=rf"{category} \(provider error {code}\)") as raised:
            runtime.invoke_artifact(AgentRole.PRODUCT, _envelope(), _candidate())
    assert runtime.attempts[-1].error_category == category
    assert "private-provider-value" not in str(raised.value)
    assert "choices" not in str(raised.value)
