from engineering_team.contracts.enums import (
    ActionMode,
    AgentRole,
    ErrorCode,
    RemediationCategory,
    ReviewerStatus,
    RouteTarget,
    SecurityStatus,
    ToolStatus,
)
from engineering_team.contracts.models import ReviewerDecision, ToolResult
from engineering_team.guardrails.secrets import redact_secrets
from engineering_team.models.context import ContextEnvelope
from engineering_team.testing_evidence import (
    classify_failures,
    describe_failures,
    failing_tests,
    failure_diagnostics,
)

from .base import AgentBase
from .testing import TEST_EVIDENCE_TOOLS

_DIMENSIONS = (
    "requirements", "architecture", "security", "testing", "implementation", "rag_grounding",
)


def _implementation_evidence_problems(
    projection: dict[str, object], tool_results: list[ToolResult]
) -> list[str]:
    repository_context = projection.get("repository_context") or {}
    if (
        not isinstance(repository_context, dict)
        or not repository_context.get("apply_changes")
    ):
        return []

    implementation = projection.get("implementation")
    if implementation is None:
        return ["authorized apply run has no Developer implementation result"]
    if implementation.action_mode is not ActionMode.APPLIED:
        return [
            (
                "authorized apply run requires Developer action_mode=APPLIED; "
                f"got {implementation.action_mode.value}"
            )
        ]

    problems: list[str] = []
    targets = set(implementation.changed_files)
    content_paths = set(implementation.file_contents)
    if (
        not targets
        or content_paths != targets
        or any(
            not implementation.file_contents[path].strip()
            for path in content_paths
        )
    ):
        problems.append(
            "file_contents must contain non-empty content for exactly every "
            "governed changed_files target"
        )
    missing_newlines = sorted(
        path
        for path, content in implementation.file_contents.items()
        if content and not content.endswith("\n")
    )
    if missing_newlines:
        problems.append(
            "authored text must end with a newline for: "
            + ", ".join(missing_newlines)
        )

    written_paths = {
        item.output_summary.strip().replace("\\", "/")
        for item in tool_results
        if item.tool_name in {"create_file", "update_file"}
        and item.allowed_role is AgentRole.DEVELOPER
        and item.status is ToolStatus.SUCCESS
        and item.output_summary.strip()
    }

    latest_diff = next(
        (
            item
            for item in reversed(tool_results)
            if item.tool_name == "get_diff"
            and item.allowed_role is AgentRole.DEVELOPER
        ),
        None,
    )
    if (
        latest_diff is None
        or latest_diff.status is not ToolStatus.SUCCESS
        or not latest_diff.output_summary.strip()
    ):
        problems.append(
            "authorized apply run requires a successful non-empty resulting diff"
        )
        # Also surface missing writes on this early return: otherwise a claim of
        # APPLIED with no get_diff only reports the empty-diff problem and hides
        # which allowlisted paths never got a Repository write
        # (test_reviewer_rejects_applied_content_without_write_evidence).
        missing_writes = sorted(targets - written_paths)
        if missing_writes:
            problems.append(
                "no successful Repository write exists for: "
                + ", ".join(missing_writes)
            )
        return problems

    # Paths that appear in the resulting diff (+++ b/...). A Repository._write
    # whitespace-only NO-OP still returns SUCCESS but never mutates the tree, so
    # it leaves no footprint here (apply-399a301c / product.py). Drop those from
    # written_paths and changed_files targets so models-only WS churn cannot
    # inflate scope or shadow real route/test edits.
    diff_paths: set[str] = set()
    current_path = "unknown path"
    trailing_whitespace_paths: set[str] = set()
    for line in latest_diff.output_summary.splitlines():
        if line.startswith("+++ b/"):
            current_path = line.removeprefix("+++ b/")
            if current_path != "/dev/null":
                diff_paths.add(current_path)
        elif (
            line.startswith("+")
            and not line.startswith("+++")
            and line.endswith((" ", "	"))
        ):
            trailing_whitespace_paths.add(current_path)
    noop_paths = {
        path for path in written_paths
        if path != "unknown path" and path not in diff_paths
    }
    if noop_paths:
        written_paths -= noop_paths
        targets -= noop_paths

    missing_writes = sorted(targets - written_paths)
    if missing_writes:
        problems.append(
            "no successful Repository write exists for: "
            + ", ".join(missing_writes)
        )

    hard_trailing = trailing_whitespace_paths - noop_paths
    if hard_trailing:
        problems.append(
            "resulting diff adds trailing whitespace in: "
            + ", ".join(sorted(hard_trailing))
        )

    # Reject brand-new root-level files that shadow an existing nested path
    # (apply-5d1c2020 wrote products.py at repo root while app/routes/products.py
    # already existed; Reviewer APPROVED and never touched the real route).
    root_creates = sorted(
        path
        for path in targets
        if "/" not in path.replace("\\", "/")
    )
    if root_creates:
        problems.append(
            "changed_files must not create bare root paths when a nested file "
            "is intended; reject: " + ", ".join(root_creates)
        )
    return problems


