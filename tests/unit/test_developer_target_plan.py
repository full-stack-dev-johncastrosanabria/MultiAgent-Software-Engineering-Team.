from pathlib import Path

import pytest

from engineering_team.agents.developer import DeveloperAgent
from engineering_team.contracts.developer_plan import (
    DeveloperTargetPlan,
    NewDeveloperFile,
    is_test_path,
    plan_candidate,
    validate_target_plan,
)
from engineering_team.contracts.enums import ActionMode, AgentRole, ToolStatus
from engineering_team.contracts.models import ImplementationResult, ModelExecutionInfo
from engineering_team.contracts.state import EngineeringState
from engineering_team.graph.stategraph import build_engineering_graph
from engineering_team.llm.prompting import build_role_prompts
from engineering_team.llm.runtime import _preserves_governed_facts
from engineering_team.mcp.repository import RepositoryMCP
from engineering_team.models.context import build_context

PATHS = ["api/pyproject.toml", "api/products.py", "api/tests/test_original.py"]


def proposed_plan(candidate, **updates):
    return candidate.model_copy(update={
        "edit_paths": ["api/products.py"],
        "new_files": [NewDeveloperFile(
            path="api/tests/test_validation.py", kind="test_source", component_root="api",
        )],
        **updates,
    })


def test_natural_requirement_gets_bounded_source_and_new_test_targets():
    candidate = plan_candidate(PATHS, authored=set())
    proposed = proposed_plan(candidate)
    writes, reads = validate_target_plan(candidate, proposed, all_paths=set(PATHS))
    assert writes == ["api/products.py", "api/tests/test_validation.py"]
    assert set(reads) == set(PATHS)
    assert _preserves_governed_facts(candidate.model_dump(mode="json"), proposed)


@pytest.mark.parametrize("path", [
    "api/tests/test_original.py", "missing.py", "../escape.py", "/tmp/escape.py",
    "api/.env", "api/node_modules/tool.js", "api/pyproject.toml",
])
def test_untrusted_plan_cannot_choose_arbitrary_or_original_test_edits(path):
    candidate = plan_candidate(PATHS, authored=set())
    proposed = proposed_plan(candidate, edit_paths=[path])
    with pytest.raises(ValueError):
        validate_target_plan(candidate, proposed, all_paths=set(PATHS))
    assert not _preserves_governed_facts(candidate.model_dump(mode="json"), proposed)


@pytest.mark.parametrize("path, kind", [
    ("outside/test_injected.py", "test_source"),
    ("api/products_extra.py", "test_source"),
    ("api/tests/test_original.py", "test_source"),
    ("api/tests/evil.sh", "test_support"),
    ("api/tests/secrets.json", "test_support"),
    ("api/tests/../escape.py", "test_source"),
])
def test_new_file_allowlist_is_typed_bounded_and_component_scoped(path, kind):
    candidate = plan_candidate(PATHS, authored=set())
    proposed = proposed_plan(candidate, new_files=[NewDeveloperFile(
        path=path, kind=kind, component_root="api",
    )])
    with pytest.raises(ValueError):
        validate_target_plan(candidate, proposed, all_paths=set(PATHS))


def test_inventory_cannot_be_rewritten_to_grant_authority():
    candidate = plan_candidate(PATHS, authored=set())
    proposed = proposed_plan(candidate, inventory_paths=[*PATHS, "injected.py"])
    assert not _preserves_governed_facts(candidate.model_dump(mode="json"), proposed)


def test_original_tests_remain_protected_but_own_new_tests_can_be_repaired():
    paths = [*PATHS, "api/tests/test_validation.py"]
    candidate = plan_candidate(paths, authored={"api/tests/test_validation.py"})
    proposed = proposed_plan(candidate, new_files=[], edit_paths=[
        "api/products.py", "api/tests/test_validation.py",
    ])
    assert "api/tests/test_original.py" in candidate.protected_test_paths
    writes, _ = validate_target_plan(candidate, proposed, all_paths=set(paths))
    assert writes[-1] == "api/tests/test_validation.py"


def test_dotnet_without_tests_can_plan_new_sibling_test_project_and_source():
    paths = ["Sales.Api/Sales.Api.csproj", "Sales.Api/Controllers/SalesController.cs"]
    candidate = plan_candidate(paths, authored=set())
    proposed = candidate.model_copy(update={
        "edit_paths": [paths[1]],
        "new_files": [
            NewDeveloperFile(path="tests/Sales.Tests/Sales.Tests.csproj",
                             kind="test_project", component_root="Sales.Api"),
            NewDeveloperFile(path="tests/Sales.Tests/SalesTests.cs",
                             kind="test_source", component_root="Sales.Api"),
        ],
    })
    writes, reads = validate_target_plan(candidate, proposed, all_paths=set(paths))
    assert len(writes) == 3
    assert paths[0] in reads


