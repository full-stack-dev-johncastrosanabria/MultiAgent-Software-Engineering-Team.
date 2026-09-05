"""Sanitized, classified diagnostics at the cloud HTTP boundary."""

from __future__ import annotations

import httpx
import pytest

from engineering_team.config import Settings
from engineering_team.contracts.enums import (
    ActionMode,
    AgentRole,
    RemediationCategory,
    ReviewerStatus,
    RouteTarget,
)
from engineering_team.contracts.models import (
    ImplementationResult,
    ProductSpecification,
    ReviewerDecision,
)
from engineering_team.contracts.state import EngineeringState
from engineering_team.llm.cloud import CloudModelRuntime
from engineering_team.models.context import ContextEnvelope, build_context
from engineering_team.observability.langfuse import TraceSession
from engineering_team.run_events import run_event_from_trace


def cloud_envelope() -> ContextEnvelope:
    return ContextEnvelope(
        agent=AgentRole.PRODUCT, current_task="classify requirement",
        state_projection={"requirement": "Add a health endpoint"},
        rag_evidence=[], tool_results=[], remediation_feedback=None,
        output_schema="", allowed_tools=[], model_profile="CLOUD_FALLBACK",
        projection_fingerprint="fixture-fingerprint",
    )


def product_candidate() -> ProductSpecification:
    return ProductSpecification(
        objective="Add a health endpoint", actors=["operator"],
        business_rules=["Return healthy status"], constraints=["Keep compatibility"],
        acceptance_criteria=["GET health returns 200"], nfrs=["Deterministic"],
        ambiguities=[], assumptions=[], source_requirement="Add a health endpoint",
    )


def _runtime(status: int, body: dict[str, object]) -> CloudModelRuntime:
    settings = Settings(
        cloud_enabled=True, local_first=False, gemini_api_key="fixture-key",
    )
    transport = httpx.MockTransport(lambda _: httpx.Response(status, json=body))
    return CloudModelRuntime(settings, client=httpx.Client(transport=transport), primary=True)


def test_cloud_http_401_is_sanitized_and_classified() -> None:
    runtime = _runtime(401, {"error": {"message": "api key sk-secret is invalid"}})
    with pytest.raises(RuntimeError, match="authentication"):
        runtime.invoke_artifact(AgentRole.PRODUCT, cloud_envelope(), product_candidate())
    attempt = runtime.attempts[-1]
    assert attempt.http_status == 401
    assert attempt.error_category == "authentication"
    assert attempt.retryable is False
    assert "sk-secret" not in attempt.error


def test_cloud_http_404_is_model_unavailable_and_not_retryable() -> None:
    runtime = _runtime(404, {"error": {"message": "model not found"}})
    with pytest.raises(RuntimeError, match="model_unavailable"):
        runtime.invoke_artifact(AgentRole.PRODUCT, cloud_envelope(), product_candidate())
    attempt = runtime.attempts[-1]
    assert attempt.http_status == 404
    assert attempt.error_category == "model_unavailable"
    assert attempt.retryable is False


def test_cloud_http_429_is_rate_limit_and_retryable() -> None:
    runtime = _runtime(429, {"error": {"message": "too many requests"}})
    with pytest.raises(RuntimeError, match="rate_limit"):
        runtime.invoke_artifact(AgentRole.PRODUCT, cloud_envelope(), product_candidate())
    attempt = runtime.attempts[-1]
    assert attempt.http_status == 429
    assert attempt.error_category == "rate_limit"
    assert attempt.retryable is True


def test_cloud_http_503_is_provider_unavailable_and_retryable() -> None:
    runtime = _runtime(503, {"error": {"message": "service unavailable"}})
    with pytest.raises(RuntimeError, match="provider_unavailable"):
        runtime.invoke_artifact(AgentRole.PRODUCT, cloud_envelope(), product_candidate())
    attempt = runtime.attempts[-1]
    assert attempt.http_status == 503
    assert attempt.error_category == "provider_unavailable"
    assert attempt.retryable is True


def test_cloud_http_error_never_leaks_response_body() -> None:
    runtime = _runtime(401, {"error": {"message": "secret-token-value should never leak"}})
    with pytest.raises(RuntimeError):
        runtime.invoke_artifact(AgentRole.PRODUCT, cloud_envelope(), product_candidate())
    attempt = runtime.attempts[-1]
    assert "secret-token-value" not in attempt.error
    assert "should never leak" not in attempt.error