class ReviewerAgent(AgentBase[ReviewerDecision]):
    role = "Reviewer"

    def execute(self, envelope: ContextEnvelope) -> ReviewerDecision:
        projection = envelope.state_projection
        security = projection.get("security_review")
        tests = projection.get("test_results") or []
        latest_test = tests[-1] if tests else None
        evidence = [item.chunk_id for item in envelope.rag_evidence]
        evidence.extend(item.evidence_reference or item.tool_name for item in envelope.tool_results)
        errors = projection.get("errors") or []
        if any(item.code is ErrorCode.RAG_ERROR for item in errors):
            return ReviewerDecision(
                status=ReviewerStatus.REJECTED, score=35,
                subscores={item: (0 if item == "rag_grounding" else 70) for item in _DIMENSIONS},
                problems=["required specialized RAG grounding is unavailable"],
                reason="RAG_ERROR requires architecture remediation or human evidence",
                remediation_category=RemediationCategory.ARCHITECTURE,
                return_to=RouteTarget.ARCHITECTURE, confidence=1,
                evidence_references=evidence,
            )
        if security is not None and security.status is SecurityStatus.FAIL:
            problems = [finding.description for finding in security.findings]
            if any(finding.category == "security tooling" for finding in security.findings):
                latest_scans = {(item.tool_name, item.input_summary): item
                    for item in envelope.tool_results if item.tool_name in {
                        "run_security_scan", "scan_dependencies", "get_security_report"}}
                failures = [item for item in latest_scans.values()
                            if item.status is not ToolStatus.SUCCESS]
                problems.extend(f"{item.tool_name}: {redact_secrets(item.output_summary)[-2000:]}"
                                for item in failures[:2])
            return ReviewerDecision(
                status=ReviewerStatus.REJECTED, score=40,
                subscores={item: (0 if item == "security" else 70) for item in _DIMENSIONS},
                problems=problems,
                reason=("unsafe requirement requires human revision" if security.requires_hitl
                        else "security findings require code remediation"),
                remediation_category=RemediationCategory.SECURITY,
                return_to=None if security.requires_hitl else RouteTarget.DEVELOPER, confidence=1,
                evidence_references=evidence,
            )
        implementation_problems = _implementation_evidence_problems(
            projection, envelope.tool_results
        )
        if latest_test is not None and latest_test.status is not ToolStatus.SUCCESS:
            failure_output = "\n".join(latest_test.failures)
            failed_identifiers = failing_tests(failure_output)
            baseline = tuple(envelope.state_projection.get("baseline_tests") or ())
            regressions, new_failures = classify_failures(failed_identifiers, baseline)
            diagnostic_order = regressions + new_failures
            # Where does a failure belong? Every failure used to go to the
            # Developer, which is right when the design was sound and the code
            # was not. It is wrong when the design was built on a slice of the
            # repository: the Developer is then asked to satisfy interfaces
            # nobody verified, produces the same mismatch, and the cycle repeats
            # against the same evidence -- the loop finding 8 describes.
            #
            # The condition is the graph's own count of what Architecture read,
            # never the model's account of itself, so the routing stays
            # deterministic.
            architecture = envelope.state_projection.get("architecture")
            if getattr(architecture, "evidence_sufficient", None) is False:
                gap = getattr(architecture, "evidence_gap", "") or "evidence was incomplete"
                return ReviewerDecision(
                    status=ReviewerStatus.REJECTED, score=40,
                    subscores={
                        item: (0 if item in {"testing", "architecture"} else 70)
                        for item in _DIMENSIONS
                    },
                    problems=[
                        f"the design was produced from incomplete evidence: {gap}",
                        *latest_test.failures,
                    ],
                    reason=(
                        "tests fail against a design built on incomplete repository "
                        "evidence; the architecture needs to be revisited before "
                        "the implementation"
                    ),
                    remediation_category=RemediationCategory.ARCHITECTURE,
                    return_to=RouteTarget.ARCHITECTURE, confidence=1,
                    evidence_references=evidence,
                )
            return ReviewerDecision(
                status=ReviewerStatus.REJECTED, score=45,
                subscores={
                    item: (
                        0
                        if item == "testing"
                        or (item == "implementation" and implementation_problems)
                        else 75
                    )
                    for item in _DIMENSIONS
                },
                # A break and a not-yet-working feature are different news, and
                # naming them the same is why three cycles went to the wrong one.
                problems=[
                    *(
                        describe_failures(
                            failed_identifiers,
                            baseline,
                            failure_diagnostics(failure_output, diagnostic_order),
                        )
                        or list(latest_test.failures)
                    ),
                    *implementation_problems,
                ],
                reason="failed tests require implementation remediation",
                remediation_category=RemediationCategory.TESTING,
                return_to=RouteTarget.DEVELOPER, confidence=1,
                evidence_references=evidence,
            )
        # Trailing whitespace alone must not HITL a green run (apply-474c7045):
        # tests already proved behavior; style is normalized at Repository write.
        hard_implementation_problems = [
            problem
            for problem in implementation_problems
            if "trailing whitespace" not in problem
        ]
        if hard_implementation_problems:
            return ReviewerDecision(
                status=ReviewerStatus.REJECTED,
                score=40,
                subscores={
                    item: (0 if item == "implementation" else 75)
                    for item in _DIMENSIONS
                },
                problems=hard_implementation_problems,
                reason="implementation evidence gate requires an applied workspace change",
                remediation_category=RemediationCategory.IMPLEMENTATION,
                return_to=RouteTarget.DEVELOPER,
                confidence=1,
                evidence_references=evidence,
            )
        test_evidence_problems: list[str] = []
        run_tests = [
            item for item in envelope.tool_results
            if item.tool_name in TEST_EVIDENCE_TOOLS and item.allowed_role is AgentRole.TESTING
        ]
        if latest_test is None:
            test_evidence_problems.append("no interpreted test result is available")
        if not run_tests:
            test_evidence_problems.append("no real run_tests execution is recorded")
        else:
            # The latest result of every component, not the last result overall:
            # tool_results accumulates across remediation cycles, so a failure a
            # later cycle fixed must not keep counting.
            current: dict[str, ToolResult] = {}
            for item in run_tests:
                current[item.evidence_reference or item.tool_name] = item
            unsuccessful = [
                reference
                for reference, item in current.items()
                if item.status is not ToolStatus.SUCCESS
            ]
            test_evidence_problems.extend(
                f"a run_tests execution did not succeed: {reference}"
                for reference in unsuccessful
            )
        if latest_test is not None:
            executed_evidence = set(latest_test.executed_tests)
            recorded_evidence = {
                item.evidence_reference or item.tool_name
                for item in run_tests
                if item.status is ToolStatus.SUCCESS
            }
            valid_coverage_evidence = executed_evidence & recorded_evidence
            # Security PASS is its own evidence for the `security` coverage
            # dimension (apply-399a301c / v5). Mapping security_review into
            # coverage_mapping would fail "cites unexecuted evidence" against
            # run_tests, so Reviewer exempts an empty/unexecuted `security`
            # dimension when SecurityStatus.PASS — other dimensions stay strict.
            security_pass = (
                security is not None and security.status is SecurityStatus.PASS
            )

            def _security_exempt(dimension: str) -> bool:
                return dimension == "security" and security_pass

            gaps = sorted(
                dimension
                for dimension in latest_test.proposed_tests
                if not _security_exempt(dimension)
                and not any(
                    reference.strip()
                    for reference in latest_test.coverage_mapping.get(dimension, [])
                )
            )
            test_evidence_problems.extend(
                f"required coverage dimension has no evidence: {dimension}"
                for dimension in gaps
            )
            invalid_coverage = sorted(
                dimension
                for dimension in latest_test.proposed_tests
                if not _security_exempt(dimension)
                and any(
                    reference not in valid_coverage_evidence
                    for reference in latest_test.coverage_mapping.get(dimension, [])
                )
            )
            test_evidence_problems.extend(
                f"required coverage dimension cites unexecuted evidence: {dimension}"
                for dimension in invalid_coverage
            )
        if test_evidence_problems:
            return ReviewerDecision(
                status=ReviewerStatus.REJECTED, score=45,
                subscores={item: (0 if item == "testing" else 75) for item in _DIMENSIONS},
                problems=test_evidence_problems,
                reason="testing evidence gate requires a real successful run and complete coverage",
                remediation_category=RemediationCategory.TESTING,
                return_to=RouteTarget.DEVELOPER, confidence=1,
                evidence_references=evidence,
            )
        return ReviewerDecision(
            status=ReviewerStatus.APPROVED, score=100,
            subscores={item: 100 for item in _DIMENSIONS}, reason="validated evidence satisfies acceptance checks",
            confidence=1, evidence_references=evidence,
        )
