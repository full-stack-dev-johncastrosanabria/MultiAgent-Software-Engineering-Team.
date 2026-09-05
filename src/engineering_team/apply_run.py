"""Run the full engineering workflow directly against a real, external project.

Unlike ``observability.evaluation.run_multimodel_acceptance`` (which always
works against an isolated copy of the bundled ``sample_app``), this module
points Repository/Quality MCP at a caller-supplied project path. When the
Reviewer approves and ``authorize_writes=True``, the Developer's LLM-authored
file content is written for real via ``create_file``/``update_file`` — see
``ImplementationResult.file_contents`` and the write block in
``graph.stategraph.build_engineering_graph``.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from contextlib import ExitStack
from pathlib import Path
from typing import Any

from engineering_team.components import Component, components_in
from engineering_team.config import Settings
from engineering_team.contracts.enums import ErrorCode, ReviewerStatus
from engineering_team.delivery import (
    BRANCH_NAMESPACE,
    DeliveryRefused,
    GitDelivery,
    Proposal,
    build_delivery,
)
from engineering_team.graph.stategraph import build_engineering_graph
from engineering_team.llm.cloud import CloudModelRuntime
from engineering_team.llm.runtime import LocalModelRuntime
from engineering_team.mcp.client import MCPQualityClient, MCPRepositoryClient
from engineering_team.observability.langfuse import LangfuseTracer
from engineering_team.rag import build_retriever
from engineering_team.run_events import EventForwardingTrace
from engineering_team.testing_evidence import passing_tests


def quality_selection_is_explicit(settings: Settings) -> bool:
    """Whether the caller named a stack or component path.

    Defaults are not a choice: ``Settings.quality_stack`` is ``"python"`` so that
    callers that predate profiles keep working, and so an explicit
    ``QUALITY_STACK=python`` (Flask) stays distinct from "not set, detect".
    """
    return (
        "quality_stack" in settings.model_fields_set
        or "quality_component_path" in settings.model_fields_set
    )


def quality_targets_for(settings: Settings, project_root: Path) -> list[Component]:
    """Which components this apply run will exercise.

    Explicit settings yield one synthetic target. Otherwise every detected
    component is a target. An empty tree keeps the historical Python default so
    callers without a manifest are unchanged. Unknown stacks fail closed through
    ``profile_for`` — never a silent pytest fallback.
    """
    from engineering_team.stacks import profile_for

    if quality_selection_is_explicit(settings):
        stack = settings.quality_stack or "python"
        profile_for(stack)
        return [
            Component(
                path=settings.quality_component_path or "",
                stack=stack,
                manifest="",
            )
        ]
    found = components_in(project_root)
    if not found:
        profile_for("python")
        return [Component(path="", stack="python", manifest="")]
    for component in found:
        profile_for(component.stack)
    return found


def open_project_quality(
    project_root: Path,
    settings: Settings,
    *,
    timeout_seconds: float,
    runner: Any | None = None,
) -> Any:
    """Quality handle for an apply run: one MCP client, or a per-component fan-out.

    A single target keeps the existing MCP ``--stack`` / ``--component-root``
    path (Flask's one-python-component process included). Multiple targets open
    one ``QualityMCP`` per component behind ``CompositeQuality`` so each profile
    runs its own commands. An injected ``runner`` is for tests that spy on argv.
    """
    from engineering_team.mcp.quality import CompositeQuality, QualityMCP
    from engineering_team.stacks import profile_for

    targets = quality_targets_for(settings, project_root)
    container_run = settings.quality_runner == "container" and runner is None
    if container_run:
        return _ProjectInfrastructureQuality(project_root, settings, targets, timeout_seconds)
    if len(targets) == 1 and runner is None:
        component = targets[0]
        adjusted = settings.model_copy(
            update={
                "quality_stack": component.stack,
                "quality_component_path": component.path,
            }
        )
        return MCPQualityClient(
            project_root, timeout_seconds=timeout_seconds, settings=adjusted
        )

    backends: list[Any] = []
    multi = len(targets) > 1
    for component in targets:
        component_root = (
            project_root / component.path if component.path else project_root
        )
        label = component.path or ("." if multi else "")
        child_settings = settings.model_copy(
            update={
                "quality_stack": component.stack,
                "quality_component_path": component.path,
            }
        )
        backends.append(
            QualityMCP(
                component_root,
                timeout_seconds=timeout_seconds,
                runner=runner,
                settings=child_settings,
                profile=profile_for(component.stack),
                component=label,
            )
        )
    if len(backends) == 1:
        backend = backends[0]

        class _SingleQuality:
            """Context-manager adapter around a direct QualityMCP backend."""

            transport = "direct-backend"

            def __enter__(self):
                return backend

            def __exit__(self, exc_type, exc, traceback) -> None:
                backend.close()

            def __getattr__(self, name: str):
                return getattr(backend, name)

        return _SingleQuality()
    return CompositeQuality(backends)


class _ProjectInfrastructureQuality:
    """Own infrastructure once, outside the lifetime of individual components."""

    transport = "direct-backend"

    def __init__(self, root, settings, targets, timeout_seconds):
        self.root = root
        self.settings = settings
        self.targets = targets
        self.timeout_seconds = timeout_seconds
        self.services = None
        self.backends = []
        self.quality = None
        self._closed = False

    def __enter__(self):
        from engineering_team.mcp.quality import CompositeQuality, QualityMCP
        from engineering_team.services import ServiceStack, ServiceStartupError
        from engineering_team.stacks import profile_for

        try:
            self.services = ServiceStack(self.root, str(uuid.uuid4()))
            self.services.up(time.monotonic() + self.timeout_seconds)
            for component in self.targets:
                component_root = self.root / component.path
                child_settings = self.settings.model_copy(update={
                    "quality_stack": component.stack,
                    "quality_component_path": component.path,
                })
                backend = QualityMCP(
                    component_root,
                    timeout_seconds=self.timeout_seconds,
                    settings=child_settings,
                    profile=profile_for(component.stack),
                    component=component.path or ("." if len(self.targets) > 1 else ""),
                    services=self.services,
                )
                self.backends.append(backend)
                backend._services_started = True
                backend._runner.network = self.services.network
                backend._runner.networks = getattr(
                    self.services,
                    "networks",
                    (self.services.network,) if self.services.network else (),
                )
                backend.service_environment = self.services.environment_for_component(
                    component.stack, component_root
                )
            self.quality = (
                self.backends[0] if len(self.backends) == 1 else CompositeQuality(self.backends)
            )
            return self.quality
        except Exception as exc:
            self.close()
            raise ServiceStartupError(f"INFRASTRUCTURE_ERROR: {exc}") from exc

    def close(self):
        if self._closed:
            return
        self._closed = True
        with ExitStack() as cleanup:
            if self.services is not None:
                cleanup.callback(self.services.down)
            for backend in self.backends:
                cleanup.callback(backend.close)

    def __exit__(self, exc_type, exc, traceback):
        self.close()


def execute_on_project(
    settings: Settings,
    *,
    project_path: str | Path,
    specification: str,
    test_specification: str | None = None,
    authorize_writes: bool = False,
    test_paths: list[str] | None = None,
    run_id: str | None = None,
    event_observer: Callable[[dict[str, Any]], None] | None = None,
    on_trace_started: Callable[[str], None] | None = None,
) -> tuple[dict[str, Any], Any, float, bool]:
    """Execute the one production LangGraph and return its real terminal state."""
    project_root = Path(project_path).resolve()
    if not project_root.is_dir():
        raise ValueError(f"project path does not exist or is not a directory: {project_root}")

    requirement = specification.strip()
    if test_specification and test_specification.strip():
        requirement = f"{requirement}\n\nTest specification: {test_specification.strip()}"

    run_id = run_id or f"apply-{uuid.uuid4()}"
    trace_session = LangfuseTracer(
        public_key=settings.langfuse_public_key,
        secret_key=(
            settings.langfuse_secret_key.get_secret_value()
            if settings.langfuse_secret_key else None
        ),
        base_url=settings.langfuse_base_url,
        offline_directory="evaluation/reports/traces",
    ).start_run(run_id, requirement)
    if on_trace_started is not None:
        # Publish the real trace id at the start of execution, not at the end, so a
        # run in flight can already be cited by it.
        on_trace_started(trace_session.trace_id)
    trace = (
        EventForwardingTrace(trace_session, event_observer)
        if event_observer is not None else trace_session
    )

    cloud_first = bool(settings.cloud_enabled and not settings.local_first)
    if cloud_first:
        primary_runtime: Any = CloudModelRuntime(settings, trace=trace, primary=True)
        secondary_runtime: Any | None = LocalModelRuntime(settings, trace=trace)
    else:
        primary_runtime = LocalModelRuntime(settings, trace=trace)
        secondary_runtime = CloudModelRuntime(settings, trace=trace) if settings.cloud_enabled else None

    retriever = build_retriever(settings, settings.rag_persist_directory, reindex=True)
    # An apply run must execute the project's complete default suite unless the
    # caller explicitly narrows it. Selecting paths from the Developer's output
    # made deleting pre-existing tests invisible to the regression gate.
    resolved_test_paths = test_paths

    started = time.perf_counter()
    with (
        MCPRepositoryClient(project_root, timeout_seconds=120) as repository_mcp,
        open_project_quality(
            project_root,
            settings,
            timeout_seconds=settings.quality_timeout_seconds,
        ) as quality_mcp,
    ):
        graph = build_engineering_graph(
            repository_mcp=repository_mcp,
            quality_mcp=quality_mcp,
            retriever=retriever,
            model_runtime=primary_runtime,
            cloud_runtime=secondary_runtime,
            trace=trace,
            test_paths=resolved_test_paths,
            model_stage_retries=settings.max_model_stage_retries,
            max_remediation_iterations=settings.max_remediation_iterations,
        )
        # Before anything is written, record what already passes. A failure and
        # a break are different news, and after the first write there is no way
        # left to tell them apart.
        baseline = baseline_tests(quality_mcp)
        state: dict[str, Any] | None = None
        for streamed_state in graph.stream({
            "run_id": run_id,
            "requirement": requirement,
            "repository_context": {
                "apply_changes": True,
                "authorized": authorize_writes,
                "project_path": str(project_root),
            },
            "baseline_tests": list(baseline),
        }, stream_mode="values"):
            state = streamed_state
        if state is None:
            raise RuntimeError("workflow completed without a terminal state")
    duration = time.perf_counter() - started
    return state, trace, duration, cloud_first



def _baseline_extra(quality_mcp: Any) -> list[str] | None:
    """`-v` is a pytest flag. Non-Python profiles must not receive it."""
    profile = getattr(quality_mcp, "profile", None)
    if profile is not None:
        return ["-v"] if profile.name == "python" else None
    if getattr(quality_mcp, "_backends", None):
        return ["-v"]
    settings = getattr(quality_mcp, "settings", None)
    stack = getattr(settings, "quality_stack", None)
    if stack and stack != "python":
        return None
    return ["-v"]


def baseline_tests(quality_mcp: Any) -> tuple[str, ...]:
    """Which tests pass on the untouched project.

    Asked once, before the first write, and never treated as required: a project
    whose suite cannot run yields no baseline, and no baseline means nothing is
    later called a regression. Claiming otherwise would send the Developer after
    a break that never happened.
    """
    from engineering_team.contracts.enums import AgentRole

    try:
        result = quality_mcp.run_tests(AgentRole.TESTING, _baseline_extra(quality_mcp))
    except (OSError, RuntimeError, TimeoutError, ValueError):
        # A baseline is a convenience, never a precondition: a project whose
        # suite will not start simply has no past to compare against.
        return ()
    results = list(getattr(quality_mcp, "last_component_results", None) or [result])
    identifiers: list[str] = []
    for item in results:
        identifiers.extend(passing_tests(getattr(item, "output_summary", "") or ""))
    return tuple(dict.fromkeys(identifiers))



def _delivery_branch_for(run_id: str) -> str:
    """Sanitize run_id into an aset/ branch matching `_BRANCH` in delivery."""
    import re

    raw = re.sub(r"[^a-z0-9._-]+", "-", run_id.lower()).strip("-._")
    if not raw or not raw[0].isalnum():
        raw = f"r{raw}"
    # aset/ + [a-z0-9][a-z0-9._-]{0,80} → at most 81 chars after the prefix
    return f"{BRANCH_NAMESPACE}{raw[:81]}"


def _proposal_from_implementation(
    *,
    project_root: Path,
    run_id: str,
    implementation: Any,
    review: Any,
    written_paths: list[str] | None = None,
) -> Proposal | None:
    """Build a delivery Proposal from APPROVED written file contents.

    Prefer successfully written / changed paths that have `file_contents`.
    Content prefers on-disk bytes at `project_root` when the path exists
    (post-write truth); otherwise use `file_contents`. Paths present on disk
    go in `updates` (full replace); absent paths go in `files` (create-only).
    """
    contents = dict(getattr(implementation, "file_contents", None) or {})
    if not contents:
        return None
    changed = list(getattr(implementation, "changed_files", None) or [])
    preferred: list[str] = []
    for source in (written_paths or [], changed, list(contents)):
        for path in source:
            if path in contents and path not in preferred:
                preferred.append(path)
    if not preferred:
        preferred = list(contents)
    files: dict[str, str] = {}
    updates: dict[str, str] = {}
    for relative in preferred:
        disk = project_root / relative
        if disk.is_file():
            # Prefer what was actually written to the workspace.
            body = disk.read_text(encoding="utf-8")
            updates[relative] = body
        else:
            files[relative] = contents[relative]
    if not files and not updates:
        return None
    listed = sorted({*files, *updates})
    title = f"ASET approved changes ({run_id})"
    body_lines = [
        "Reviewer-APPROVED implementation written by ASET.",
        "",
        "Changed paths:",
        *(f"- `{path}`" for path in listed),
    ]
    if review is not None and getattr(review, "reason", None):
        body_lines.extend(["", f"Reviewer: {review.reason}"])
    return Proposal(
        branch=_delivery_branch_for(run_id),
        title=title,
        body="\n".join(body_lines),
        files=files,
        run_id=run_id,
        updates=updates,
    )


def run_on_project(
    settings: Settings,
    *,
    project_path: str | Path,
    specification: str,
    test_specification: str | None = None,
    authorize_writes: bool = False,
    test_paths: list[str] | None = None,
    report_path: str | Path | None = None,
    confirm_delivery: bool = False,
) -> dict[str, Any]:
    """Run Product→...→Reviewer against ``project_path`` and, if authorized, apply changes.

    ``authorize_writes`` is the explicit human authorization the destructive-change
    guardrail requires (``guardrails.validation.require_explicit_destructive_authorization``)
    — without it the Developer still produces a full ``ImplementationResult`` with
    LLM-authored ``file_contents``, but nothing is written to disk and the run is
    routed to human review instead.
    """
    state, trace, duration, cloud_first = execute_on_project(
        settings,
        project_path=project_path,
        specification=specification,
        test_specification=test_specification,
        authorize_writes=authorize_writes,
        test_paths=test_paths,
    )
    project_root = Path(project_path).resolve()
    run_id = str(state["run_id"])

    implementation = state.get("implementation")
    review = state.get("review")
    diff_result = next(
        (item for item in state.get("tool_results", []) if item.tool_name == "get_diff"),
        None,
    )
    writes = [
        item for item in state.get("tool_results", [])
        if item.tool_name in {"create_file", "update_file"}
    ]
    errors = state.get("errors", [])
    evidence = {
        "run_id": run_id,
        "trace_id": trace.trace_id,
        "langfuse_live": trace.live,
        "project_path": str(project_root),
        "cloud_first": cloud_first,
        "final_status": state.get("final_status"),
        "route_history": state.get("route_history", []),
        "iterations": state.get("iteration", 0),
        "duration_seconds": duration,
        "authorize_writes": authorize_writes,
        "action_mode": implementation.action_mode.value if implementation else None,
        "changed_files": implementation.changed_files if implementation else [],
        "diff_summary": implementation.diff if implementation else "",
        "proposed_file_contents": implementation.file_contents if implementation else {},
        "files_written": [item.output_summary for item in writes if item.status.value == "SUCCESS"],
        "write_errors": [
            f"{item.tool_name}({item.input_summary}): {item.error}"
            for item in writes if item.status.value != "SUCCESS"
        ],
        "applied_diff": diff_result.output_summary if diff_result else "",
        "review": review.model_dump(mode="json") if review else None,
        "model_usage": [item.model_dump(mode="json") for item in state.get("model_usage", [])],
        "errors": [
            f"{item.code.value}: {item.detail}" for item in errors
        ],
        "human_review_required": bool(state.get("human_review_required")),
        "destructive_authorization_blocked": any(
            item.code is ErrorCode.TOOL_ERROR and "destructive operation" in item.detail
            for item in errors
        ),
    }
    # Optional post-APPROVED delivery (ADR 6). Default delivery_backend remains
    # "none"; confirm_delivery must also be True — configuration alone is not
    # enough to push or open a PR.
    if (
        authorize_writes
        and confirm_delivery
        and review is not None
        and getattr(review, "status", None) is ReviewerStatus.APPROVED
    ):
        try:
            delivery = build_delivery(settings)
        except DeliveryRefused as exc:
            evidence["delivery_error"] = str(exc)
            delivery = None
        if delivery is not None:
            proposal = _proposal_from_implementation(
                project_root=project_root,
                run_id=run_id,
                implementation=implementation,
                review=review,
                written_paths=list(evidence.get("files_written") or []),
            )
            if proposal is None:
                evidence["delivery_error"] = "no file contents available for delivery"
            else:
                try:
                    GitDelivery().push(project_root, proposal, confirmed=True)
                    evidence["delivery_branch"] = proposal.branch
                    open_pr = getattr(delivery, "open", None)
                    if callable(open_pr):
                        evidence["delivery_pr_url"] = open_pr(
                            project_root, proposal, confirmed=True
                        )
                except DeliveryRefused as exc:
                    evidence["delivery_error"] = str(exc)
    if report_path is not None:
        path = Path(report_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(evidence, indent=2, default=str), encoding="utf-8")
    return evidence