@pytest.mark.parametrize("path", [
    "src/test/java/FooTests.java", "Sales.Tests/FooTests.cs", "src/foo.test.ts",
    "src/foo.spec.ts", "src/foo_test.go", "test_original.py",
])
def test_multistack_original_test_detection(path):
    assert is_test_path(path)
    assert DeveloperAgent._is_test_path(path)


@pytest.mark.parametrize("path", ["api/contest.py", "api/latest.py", "api/Contest.cs"])
def test_source_names_containing_test_are_not_test_files(path):
    assert not is_test_path(path)


def test_planning_inventory_drops_secrets_and_generated_files():
    candidate = plan_candidate([
        *PATHS, "api/.env", "api/bin/Foo.cs", "api/obj/generated.cs",
        "api/node_modules/foo.js", "api/.git/config", "api/dist/app.js",
    ], authored=set())
    assert candidate.inventory_paths == PATHS


class NaturalRuntime:
    def __init__(self, *, reject=False):
        self.attempts = []
        self.calls = []
        self.reject = reject

    def invoke_artifact(self, role, envelope, candidate, **kwargs):
        self.calls.append((candidate, envelope))
        info = ModelExecutionInfo(
            agent=role, provider="ollama", requested_model="test", model_profile="LOCAL",
            latency_ms=1, structured_output_success=True,
        )
        if isinstance(candidate, DeveloperTargetPlan):
            return proposed_plan(candidate, edit_paths=[
                "api/tests/test_original.py" if self.reject else "api/products.py",
            ]), info
        if isinstance(candidate, ImplementationResult) and candidate.action_mode is ActionMode.APPLIED:
            assert {item.input_summary for item in envelope.tool_results} == {
                "path=" + path for path in PATHS
            }
            assert envelope.state_projection["requirement"] == REQUIREMENT
            return candidate.model_copy(update={"file_contents": {
                "api/products.py": "def valid(name):\n    return bool(name.strip())\n",
                "api/tests/test_validation.py": "def test_blank():\n    assert not ''.strip()\n",
            }}), info
        return candidate, info


REQUIREMENT = "Al crear un producto, rechazar nombres vacíos con estado 400 y añadir pruebas."


def setup_repository(tmp_path: Path):
    (tmp_path / "api/tests").mkdir(parents=True)
    (tmp_path / PATHS[0]).write_text("[project]\nname = 'example'\nversion = '0.1'\n")
    (tmp_path / PATHS[1]).write_text("def valid(name):\n    return True\n")
    (tmp_path / PATHS[2]).write_text("def test_original():\n    assert True\n")
    return RepositoryMCP(tmp_path)


def test_authorized_natural_apply_plans_reads_then_authors_without_spec_path_hints(tmp_path):
    repository = setup_repository(tmp_path)
    runtime = NaturalRuntime()
    graph = build_engineering_graph(repository_mcp=repository, model_runtime=runtime)
    patch = graph.nodes["Developer"].invoke({
        "run_id": "natural", "requirement": REQUIREMENT,
        "repository_context": {"apply_changes": True, "authorized": True},
    })
    assert patch["implementation"].action_mode is ActionMode.APPLIED
    assert "return bool(name.strip())" in (tmp_path / PATHS[1]).read_text()
    assert (tmp_path / "api/tests/test_validation.py").exists()
    assert (tmp_path / PATHS[2]).read_text() == "def test_original():\n    assert True\n"
    assert len(runtime.calls) == 2
    planner, envelope = runtime.calls[0]
    system, prompt = build_role_prompts(AgentRole.DEVELOPER, envelope, type(planner), planner.model_dump())
    assert "target planning phase" in system
    assert "Copy every candidate key" not in prompt
    assert REQUIREMENT in prompt


def test_invalid_plan_blocks_authoring_and_all_writes(tmp_path):
    repository = setup_repository(tmp_path)
    runtime = NaturalRuntime(reject=True)
    graph = build_engineering_graph(repository_mcp=repository, model_runtime=runtime)
    patch = graph.nodes["Developer"].invoke({
        "run_id": "natural-invalid", "requirement": REQUIREMENT,
        "repository_context": {"apply_changes": True, "authorized": True},
    })
    assert patch["human_review_required"]
    assert len(runtime.calls) == 1
    assert (tmp_path / PATHS[1]).read_text() == "def valid(name):\n    return True\n"
    assert not (tmp_path / "api/tests/test_validation.py").exists()


def test_no_authorization_never_invokes_target_planner(tmp_path):
    repository = setup_repository(tmp_path)
    runtime = NaturalRuntime()
    graph = build_engineering_graph(repository_mcp=repository, model_runtime=runtime)
    graph.nodes["Developer"].invoke({
        "run_id": "natural-preview", "requirement": REQUIREMENT,
        "repository_context": {"apply_changes": True, "authorized": False},
    })
    assert not any(isinstance(candidate, DeveloperTargetPlan) for candidate, _ in runtime.calls)
    assert not (tmp_path / "api/tests/test_validation.py").exists()


