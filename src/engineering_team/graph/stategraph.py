"""The single governed LangGraph orchestrator for the engineering workflow."""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from engineering_team.agents.architecture import ArchitectureAgent
from engineering_team.agents.developer import DeveloperAgent
from engineering_team.agents.product import ProductAgent
from engineering_team.agents.reviewer import ReviewerAgent
from engineering_team.agents.security import SecurityAgent
from engineering_team.agents.testing import TestingAgent
from engineering_team.contracts.enums import (
    ActionMode,
    AgentRole,
    ErrorCode,
    RemediationCategory,
    ReviewerStatus,
    ToolStatus,
)
from engineering_team.contracts.models import FinalReport, WorkflowError
from engineering_team.contracts.state import EngineeringState
from engineering_team.guardrails.validation import require_explicit_destructive_authorization
from engineering_team.models.context import build_context
from engineering_team.repository_evidence import (
    ARCHITECTURE_ENVELOPE_BYTES,
    MAX_ARCHITECTURE_RAG_ITEMS,
    MAX_ARCHITECTURE_READ_BYTES,
    MAX_ARCHITECTURE_READ_CANDIDATES,
    MAX_ARCHITECTURE_SEARCH_BYTES,
    MIN_ARCHITECTURE_SLICE_BYTES,
    assess_evidence_sufficiency,
    bounded_rag_evidence,
    bounded_redacted_text,
    budgeted_slices,
    parse_repository_paths,
    summarize_path_tool_result,
)

from .routers import review_route, security_route


class WalkingState(TypedDict):
    visited: list[str]
    final_status: str


class WorkflowState(TypedDict, total=False):
    run_id: str
    requirement: str
    specification: object
    repository_context: dict
    architecture: object
    implementation: object
    security_review: object
    test_results: list
    baseline_tests: list
    review: object
    rag_evidence: list
    tool_results: list
    model_usage: list
    iteration: int
    errors: list
    human_review_required: bool
    final_status: str
    remediation_request: str
    next_validation_path: str
    cloud_escalations_by_agent: dict
    cloud_escalations_run: int
    local_retries_by_stage: dict
    local_repairs_by_stage: dict
    trace_id: str
    route_history: list
    final_report: object
    human_decision: str


def _visit(role: str):
    def node(state: WalkingState) -> dict[str, object]:
        return {"visited": [*state.get("visited", []), role]}
    return node


def _review(state: WalkingState) -> dict[str, object]:
    return {"visited": [*state.get("visited", []), "Reviewer"], "final_status": "APPROVED"}


def build_walking_graph():
    graph = StateGraph(WalkingState)
    graph.add_node("Product", _visit("Product"))
    graph.add_node("Architecture", _visit("Architecture"))
    graph.add_node("Developer", _visit("Developer"))
    graph.add_node("Security", _visit("Security"))
    graph.add_node("Testing", _visit("Testing"))
    graph.add_node("Reviewer", _review)
    graph.add_edge(START, "Product")
    graph.add_edge("Product", "Architecture")
    graph.add_edge("Architecture", "Developer")
    graph.add_edge("Developer", "Security")
    graph.add_edge("Security", "Testing")
    graph.add_edge("Testing", "Reviewer")
    graph.add_edge("Reviewer", END)
    return graph.compile()


def _report(state: EngineeringState, status: str) -> FinalReport:
    return FinalReport(
        feature="Autonomous Software Engineering Team",
        status=status,
        requirements=state.specification.objective if state.specification else state.requirement,
        architecture=state.architecture.impact if state.architecture else "unavailable",
        security=state.security_review.status.value if state.security_review else "unavailable",
        testing=state.test_results[-1].status.value if state.test_results else "unavailable",
        implementation=state.implementation.validation_result if state.implementation else "unavailable",
        risk=(state.security_review.highest_severity.value if state.security_review else "unknown"),
        iterations=state.iteration,
        documentation_used=list(dict.fromkeys(item.source for item in state.rag_evidence)),
        tools_executed=[item.tool_name for item in state.tool_results],
        models_used=[item.actual_model or item.requested_model for item in state.model_usage],
        errors_degradations=[f"{item.code.value}: {item.detail}" for item in state.errors],
        trace_id=state.trace_id or state.run_id,
        next_action="none" if status == "APPROVED" else "human review",
    )
