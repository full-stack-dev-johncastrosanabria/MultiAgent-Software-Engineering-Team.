"""Why a run stopped, decided from typed state instead of from error prose.

Every fixture here is built from `WorkflowError`s and `ModelExecutionInfo`s, not
from message strings: the point of `classify_stop_cause` is that the graph stops
needing to read its own error text back.
"""

import importlib.util
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from engineering_team.contracts.enums import (
    ActionMode,
    AgentRole,
    ErrorCode,
    RemediationCategory,
    ReviewerStatus,
    RouteTarget,
    StopCause,
    ToolStatus,
)
from engineering_team.contracts.models import (
    ImplementationResult,
    ModelExecutionInfo,
    ReviewerDecision,
    ToolResult,
    WorkflowError,
)
from engineering_team.contracts.state import EngineeringState
from engineering_team.graph.routers import classify_stop_cause
from engineering_team.graph.stategraph import build_engineering_graph
from engineering_team.mcp.quality import CompositeQuality, QualityMCP

SUBSCORES = {
    "requirements": 100.0, "architecture": 100.0, "security": 100.0,
    "testing": 100.0, "implementation": 100.0, "rag_grounding": 100.0,
}


def _state(**overrides) -> EngineeringState:
    return EngineeringState(run_id="stop", requirement="bounded change", **overrides)


def _decision(status: ReviewerStatus) -> ReviewerDecision:
    rejected = status is ReviewerStatus.REJECTED
    return ReviewerDecision(
        status=status,
        score=40.0 if rejected else 100.0,
        subscores=dict(SUBSCORES),
        problems=["the endpoint is unvalidated"] if rejected else [],
        reason="rejected" if rejected else "accepted",
        remediation_category=RemediationCategory.IMPLEMENTATION if rejected else None,
        return_to=RouteTarget.DEVELOPER if rejected else None,
        confidence=0.9,
    )


def _applied_implementation() -> ImplementationResult:
    return ImplementationResult(
        action_mode=ActionMode.APPLIED,
        changed_files=["app.py"],
        diff="--- a/app.py\n+++ b/app.py\n+x = 2\n",
        evidence=["read_file(app.py)"],
        validation_result="tests pass",
        file_contents={"app.py": "x = 2\n"},
    )


def _tool(name: str, status: ToolStatus) -> ToolResult:
    return ToolResult(
        tool_name=name, allowed_role=AgentRole.DEVELOPER, status=status,
        input_summary="safe", output_summary="app.py", duration_ms=1,
        error=None if status is ToolStatus.SUCCESS else "disk is read-only",
    )


def _error(code: ErrorCode, detail: str, *, retryable: bool) -> WorkflowError:
    return WorkflowError(
        code=code, source_stage=AgentRole.DEVELOPER.value,
        retryable=retryable, detail=detail,
    )


def _attempt(*, error: str, category: str | None, **extra) -> ModelExecutionInfo:
    return ModelExecutionInfo(
        agent=AgentRole.DEVELOPER, provider="groq", requested_model="m",
        model_profile="CLOUD_FALLBACK", degraded=True, latency_ms=1,
        structured_output_success=False, error=error, error_category=category,
        **extra,
    )


def _produced_an_artifact() -> ModelExecutionInfo:
    """An attempt that worked: what separates one failure from the next."""
    return ModelExecutionInfo(
        agent=AgentRole.DEVELOPER, provider="ollama", requested_model="local",
        actual_model="local", model_profile="LOCAL", degraded=False, latency_ms=1,
        structured_output_success=True, error=None,
    )


class WorkspaceSyncError(RuntimeError):
    """The failure the only two UNAVAILABLE results in the campaign came from."""


