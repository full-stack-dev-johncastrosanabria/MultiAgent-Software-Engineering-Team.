import re
from pathlib import PurePosixPath
from typing import Any, ClassVar

from engineering_team.contracts.enums import AgentRole, ToolStatus
from engineering_team.contracts.models import ArchitectureProposal
from engineering_team.models.context import ContextEnvelope
from engineering_team.repository_evidence import bounded_utf8, result_path

from .base import AgentBase


class ArchitectureAgent(AgentBase[ArchitectureProposal]):
    role = "Architecture"

    _STOP_WORDS: ClassVar[set[str]] = {
        "and", "architecture", "bounded", "change", "design", "for", "from",
        "implement", "model", "service", "that", "the", "this", "using", "with",
    }

    @classmethod
    def relevance_terms(
        cls, specification: Any, requirement: str, feedback: str = ""
    ) -> list[str]:
        """Terms that decide which files this stage reads.

        `feedback` is what the Reviewer said when it sent the work back. Without
        it the function is pure in the specification and the requirement, neither
        of which a remediation changes, so a rejected design re-read the same
        files, proposed the same interfaces and was rejected again. The names in
        a failure -- the module that would not import, the attribute that did not
        exist -- are exactly the terms that would have found the missing file.
        """
        values = [
            feedback,
            requirement,
            getattr(specification, "objective", ""),
            " ".join(getattr(specification, "business_rules", [])),
            " ".join(getattr(specification, "acceptance_criteria", [])),
        ]
        terms = []
        for token in re.findall(r"[A-Za-z_][A-Za-z0-9_-]*", " ".join(values).lower()):
            normalized = token.strip("_-")
            if len(normalized) >= 4 and normalized not in cls._STOP_WORDS:
                terms.append(normalized)
        return list(dict.fromkeys(terms))

    @staticmethod
    def rank_paths(paths: list[str], search_hits: list[str], terms: list[str]) -> list[str]:
        hits = {path: search_hits.count(path) for path in paths}

        def score(path: str) -> tuple[int, int, str]:
            folded = path.casefold()
            lexical = sum(term in folded for term in terms)
            source = hits[path]
            suffix = PurePosixPath(path).suffix.casefold()
            code = suffix in {".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".java", ".rs"}
            manifest = PurePosixPath(path).name.casefold() in {
                "pyproject.toml", "package.json", "go.mod", "cargo.toml",
            }
            return (source * 20 + lexical * 5 + int(code) * 2 + int(manifest), -len(path), path)

        return sorted(paths, key=score, reverse=True)

    @staticmethod
    def _component(path: str) -> str:
        without_suffix = str(PurePosixPath(path).with_suffix(""))
        for prefix in ("src/", "app/", "lib/"):
            if without_suffix.startswith(prefix):
                return without_suffix[len(prefix):]
        return without_suffix

    @staticmethod
    def _symbols(content: str) -> list[str]:
        return list(dict.fromkeys([
            *re.findall(r"(?m)^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)", content),
            *re.findall(
                r"(?m)^\s*(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)", content
            ),
        ]))[:6]

    @staticmethod
    def _read_reference(item: Any, path: str) -> str:
        base = item.evidence_reference or f"repository:{item.tool_name}"
        return f"{base}#{path}"

    def execute(self, envelope: ContextEnvelope) -> ArchitectureProposal:
        latest_reads: dict[str, Any] = {}
        for item in reversed(envelope.tool_results):
            if (
                item.status is ToolStatus.SUCCESS
                and item.allowed_role is AgentRole.ARCHITECTURE
                and item.tool_name in {"read_file", "get_file_content"}
                and (path := result_path(item.input_summary))
                and path not in latest_reads
            ):
                latest_reads[path] = item

        inspected: dict[str, str] = {}
        read_sources: list[str] = []
        for path, item in list(latest_reads.items())[:4]:
            inspected[path] = bounded_utf8(item.output_summary)
            read_sources.append(self._read_reference(item, path))

        rag_sources = [item.chunk_id for item in envelope.rag_evidence]
        sources = list(dict.fromkeys([*read_sources, *rag_sources]))
        components = list(dict.fromkeys(
            f"{symbol} ({path})"
            for path, content in inspected.items()
            for symbol in self._symbols(content)
        ))
        components.extend(
            component for path in inspected
            if (component := self._component(path)) not in components
            and not self._symbols(inspected[path])
        )
        if not components:
            components = ["modular monolith (repository evidence unavailable)"]

        joined = "\n".join(inspected.values())
        folded = joined.casefold()
        apis = list(dict.fromkeys(
            f"{method.upper()} {route}"
            for _, method, route in re.findall(
                r"@(app|router)\.(get|post|put|patch|delete)\([\"']([^\"']+)", joined
            )
        ))[:8]
        data_changes = []
        if re.search(r"\b(create|alter|drop)\s+table\b|\bmigration\b", folded):
            data_changes.append("schema or migration behavior in inspected repository files")
        integrations = []
        for marker, label in (
            ("queue", "message queue"), ("publish(", "event publication"),
            ("http", "HTTP service"), ("database", "database"), ("execute(", "database"),
        ):
            if marker in folded:
                integrations.append(label)
        integrations = list(dict.fromkeys(integrations))
        dependencies = list(dict.fromkeys(
            match.split(".")[0]
            for match in re.findall(
                r"(?m)^\s*(?:from|import)\s+([A-Za-z_][A-Za-z0-9_.]*)", joined
            )
        ))[:8]
        decisions = []
        for path, content in inspected.items():
            content_folded = content.casefold()
            symbols = self._symbols(content)
            boundary = ", ".join(symbols) or self._component(path)
            if any(term in content_folded for term in ("token", "password", "jwt", "auth")):
                decisions.append(
                    f"Keep {boundary} behind an authentication boundary in {path}"
                )
            if any(term in content_folded for term in ("queue", "publish(", "event")):
                rag_text = " ".join(item.fragment for item in envelope.rag_evidence).casefold()
                if "outbox" in rag_text:
                    decisions.append(
                        f"Use a transactional outbox for event publication from {boundary}"
                    )
                else:
                    decisions.append(
                        f"Keep asynchronous event publication and retry handling in {boundary}"
                    )
            if any(term in content_folded for term in ("execute(", "database", "migration")):
                decisions.append(
                    f"Isolate persistence and transaction handling behind {boundary}"
                )
            if not any(path in item for item in decisions):
                decisions.append(f"Maintain {boundary} as the bounded component represented by {path}")
        if not decisions:
            decisions = ["Require repository read evidence before making file-specific decisions"]
        risks = []
        if any(term in folded for term in ("token", "password", "jwt", "auth")):
            risks.append("Authentication-sensitive behavior requires threat-focused validation")
        if any(term in folded for term in ("todo", "fixme", "pass\n", "...")):
            risks.append("Inspected implementation contains incomplete behavior")
        if any(term in folded for term in ("execute(", "migration", "create table")):
            risks.append("Data integrity and rollback behavior require validation")
        if any(term in folded for term in ("queue", "publish(", "event")):
            risks.append("Event delivery, idempotency, and failure recovery require validation")
        if not risks:
            risks.append(
                "Architecture confidence is limited to the bounded repository and RAG evidence supplied"
            )
        inspected_label = ", ".join(components)
        return ArchitectureProposal(
            components=components,
            apis=apis,
            data_changes=data_changes,
            integrations=integrations,
            dependencies=dependencies,
            decisions=decisions,
            risks=risks,
            impact=(
                f"Change affects {inspected_label}; grounded by {len(inspected)} repository "
                f"read(s) and {len(envelope.rag_evidence)} RAG source(s)"
                if inspected
                else "No repository-grounded impact can be asserted until readable evidence exists"
            ),
            evidence_references=sources,
        )
