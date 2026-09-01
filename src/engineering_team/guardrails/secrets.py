"""Secret redaction and outbound payload validation."""

import ast
import json
import re
from collections.abc import Iterable
from typing import Any

_SENSITIVE_KEYS = {
    "api_key", "apikey", "secret", "secret_key", "access_token", "password",
    "gemini_api_key", "groq_api_key", "langfuse_secret_key",
    "mistral_api_key", "open_router_api_key", "openrouter_api_key",
}


def _without_plain_string_annotations(text: str) -> str:
    """Mask syntax, never credential values, while scanning complete Python files.

    Work on source spans rather than unparse: comments and defaults must remain
    visible to the secret detector. A typed default becomes `password = ...`.
    """
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return text
    lines = text.encode().splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    source = text.encode()
    spans = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.arg, ast.AnnAssign)):
            continue
        annotation = node.annotation
        if not isinstance(annotation, ast.Name) or annotation.id != "str":
            continue
        start = offsets[node.lineno - 1] + node.col_offset
        annotation_start = offsets[annotation.lineno - 1] + annotation.col_offset
        end = offsets[annotation.end_lineno - 1] + annotation.end_col_offset
        colon = source.rfind(b":", start, annotation_start)
        if colon < 0:
            continue
        # Pydantic validation metadata with no default is a declaration, not a
        # password assignment. Only numeric length bounds are exempted.
        value = node.value if isinstance(node, ast.AnnAssign) else None
        if (isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
                and value.func.id == "Field" and not value.args and value.keywords
                and all(kw.arg in {"min_length", "max_length"}
                        and isinstance(kw.value, ast.Constant)
                        and type(kw.value.value) is int for kw in value.keywords)):
            end = offsets[node.end_lineno - 1] + node.end_col_offset
        # A multiline annotation/Field call may contain a comment with a secret.
        # Conservatively keep that whole span; syntax masking must never hide it.
        if b"#" in source[colon:end]:
            continue
        spans.append((colon, end))
    for start, end in sorted(spans, reverse=True):
        source = source[:start] + source[end:]
    masked = source.decode()
    # Docstrings are documentation, not assignments. Mask their parameter lines after
    # the annotation pass, and only where the description is prose.
    try:
        parsed = ast.parse(masked)
    except (SyntaxError, ValueError):
        return masked
    docstrings = []
    for node in ast.walk(parsed):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        doc = ast.get_docstring(node, clean=False)
        if doc:
            docstrings.append(doc)
    for doc in docstrings:
        replacement = _without_documented_parameters(doc)
        if replacement != doc:
            masked = masked.replace(doc, replacement)
    return masked


# A credential-shaped run: long, unbroken, and mixing letters with digits or symbols.
# Prose never looks like this, and a leaked value almost always does.
_CREDENTIAL_LIKE = re.compile(r"[A-Za-z0-9+/=_\-]{16,}")


def _is_prose(description: str) -> bool:
    """True when a description reads as documentation rather than a value.

    Requires whitespace (a bare value has none) and the absence of any
    credential-shaped run, so `password: hunter2` and
    `password: my key is aB3xQ9tZ7LmW2pR4` both stay visible to the detector.
    """
    stripped = description.strip()
    if not stripped or " " not in stripped:
        return False
    return not _CREDENTIAL_LIKE.search(stripped)


_DOC_PARAM = re.compile(
    r"(?im)^(?P<indent>[ \t]*)(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?P<sep>[ \t]*:[ \t]*)(?P<text>\S.*)$"
)


def _without_documented_parameters(text: str) -> str:
    """Neutralise Google/NumPy-style `name: description` lines inside docstrings.

    `nueva_password: Nueva contraseña para el usuario.` documents an argument; it
    carries no value. Only the separator is removed, and only when the description is
    prose, so a docstring that really does embed a credential is still reported.
    """

    def mask(match: re.Match[str]) -> str:
        if not _is_prose(match.group("text")):
            return match.group()
        return f"{match.group('indent')}{match.group('name')} {match.group('text')}"

    return _DOC_PARAM.sub(mask, text)