def test_governed_contradiction_reports_field_names_without_provider_values() -> None:
    changed = product_candidate().model_copy(update={"source_requirement": "private-provider-value"})
    body = {"candidates": [{"content": {"parts": [{"text": changed.model_dump_json()}]}}]}
    settings = Settings(cloud_enabled=True, gemini_api_key="fixture-key",
                        groq_api_key="fixture-key", sambanova_api_key="fixture-key",
                        open_router_api_key="fixture-key")

    def contradicting(request: httpx.Request) -> httpx.Response:
        """Both providers answer with the same contradiction, so the chain is walked to
        the end and the surfaced error is the contradiction rather than a shape error
        from an unmocked second attempt."""
        # Every provider but Google speaks the OpenAI shape, so match on the one that
        # does not rather than naming each of the others.
        if "generativelanguage.googleapis.com" not in str(request.url):
            return httpx.Response(200, json={
                "choices": [{"message": {"content": changed.model_dump_json()}}]})
        return httpx.Response(200, json=body)

    with httpx.Client(transport=httpx.MockTransport(contradicting)) as client:
        runtime = CloudModelRuntime(settings, client=client, primary=True)
        with pytest.raises(RuntimeError, match="source_requirement"):
            runtime.invoke_artifact(AgentRole.PRODUCT, cloud_envelope(), product_candidate())
    assert runtime.attempts[-1].error_category == "governed_contradiction"
    assert "private-provider-value" not in runtime.attempts[-1].error


def test_governed_cloud_model_rejects_unchanged_developer_remediation() -> None:
    prior = ImplementationResult(
        action_mode=ActionMode.APPLIED,
        changed_files=["app.py"],
        diff="pending",
        evidence=["read:app.py"],
        validation_result="pytest failed",
        security_surface_changed=False,
        file_contents={"app.py": "value = 'wrong'\n"},
    )
    candidate = prior.model_copy(update={"file_contents": {}})
    state = EngineeringState(
        run_id="cloud",
        requirement="fix app.py",
        implementation=prior,
        remediation_request="failed tests require implementation remediation",
        review=ReviewerDecision(
            status=ReviewerStatus.REJECTED,
            score=45,
            subscores={"testing": 0},
            reason="failed tests require implementation remediation",
            problems=["FAILED ASSERTION: assert 'wrong' == 1"],
            remediation_category=RemediationCategory.TESTING,
            return_to=RouteTarget.DEVELOPER,
            confidence=1,
        ),
    )
    envelope = build_context(AgentRole.DEVELOPER, state, "remediate")
    settings = Settings(
        cloud_enabled=True,
        local_first=False,
        groq_api_key="fixture-key",
        cloud_chain_developer="groq:openai/gpt-oss-120b",
    )
    calls: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": prior.model_dump_json()}}]},
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        runtime = CloudModelRuntime(settings, client=client, primary=True)
        with pytest.raises(RuntimeError, match="unchanged developer remediation"):
            runtime.invoke_artifact(AgentRole.DEVELOPER, envelope, candidate)

    assert len(calls) == 1
    assert runtime.attempts[0].error == (
        "LLM_QUALITY_ERROR: unchanged developer remediation"
    )
    assert runtime.attempts[0].error_category == "ineffective_remediation"


@pytest.mark.parametrize("provider,model,key", [
    ("mistral", "codestral-latest", "mistral_api_key"),
    ("openrouter", "nvidia/nemotron-3-super-120b-a12b:free", "open_router_api_key"),
])
def test_schema_capable_providers_receive_schema_not_only_json_mode(provider, model, key):
    import json
    settings = Settings(cloud_enabled=True, cloud_chain_product=f"{provider}:{model}",
                        **{key: "fixture-key"})
    def respond(request):
        body = json.loads(request.content)
        assert body["response_format"]["type"] == "json_schema"
        schema = body["response_format"]["json_schema"]["schema"]
        assert "source_requirement" in schema["required"]
        if provider == "openrouter":
            assert body["provider"]["max_price"] == {"prompt": 0, "completion": 0}
            assert body["provider"]["require_parameters"] is True
        return httpx.Response(200, json={"model": model,
            "choices": [{"message": {"content": product_candidate().model_dump_json()}}]})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        runtime = CloudModelRuntime(settings, client=client, primary=True)
        result, _ = runtime.invoke_artifact(AgentRole.PRODUCT, cloud_envelope(), product_candidate())
    assert result == product_candidate()


