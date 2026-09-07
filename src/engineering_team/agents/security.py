from pathlib import PurePosixPath

from engineering_team.contracts.enums import SecuritySeverity, SecurityStatus, ToolStatus
from engineering_team.contracts.models import SecurityFinding, SecurityReview
from engineering_team.guardrails.secrets import redact_secrets
from engineering_team.models.context import ContextEnvelope

from .base import AgentBase

_SECURITY_CATEGORIES = (
    "authentication", "authorization", "input_validation", "sensitive_information",
    "secrets", "injection", "access_control", "idor", "logging", "data_protection",
    "api_abuse", "rate_limiting", "owasp",
)

# Untouched dependency scanner findings are residual baseline risk, not a
# Security FAIL that routes remediation to Developer.
_BASELINE_DEPENDENCY_TOOLS = frozenset({"scan_dependencies", "get_security_report"})
_DEPENDENCY_MANIFEST_BASENAMES = frozenset({
    "pom.xml",
    "package.json",
    "package-lock.json",
    "go.mod",
    "go.sum",
    "pyproject.toml",
    "Gemfile",
    "Gemfile.lock",
    "Cargo.toml",
    "Cargo.lock",
    "Directory.Packages.props",
    "packages.lock.json",
    "composer.json",
    "composer.lock",
    "yarn.lock",
    "pnpm-lock.yaml",
    "requirements.txt",
    "poetry.lock",
    "Pipfile",
    "Pipfile.lock",
    "libs.versions.toml",
    "pubspec.yaml",
    "Podfile",
    "Podfile.lock",
    "mix.exs",
})


def _checklist(failed: str | None = None) -> dict[str, str]:
    return {category: ("FAIL" if category == failed else "PASS") for category in _SECURITY_CATEGORIES}


def _is_dependency_manifest(path: str) -> bool:
    normalized = path.replace("\\", "/")
    name = PurePosixPath(normalized).name
    if name in _DEPENDENCY_MANIFEST_BASENAMES:
        return True
    if name.endswith((".csproj", ".fsproj", ".vbproj")):
        return True
    if name.startswith("build.gradle"):
        return True
    if normalized.endswith("gradle/libs.versions.toml"):
        return True
    return False


def _touches_dependency_manifest(changed_files: list[str]) -> bool:
    return any(_is_dependency_manifest(path) for path in changed_files)


class SecurityAgent(AgentBase[SecurityReview]):
    role = "Security"

    def execute(self, envelope: ContextEnvelope) -> SecurityReview:
        specification = envelope.state_projection.get("specification")
        requirement = " ".join(getattr(specification, "source_requirement", "").lower().split())
        sources = list(dict.fromkeys(item.source for item in envelope.rag_evidence))
        # A fresh scan can verify remediation of an earlier failure. Keep all
        # attempts in the envelope/audit, but gate on the latest result for the
        # same tool and scope; success for another scope cannot clear a failure.
        latest_tools = {
            (item.tool_name, item.input_summary): item for item in envelope.tool_results
        }
        failed_tools = [
            item for item in latest_tools.values()
            if item.status not in {ToolStatus.SUCCESS}
        ]
        baseline_dependency_findings: list[SecurityFinding] = []
        if failed_tools:
            failed_names = {item.tool_name for item in failed_tools}
            implementation = envelope.state_projection.get("implementation")
            only_baseline_dependency_tools = failed_names <= _BASELINE_DEPENDENCY_TOOLS
            # Fail closed when implementation is absent: cannot prove manifests
            # were untouched, so do not reclassify scanner failures as baseline.
            changed_files = (
                list(getattr(implementation, "changed_files", None) or [])
                if implementation is not None
                else None
            )
            if (
                only_baseline_dependency_tools
                and implementation is not None
                and not _touches_dependency_manifest(changed_files)
            ):
                snippets = []
                for item in failed_tools[:2]:
                    output = redact_secrets(item.output_summary or "")[-2000:]
                    snippets.append(
                        f"{item.tool_name}: {output}" if output else item.tool_name
                    )
                finding = SecurityFinding(
                    category="baseline dependencies",
                    severity=SecuritySeverity.HIGH,
                    description=(
                        "Residual baseline dependency risk reported by scanners; "
                        "dependency manifests were not modified by this change. "
                        + " | ".join(snippets)
                    ),
                    affected_evidence=[item.tool_name for item in failed_tools],
                    recommendation=(
                        "track baseline dependency risk separately from this change; "
                        "do not block or route to Developer for untouched manifests"
                    ),
                    sources=sources,
                )
                baseline_dependency_findings = [finding]
            else:
                finding = SecurityFinding(
                    category="security tooling", severity=SecuritySeverity.HIGH,
                    description="security validation tool did not pass",
                    affected_evidence=[item.tool_name for item in failed_tools],
                    recommendation="remediate scanner findings and rerun security validation",
                    sources=sources,
                )
                return SecurityReview(
                    status=SecurityStatus.FAIL, highest_severity=SecuritySeverity.HIGH,
                    findings=[finding], recommendations=[finding.recommendation], sources=sources,
                    checklist=_checklist("owasp"),
                )
        if any(phrase in requirement for phrase in (
            "non-expiring", "never expires", "nunca expire", "nunca expira",
            "sin expiración", "sin expiracion",
        )):
            finding = SecurityFinding(
                category="sensitive information",
                severity=SecuritySeverity.HIGH,
                description="password reset tokens must expire",
                affected_evidence=[requirement],
                recommendation="use a 15-minute single-use token",
                sources=sources,
            )
            return SecurityReview(
                status=SecurityStatus.FAIL,
                highest_severity=SecuritySeverity.HIGH,
                findings=[finding],
                recommendations=[finding.recommendation],
                sources=finding.sources,
                checklist=_checklist("sensitive_information"),
                requires_hitl=True,
            )
        if ("any user" in requirement or "arbitrary" in requirement or
            ("cualquier usuario" in requirement and any(phrase in requirement for phrase in (
                "sin requerir sesión", "sin requerir sesion", "sin autorización",
                "sin autorizacion", "únicamente el id", "unicamente el id",
            )))):
            finding = SecurityFinding(
                category="authorization/IDOR",
                severity=SecuritySeverity.HIGH,
                description="resource access must be ownership-authorized",
                affected_evidence=[requirement],
                recommendation="enforce authenticated ownership checks",
                sources=sources,
            )
            return SecurityReview(
                status=SecurityStatus.FAIL,
                highest_severity=SecuritySeverity.HIGH,
                findings=[finding],
                recommendations=[finding.recommendation],
                sources=finding.sources,
                checklist=_checklist("idor"),
                requires_hitl=True,
            )
        if baseline_dependency_findings:
            finding = baseline_dependency_findings[0]
            return SecurityReview(
                status=SecurityStatus.PASS,
                highest_severity=SecuritySeverity.HIGH,
                findings=baseline_dependency_findings,
                recommendations=[finding.recommendation],
                sources=sources,
                checklist=_checklist(),
            )
        return SecurityReview(
            status=SecurityStatus.PASS,
            highest_severity=SecuritySeverity.INFO,
            findings=[],
            recommendations=[],
            sources=sources,
            checklist=_checklist(),
        )