# Orquestación LangGraph

# el sistema utiliza una "memoria central" o estado con reglas estrictas (el TypedDict).
# En lugar de pasarse mensajes de texto desordenados, todos los agentes leen y escriben sobre un mismo formato estructurado
def build_engineering_graph(
    *,
    agent_overrides: dict[AgentRole, Any] | None = None,
    quality_mcp: Any | None = None,
    repository_mcp: Any | None = None,
    retriever: Any | None = None,
    model_runtime: Any | None = None,
    cloud_runtime: Any | None = None,
    trace: Any | None = None,
    test_paths: list[str] | None = None,
    interactive_hitl: bool = False,
    model_stage_retries: int = 1,
):
    # StateGraph(WorkflowState) real con TypedDict, un nodo por agente y edges condicionales.
    """Compile normal, remediation, MCP/RAG, and HITL routes as real nodes."""
    if model_stage_retries < 0:
        raise ValueError("model_stage_retries must be non-negative")
    graph = StateGraph(WorkflowState)
    agents: dict[AgentRole, Any] = {
        AgentRole.PRODUCT: ProductAgent(), AgentRole.ARCHITECTURE: ArchitectureAgent(),
        AgentRole.DEVELOPER: DeveloperAgent(), AgentRole.SECURITY: SecurityAgent(),
        AgentRole.TESTING: TestingAgent(), AgentRole.REVIEWER: ReviewerAgent(),
    }
    agents.update(agent_overrides or {})
    targets = {
        AgentRole.PRODUCT: "specification", AgentRole.ARCHITECTURE: "architecture",
        AgentRole.DEVELOPER: "implementation", AgentRole.SECURITY: "security_review",
        AgentRole.TESTING: "test_results", AgentRole.REVIEWER: "review",
    }

    def mcp_trace_metadata(adapter: Any) -> dict[str, Any]:
        return {
            "transport": getattr(adapter, "transport", "direct-backend"),
            "protocol_version": getattr(adapter, "last_protocol_version", None),
            "server": getattr(adapter, "last_server_name", type(adapter).__name__),
        }

    def preserve_tool_result(
        result: Any,
        role: AgentRole,
        errors: list[WorkflowError],
        tool_results: list[Any],
        adapter: Any,
        *,
        strict: bool = False,
    ) -> bool:
        """Preserve one MCP result and return whether required MCP evidence is unavailable.

        ``strict`` treats any non-SUCCESS status (including DENIED) as blocking —
        used for write calls, where a silently-ignored denial would leave a
        change set partially applied.
        """
        tool_results.append(result)
        if trace is not None:
            trace.record(
                "MCP call", as_type="tool", output=result.model_dump(mode="json"),
                metadata=mcp_trace_metadata(adapter),
            )
        blocking = (
            result.status is not ToolStatus.SUCCESS
            if strict
            else result.status in {ToolStatus.UNAVAILABLE, ToolStatus.FAIL}
        )
        if not blocking:
            return False
        code = (
            ErrorCode.MCP_ERROR
            if result.status is ToolStatus.UNAVAILABLE
            else ErrorCode.TOOL_ERROR
        )
        error = WorkflowError(
            code=code,
            source_stage=role.value,
            retryable=False,
            detail=f"{result.tool_name}: {result.error or result.status.value}",
            evidence_reference=result.evidence_reference,
        )
        errors.append(error)
        if trace is not None:
            trace.record(
                code.value,
                level="ERROR",
                status_message=error.detail,
                output=result.model_dump(mode="json"),
                metadata={"agent": role.value, "tool": result.tool_name},
            )
        return blocking if strict else result.status is ToolStatus.UNAVAILABLE

    def make_node(role: AgentRole):
        def node(raw_state: dict[str, Any]) -> dict[str, Any]:
            current = EngineeringState.model_validate(raw_state)
            rag_evidence = list(current.rag_evidence)
            errors = list(current.errors)
            tool_results = list(current.tool_results)
            required_mcp_missing = False
            existing_repo_paths: set[str] = set()
            architecture_rag = list(rag_evidence)
            architecture_read_results: list[tuple[str, Any]] = []
            architecture_coverage: Any = None
            architecture_ranked_count = 0
            architecture_retrieval_ran = False
            developer_apply_targets: list[str] = []
            if retriever is not None and role in {
                AgentRole.ARCHITECTURE, AgentRole.SECURITY, AgentRole.TESTING
            }:
                retrieved = retriever.retrieve(current.requirement, agent=role)
                new_evidence = [
                    item for item in retrieved
                    if item.chunk_id not in {old.chunk_id for old in rag_evidence}
                ]
                if role is AgentRole.ARCHITECTURE:
                    architecture_retrieval_ran = True
                    architecture_rag.extend(new_evidence)
                else:
                    rag_evidence.extend(new_evidence)
                if retriever.last_error is not None:
                    errors.append(retriever.last_error)
                if trace is not None and role is not AgentRole.ARCHITECTURE:
                    trace.record(
                        "RAG retrieval", as_type="retriever", input={"query": current.requirement},
                        output=[item.model_dump(mode="json") for item in retrieved],
                        metadata={"agent": role.value, "status": retriever.last_status},
                    )
            if repository_mcp is not None and role in {AgentRole.ARCHITECTURE, AgentRole.DEVELOPER}:
                raw_result = repository_mcp.list_files(role)
                architecture_listed_paths = (
                    parse_repository_paths(raw_result.output_summary)
                    if role is AgentRole.ARCHITECTURE
                    and raw_result.status is ToolStatus.SUCCESS
                    else []
                )
                result = (
                    summarize_path_tool_result(raw_result)
                    if role is AgentRole.ARCHITECTURE
                    else raw_result
                )
                required_mcp_missing |= preserve_tool_result(
                    result, role, errors, tool_results, repository_mcp
                )
                if role is AgentRole.ARCHITECTURE and result.status is ToolStatus.SUCCESS:
                    listed_paths = architecture_listed_paths
                    terms = ArchitectureAgent.relevance_terms(
                        current.specification,
                        current.requirement,
                        # What the Reviewer said, so a second pass does not read
                        # the same files and reach the same conclusion.
                        feedback=current.remediation_request or "",
                    )
                    search_hits: list[str] = []
                    for term in terms[:3]:
                        raw_search = repository_mcp.search_code(role, term)
                        ephemeral_hits = (
                            parse_repository_paths(raw_search.output_summary)
                            if raw_search.status is ToolStatus.SUCCESS else []
                        )
                        searched = summarize_path_tool_result(
                            raw_search, limit=MAX_ARCHITECTURE_SEARCH_BYTES
                        )
                        required_mcp_missing |= preserve_tool_result(
                            searched, role, errors, tool_results, repository_mcp
                        )
                        search_hits.extend(ephemeral_hits)
                    ranked = ArchitectureAgent.rank_paths(listed_paths, search_hits, terms)
                    if search_hits:
                        hit_set = set(search_hits)
                        relevant_ranked = [path for path in ranked if path in hit_set]
                        ranked = relevant_ranked or ranked
                    for path in ranked[:MAX_ARCHITECTURE_READ_CANDIDATES]:
                        raw_read = repository_mcp.read_file(role, path)
                        architecture_read_results.append((path, raw_read))
                    # Measured here, from what was actually fetched against what
                    # ranking said was worth fetching. The stage does not get to
                    # report on itself.
                    architecture_ranked_count = len(ranked)
                elif role is AgentRole.DEVELOPER and result.status is ToolStatus.SUCCESS:
                    listed_paths = [
                        line.strip().replace("\\", "/")
                        for line in result.output_summary.splitlines()
                        if DeveloperAgent._safe_path(line.strip().replace("\\", "/"))
                    ]
                    terms = DeveloperAgent.relevance_terms(
                        current.specification, current.architecture, current.requirement
                    )
                    search_hits: list[str] = []
                    for term in terms[:3]:
                        searched = repository_mcp.search_code(role, term)
                        required_mcp_missing |= preserve_tool_result(
                            searched, role, errors, tool_results, repository_mcp
                        )
                        if searched.status is ToolStatus.SUCCESS:
                            search_hits.extend(
                                line.strip().replace("\\", "/")
                                for line in searched.output_summary.splitlines()
                            )
                    existing_repo_paths = set(listed_paths)
                    ranked = DeveloperAgent.rank_paths(listed_paths, search_hits, terms)
                    if search_hits:
                        ranked = [path for path in ranked if path in set(search_hits)]
                    already_read = set(ranked[:4])
                    for path in ranked[:4]:
                        read = repository_mcp.read_file(role, path)
                        required_mcp_missing |= preserve_tool_result(
                            read, role, errors, tool_results, repository_mcp
                        )
                    if current.repository_context.get("apply_changes"):
                        # A test path is often the only literal path in a request. Select
                        # one related source from already inspected evidence, then read it
                        # as Developer evidence before the write candidate is governed.
                        developer_apply_targets = DeveloperAgent.apply_targets(
                            DeveloperAgent.requested_targets(current.requirement),
                            tool_results,
                            current.specification,
                            current.architecture,
                            current.requirement,
                        )
                        for target_path in developer_apply_targets:
                            if target_path in existing_repo_paths and target_path not in already_read:
                                read = repository_mcp.read_file(role, target_path)
                                required_mcp_missing |= preserve_tool_result(
                                    read, role, errors, tool_results, repository_mcp
                                )
                                already_read.add(target_path)
            if role is AgentRole.ARCHITECTURE:
                unique_rag = []
                seen_chunks: set[str] = set()
                for item in architecture_rag:
                    if item.chunk_id not in seen_chunks:
                        unique_rag.append(item)
                        seen_chunks.add(item.chunk_id)
                    if len(unique_rag) == MAX_ARCHITECTURE_RAG_ITEMS:
                        break
                # The prompt applies this same water-filled budget when rendering.
                # Count only files that can actually receive a useful slice as
                # evidence; fetching 24 files whose content is then dropped is not
                # architecture grounding.
                evidence_sizes = [
                    min(len(raw_read.output_summary.encode("utf-8")), MAX_ARCHITECTURE_READ_BYTES)
                    for _, raw_read in architecture_read_results
                ]
                evidence_sizes.extend(
                    min(len(item.fragment.encode("utf-8")), MAX_ARCHITECTURE_READ_BYTES)
                    for item in unique_rag
                )
                slices, _ = budgeted_slices(
                    evidence_sizes,
                    MAX_ARCHITECTURE_READ_BYTES,
                    minimum=MIN_ARCHITECTURE_SLICE_BYTES,
                    overhead=ARCHITECTURE_ENVELOPE_BYTES,
                )
                read_slices = slices[:len(architecture_read_results)]
                rag_slices = slices[len(architecture_read_results):]
                visible_reads = sum(slice_size > 0 for slice_size in read_slices)
                architecture_coverage = assess_evidence_sufficiency(
                    read=visible_reads,
                    ranked=architecture_ranked_count,
                    omitted=max(0, architecture_ranked_count - visible_reads),
                )
                rag_evidence = [
                    bounded_rag_evidence(item, budget)
                    for item, budget in zip(unique_rag, rag_slices, strict=False)
                    if budget > 0
                ]
                for (path, raw_read), budget in zip(
                    architecture_read_results, read_slices, strict=False
                ):
                    if budget <= 0:
                        continue
                    read = raw_read.model_copy(update={
                        "input_summary": f"path={path}",
                        "output_summary": bounded_redacted_text(
                            raw_read.output_summary, budget
                        ),
                        "error": (
                            bounded_redacted_text(raw_read.error, 2 * 1024)
                            if raw_read.error is not None else None
                        ),
                    })
                    required_mcp_missing |= preserve_tool_result(
                        read, role, errors, tool_results, repository_mcp
                    )
                if trace is not None and architecture_retrieval_ran:
                    trace.record(
                        "RAG retrieval", as_type="retriever",
                        input={"query": current.requirement},
                        output=[item.model_dump(mode="json") for item in rag_evidence],
                        metadata={"agent": role.value, "status": retriever.last_status},
                    )
            if quality_mcp is not None and role is AgentRole.TESTING:
                result = quality_mcp.run_tests(role, test_paths)
                required_mcp_missing |= preserve_tool_result(
                    result, role, errors, tool_results, quality_mcp
                )
            if quality_mcp is not None and role is AgentRole.SECURITY:
                operations = [
                    getattr(quality_mcp, name) for name in (
                        "scan_dependencies", "run_security_scan"
                    ) if hasattr(quality_mcp, name)
                ]
                for operation in operations:
                    result = operation(role)
                    required_mcp_missing |= preserve_tool_result(
                        result, role, errors, tool_results, quality_mcp
                    )
            current = current.model_copy(
                update={"rag_evidence": rag_evidence, "errors": errors, "tool_results": tool_results}
            )
            if required_mcp_missing:
                return {
                    "route_history": [*current.route_history, role.value],
                    "rag_evidence": rag_evidence,
                    "errors": errors,
                    "tool_results": tool_results,
                    "model_usage": list(current.model_usage),
                    "human_review_required": True,
                    "trace_id": trace.trace_id if trace is not None else current.trace_id,
                }
            model_usage = list(current.model_usage)
            envelope = build_context(role, current, role.value)
            candidate = agents[role].execute(envelope)
            if (
                role is AgentRole.DEVELOPER
                and developer_apply_targets
                and candidate.action_mode is ActionMode.APPLIED
            ):
                # Keep the governed candidate aligned with the files just read above.
                # This makes the orchestrator, rather than model context order, the
                # final authority on a remediation's writable scope.
                candidate = candidate.model_copy(update={"changed_files": developer_apply_targets})
            if role in {AgentRole.TESTING, AgentRole.REVIEWER}:
                # Testing and Reviewer are deterministic gates over real MCP evidence.
                # Calling a model here adds latency without improving the result.
                output = candidate
            elif model_runtime is not None:
                for stage_attempt in range(model_stage_retries + 1):
                    attempt_start = len(model_runtime.attempts)
                    try:
                        output, model_info = model_runtime.invoke_artifact(role, envelope, candidate)
                        attempts = model_runtime.attempts[attempt_start:]
                        model_usage.extend(attempts or [model_info])
                        break
                    except RuntimeError as exc:
                        model_usage.extend(model_runtime.attempts[attempt_start:])
                        message = str(exc)
                        if message.startswith(ErrorCode.LLM_QUALITY_ERROR.value):
                            code = ErrorCode.LLM_QUALITY_ERROR
                        elif message.startswith(ErrorCode.AGENT_TIMEOUT.value):
                            code = ErrorCode.AGENT_TIMEOUT
                        else:
                            code = ErrorCode.LLM_AVAILABILITY_ERROR
                        errors.append(WorkflowError(
                            code=code, source_stage=role.value, retryable=True, detail=message,
                        ))
                        if trace is not None:
                            trace.record(
                                code.value, level="ERROR", status_message=message,
                                metadata={"agent": role.value, "stage_attempt": stage_attempt + 1},
                            )

                        retryable = code in {
                            ErrorCode.LLM_AVAILABILITY_ERROR, ErrorCode.AGENT_TIMEOUT,
                        }
                        if cloud_runtime is not None:
                            cloud_attempt_start = len(getattr(cloud_runtime, "attempts", []))
                            try:
                                output, cloud_info = cloud_runtime.invoke_artifact(
                                    role,
                                    envelope,
                                    candidate,
                                    fallback_reason=code.value,
                                )
                                model_usage.append(cloud_info)
                                break
                            except RuntimeError as cloud_exc:
                                model_usage.extend(
                                    getattr(cloud_runtime, "attempts", [])[cloud_attempt_start:]
                                )
                                errors.append(WorkflowError(
                                    code=ErrorCode.CLOUD_FALLBACK_UNAVAILABLE,
                                    source_stage=role.value, retryable=retryable,
                                    detail=str(cloud_exc),
                                ))
                                if trace is not None:
                                    trace.record(
                                        "cloud fallback error", level="ERROR",
                                        status_message=str(cloud_exc),
                                        metadata={"agent": role.value, "stage_attempt": stage_attempt + 1},
                                    )

                        if retryable and stage_attempt < model_stage_retries:
                            if trace is not None:
                                trace.record(
                                    "model stage retry", level="WARNING",
                                    status_message=message,
                                    metadata={"agent": role.value, "next_attempt": stage_attempt + 2},
                                )
                            continue

                        fallback_patch: dict[str, Any] = {
                            "route_history": [*current.route_history, role.value],
                            "errors": errors, "model_usage": model_usage,
                            "rag_evidence": rag_evidence, "tool_results": tool_results,
                            "human_review_required": True,
                            "trace_id": trace.trace_id if trace is not None else current.trace_id,
                        }
                        if cloud_runtime is not None and hasattr(cloud_runtime, "budget"):
                            fallback_patch["cloud_escalations_by_agent"] = {
                                item.value: count
                                for item, count in cloud_runtime.budget.by_agent.items()
                            }
                            fallback_patch["cloud_escalations_run"] = cloud_runtime.budget.run_count
                        return fallback_patch
            else:
                output = candidate
            if (
                role is AgentRole.DEVELOPER
                and repository_mcp is not None
                and output.action_mode is ActionMode.APPLIED
                and output.file_contents
            ):
                try:
                    require_explicit_destructive_authorization(
                        bool(current.repository_context.get("authorized"))
                    )
                except PermissionError as exc:
                    errors.append(WorkflowError(
                        code=ErrorCode.TOOL_ERROR, source_stage=role.value, retryable=False,
                        detail=str(exc),
                    ))
                    if trace is not None:
                        trace.record(
                            "destructive change blocked", level="ERROR", status_message=str(exc),
                            metadata={"agent": role.value, "changed_files": output.changed_files},
                        )
                    return {
                        "route_history": [*current.route_history, role.value],
                        "errors": errors, "model_usage": model_usage,
                        "rag_evidence": rag_evidence, "tool_results": tool_results,
                        "human_review_required": True,
                        "trace_id": trace.trace_id if trace is not None else current.trace_id,
                        "implementation": output,
                    }
                write_failed = False
                for path, content in output.file_contents.items():
                    writer = (
                        repository_mcp.update_file
                        if path in existing_repo_paths
                        else repository_mcp.create_file
                    )
                    result = writer(role, path, content)
                    write_failed |= preserve_tool_result(
                        result, role, errors, tool_results, repository_mcp, strict=True
                    )
                diff_result = repository_mcp.get_diff(role)
                preserve_tool_result(diff_result, role, errors, tool_results, repository_mcp)
                if write_failed:
                    return {
                        "route_history": [*current.route_history, role.value],
                        "errors": errors, "model_usage": model_usage,
                        "rag_evidence": rag_evidence, "tool_results": tool_results,
                        "implementation": output,
                        "human_review_required": True,
                        "trace_id": trace.trace_id if trace is not None else current.trace_id,
                    }
            patch: dict[str, Any] = {
                "route_history": [*current.route_history, role.value],
                "rag_evidence": rag_evidence,
                "errors": errors,
                "tool_results": tool_results,
                "model_usage": model_usage,
                "trace_id": trace.trace_id if trace is not None else current.trace_id,
            }
            if cloud_runtime is not None and hasattr(cloud_runtime, "budget"):
                patch["cloud_escalations_by_agent"] = {
                    item.value: count for item, count in cloud_runtime.budget.by_agent.items()
                }
                patch["cloud_escalations_run"] = cloud_runtime.budget.run_count
            target = targets[role]
            if role is AgentRole.ARCHITECTURE and architecture_coverage is not None:
                output = output.model_copy(update={
                    "evidence_sufficient": architecture_coverage.sufficient,
                    "evidence_gap": architecture_coverage.gap,
                })
            patch[target] = [*current.test_results, output] if role is AgentRole.TESTING else output
            if role is AgentRole.REVIEWER:
                # Kept so the report can show what each cycle actually decided.
                patch["review_history"] = [*current.review_history, output]
            if role is AgentRole.REVIEWER and output.status is ReviewerStatus.REJECTED:
                patch["iteration"] = current.iteration + 1
                patch["remediation_request"] = output.reason
                patch["next_validation_path"] = (
                    "testing_only"
                    if output.remediation_category is RemediationCategory.TESTING
                    else "full"
                )
            if trace is not None:
                trace.record(
                    role.value, as_type="agent", output=output.model_dump(mode="json"),
                    metadata={"iteration": patch.get("iteration", current.iteration)},
                )
            return patch
        return node

    for role in AgentRole:
        graph.add_node(role.value, make_node(role))

    def developer_next(raw_state: dict[str, Any]) -> str:
        state = EngineeringState.model_validate(raw_state)
        if state.human_review_required:
            route = "HUMAN_REVIEW_REQUIRED"
            if trace is not None:
                trace.record("route", metadata={"from": "Developer", "to": route})
            return route
        if (
            state.next_validation_path == "testing_only"
            and state.implementation is not None
            and not state.implementation.security_surface_changed
        ):
            route = "Testing"
        else:
            route = "Security"
        if trace is not None:
            trace.record("route", metadata={"from": "Developer", "to": route})
        return route

    def security_next(raw_state: dict[str, Any]) -> str:
        state = EngineeringState.model_validate(raw_state)
        if state.human_review_required:
            return "HUMAN_REVIEW_REQUIRED"
        route = security_route(state.security_review.highest_severity)
        if trace is not None:
            trace.record("route", metadata={"from": "Security", "to": route})
        return route

    def next_or_human(raw_state: dict[str, Any], normal: str) -> str:
        state = EngineeringState.model_validate(raw_state)
        return "HUMAN_REVIEW_REQUIRED" if state.human_review_required else normal

    def reviewer_next(raw_state: dict[str, Any]) -> str:
        state = EngineeringState.model_validate(raw_state)
        if state.human_review_required:
            return "HUMAN_REVIEW_REQUIRED"
        route = review_route(state.review, state.iteration)
        if trace is not None:
            trace.record(
                "remediation route" if route not in {"FinalReport", "HUMAN_REVIEW_REQUIRED"} else "route",
                metadata={"from": "Reviewer", "to": route, "iteration": state.iteration},
            )
        return route

    def final_node(raw_state: dict[str, Any]) -> dict[str, Any]:
        state = EngineeringState.model_validate(raw_state)
        report = _report(state, "APPROVED")
        if trace is not None:
            trace.finish(report.model_dump(mode="json"))
        return {
            "route_history": [*state.route_history, "FinalReport"],
            "final_status": "APPROVED", "final_report": report,
        }

    def human_node(raw_state: dict[str, Any], name: str = "HUMAN_REVIEW_REQUIRED") -> dict[str, Any]:
        state = EngineeringState.model_validate(raw_state)
        human_decision = state.human_decision
        if interactive_hitl:
            human_decision = str(interrupt({
                "run_id": state.run_id, "reason": name,
                "allowed_decisions": ["RESUME", "TERMINATE"],
            })).strip().upper()
            if human_decision not in {"RESUME", "TERMINATE"}:
                raise ValueError("human decision must be RESUME or TERMINATE")
            if human_decision == "RESUME":
                if trace is not None:
                    trace.record(
                        "HITL resume", metadata={"iteration": state.iteration, "reason": name}
                    )
                return {
                    "route_history": [*state.route_history, name],
                    "human_review_required": False, "final_status": None,
                    "human_decision": human_decision,
                }
        report = _report(state, "HUMAN_REVIEW_REQUIRED")
        if trace is not None:
            trace.record(name, metadata={"iteration": state.iteration, "hitl": True})
            trace.finish(report.model_dump(mode="json"))
        return {
            "route_history": [*state.route_history, name], "human_review_required": True,
            "final_status": "HUMAN_REVIEW_REQUIRED", "final_report": report,
            "human_decision": human_decision,
        }

    graph.add_node("FinalReport", final_node)
    graph.add_node("HUMAN_REVIEW_REQUIRED", human_node)
    graph.add_node("security_hitl", lambda state: human_node(state, "security_hitl"))
    graph.add_edge(START, "Product")
    graph.add_conditional_edges(
        "Product", lambda state: next_or_human(state, "Architecture"),
        {"Architecture": "Architecture", "HUMAN_REVIEW_REQUIRED": "HUMAN_REVIEW_REQUIRED"},
    )
    graph.add_conditional_edges(
        "Architecture", lambda state: next_or_human(state, "Developer"),
        {"Developer": "Developer", "HUMAN_REVIEW_REQUIRED": "HUMAN_REVIEW_REQUIRED"},
    )
    graph.add_conditional_edges(
        "Developer", developer_next,
        {"Security": "Security", "Testing": "Testing", "HUMAN_REVIEW_REQUIRED": "HUMAN_REVIEW_REQUIRED"},
    )
    graph.add_conditional_edges(
        "Security", security_next,
        {"Testing": "Testing", "security_hitl": "security_hitl", "HUMAN_REVIEW_REQUIRED": "HUMAN_REVIEW_REQUIRED"},
    )
    graph.add_conditional_edges(
        "Testing", lambda state: next_or_human(state, "Reviewer"),
        {"Reviewer": "Reviewer", "HUMAN_REVIEW_REQUIRED": "HUMAN_REVIEW_REQUIRED"},
    )
    graph.add_conditional_edges(
        "Reviewer", reviewer_next,
        {"FinalReport": "FinalReport", "Architecture": "Architecture", "Developer": "Developer", "HUMAN_REVIEW_REQUIRED": "HUMAN_REVIEW_REQUIRED"},
    )
    graph.add_edge("FinalReport", END)
    if interactive_hitl:
        def hitl_next(raw_state: dict[str, Any], resume_target: str) -> str:
            state = EngineeringState.model_validate(raw_state)
            return resume_target if state.human_decision == "RESUME" else "END"

        graph.add_conditional_edges(
            "HUMAN_REVIEW_REQUIRED", lambda state: hitl_next(state, "Developer"),
            {"Developer": "Developer", "END": END},
        )
        graph.add_conditional_edges(
            "security_hitl", lambda state: hitl_next(state, "Testing"),
            {"Testing": "Testing", "END": END},
        )
    else:
        graph.add_edge("HUMAN_REVIEW_REQUIRED", END)
        graph.add_edge("security_hitl", END)
    return graph.compile(checkpointer=InMemorySaver() if interactive_hitl else None)