def test_author_cannot_expand_validated_paths_even_when_runtime_returns_them(tmp_path):
    class ScopeExpandingRuntime(NaturalRuntime):
        def invoke_artifact(self, role, envelope, candidate, **kwargs):
            output, info = super().invoke_artifact(role, envelope, candidate, **kwargs)
            if isinstance(output, ImplementationResult) and output.file_contents:
                output = output.model_copy(update={"file_contents": {
                    **output.file_contents, "api/tests/test_original.py": "# overwritten\n",
                }})
            return output, info

    graph = build_engineering_graph(
        repository_mcp=setup_repository(tmp_path), model_runtime=ScopeExpandingRuntime(),
    )
    patch = graph.nodes["Developer"].invoke({
        "run_id": "natural-expand", "requirement": REQUIREMENT,
        "repository_context": {"apply_changes": True, "authorized": True},
    })
    assert patch["human_review_required"]
    assert (tmp_path / PATHS[1]).read_text() == "def valid(name):\n    return True\n"
    assert (tmp_path / PATHS[2]).read_text() == "def test_original():\n    assert True\n"


def test_truncated_inventory_cannot_prove_new_file_absent(tmp_path):
    class TruncatedRepository(RepositoryMCP):
        def list_files(self, role):
            result = super().list_files(role)
            return result.model_copy(update={
                "output_summary": result.output_summary + "\n# truncated: 3 of 3000 paths",
            })

    setup_repository(tmp_path)
    runtime = NaturalRuntime()
    graph = build_engineering_graph(repository_mcp=TruncatedRepository(tmp_path), model_runtime=runtime)
    patch = graph.nodes["Developer"].invoke({
        "run_id": "natural-truncated", "requirement": REQUIREMENT,
        "repository_context": {"apply_changes": True, "authorized": True},
    })
    assert patch["human_review_required"]
    assert len(runtime.calls) == 1
    assert not (tmp_path / "api/tests/test_validation.py").exists()


def test_planner_provider_failure_uses_existing_fallback_and_accounts_both_phases(tmp_path):
    class FailingPlanner(NaturalRuntime):
        def invoke_artifact(self, role, envelope, candidate, **kwargs):
            if isinstance(candidate, DeveloperTargetPlan):
                raise RuntimeError("LLM_AVAILABILITY_ERROR: unavailable")  # noqa: TRY004
            return super().invoke_artifact(role, envelope, candidate, **kwargs)

    fallback = NaturalRuntime()
    graph = build_engineering_graph(
        repository_mcp=setup_repository(tmp_path), model_runtime=FailingPlanner(),
        cloud_runtime=fallback,
    )
    patch = graph.nodes["Developer"].invoke({
        "run_id": "natural-fallback", "requirement": REQUIREMENT,
        "repository_context": {"apply_changes": True, "authorized": True},
    })
    assert patch["implementation"].action_mode is ActionMode.APPLIED
    assert len(fallback.calls) == 1
    assert len(patch["model_usage"]) == 2


def test_planned_source_must_be_read_successfully_before_authoring(tmp_path):
    class DeniedSourceRepository(RepositoryMCP):
        def read_file(self, role, relative):
            result = super().read_file(role, relative)
            if relative == "api/products.py":
                return result.model_copy(update={"status": ToolStatus.DENIED, "output_summary": ""})
            return result

    setup_repository(tmp_path)
    runtime = NaturalRuntime()
    graph = build_engineering_graph(repository_mcp=DeniedSourceRepository(tmp_path), model_runtime=runtime)
    patch = graph.nodes["Developer"].invoke({
        "run_id": "natural-read-denied", "requirement": REQUIREMENT,
        "repository_context": {"apply_changes": True, "authorized": True},
    })
    assert patch["human_review_required"]
    assert len(runtime.calls) == 1
    assert (tmp_path / PATHS[1]).read_text() == "def valid(name):\n    return True\n"


def test_remediation_may_repropose_its_own_test_as_new_and_it_becomes_an_edit():
    """apply-d183c108 and apply-523385f8: in remediation the planner listed the
    test it wrote in the previous iteration under new_files, and the whole plan
    was rejected because that path already existed."""
    paths = [*PATHS, "api/tests/test_validation.py"]
    candidate = plan_candidate(paths, authored={"api/tests/test_validation.py"})
    proposed = proposed_plan(candidate)  # new_files: api/tests/test_validation.py
    writes, reads = validate_target_plan(candidate, proposed, all_paths=set(paths))
    assert writes == ["api/products.py", "api/tests/test_validation.py"]
    assert "api/tests/test_validation.py" in reads


