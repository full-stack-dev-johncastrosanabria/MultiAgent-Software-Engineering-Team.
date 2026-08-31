from engineering_team.contracts.enums import (
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
from engineering_team.testing_evidence import describe_failures, failing_tests

from .base import AgentBase
from .testing import TEST_EVIDENCE_TOOLS

_DIMENSIONS = (
    "requirements", "architecture", "security", "testing", "implementation", "rag_grounding",
)


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
                problems.extend(f"{item.tool_name}: {redact_secrets(item.output_summary[-2000:])}"
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
        if latest_test is not None and latest_test.status is not ToolStatus.SUCCESS:
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
                subscores={item: (0 if item == "testing" else 75) for item in _DIMENSIONS},
                # A break and a not-yet-working feature are different news, and
                # naming them the same is why three cycles went to the wrong one.
                problems=(
                    describe_failures(
                        failing_tests(" ".join(latest_test.failures)),
                        tuple(envelope.state_projection.get("baseline_tests") or ()),
                    )
                    or list(latest_test.failures)
                ),
                reason="failed tests require implementation remediation",
                remediation_category=RemediationCategory.TESTING,
                return_to=RouteTarget.DEVELOPER, confidence=1,
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
            gaps = sorted(
                dimension
                for dimension in latest_test.proposed_tests
                if not any(
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
                if any(
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