_ENV_FILE = re.compile(r"\.env\b", re.IGNORECASE)
_SECRET_KEY_PATTERN = (
    r"api[_-]?key|access[_-]?token|token|password|secret(?:[_-]?key)?"
)
_QUOTED_SECRET_VALUE = re.compile(
    rf"(?i)(?P<prefix>['\"]?(?:{_SECRET_KEY_PATTERN})['\"]?\s*[=:]\s*)"
    r'''(?:(?P<double>"(?:\\.|[^"\\])*")|(?P<single>'(?:\\.|[^'\\])*'))'''
)
_UNQUOTED_SECRET_VALUE = re.compile(
    rf"(?i)({_SECRET_KEY_PATTERN})\s*[=:]\s*[^\s,]+"
)


def _scan_text(text: str) -> str:
    text = _without_plain_string_annotations(text)
    text = re.sub(
        r"(```python\n)(.*?)(\n```)",
        lambda match: match[1] + _without_plain_string_annotations(match[2]) + match[3],
        text, flags=re.DOTALL,
    )
    # Prompt envelopes contain JSON-encoded source strings. Decode only complete
    # JSON string literals and apply the same syntax-aware masking to their text.
    def mask(match: re.Match[str]) -> str:
        try:
            decoded = json.loads(match.group())
        except ValueError:
            return match.group()
        return json.dumps(_without_plain_string_annotations(decoded), ensure_ascii=False)
    return re.sub(r'"(?:\\.|[^"\\])*"', mask, text)


def redact_secrets(value: str, known_values: Iterable[str] = ()) -> str:
    redacted = value
    for secret in known_values:
        if secret:
            redacted = redacted.replace(secret, "[REDACTED]")
    def redact_quoted(match: re.Match[str]) -> str:
        quote = '"' if match.group("double") else "'"
        return match.group("prefix") + quote + "[REDACTED]" + quote

    redacted = _QUOTED_SECRET_VALUE.sub(redact_quoted, redacted)
    return _UNQUOTED_SECRET_VALUE.sub(r"\1=[REDACTED]", redacted)


def _names_a_credential_file(name: str) -> bool:
    """Imported lazily: repository_evidence depends on this module, not the other
    way round, and a top-level import would close the cycle."""
    from engineering_team.repository_evidence import is_credential_path

    return is_credential_path(name)


def require_safe_cloud_context(value: Any) -> None:
    if isinstance(value, dict):
        if any(str(key).lower() in _SENSITIVE_KEYS for key in value):
            raise ValueError("sensitive content is not allowed in cloud context")
        # A structure that names a credential file *and* carries content is
        # presenting that file's contents. Structural, not textual: prose that
        # mentions .env is a project explaining itself, while {"file": ".env",
        # "content": ...} is the file itself. Unreachable through the repository
        # ports, which never read such a path, and kept as the layer beneath them.
        named = next(
            (str(value[k]) for k in ("file", "path", "filename") if k in value), ""
        )
        if named and _names_a_credential_file(named) and any(
            k in value for k in ("content", "contents", "body", "text")
        ):
            raise ValueError("sensitive content is not allowed in cloud context")
        for item in value.values():
            require_safe_cloud_context(item)
        return
    if isinstance(value, (list, tuple, set)):
        for item in value:
            require_safe_cloud_context(item)
        return
    text = str(value)
    # Checks content, not filenames. Mentioning a .env file is not a secret: a
    # comment saying where configuration comes from, a .gitignore entry, a setup
    # document explaining it. Measured against a real repository that mention
    # appeared in five files, and `os.environ` matched too because `.environ`
    # begins with `.env` -- the Developer stage could not run at all.
    #
    # The contents of such a file never reach a prompt, and not because of this
    # check: `safe_repository_path` admits only an allowlist of source suffixes,
    # and `is_credential_path` excludes .env by name on top of that. Refusing the
    # mention as well bought nothing and cost every project that has one.
    if re.search(
        r"(?i)(api[_-]?key|access[_-]?token|password|secret)\s*[=:]\s*[^\s,]+",
        _scan_text(text),
    ):
        raise ValueError("sensitive content is not allowed in cloud context")