class IsolatedEnvironmentDown:
    """The quality MCP a multi-component run gets when its workspace never syncs.

    Built out of the real producers rather than out of a hand-written
    `ToolResult`, because the hand-written shape is the one production almost
    never emits: `QualityMCP._unavailable` writes no marker into the message at
    all, and `CompositeQuality._aggregate` then relabels every component's error
    with its evidence reference. `apply_run` always wraps the backends in
    `CompositeQuality`, so this pair is what actually reached the graph in
    flaskapiproduct-dry-20260916k, the one run in
    `evaluation/benchmarks/ghcycle/results/raw/` that has UNAVAILABLE results:

        mcp://quality/scan_dependencies#client: isolated environment
        unavailable: WorkspaceSyncError: workspace transfer container failed
    """

    def __init__(self, root: Path) -> None:
        self._components = [
            QualityMCP(root / name, workspace_root=root, component=name)
            for name in ("client", "server")
        ]

    def run_tests(self, role, paths=None) -> ToolResult:
        failure = WorkspaceSyncError("workspace transfer container failed")
        results = [
            component._unavailable(role, "run_tests", failure, time.perf_counter())
            for component in self._components
        ]
        return CompositeQuality._aggregate("run_tests", role, results)


class SuiteRanPastItsDeadline:
    """The quality MCP a run gets when the suite it launched never finished.

    Built out of the real producer, like `IsolatedEnvironmentDown`: the
    `subprocess.TimeoutExpired` below is exactly what `ContainerRunner.
    _run_container` raises when the suite command itself outlives its deadline,
    and `QualityMCP._run` is where it lands. The container came up and the code
    under test ran -- it hung, or was slow -- so a patch that deadlocks its own
    suite is a product failure, not an environment that never came up.
    """

    def __init__(self, root: Path) -> None:
        self._backend = QualityMCP(root)

    def run_tests(self, role, paths=None) -> ToolResult:
        def _suite_outlived_its_deadline(args, **_kwargs):
            raise subprocess.TimeoutExpired(list(args), 0.01)

        self._backend._execute_process = _suite_outlived_its_deadline
        return self._backend._run(
            role, "run_tests", ["pytest"], {AgentRole.TESTING},
            time.monotonic() + 1, cwd=self._backend.root,
        )