def test_rate_limit_skips_same_model_on_next_invocation_and_retains_evidence():
    settings = Settings(cloud_enabled=True, mistral_api_key="fixture", groq_api_key="fixture",
                        cloud_chain_product="mistral:mistral-small-latest,groq:openai/gpt-oss-120b")
    calls = []
    def respond(request):
        calls.append(request.url.host)
        if request.url.host == "api.mistral.ai":
            return httpx.Response(429, headers={"Retry-After": "60"}, json={})
        return httpx.Response(200, json={"choices": [{"message": {
            "content": product_candidate().model_dump_json()}}]})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        runtime = CloudModelRuntime(settings, client=client, primary=True)
        for _ in range(2):
            runtime.invoke_artifact(AgentRole.PRODUCT, cloud_envelope(), product_candidate())
    assert calls == ["api.mistral.ai", "api.groq.com", "api.groq.com"]
    assert runtime.attempts[0].http_status == 429


def test_one_model_quota_does_not_disable_other_models_at_that_provider():
    settings = Settings(_env_file=None, cloud_enabled=True, gemini_api_key="fixture",
        cloud_chain_product="google:gemini-3.6-flash,google:gemini-3.5-flash")
    calls = []
    def respond(request):
        calls.append(request.url.path)
        if "3.6" in request.url.path:
            return httpx.Response(429, json={})
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{
            "text": product_candidate().model_dump_json()}]}}]})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        runtime = CloudModelRuntime(settings, client=client, primary=True)
        artifact, _ = runtime.invoke_artifact(AgentRole.PRODUCT, cloud_envelope(), product_candidate())
    assert artifact == product_candidate()
    assert len(calls) == 2


def test_auth_failure_skips_all_models_on_that_provider():
    settings = Settings(_env_file=None, cloud_enabled=True, mistral_api_key="fixture",
        groq_api_key="fixture", cloud_chain_product=(
            "mistral:mistral-small-latest,mistral:mistral-medium-latest,groq:openai/gpt-oss-120b"))
    calls = []
    def respond(request):
        calls.append(request.url.host)
        if request.url.host == "api.mistral.ai":
            return httpx.Response(401, json={})
        return httpx.Response(200, json={"choices": [{"message": {
            "content": product_candidate().model_dump_json()}}]})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        runtime = CloudModelRuntime(settings, client=client, primary=True)
        runtime.invoke_artifact(AgentRole.PRODUCT, cloud_envelope(), product_candidate())
    assert calls == ["api.mistral.ai", "api.groq.com"]


def test_role_budget_stops_starting_new_attempts_after_deadline(monkeypatch):
    from engineering_team.llm import cloud
    clock = [0.0]
    monkeypatch.setattr(cloud.time, "monotonic", lambda: clock[0])
    settings = Settings(_env_file=None, cloud_enabled=True, mistral_api_key="fixture",
        groq_api_key="fixture", cloud_role_timeout_seconds=20,
        cloud_chain_product="mistral:mistral-small-latest,groq:openai/gpt-oss-120b")
    calls = []
    def respond(request):
        calls.append(request.url.host)
        assert request.extensions["timeout"]["read"] == 20
        clock[0] = 21
        return httpx.Response(503, json={})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        runtime = CloudModelRuntime(settings, client=client, primary=True)
        with pytest.raises(RuntimeError, match="deadline"):
            runtime.invoke_artifact(AgentRole.PRODUCT, cloud_envelope(), product_candidate())
    assert calls == ["api.mistral.ai"]
    assert runtime.attempts[0].http_status == 503


def test_truncated_output_is_classified_before_json_validation():
    settings = Settings(_env_file=None, cloud_enabled=True, mistral_api_key="fixture",
        cloud_chain_product="mistral:mistral-small-latest")
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={
        "choices": [{"finish_reason": "length", "message": {"content": '{"incomplete":'}}]}))) as client:
        runtime = CloudModelRuntime(settings, client=client, primary=True)
        with pytest.raises(RuntimeError):
            runtime.invoke_artifact(AgentRole.PRODUCT, cloud_envelope(), product_candidate())
    assert runtime.attempts[0].error_category == "incomplete_output"


def test_http_date_retry_after_controls_the_model_cooldown():
    import time
    from datetime import datetime, timedelta, timezone
    from email.utils import format_datetime

    settings = Settings(_env_file=None, cloud_enabled=True, mistral_api_key="fixture",
        cloud_chain_product="mistral:mistral-small-latest")
    retry_at = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=120), usegmt=True)
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(
            429, headers={"Retry-After": retry_at}, json={}))) as client:
        runtime = CloudModelRuntime(settings, client=client, primary=True)
        with pytest.raises(RuntimeError):
            runtime.invoke_artifact(AgentRole.PRODUCT, cloud_envelope(), product_candidate())
    remaining = runtime._unavailable_until[("mistral", "mistral-small-latest")] - time.monotonic()
    assert 115 < remaining <= 120