def test_an_original_test_reproposed_as_new_is_still_refused():
    candidate = plan_candidate(PATHS, authored=set())
    proposed = proposed_plan(candidate, new_files=[NewDeveloperFile(
        path="api/tests/test_original.py", kind="test_source", component_root="api",
    )])
    with pytest.raises(ValueError, match="original tests"):
        validate_target_plan(candidate, proposed, all_paths=set(PATHS))


def test_planning_prompt_says_how_to_change_tests_this_run_wrote():
    candidate = plan_candidate([*PATHS, "api/tests/test_validation.py"],
                               authored={"api/tests/test_validation.py"})
    envelope = build_context(AgentRole.DEVELOPER, EngineeringState(run_id="p", requirement=REQUIREMENT), "Developer")
    system, _ = build_role_prompts(AgentRole.DEVELOPER, envelope, type(candidate), candidate.model_dump())
    assert "not in protected_test_paths" in system and "edit_paths" in system


def test_cloud_reports_why_a_target_plan_was_rejected():
    import httpx

    from engineering_team.config import Settings
    from engineering_team.llm.cloud import CloudModelRuntime

    candidate = plan_candidate(PATHS, authored=set())
    rejected = proposed_plan(candidate, edit_paths=["api/tests/test_original.py"])
    settings = Settings(_env_file=None, cloud_enabled=True, mistral_api_key="fixture",
                        cloud_chain_developer="mistral:codestral-latest")
    envelope = build_context(AgentRole.DEVELOPER, EngineeringState(run_id="p", requirement=REQUIREMENT), "Developer")
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={
            "choices": [{"message": {"content": rejected.model_dump_json()}, "finish_reason": "stop"}]}))) as client:
        runtime = CloudModelRuntime(settings, client=client, primary=True)
        with pytest.raises(RuntimeError, match="target plan rejected: target plan attempts to modify original tests"):
            runtime.invoke_artifact(AgentRole.DEVELOPER, envelope, candidate)


def test_a_remediation_that_only_adds_a_test_is_a_valid_plan():
    """spring-demo apply-de2851ce: every test passed and only coverage was missing;
    plans adding a test without touching implementation were rejected as
    "requires bounded distinct implementation edits"."""
    candidate = plan_candidate(PATHS, authored=set())
    proposed = proposed_plan(candidate, edit_paths=[])
    writes, _ = validate_target_plan(candidate, proposed, all_paths=set(PATHS))
    assert writes == ["api/tests/test_validation.py"]


def test_a_plan_that_writes_nothing_is_still_refused():
    candidate = plan_candidate(PATHS, authored=set())
    with pytest.raises(ValueError, match="bounded distinct"):
        validate_target_plan(candidate, proposed_plan(candidate, edit_paths=[], new_files=[]),
                             all_paths=set(PATHS))


def test_a_new_production_source_beside_existing_sources_is_allowed():
    """spring-demo apply-5f7b9e7e: authors referenced InvalidProductNameException,
    a class the plan contract would not let them create, and compilation failed."""
    paths = [*PATHS, "api/errors.py"]
    candidate = plan_candidate(paths, authored=set())
    proposed = proposed_plan(candidate, new_files=[
        NewDeveloperFile(path="api/validation_errors.py", kind="source", component_root="api"),
    ])
    writes, _ = validate_target_plan(candidate, proposed, all_paths=set(paths))
    assert writes == ["api/products.py", "api/validation_errors.py"]


@pytest.mark.parametrize("path", [
    "api/new_dir/invented.py",       # directory holds no inspected source
    "api/tests/test_sneaky.py",      # a test is not a source
    "api/setup.cfg",                 # not a source suffix
    "other/invented.py",             # outside the component
])
def test_new_production_sources_stay_bounded(path):
    candidate = plan_candidate(PATHS, authored=set())
    proposed = proposed_plan(candidate, new_files=[
        NewDeveloperFile(path=path, kind="source", component_root="api"),
    ])
    with pytest.raises(ValueError):
        validate_target_plan(candidate, proposed, all_paths=set(PATHS))


def test_shared_test_fixtures_of_the_component_are_always_read():
    """FlaskApiProduct apply-470d0440: tests/conftest.py has an autouse fixture that
    deletes every category before each test. The author never read it, created data
    in its own fixture, and its tests failed on data the conftest had wiped."""
    paths = [*PATHS, "api/tests/test_other_a.py", "api/tests/test_other_b.py",
             "api/tests/test_other_c.py", "api/tests/conftest.py"]
    candidate = plan_candidate(paths, authored=set())
    _, reads = validate_target_plan(candidate, proposed_plan(candidate), all_paths=set(paths))
    assert "api/tests/conftest.py" in reads
