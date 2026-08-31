import re
from pathlib import Path, PurePosixPath
from typing import Any, ClassVar

from engineering_team.contracts.enums import ActionMode, ToolStatus
from engineering_team.contracts.models import ImplementationResult
from engineering_team.models.context import ContextEnvelope
from engineering_team.repository_evidence import is_credential_path

from .base import AgentBase


class DeveloperAgent(AgentBase[ImplementationResult]):
    role = "Developer"

    _STOP_WORDS: ClassVar[set[str]] = {
        "after", "allow", "authorized", "belonging", "bounded", "change",
        "exactly", "from", "latest", "only", "provide", "return", "safe",
        "that", "their", "this", "using", "with",
    }

    _TARGET_EXTENSIONS: ClassVar[set[str]] = {
        "py", "ts", "tsx", "js", "jsx", "java", "go", "rb", "md", "json",
        "yaml", "yml", "toml", "txt", "cfg", "ini", "sql", "html", "css",
        "c", "cpp", "h", "hpp", "rs", "kt", "swift",
    }
    _SOURCE_EXTENSIONS: ClassVar[set[str]] = _TARGET_EXTENSIONS - {"md", "txt"}

    @classmethod
    def requested_targets(cls, requirement: str) -> list[str]:
        """File paths the requirement text explicitly names, in order of first mention.

        Used only when the caller opts into apply mode — a deterministic,
        auditable way to decide *which* files may be written, independent of
        whatever the LLM later proposes as content.
        """
        targets: list[str] = []
        for token in re.findall(r"[A-Za-z0-9_][A-Za-z0-9_./-]*\.[A-Za-z]+", requirement):
            cleaned = token.rstrip(".,;:()")
            extension = cleaned.rsplit(".", 1)[-1].lower()
            if extension in cls._TARGET_EXTENSIONS and cls._safe_path(cleaned):
                targets.append(cleaned)
        # A directory instruction such as ``tests/`` names no writable file.
        # For a requested public constant, derive a stable, bounded test path so
        # the Developer must satisfy both the implementation and verification.
        constant = re.search(
            r"(?:constante|constant)\s+(?:pública|public)?\s*(?:llamada|called)\s+([A-Z][A-Z0-9_]*)",
            requirement,
            flags=re.IGNORECASE,
        )
        if constant and re.search(r"\btests?/", requirement, flags=re.IGNORECASE):
            targets.append(f"tests/test_{constant.group(1).lower()}.py")
        return list(dict.fromkeys(targets))

    @classmethod
    def apply_targets(
        cls,
        explicit: list[str],
        repository_results: list[Any],
        specification: Any,
        architecture: Any,
        requirement: str,
    ) -> list[str]:
        """Expand a test-only request with one inspected implementation file.

        Apply mode intentionally does not let a model invent writable paths. A
        test specification often names its test file but not the source it
        verifies, however. In that shape, restricting the candidate to the test
        file makes an implementation impossible. The extra path is therefore
        selected deterministically from successful Repository reads, never from
        model text, and only when it has a positive relevance score.
        """
        if not explicit or not any(cls._is_test_path(path) for path in explicit):
            return explicit
        if any(cls._is_source_path(path) for path in explicit):
            return explicit
        terms = [
            *cls.relevance_terms(specification, architecture, requirement),
            *(
                Path(path).stem.removeprefix("test_")
                for path in explicit
                if cls._is_test_path(path)
            ),
        ]
        candidates: list[tuple[int, str]] = []
        for item in repository_results:
            if (
                item.status is not ToolStatus.SUCCESS
                or item.tool_name not in {"read_file", "get_file_content"}
                or not item.input_summary.startswith("path=")
            ):
                continue
            path = item.input_summary[5:].replace("\\", "/")
            suffix = path.rsplit(".", 1)[-1].lower() if "." in path else ""
            if (
                path in explicit
                or cls._is_test_path(path)
                or suffix not in cls._TARGET_EXTENSIONS
                or not cls._safe_path(path)
            ):
                continue
            haystack = f"{path}\n{item.output_summary}".lower()
            score = sum(haystack.count(term.lower()) for term in terms if term)
            if score:
                candidates.append((score, path))
        if not candidates:
            return explicit
        _, source = min(candidates, key=lambda candidate: (-candidate[0], candidate[1]))
        return [source, *explicit]

    @staticmethod
    def _is_test_path(path: str) -> bool:
        normalized = path.replace("\\", "/")
        return normalized.startswith(("test/", "tests/")) or Path(normalized).name.startswith("test_")

    @classmethod
    def _is_source_path(cls, path: str) -> bool:
        suffix = path.rsplit(".", 1)[-1].lower() if "." in path else ""
        return not cls._is_test_path(path) and suffix in cls._SOURCE_EXTENSIONS

    @classmethod
    def relevance_terms(cls, specification: Any, architecture: Any, requirement: str) -> list[str]:
        values = [
            requirement,
            getattr(specification, "objective", ""),
            " ".join(getattr(specification, "business_rules", [])),
            " ".join(getattr(architecture, "components", [])),
            " ".join(getattr(architecture, "apis", [])),
            " ".join(getattr(architecture, "data_changes", [])),
        ]
        terms: list[str] = []
        for token in re.findall(r"[A-Za-z_][A-Za-z0-9_/-]*", " ".join(values).lower()):
            normalized = token.strip("/_-")
            if len(normalized) >= 4 and normalized not in cls._STOP_WORDS:
                terms.append(normalized)
        return list(dict.fromkeys(terms))

    @staticmethod
    def rank_paths(paths: list[str], search_hits: list[str], terms: list[str]) -> list[str]:
        hit_counts = {path: search_hits.count(path) for path in paths}

        def score(path: str) -> tuple[int, int, str]:
            folded = path.casefold()
            term_score = sum(term in folded for term in terms)
            source_score = hit_counts[path]
            code_score = 1 if PurePosixPath(path).suffix in {".py", ".js", ".ts", ".java"} else 0
            return (source_score * 10 + term_score * 4 + code_score, -len(path), path)

        return sorted(paths, key=score, reverse=True)

    @staticmethod
    def _safe_path(path: str) -> bool:
        candidate = PurePosixPath(path.replace("\\", "/"))
        return bool(
            path
            and not candidate.is_absolute()
            and ".." not in candidate.parts
            and "__pycache__" not in candidate.parts
            # El contenido que lee el Developer va literal al prompt y no puede
            # sanearse: debe reescribir el archivo fiel. El control es no leerlo.
            and not is_credential_path(path)
        )

    @staticmethod
    def _symbols(content: str) -> list[str]:
        patterns = (
            r"(?m)^\s*(?:async\s+)?def\s+([A-Za-z_]\w*\s*\([^)]*\))",
            r"(?m)^\s*class\s+([A-Za-z_]\w*)",
        )
        symbols = [match for pattern in patterns for match in re.findall(pattern, content)]
        return list(dict.fromkeys(symbols))[:6]

    def _apply_candidate(
        self,
        requested: list[str],
        repository_results: list[Any],
        specification: Any,
        architecture: Any,
        envelope: ContextEnvelope,
    ) -> ImplementationResult:
        """Deterministic APPLY-mode candidate: decide *which* files change and why.

        The LLM elaborates *what* to write (real file content) — see
        ``_preserves_governed_facts`` in ``llm/runtime.py``, which only governs
        this structural decision (changed_files/evidence/security signal), not
        the code text itself.
        """
        evidence = list(dict.fromkeys(
            (
                f"{item.evidence_reference}#{item.input_summary[5:]}"
                if item.evidence_reference
                and item.tool_name in {"read_file", "get_file_content"}
                and item.input_summary.startswith("path=")
                else item.evidence_reference or f"repository:{item.tool_name}"
            )
            for item in repository_results
            if item.status is ToolStatus.SUCCESS
        )) or [f"requirement:target:{path}" for path in requested]
        objective = getattr(specification, "objective", envelope.current_task)
        apis = ", ".join(getattr(architecture, "apis", [])) or "no API change declared"
        data_changes = (
            ", ".join(getattr(architecture, "data_changes", []))
            or "no data change declared"
        )
        security_terms = " ".join((
            getattr(specification, "source_requirement", ""),
            apis,
            data_changes,
            " ".join(getattr(architecture, "risks", [])),
            str(envelope.state_projection.get("requirement", "")),
        )).lower()
        return ImplementationResult(
            action_mode=ActionMode.APPLIED,
            changed_files=requested,
            diff=(
                "APPLY REQUESTED: author complete replacement content for each path in "
                f"changed_files honoring the requirement. Objective: {objective}."
            ),
            evidence=evidence,
            validation_result=(
                "APPLY validation strategy: write file_contents via Repository MCP, then "
                "run_build/run_linter/run_tests against the target project before Reviewer "
                "sign-off."
            ),
            security_surface_changed=any(
                term in security_terms
                for term in ("api", "auth", "owner", "security", "token", "password", "idor")
            ),
            file_contents={},
        )

    def execute(self, envelope: ContextEnvelope) -> ImplementationResult:
        specification = envelope.state_projection.get("specification")
        architecture = envelope.state_projection.get("architecture")
        repository_results = [
            item for item in envelope.tool_results
            if item.tool_name in {"list_files", "read_file", "search_code", "get_file_content"}
        ]
        repository_context = envelope.state_projection.get("repository_context") or {}
        if repository_context.get("apply_changes"):
            requested = self.requested_targets(
                str(envelope.state_projection.get("requirement", ""))
            )
            requested = self.apply_targets(
                requested,
                repository_results,
                specification,
                architecture,
                str(envelope.state_projection.get("requirement", "")),
            )
            if requested:
                return self._apply_candidate(
                    requested, repository_results, specification, architecture, envelope
                )
        listed_paths: list[str] = []
        search_hits: list[str] = []
        inspected_content: dict[str, str] = {}
        for item in repository_results:
            if item.status is not ToolStatus.SUCCESS:
                continue
            if item.tool_name == "list_files":
                listed_paths.extend(
                    line.strip().replace("\\", "/") for line in item.output_summary.splitlines()
                )
            elif item.tool_name == "search_code":
                search_hits.extend(
                    line.strip().replace("\\", "/") for line in item.output_summary.splitlines()
                )
            elif item.tool_name in {"read_file", "get_file_content"}:
                prefix = "path="
                if item.input_summary.startswith(prefix):
                    path = item.input_summary[len(prefix):].replace("\\", "/")
                    if self._safe_path(path):
                        inspected_content[path] = item.output_summary
        safe_listed = list(dict.fromkeys(path for path in listed_paths if self._safe_path(path)))
        terms = self.relevance_terms(
            specification, architecture, str(envelope.state_projection.get("requirement", ""))
        )
        ranked_paths = self.rank_paths(safe_listed, search_hits, terms)
        inspected_paths = [path for path in ranked_paths if path in inspected_content]
        if search_hits:
            inspected_paths = [path for path in inspected_paths if path in set(search_hits)]
        evidence = list(dict.fromkeys(
            (
                f"{item.evidence_reference}#{item.input_summary[5:]}"
                if item.evidence_reference
                and item.tool_name in {"read_file", "get_file_content"}
                and item.input_summary.startswith("path=")
                else item.evidence_reference or f"repository:{item.tool_name}"
            )
            for item in repository_results
        ))
        if not inspected_paths:
            return ImplementationResult(
                action_mode=ActionMode.PROPOSED,
                changed_files=[],
                diff=(
                    "NO-OP: repository inspection returned no relevant readable file; "
                    "implementation requires bounded search_code/read_file evidence."
                ),
                evidence=evidence or ["repository inspection returned no safe paths"],
                validation_result=(
                    "NO-OP validation: no proposal can be applied until Repository MCP "
                    "returns a relevant inspected file."
                ),
                security_surface_changed=False,
            )

        components = ", ".join(getattr(architecture, "components", [])) or "current component"
        apis = ", ".join(getattr(architecture, "apis", [])) or "no API change declared"
        data_changes = (
            ", ".join(getattr(architecture, "data_changes", []))
            or "no data change declared"
        )
        decisions = "; ".join(getattr(architecture, "decisions", [])) or "preserve design"
        objective = getattr(specification, "objective", envelope.current_task)
        changed_files = inspected_paths[:4]
        proposal = [
            "PROPOSED TECHNICAL CHANGE",
            f"Objective: {objective}",
            f"Components: {components}",
            f"APIs: {apis}",
            f"Data: {data_changes}",
            f"Design decisions: {decisions}",
        ]
        for path in changed_files:
            symbols = self._symbols(inspected_content[path])
            target = ", ".join(symbols) if symbols else "the inspected module boundary"
            proposal.extend([
                f"FILE: {path}",
                f"Observed symbols: {target}",
                f"Technical change: adapt {target} to satisfy {objective}.",
                f"API implications: {apis}.",
                f"Data implications: {data_changes}.",
                f"--- a/{path}",
                f"+++ b/{path}",
                "@@ proposed @@",
                f"+ Update {target} while preserving: {decisions}.",
            ])
        security_terms = " ".join((
            getattr(specification, "source_requirement", ""),
            apis,
            data_changes,
            " ".join(getattr(architecture, "risks", [])),
        )).lower()
        return ImplementationResult(
            action_mode=ActionMode.PROPOSED,
            changed_files=changed_files,
            diff="\n".join(proposal),
            evidence=evidence or [f"repository:list_files:{path}" for path in changed_files],
            validation_result=(
                "PROPOSED validation strategy: run_build, run_linter, and run_tests in the "
                f"isolated workspace after applying changes to {len(changed_files)} inspected path(s)."
            ),
            security_surface_changed=any(
                term in security_terms
                for term in ("api", "auth", "owner", "security", "token", "password", "idor")
            ),
        )