def test_primary_google_failure_uses_secondary_key_at_official_endpoint():
    settings = Settings(
        _env_file=None,
        cloud_enabled=True,
        gemini_api_key="primary-fixture-key",
        gemini_api_key_2="secondary-fixture-key",
        cloud_chain_product="google:gemini-primary,google2:gemini-secondary",
    )
    calls: list[tuple[str, str]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append((str(request.url), request.headers["x-goog-api-key"]))
        if "gemini-primary" in request.url.path:
            return httpx.Response(503, json={})
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{
            "text": product_candidate().model_dump_json(),
        }]}}]})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        runtime = CloudModelRuntime(settings, client=client, primary=True)
        artifact, info = runtime.invoke_artifact(
            AgentRole.PRODUCT, cloud_envelope(), product_candidate()
        )

    assert artifact == product_candidate()
    assert info.provider == "google2"
    assert calls == [
        (
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-primary:generateContent",
            "primary-fixture-key",
        ),
        (
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-secondary:generateContent",
            "secondary-fixture-key",
        ),
    ]


def test_missing_secondary_google_credential_skips_route_cleanly():
    settings = Settings(
        _env_file=None,
        cloud_enabled=True,
        gemini_api_key="primary-fixture-key",
        gemini_api_key_2=None,
        cloud_chain_product="google:gemini-primary,google2:gemini-secondary",
    )
    calls: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request.headers["x-goog-api-key"])
        return httpx.Response(503, json={})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        runtime = CloudModelRuntime(settings, client=client, primary=True)
        with pytest.raises(RuntimeError, match="CLOUD_FALLBACK_UNAVAILABLE"):
            runtime.invoke_artifact(AgentRole.PRODUCT, cloud_envelope(), product_candidate())

    assert calls == ["primary-fixture-key"]
    assert runtime.budget.run_count == 1


def test_primary_google_cooldown_does_not_disable_secondary_credential():
    settings = Settings(
        _env_file=None,
        cloud_enabled=True,
        gemini_api_key="primary-fixture-key",
        gemini_api_key_2="secondary-fixture-key",
        cloud_chain_product="google:gemini-shared,google2:gemini-shared",
    )
    calls: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        key = request.headers["x-goog-api-key"]
        calls.append(key)
        if key == "primary-fixture-key":
            return httpx.Response(429, headers={"Retry-After": "60"}, json={})
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{
            "text": product_candidate().model_dump_json(),
        }]}}]})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        runtime = CloudModelRuntime(settings, client=client, primary=True)
        for _ in range(2):
            runtime.invoke_artifact(AgentRole.PRODUCT, cloud_envelope(), product_candidate())

    assert calls == [
        "primary-fixture-key", "secondary-fixture-key", "secondary-fixture-key",
    ]
    assert ("google", "gemini-shared") in runtime._unavailable_until
    assert ("google2", "gemini-shared") not in runtime._unavailable_until


def test_secondary_google_route_respects_shared_role_deadline(monkeypatch):
    from engineering_team.llm import cloud

    clock = [0.0]
    monkeypatch.setattr(cloud.time, "monotonic", lambda: clock[0])
    settings = Settings(
        _env_file=None,
        cloud_enabled=True,
        gemini_api_key="primary-fixture-key",
        gemini_api_key_2="secondary-fixture-key",
        cloud_role_timeout_seconds=20,
        cloud_chain_product="google:gemini-primary,google2:gemini-secondary",
    )
    calls: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request.headers["x-goog-api-key"])
        clock[0] = 21
        return httpx.Response(503, json={})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        runtime = CloudModelRuntime(settings, client=client, primary=True)
        with pytest.raises(RuntimeError, match="deadline"):
            runtime.invoke_artifact(AgentRole.PRODUCT, cloud_envelope(), product_candidate())

    assert calls == ["primary-fixture-key"]


def test_secondary_google_credential_name_is_redacted_from_trace_and_events():
    trace = TraceSession(trace_id="trace", run_id="run", live=False)
    trace.record("credential", metadata={"gemini_api_key_2": "secondary-secret"})
    event = run_event_from_trace(
        run_id="run",
        sequence=1,
        trace_event={
            "name": "credential",
            "metadata": {"gemini_api_key_2": "secondary-secret"},
        },
    )

    assert trace.events[0]["metadata"]["gemini_api_key_2"] == "[REDACTED]"
    assert "secondary-secret" not in str(event)