def _load_run_cycle():
    """The ghcycle scorer, imported by path as `test_ghcycle_scoring.py` does."""
    path = (
        Path(__file__).resolve().parents[2]
        / "evaluation" / "benchmarks" / "ghcycle" / "run_cycle.py"
    )
    spec = importlib.util.spec_from_file_location("run_cycle_for_stop_cause", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_an_approved_review_that_never_raised_the_flag_is_approved() -> None:
    state = _state(review=_decision(ReviewerStatus.APPROVED), iteration=1)

    assert classify_stop_cause(state, max_iterations=3) is StopCause.APPROVED


def test_exhausting_the_remediation_budget_is_the_iteration_limit() -> None:
    state = _state(review=_decision(ReviewerStatus.REJECTED), iteration=3)

    assert classify_stop_cause(state, max_iterations=3) is StopCause.ITERATION_LIMIT


def test_repeating_one_failure_class_or_one_diff_is_stagnation() -> None:
    repeated = _state(
        review=_decision(ReviewerStatus.REJECTED), iteration=1,
        failure_fingerprints=["aa", "aa", "aa"],
    )
    unchanged = _state(
        review=_decision(ReviewerStatus.REJECTED), iteration=1,
        failure_fingerprints=["aa", "bb", "aa"],
        applied_diff_fingerprints=["cc", "dd", "cc"],
    )

    assert classify_stop_cause(repeated, max_iterations=5) is StopCause.STAGNATION
    assert classify_stop_cause(unchanged, max_iterations=5) is StopCause.STAGNATION


def test_a_rejection_with_no_usable_route_outranks_the_stagnation_it_also_shows() -> None:
    """`review_route` refuses a self-contradicting rejection before it reads
    stagnation, so a run holding both was stopped by the contradiction. Naming
    it stagnation would send the reader looking for a loop that never ran.
    """
    contradictory = _decision(ReviewerStatus.REJECTED).model_copy(
        update={"return_to": RouteTarget.TESTING}
    )
    state = _state(
        review=contradictory, iteration=1, failure_fingerprints=["aa", "aa", "aa"]
    )

    cause = classify_stop_cause(state, max_iterations=5)

    assert cause is StopCause.UNKNOWN
    assert cause is not StopCause.STAGNATION


def test_a_critical_security_stop_reaches_the_node_before_any_review_exists() -> None:
    """`security_hitl` stops with no reviewer decision at all.

    Nothing in this vocabulary names a critical finding yet, and the earlier
    branches must not claim the run ran out of budget just because it has none.
    """
    state = _state(iteration=0, failure_fingerprints=[], review=None)

    assert classify_stop_cause(state, max_iterations=1) is StopCause.UNKNOWN


def test_an_unavailable_mcp_server_is_named_as_unavailable() -> None:
    state = _state(
        human_review_required=True,
        errors=[_error(ErrorCode.MCP_ERROR, "read_file: UNAVAILABLE", retryable=False)],
    )

    assert classify_stop_cause(state, max_iterations=3) is StopCause.MCP_UNAVAILABLE


def test_a_blocked_destructive_change_is_not_reported_as_a_failed_write() -> None:
    # The guardrail refuses before the write loop, so the run ends holding
    # applied file contents that no write tool ever saw.
    state = _state(
        human_review_required=True,
        implementation=_applied_implementation(),
        tool_results=[_tool("read_file", ToolStatus.SUCCESS)],
        errors=[_error(
            ErrorCode.TOOL_ERROR,
            "destructive operation requires explicit authorization",
            retryable=False,
        )],
    )

    cause = classify_stop_cause(state, max_iterations=3)

    assert cause is StopCause.DESTRUCTIVE_AUTHORIZATION_BLOCKED
    assert cause is not StopCause.WRITE_FAILED


def test_a_write_tool_that_ran_and_failed_is_a_write_failure() -> None:
    state = _state(
        human_review_required=True,
        implementation=_applied_implementation(),
        tool_results=[
            _tool("update_file", ToolStatus.FAIL),
            _tool("get_diff", ToolStatus.SUCCESS),
        ],
        errors=[_error(
            ErrorCode.TOOL_ERROR, "update_file: disk is read-only", retryable=False
        )],
    )

    assert classify_stop_cause(state, max_iterations=3) is StopCause.WRITE_FAILED


def test_a_rejected_developer_target_plan_is_a_quality_rejection() -> None:
    state = _state(
        human_review_required=True,
        errors=[_error(
            ErrorCode.LLM_QUALITY_ERROR,
            "Developer target plan rejected: a path outside the inventory",
            retryable=False,
        )],
    )

    assert classify_stop_cause(state, max_iterations=3) is StopCause.LLM_QUALITY_REJECTED


def test_a_governed_contradiction_is_a_quality_rejection_not_an_exhausted_chain() -> None:
    """A-09 as a test: the provider answered, the answer was refused.

    The local model contradicted governed facts and the cloud chain then ran out
    of links. The last error says CLOUD_FALLBACK_UNAVAILABLE either way; what
    separates the two is that the graph copies the local failure's retryability
    onto it, and only a quality failure is unretryable.
    """
    state = _state(
        human_review_required=True,
        errors=[
            _error(
                ErrorCode.LLM_QUALITY_ERROR,
                "LLM_QUALITY_ERROR: governed artifact contradiction",
                retryable=True,
            ),
            _error(
                ErrorCode.CLOUD_FALLBACK_UNAVAILABLE,
                "CLOUD_FALLBACK_UNAVAILABLE: rate_limit (provider error 429)",
                retryable=False,
            ),
        ],
        model_usage=[
            _attempt(error="LLM_QUALITY_ERROR: governed contradiction", category=None),
            _attempt(
                error="CLOUD_FALLBACK_UNAVAILABLE: rate_limit (provider error 429)",
                category="rate_limit",
            ),
        ],
    )

    cause = classify_stop_cause(state, max_iterations=3)

    assert cause is StopCause.LLM_QUALITY_REJECTED
    assert cause is not StopCause.PROVIDER_CHAIN_EXHAUSTED


def test_a_cloud_side_governed_contradiction_is_also_a_quality_rejection() -> None:
    """A-09 again, from the other direction.

    Here the local model was merely unreachable, so the error's retryability
    says nothing; the cloud link is the one that refused the content, and the
    attempt it recorded is the only place that fact survives typed.
    """
    state = _state(
        human_review_required=True,
        errors=[
            _error(
                ErrorCode.LLM_AVAILABILITY_ERROR,
                "LLM_AVAILABILITY_ERROR: ConnectError", retryable=True,
            ),
            _error(
                ErrorCode.CLOUD_FALLBACK_UNAVAILABLE,
                "CLOUD_FALLBACK_UNAVAILABLE: governed fields differ: objective",
                retryable=True,
            ),
        ],
        model_usage=[
            _attempt(error="LLM_AVAILABILITY_ERROR: ConnectError", category=None),
            _attempt(
                error="CLOUD_FALLBACK_UNAVAILABLE: governed fields differ: objective",
                category="governed_contradiction",
                governed_fields_diff=["objective"],
            ),
        ],
    )

    cause = classify_stop_cause(state, max_iterations=3)

    assert cause is StopCause.LLM_QUALITY_REJECTED
    assert cause is not StopCause.PROVIDER_CHAIN_EXHAUSTED


def test_a_cloud_first_refusal_survives_an_ordinary_local_outage_on_top_of_it() -> None:
    """A-09 in the configuration that hid it: `cloud_first`.

    `apply_run` hands the cloud in as the primary runtime and the local model as
    the secondary, so the refusal is recorded first and a plain local outage --
    which records no category, because the local runtime never stamps one -- is
    recorded after it. The refusal also arrives mislabelled: `cloud.py` raises a
    governed contradiction as CLOUD_FALLBACK_UNAVAILABLE, and the graph
    classifies that message by prefix, so it is filed as LLM_AVAILABILITY_ERROR.
    Reading only the newest attempt made the verdict depend on the bookkeeping of
    the runtime that was not at fault.
    """
    state = _state(
        human_review_required=True,
        errors=[
            _error(
                ErrorCode.LLM_AVAILABILITY_ERROR,
                "CLOUD_FALLBACK_UNAVAILABLE: governed fields differ: objective",
                retryable=True,
            ),
            _error(
                ErrorCode.CLOUD_FALLBACK_UNAVAILABLE,
                "LLM_AVAILABILITY_ERROR: ConnectError", retryable=True,
            ),
        ],
        model_usage=[
            _attempt(
                error="CLOUD_FALLBACK_UNAVAILABLE: governed fields differ: objective",
                category="governed_contradiction",
                governed_fields_diff=["objective"],
            ),
            _attempt(error="LLM_AVAILABILITY_ERROR: ConnectError", category=None),
        ],
    )

    cause = classify_stop_cause(state, max_iterations=3)

    assert cause is StopCause.LLM_QUALITY_REJECTED
    assert cause is not StopCause.PROVIDER_CHAIN_EXHAUSTED


def test_a_cloud_first_refusal_with_no_local_behind_it_is_still_a_refusal() -> None:
    """The same stop with no secondary configured.

    Nothing follows the refusal, so the last error keeps the availability code
    the prefix check gave it. Trusting that code alone reported a run we stopped
    on our own terms as a provider that fell over.
    """
    state = _state(
        human_review_required=True,
        errors=[_error(
            ErrorCode.LLM_AVAILABILITY_ERROR,
            "CLOUD_FALLBACK_UNAVAILABLE: target plan rejected: path outside inventory",
            retryable=True,
        )],
        model_usage=[
            _attempt(
                error="CLOUD_FALLBACK_UNAVAILABLE: target plan rejected",
                category="governed_contradiction",
                violated_rule="path outside inventory",
            ),
        ],
    )

    assert classify_stop_cause(state, max_iterations=3) is StopCause.LLM_QUALITY_REJECTED


def test_a_refusal_a_later_retry_recovered_from_does_not_colour_a_real_outage() -> None:
    """The widened search is scoped to the failure that ended the run.

    An earlier cycle was refused and then succeeded; the run died later, of an
    outage. Counting that spent rejection would be the mirror of A-09 -- a
    provider outage filed as our own refusal -- so the attempt that produced an
    artifact closes the failure before it.
    """
    state = _state(
        human_review_required=True,
        errors=[_error(
            ErrorCode.LLM_AVAILABILITY_ERROR, "LLM_AVAILABILITY_ERROR: ConnectError",
            retryable=True,
        )],
        model_usage=[
            _attempt(
                error="CLOUD_FALLBACK_UNAVAILABLE: governed fields differ: objective",
                category="governed_contradiction",
                governed_fields_diff=["objective"],
            ),
            _produced_an_artifact(),
            _attempt(error="LLM_AVAILABILITY_ERROR: ConnectError", category=None),
        ],
    )

    assert (
        classify_stop_cause(state, max_iterations=3) is StopCause.PROVIDER_CHAIN_EXHAUSTED
    )


def test_an_unavailable_server_that_is_not_infrastructure_stays_an_mcp_outage() -> None:
    state = _state(
        human_review_required=True,
        errors=[_error(
            ErrorCode.MCP_ERROR, "read_file: repository server did not answer",
            retryable=False,
        )],
    )

    assert classify_stop_cause(state, max_iterations=3) is StopCause.MCP_UNAVAILABLE


def test_one_refused_link_outranks_every_genuine_outage_beside_it() -> None:
    """The declared policy, fixed so it cannot erode into a regression.

    Three links of this chain were really unreachable and one refused what we
    asked it to write. The stop is the refusal, and deliberately so: an outage is
    repaired by waiting or by changing provider, a refusal is not, so reporting
    the majority would send the reader to the wrong repair. Changing this
    assertion means deciding the policy again, which is the point of writing it
    down as a test rather than only as a comment.
    """
    state = _state(
        human_review_required=True,
        errors=[_error(
            ErrorCode.CLOUD_FALLBACK_UNAVAILABLE,
            "CLOUD_FALLBACK_UNAVAILABLE: timeout (provider error 504)", retryable=True,
        )],
        model_usage=[
            _attempt(error="rate_limit (provider error 429)", category="rate_limit"),
            _attempt(
                error="governed fields differ: objective",
                category="governed_contradiction", governed_fields_diff=["objective"],
            ),
            _attempt(error="server_error (provider error 503)", category="server_error"),
            _attempt(error="timeout (provider error 504)", category="timeout"),
        ],
    )

    assert classify_stop_cause(state, max_iterations=3) is StopCause.LLM_QUALITY_REJECTED


def test_a_rate_limited_chain_really_is_an_exhausted_provider_chain() -> None:
    state = _state(
        human_review_required=True,
        errors=[
            _error(
                ErrorCode.LLM_AVAILABILITY_ERROR,
                "LLM_AVAILABILITY_ERROR: ConnectError", retryable=True,
            ),
            _error(
                ErrorCode.CLOUD_FALLBACK_UNAVAILABLE,
                "CLOUD_FALLBACK_UNAVAILABLE: rate_limit (provider error 429)",
                retryable=True,
            ),
        ],
        model_usage=[
            _attempt(
                error="CLOUD_FALLBACK_UNAVAILABLE: rate_limit (provider error 429)",
                category="rate_limit",
            ),
        ],
    )

    assert (
        classify_stop_cause(state, max_iterations=3) is StopCause.PROVIDER_CHAIN_EXHAUSTED
    )


def test_a_timed_out_model_with_no_cloud_chain_is_an_exhausted_provider_chain() -> None:
    state = _state(
        human_review_required=True,
        errors=[_error(ErrorCode.AGENT_TIMEOUT, "AGENT_TIMEOUT: ReadTimeout", retryable=True)],
    )

    assert (
        classify_stop_cause(state, max_iterations=3) is StopCause.PROVIDER_CHAIN_EXHAUSTED
    )


def test_a_stop_with_no_recorded_evidence_is_unknown_rather_than_guessed() -> None:
    state = _state(human_review_required=True)

    assert classify_stop_cause(state, max_iterations=3) is StopCause.UNKNOWN


class PassingQuality:
    """A green suite: the Reviewer's evidence gate rejects any run without one."""

    def run_tests(self, role, paths=None):
        return ToolResult(
            tool_name="run_tests", allowed_role=role, status=ToolStatus.SUCCESS,
            input_summary="safe", output_summary="1 passed", duration_ms=1,
        )


class UnreachableLocalRuntime:
    def __init__(self) -> None:
        self.attempts: list[ModelExecutionInfo] = []

    def invoke_artifact(self, role, envelope, candidate, *, fallback_reason=None):
        info = ModelExecutionInfo(
            agent=role, provider="ollama", requested_model="local", actual_model=None,
            model_profile="LOCAL", degraded=True, latency_ms=1,
            structured_output_success=False, error="LLM_AVAILABILITY_ERROR: ConnectError",
        )
        self.attempts.append(info)
        raise RuntimeError(info.error)


class RateLimitedCloudRuntime:
    def __init__(self) -> None:
        self.attempts: list[ModelExecutionInfo] = []

    def invoke_artifact(self, role, envelope, candidate, *, fallback_reason):
        info = ModelExecutionInfo(
            agent=role, provider="groq", requested_model="cloud", actual_model=None,
            model_profile="CLOUD_FALLBACK", fallback_used=True,
            fallback_reason=fallback_reason, degraded=True, latency_ms=1,
            structured_output_success=False,
            error="CLOUD_FALLBACK_UNAVAILABLE: rate_limit (provider error 429)",
            error_category="rate_limit", retryable=True,
        )
        self.attempts.append(info)
        raise RuntimeError(info.error)


@pytest.fixture
def exhausted_chain_state() -> dict:
    return build_engineering_graph(
        model_runtime=UnreachableLocalRuntime(),
        cloud_runtime=RateLimitedCloudRuntime(),
    ).invoke({"run_id": "exhausted", "requirement": "safe bounded change"})


def test_an_exhausted_chain_carries_its_cause_out_of_the_graph(
    exhausted_chain_state,
) -> None:
    state = exhausted_chain_state

    assert state["final_status"] == "HUMAN_REVIEW_REQUIRED"
    assert state["final_report"].status == "HUMAN_REVIEW_REQUIRED"
    assert state["stop_cause"] == StopCause.PROVIDER_CHAIN_EXHAUSTED.value


def test_an_exhausted_chain_carries_its_cause_into_the_evidence(
    exhausted_chain_state, tmp_path, monkeypatch
) -> None:
    from engineering_team.apply_run import run_on_project
    from engineering_team.config import Settings

    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(
        "engineering_team.apply_run.execute_on_project",
        lambda *a, **k: (
            exhausted_chain_state,
            SimpleNamespace(trace_id="trace-stop", live=False),
            0.01,
            False,
        ),
    )

    evidence = run_on_project(
        Settings(delivery_backend="none"),
        project_path=project,
        specification="add endpoint",
    )

    assert evidence["final_status"] == "HUMAN_REVIEW_REQUIRED"
    assert evidence["stop_cause"] == StopCause.PROVIDER_CHAIN_EXHAUSTED.value
    assert evidence["destructive_authorization_blocked"] is False


def test_the_blocked_write_flag_is_derived_from_the_cause_not_matched_on_text(
    tmp_path, monkeypatch
) -> None:
    """One fact, one vocabulary.

    The evidence dict recomputed this by searching an error detail for the words
    "destructive operation", one key after recording the typed cause. The state
    below carries the cause and no such wording anywhere, so the flag can only be
    true if it was derived rather than matched.
    """
    from engineering_team.apply_run import run_on_project
    from engineering_team.config import Settings

    project = tmp_path / "project"
    project.mkdir()
    blocked = {
        "run_id": "blocked",
        "final_status": "HUMAN_REVIEW_REQUIRED",
        "stop_cause": StopCause.DESTRUCTIVE_AUTHORIZATION_BLOCKED.value,
        "implementation": _applied_implementation(),
        "errors": [_error(
            ErrorCode.TOOL_ERROR,
            "the guardrail refused an unauthorised write",
            retryable=False,
        )],
    }
    monkeypatch.setattr(
        "engineering_team.apply_run.execute_on_project",
        lambda *a, **k: (blocked, SimpleNamespace(trace_id="t", live=False), 0.01, False),
    )

    evidence = run_on_project(
        Settings(delivery_backend="none"),
        project_path=project,
        specification="add endpoint",
    )

    assert not any("destructive operation" in item for item in evidence["errors"])
    assert evidence["destructive_authorization_blocked"] is True


def test_a_workspace_that_never_synchronised_is_not_filed_against_the_mcp_layer(
    tmp_path,
) -> None:
    """The real shape, through the real producers, end to end.

    Two component results from `QualityMCP._unavailable`, merged by
    `CompositeQuality._aggregate`, classified by `preserve_tool_result` and named
    by `classify_stop_cause`. Nothing here is hand-shaped, which matters: the
    message that comes out carries no marker a reader could match on, so the
    typed code is the only thing that survives the trip. The environment failed;
    the MCP server answered every call it was given.
    """
    state = build_engineering_graph(
        quality_mcp=IsolatedEnvironmentDown(tmp_path)
    ).invoke({"run_id": "workspace", "requirement": "safe bounded change"})

    blocking = next(
        item for item in state["tool_results"] if item.status is ToolStatus.UNAVAILABLE
    )

    assert blocking.error.startswith("mcp://quality/run_tests#client:")
    assert ErrorCode.INFRASTRUCTURE_ERROR.value not in blocking.error
    assert blocking.error_code is ErrorCode.INFRASTRUCTURE_ERROR
    assert state["errors"][-1].code is ErrorCode.INFRASTRUCTURE_ERROR
    assert state["final_status"] == "HUMAN_REVIEW_REQUIRED"
    assert state["stop_cause"] == StopCause.INFRASTRUCTURE_UNAVAILABLE.value


def test_a_suite_that_outlived_its_deadline_is_not_filed_as_an_environment_failure(
    tmp_path,
) -> None:
    """B-11 inverted is still B-11: a hung suite must not read as infrastructure.

    End to end through the real producer (`QualityMCP._run`), the real graph
    (`preserve_tool_result`, `classify_stop_cause`), the real receipt
    (`apply_run.tool_outcomes`) and the real scorer
    (`run_cycle._classify_environment_failure`). The run stops on the
    UNAVAILABLE result as before; what changes is that nothing along the way
    calls it an environment failure. It falls back to `MCP_ERROR` /
    `mcp_unavailable`, the label it carried before phase 1, which the scorer
    does not count as environment. A suite timeout still needs a typed cause of
    its own (phase 2).
    """
    from engineering_team.apply_run import tool_outcomes

    state = build_engineering_graph(
        quality_mcp=SuiteRanPastItsDeadline(tmp_path)
    ).invoke({"run_id": "hung-suite", "requirement": "safe bounded change"})

    blocking = next(
        item for item in state["tool_results"] if item.status is ToolStatus.UNAVAILABLE
    )
    assert blocking.error_code is None
    assert state["errors"][-1].code is ErrorCode.MCP_ERROR
    assert state["stop_cause"] == StopCause.MCP_UNAVAILABLE.value

    evidence = {
        "stop_cause": state["stop_cause"],
        "tool_outcomes": tool_outcomes(state["tool_results"]),
    }
    assert _load_run_cycle()._classify_environment_failure(evidence) is None


def test_an_approved_run_names_its_cause_too_instead_of_leaving_it_empty() -> None:
    """An approved run never passes through `human_node`.

    If only that node named the cause, `stop_cause` would be absent from exactly
    the runs that went well, and a reader would be back to inferring the outcome
    from a second field -- the habit this whole change removes.
    """
    state = build_engineering_graph(quality_mcp=PassingQuality()).invoke(
        {"run_id": "approved", "requirement": "safe bounded change"}
    )

    assert state["final_status"] == "APPROVED"
    assert state["stop_cause"] == StopCause.APPROVED.value
