"""Bounded, transport-neutral helpers for repository evidence."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator
from pathlib import PurePosixPath
from typing import Any

from engineering_team.guardrails.secrets import redact_secrets

MAX_ARCHITECTURE_READ_FILES = 4
MAX_ARCHITECTURE_READ_BYTES = 16 * 1024
MAX_ARCHITECTURE_LIST_BYTES = 8 * 1024
MAX_ARCHITECTURE_SEARCH_BYTES = 8 * 1024
MAX_ARCHITECTURE_RAW_EVIDENCE_BYTES = 64 * 1024
MAX_ARCHITECTURE_JSON_DEPTH = 64
MAX_ARCHITECTURE_JSON_NODES = 4_096
MAX_REPOSITORY_PATH_INPUT_BYTES = 4 * 1024 * 1024
MAX_REPOSITORY_PATH_DEPTH = 64
MAX_REPOSITORY_PATH_NODES = 100_000
MAX_REPOSITORY_PATHS = 50_000

_EXCLUDED_PARTS = {
    ".aws", ".git", ".gnupg", ".secrets", ".ssh", ".venv", "__pycache__",
    "node_modules", "secrets",
}
_EXCLUDED_NAMES = {
    ".env", ".npmrc", ".pypirc", "credentials", "credentials.json",
    "id_dsa", "id_ed25519", "id_rsa",
}
_ALLOWED_NAMES = {
    "cargo.lock", "cargo.toml", "dockerfile", "go.mod", "go.sum", "package-lock.json",
    "package.json", "pnpm-lock.yaml", "pom.xml", "pyproject.toml", "readme", "readme.md",
    "settings.gradle", "yarn.lock",
    "compose.yaml", "compose.yml", "docker-compose.yaml", "docker-compose.yml",
    "jsconfig.json", "tsconfig.json",
}
_ALLOWED_SUFFIXES = {
    ".c", ".cc", ".cpp", ".cs", ".css", ".dart", ".go", ".gradle", ".h", ".hpp",
    ".html", ".java", ".js", ".jsx", ".kt", ".kts", ".lock", ".md",
    ".php", ".proto", ".py", ".rb", ".rs", ".rst", ".scala", ".sh", ".sql",
    ".swift", ".toml", ".ts", ".tsx", ".vue", ".xml", ".yaml", ".yml",
}
_ASSIGNMENT = re.compile(
    r"(?i)\b([A-Za-z_][A-Za-z0-9_-]{0,63})(\s*[=:]\s*)([^\s,;]+)"
)
_PEM_BEGIN = re.compile(r"-----BEGIN ((?:[A-Z0-9]+ )?PRIVATE KEY)-----")
_SENSITIVE_NAME_MARKERS = {
    "credential", "private-key", "private_key", "secret", "service-account", "service_account",
}


def _sensitive_json_key(key: object) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(key).casefold()).strip("_")
    return normalized in {
        "api_key", "access_token", "authorization", "credential", "credentials",
        "password", "passwd", "private_key", "secret", "token",
    } or normalized.endswith((
        "_api_key", "_access_token", "_credential", "_password", "_private_key",
        "_secret", "_token",
    ))


def _redact_json_keys(
    value: Any, *, depth: int = 0, nodes: list[int] | None = None,
) -> Any:
    if nodes is None:
        nodes = [0]
    nodes[0] += 1
    if nodes[0] > MAX_ARCHITECTURE_JSON_NODES:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        if depth >= MAX_ARCHITECTURE_JSON_DEPTH:
            return "[TRUNCATED]"
        return {
            key: (
                "[REDACTED]" if _sensitive_json_key(key)
                else _redact_json_keys(item, depth=depth + 1, nodes=nodes)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        if depth >= MAX_ARCHITECTURE_JSON_DEPTH:
            return "[TRUNCATED]"
        return [_redact_json_keys(item, depth=depth + 1, nodes=nodes) for item in value]
    return value


def _redact_sensitive_assignment(match: re.Match[str]) -> str:
    if not _sensitive_json_key(match.group(1)):
        return match.group(0)
    return f"{match.group(1)}{match.group(2)}[REDACTED]"


def _redact_pem_private_keys(value: str) -> str:
    """Redact complete or unterminated PEM blocks with a forward-only scan."""
    output: list[str] = []
    cursor = 0
    while match := _PEM_BEGIN.search(value, cursor):
        output.append(value[cursor:match.start()])
        output.append("[REDACTED PEM PRIVATE KEY]")
        end_marker = f"-----END {match.group(1)}-----"
        end = value.find(end_marker, match.end())
        if end < 0:
            return "".join(output)
        cursor = end + len(end_marker)
    output.append(value[cursor:])
    return "".join(output)


def _closing_quote(value: str, start: int, quote: str) -> int | None:
    cursor = start
    while cursor < len(value):
        if value[cursor] == "\\":
            cursor += 2
            continue
        if value[cursor] == quote:
            return cursor
        cursor += 1
    return None


def _redact_quoted_sensitive_values(value: str) -> str:
    """Redact complete or cap-truncated quoted values with a forward-only scan."""
    output: list[str] = []
    emit_cursor = 0
    scan_cursor = 0
    while scan_cursor < len(value):
        double = value.find('"', scan_cursor)
        single = value.find("'", scan_cursor)
        starts = [position for position in (double, single) if position >= 0]
        if not starts:
            break
        key_start = min(starts)
        quote = value[key_start]
        key_end = _closing_quote(value, key_start + 1, quote)
        if key_end is None:
            break
        key = value[key_start + 1:key_end]
        cursor = key_end + 1
        while cursor < len(value) and value[cursor].isspace():
            cursor += 1
        if cursor >= len(value) or value[cursor] != ":":
            scan_cursor = key_end + 1
            continue
        cursor += 1
        while cursor < len(value) and value[cursor].isspace():
            cursor += 1
        if cursor >= len(value) or value[cursor] not in {'"', "'"}:
            scan_cursor = cursor
            continue
        value_quote = value[cursor]
        value_end = _closing_quote(value, cursor + 1, value_quote)
        if not _sensitive_json_key(key):
            if value_end is None:
                break
            scan_cursor = value_end + 1
            continue
        output.append(value[emit_cursor:cursor + 1])
        output.append("[REDACTED]")
        output.append(value_quote)
        if value_end is None:
            emit_cursor = len(value)
            return "".join(output)
        emit_cursor = value_end + 1
        scan_cursor = value_end + 1
    output.append(value[emit_cursor:])
    return "".join(output)


def is_credential_path(raw_path: str) -> bool:
    """True si la ruta nombra material de credenciales, sin opinar sobre el resto.

    Se comparte con el Developer, que necesita EXACTAMENTE esta parte y no la
    allowlist de sufijos: debe poder escribir archivos nuevos de cualquier tipo,
    pero nunca leer una clave privada -su contenido va literal al prompt-.
    """
    candidate = PurePosixPath(raw_path.strip().replace("\\", "/"))
    folded = tuple(part.casefold() for part in candidate.parts)
    return (
        any(part in _EXCLUDED_PARTS for part in folded)
        or candidate.name.casefold() in _EXCLUDED_NAMES
        or any(part == ".env" or part.startswith(".env.") for part in folded)
        or any(marker in part for part in folded for marker in _SENSITIVE_NAME_MARKERS)
    )


def safe_repository_path(raw_path: str) -> str | None:
    """Normalize a relative, non-secret repository path or reject it.

    Symlink containment remains enforced by RepositoryMCP, which resolves the
    actual filesystem entry. This preflight prevents an untrusted listing from
    asking that boundary to inspect an absolute, traversal, cache, or secret
    path.
    """
    normalized = raw_path.strip().replace("\\", "/")
    candidate = PurePosixPath(normalized)
    folded_parts = tuple(part.casefold() for part in candidate.parts)
    filename = candidate.name.casefold()
    if (
        not normalized
        or candidate.is_absolute()
        or ".." in candidate.parts
        or any(part in _EXCLUDED_PARTS for part in folded_parts)
        or filename in _EXCLUDED_NAMES
        or filename.startswith(".env.")
        or any(
            marker in part for part in folded_parts for marker in _SENSITIVE_NAME_MARKERS
        )
        or (filename not in _ALLOWED_NAMES and candidate.suffix.casefold() not in _ALLOWED_SUFFIXES)
    ):
        return None
    return candidate.as_posix()


def bounded_utf8(value: str, limit: int = MAX_ARCHITECTURE_READ_BYTES) -> str:
    """Return at most ``limit`` UTF-8 bytes without splitting a code point."""
    prefix = value[:limit]
    encoded = prefix.encode("utf-8")
    if len(encoded) <= limit and len(prefix) == len(value):
        return value
    if len(encoded) <= limit:
        return prefix
    return encoded[:limit].decode("utf-8", errors="ignore")




# `(?:-\s+)?` tolera el guion de item de lista: en un `kind: List` el Secret
# llega como `- kind: Secret`, y sin eso el fallback no lo reconocia.
SECRET_MANIFEST_PLACEHOLDER = "[EXCLUDED: Kubernetes Secret manifest]"

# Deliberadamente permisiva y sin anclas de linea: tolera indentacion, guion de
# item, comillas, flow style, ancla en el valor y CRLF, y encuentra el kind
# aunque venga embebido en el scalar de otro documento.
#
# Excluir en vez de redactar invierte el costo de los falsos positivos: de mas
# cuesta un archivo menos de evidencia; de menos cuesta un secreto enviado a un
# proveedor cloud. Por eso conviene errar hacia excluir, y por eso ya no hace
# falta parsear YAML no confiable -lo que elimina de paso toda la superficie de
# bombas de alias, agotamiento de presupuesto y fallos de parseo-.
# `(?:[&!]\S+\s+|[|>][-+0-9]*\s+)*` cubre lo que YAML admite entre los dos puntos
# y el valor: ancla (`&a`), tag explicito (`!!str`) y escalar de bloque (`|`, `>`).
_SECRET_MANIFEST = re.compile(
    r"""['"]?\bkind['"]?\s*:\s*(?:[&!]\S+\s+|[|>][-+0-9]*\s+)*['"]?Secret""",
    re.IGNORECASE,
)


def is_secret_manifest(value: str) -> bool:
    """True si el texto declara un `kind: Secret` en cualquier forma."""
    return _SECRET_MANIFEST.search(value) is not None


def bounded_redacted_text(value: str, limit: int) -> str:
    """Redact credential-shaped assignments before retaining bounded evidence."""
    # Antes de recortar, no despues: YAML no impone orden de claves, asi que un
    # `kind: Secret` puede caer mas alla del tope mientras su `data:` queda dentro.
    if is_secret_manifest(value):
        return SECRET_MANIFEST_PLACEHOLDER
    raw = bounded_utf8(value, MAX_ARCHITECTURE_RAW_EVIDENCE_BYTES)
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, RecursionError, TypeError):
        redacted = raw
    else:
        try:
            redacted = json.dumps(
                _redact_json_keys(parsed), ensure_ascii=False, separators=(",", ":")
            )
        except RecursionError:
            redacted = raw
    redacted = _redact_pem_private_keys(redacted)
    redacted = _redact_quoted_sensitive_values(redacted)
    redacted = _ASSIGNMENT.sub(_redact_sensitive_assignment, redact_secrets(redacted))
    return bounded_utf8(redacted, limit)


def summarize_path_tool_result(
    result: Any, *, limit: int = MAX_ARCHITECTURE_LIST_BYTES,
) -> Any:
    """Persist bounded listing metadata while callers retain full safe paths ephemerally."""
    paths = parse_repository_paths(result.output_summary)
    selected: list[str] = []
    prefix = f'{{"total_paths":{len(paths)},"selected_paths":['
    # ``false`` is the longer boolean spelling, so this remains a safe upper bound.
    suffix = '],"truncated":false}'
    used = len(prefix.encode("utf-8")) + len(suffix.encode("utf-8"))
    for path in paths:
        encoded = json.dumps(path, ensure_ascii=False).encode("utf-8")
        separator = 1 if selected else 0
        if used + separator + len(encoded) > limit:
            break
        selected.append(path)
        used += separator + len(encoded)
    summary = {
        "total_paths": len(paths),
        "selected_paths": selected,
        "truncated": len(selected) < len(paths),
    }
    return result.model_copy(update={
        "output_summary": json.dumps(summary, ensure_ascii=False, separators=(",", ":")),
        "error": (
            bounded_redacted_text(result.error, 2 * 1024) if result.error is not None else None
        ),
    })


def bounded_rag_evidence(item: Any, limit: int) -> Any:
    """Redact and fit every textual RAG field inside one serialized-object budget."""
    text_fields = ("source", "section", "version", "chunk_id", "fragment", "domain", "query")
    updates = {
        field: bounded_redacted_text(str(getattr(item, field)), MAX_ARCHITECTURE_READ_BYTES)
        for field in text_fields
    }
    bounded = item.model_copy(update=updates)

    def size() -> int:
        payload = json.dumps(
            bounded.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")
        )
        return len(payload.encode("utf-8"))

    while size() > limit:
        largest = max(text_fields, key=lambda field: len(getattr(bounded, field).encode("utf-8")))
        value = getattr(bounded, largest)
        current_size = len(value.encode("utf-8"))
        if current_size == 0:
            break
        target = max(0, current_size - (size() - limit) - 1)
        bounded = bounded.model_copy(update={largest: bounded_utf8(value, target)})
    return bounded


def _paths_from_json(
    value: Any, *, frontier_observer: Callable[[int], None] | None = None
) -> list[str]:
    """Extract paths within explicit depth, node, and result limits.

    The frontier holds one lazy iterator per open container instead of the expanded
    children, so a list of 500k entries costs a single stack slot rather than 500k.
    Its size therefore tracks nesting depth, never sibling width.
    """
    paths: list[str] = []
    stack: list[Iterator[tuple[Any, int]]] = []
    nodes = 0

    def observe() -> None:
        if frontier_observer is not None:
            frontier_observer(len(stack))

    def descend(current: Any, depth: int) -> Iterator[tuple[Any, int]] | None:
        """Record a direct hit, or return the children to walk lazily."""
        nonlocal nodes
        nodes += 1
        if depth > MAX_REPOSITORY_PATH_DEPTH:
            return None
        if isinstance(current, str):
            paths.append(current)
            return None
        if isinstance(current, list):
            return ((item, depth + 1) for item in current)
        if not isinstance(current, dict):
            return None
        path = current.get("path") or current.get("relative_path")
        if isinstance(path, str):
            paths.append(path)
            return None
        for key in ("paths", "files", "items", "entries", "results"):
            if key in current:
                return iter([(current[key], depth + 1)])
        return None

    root = descend(value, 0)
    if root is not None:
        stack.append(root)
    observe()
    while stack and nodes < MAX_REPOSITORY_PATH_NODES and len(paths) < MAX_REPOSITORY_PATHS:
        child = next(stack[-1], None)
        if child is None:
            stack.pop()
            observe()
            continue
        nested = descend(child[0], child[1])
        if nested is not None:
            stack.append(nested)
        observe()
    return paths


def parse_repository_paths(output_summary: str) -> list[str]:
    """Parse both legacy newline listings and future typed/paginated JSON pages."""
    raw = bounded_utf8(output_summary, MAX_REPOSITORY_PATH_INPUT_BYTES)
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, RecursionError, TypeError):
        candidates = raw.splitlines()[:MAX_REPOSITORY_PATHS]
    else:
        candidates = _paths_from_json(parsed)
    safe = [path for item in candidates if (path := safe_repository_path(str(item)))]
    return list(dict.fromkeys(safe))


def result_path(input_summary: str) -> str | None:
    if not input_summary.startswith("path="):
        return None
    return safe_repository_path(input_summary.removeprefix("path="))
