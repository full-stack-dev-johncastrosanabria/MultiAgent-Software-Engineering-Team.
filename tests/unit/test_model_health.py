"""Models that keep failing a role are tried later, and can earn their place back."""

import json

import httpx
import pytest

from engineering_team.config import Settings
from engineering_team.contracts.enums import AgentRole
from engineering_team.llm.cloud import CloudModelRuntime
from engineering_team.llm.model_health import ModelHealth
from engineering_team.llm.registry import ModelSelection
from tests.unit.test_cloud_runtime import cloud_envelope, product_candidate

ROLE = AgentRole.DEVELOPER


def _chain(*pairs):
    return tuple(ModelSelection(ROLE, "CLOUD_FALLBACK", provider, model) for provider, model in pairs)


CHAIN = _chain(("mistral", "codestral-latest"), ("groq", "gpt-oss"), ("cohere", "command-a"))


def test_a_model_that_keeps_breaking_the_contract_moves_to_the_end(tmp_path):
    health = ModelHealth(tmp_path / "health.json")
    for _ in range(4):
        health.record_attempt(ROLE, "mistral", "codestral-latest", "governed_contradiction")
    ordered = [(item.provider, item.model) for item in health.ordered(ROLE, CHAIN)]
    assert ordered == [("groq", "gpt-oss"), ("cohere", "command-a"), ("mistral", "codestral-latest")]


def test_too_few_attempts_or_mostly_successes_keep_the_order(tmp_path):
    health = ModelHealth(tmp_path / "health.json")
    health.record_attempt(ROLE, "mistral", "codestral-latest", "schema_validation")
    for _ in range(5):
        health.record_attempt(ROLE, "groq", "gpt-oss", None)
    health.record_attempt(ROLE, "groq", "gpt-oss", "timeout")
    assert health.ordered(ROLE, CHAIN) == CHAIN


def test_capacity_errors_weigh_less_than_quality_errors(tmp_path):
    health = ModelHealth(tmp_path / "health.json")
    for _ in range(3):
        health.record_attempt(ROLE, "mistral", "codestral-latest", "rate_limit")
    health.record_attempt(ROLE, "mistral", "codestral-latest", None)
    assert health.ordered(ROLE, CHAIN) == CHAIN


def test_authored_code_whose_tests_keep_failing_demotes_the_author(tmp_path):
    """spring-demo: one model wrote Spring Boot 3 tests for a Boot 4 project, five times."""
    health = ModelHealth(tmp_path / "health.json")
    for _ in range(3):
        health.record_attempt(ROLE, "mistral", "codestral-latest", None)
        health.record_authoring(ROLE, "mistral", "codestral-latest", passed=False)
    assert health.ordered(ROLE, CHAIN)[-1].provider == "mistral"


def test_a_demoted_model_recovers_once_recent_outcomes_are_good(tmp_path):
    health = ModelHealth(tmp_path / "health.json", window=6)
    for _ in range(4):
        health.record_attempt(ROLE, "mistral", "codestral-latest", "schema_validation")
    for _ in range(6):
        health.record_attempt(ROLE, "mistral", "codestral-latest", None)
    assert health.ordered(ROLE, CHAIN) == CHAIN


def test_health_is_remembered_across_runs_and_scoped_by_role(tmp_path):
    path = tmp_path / "health.json"
    first = ModelHealth(path)
    for _ in range(4):
        first.record_attempt(ROLE, "mistral", "codestral-latest", "invalid_response")
    second = ModelHealth(path)
    assert second.ordered(ROLE, CHAIN)[-1].provider == "mistral"
    product = tuple(ModelSelection(AgentRole.PRODUCT, "CLOUD_FALLBACK", i.provider, i.model) for i in CHAIN)
    assert second.ordered(AgentRole.PRODUCT, product) == product


@pytest.mark.parametrize("content", ["not json", '{"entries": 3}', "[]"])
def test_an_unreadable_ledger_starts_empty_instead_of_failing_the_run(tmp_path, content):
    path = tmp_path / "health.json"
    path.write_text(content)
    assert ModelHealth(path).ordered(ROLE, CHAIN) == CHAIN


def test_the_runtime_records_outcomes_and_tries_the_demoted_model_last(tmp_path):
    path = tmp_path / "health.json"
    health = ModelHealth(path)
    for _ in range(4):
        health.record_attempt(AgentRole.PRODUCT, "mistral", "mistral-small-latest", "schema_validation")
    settings = Settings(_env_file=None, cloud_enabled=True, mistral_api_key="fixture", groq_api_key="fixture",
                        cloud_chain_product="mistral:mistral-small-latest,groq:openai/gpt-oss-120b")
    hosts = []

    def respond(request):
        hosts.append(request.url.host)
        return httpx.Response(200, json={"choices": [{"message": {
            "content": product_candidate().model_dump_json()}, "finish_reason": "stop"}]})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        runtime = CloudModelRuntime(settings, client=client, primary=True, health=health)
        runtime.invoke_artifact(AgentRole.PRODUCT, cloud_envelope(), product_candidate())
    assert hosts == ["api.groq.com"]
    stored = json.loads(path.read_text())
    assert any("groq" in key for key in stored["entries"])


def test_testing_attributes_the_suite_result_to_the_model_that_authored_the_change(tmp_path):
    from engineering_team.contracts.enums import ActionMode, ToolStatus
    from engineering_team.contracts.models import (
        ImplementationResult,
        ModelExecutionInfo,
        ToolResult,
    )
    from engineering_team.graph.stategraph import build_engineering_graph

    class Quality:
        def run_tests(self, role, paths=None):
            return ToolResult(tool_name="run_tests", allowed_role=role, status=ToolStatus.FAIL,
                              input_summary="suite", output_summary="1 failed", duration_ms=1)

    class Runtime:
        def __init__(self):
            self.attempts = []
            self.health = ModelHealth(tmp_path / "health.json")

    runtime = Runtime()
    usage = [
        ModelExecutionInfo(agent=AgentRole.DEVELOPER, provider="mistral", requested_model="codestral-latest",
                           model_profile="CLOUD_FALLBACK", latency_ms=1, structured_output_success=True),
        ModelExecutionInfo(agent=AgentRole.DEVELOPER, provider="cohere", requested_model="command-a",
                           model_profile="CLOUD_FALLBACK", latency_ms=1, structured_output_success=False),
    ]
    implementation = ImplementationResult(
        action_mode=ActionMode.APPLIED, changed_files=["app.py"], diff="d", evidence=["e"],
        validation_result="v", security_surface_changed=False, file_contents={"app.py": "x = 1\n"},
    )
    graph = build_engineering_graph(quality_mcp=Quality(), model_runtime=runtime)
    graph.nodes["Testing"].invoke({
        "run_id": "authoring", "requirement": "r", "implementation": implementation, "model_usage": usage,
    })
    assert runtime.health.entries["Developer|mistral|codestral-latest"]["authoring"] == ["fail"]
    assert "Developer|cohere|command-a" not in runtime.health.entries
