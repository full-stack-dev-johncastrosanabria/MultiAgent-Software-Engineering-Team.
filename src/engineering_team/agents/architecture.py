import re
from pathlib import PurePosixPath
from typing import Any, ClassVar

from engineering_team.contracts.enums import AgentRole, ToolStatus
from engineering_team.contracts.models import ArchitectureProposal
from engineering_team.models.context import ContextEnvelope
from engineering_team.repository_evidence import (
    ARCHITECTURE_ENVELOPE_BYTES,
    MAX_ARCHITECTURE_READ_BYTES,
    MAX_ARCHITECTURE_READ_CANDIDATES,
    MIN_ARCHITECTURE_SLICE_BYTES,
    bounded_redacted_text,
    budgeted_slices,
    result_path,
)

from .base import AgentBase


class ArchitectureAgent(AgentBase[ArchitectureProposal]):
    role = "Architecture"

    _STOP_WORDS: ClassVar[set[str]] = {
        "and", "architecture", "bounded", "change", "design", "for", "from",
        "implement", "model", "service", "that", "the", "this", "using", "with",
    }

    @staticmethod
    def task_boundary_paths(paths: list[str], requirement: str) -> list[str]:
        """Find source boundaries named by an HTTP request, without an LLM guess.

        Broad domain searches (for example ``stock``) often find analytics before
        the blueprint that owns ``/api/products/...``. A route and its model are
        mandatory evidence for that request even when their content does not use
        the endpoint's final path segment.
        """
        available = set(paths)
        mentioned = {
            match.group(0).replace("\\", "/")
            for match in re.finditer(r"(?<![A-Za-z0-9_./-])[A-Za-z0-9_./-]+\.[A-Za-z0-9]+", requirement)
        }
        resources: set[str] = set()
        for route in re.findall(
            r"\b(?:get|post|put|patch|delete)\s+(/[^\s,;]+)", requirement, re.IGNORECASE
        ):
            for segment in route.split("/"):
                normalized = segment.casefold().strip("-_")
                if normalized and normalized not in {"api", "v1", "v2"}:
                    resources.add(normalized)
        resource_stems = set(resources)
        for resource in tuple(resources):
            if resource.endswith("ies") and len(resource) > 3:
                resource_stems.add(resource[:-3] + "y")
            elif resource.endswith("s") and len(resource) > 1:
                resource_stems.add(resource[:-1])

        candidates: list[tuple[int, str]] = []
        for path in available:
            folded = path.casefold()
            stem = PurePosixPath(path).stem.casefold()
            if path in mentioned:
                candidates.append((0, path))
            if stem not in resource_stems:
                continue
            if "/routes/" in f"/{folded}" or "/controllers/" in f"/{folded}":
                candidates.append((1, path))
            elif "/models/" in f"/{folded}" or "/domain/" in f"/{folded}":
                candidates.append((2, path))

        # One path can be named directly and also be a conventional boundary.
        priorities: dict[str, int] = {}
        for priority, path in candidates:
            priorities[path] = min(priority, priorities.get(path, priority))
        return [path for path, _ in sorted(priorities.items(), key=lambda item: (item[1], item[0]))]

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
        route_aliases: set[str] = set()
        for token in re.findall(r"[A-Za-z_][A-Za-z0-9_-]*", " ".join(values).lower()):
            normalized = token.strip("_-")
            if len(normalized) >= 4 and normalized not in cls._STOP_WORDS:
                terms.append(normalized)
                # A product requirement normally spells an HTTP route with a
                # hyphen, while implementation symbols use underscores.
                if "-" in normalized:
                    alias = normalized.replace("-", "_")
                    terms.append(alias)
                    route_aliases.add(alias)
        first_seen = {term: index for index, term in enumerate(terms)}
        frequency = {term: terms.count(term) for term in first_seen}
        # The graph can issue only three bounded searches. A repeated domain term
        # such as "stock" is a better discriminator than the opening verb of a
        # requirement, and it reaches supporting modules whose path has no API name.
        return sorted(
            first_seen,
            key=lambda term: (
                -int(term in route_aliases), -frequency[term], -len(term), first_seen[term],
            ),
        )

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
        for item in envelope.tool_results:
            if (
                item.status is ToolStatus.SUCCESS
                and item.allowed_role is AgentRole.ARCHITECTURE
                and item.tool_name in {"read_file", "get_file_content"}
                and (path := result_path(item.input_summary))
            ):
                latest_reads.pop(path, None)
                latest_reads[path] = item

        inspected: dict[str, str] = {}
        read_sources: list[str] = []
        reads = list(latest_reads.items())[-MAX_ARCHITECTURE_READ_CANDIDATES:]
        sizes = [len(item.output_summary.encode("utf-8")) for _, item in reads]
        slices, _ = budgeted_slices(
            sizes,
            MAX_ARCHITECTURE_READ_BYTES,
            minimum=MIN_ARCHITECTURE_SLICE_BYTES,
            overhead=ARCHITECTURE_ENVELOPE_BYTES,
        )
        for (path, item), budget in zip(reads, slices, strict=False):
            if budget <= 0:
                continue
            inspected[path] = bounded_redacted_text(item.output_summary, budget)
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
