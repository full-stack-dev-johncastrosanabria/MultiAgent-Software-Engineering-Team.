"""Bounded cloud contingency routing; not normal model selection."""

import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from engineering_team.config import Settings
from engineering_team.contracts.developer_plan import DeveloperTargetPlan, validate_target_plan
from engineering_team.contracts.enums import AgentRole, ErrorCode
from engineering_team.contracts.models import CloudFallbackContext, ModelExecutionInfo
from engineering_team.guardrails.secrets import (
    redacted_for_cloud,
    require_safe_cloud_context,
)
from engineering_team.llm.prompting import build_role_prompts, governed_output_schema
from engineering_team.models.context import ContextEnvelope

from .registry import ModelSelection
from .runtime import _ineffective_remediation_error, _preserves_governed_facts

# Every provider but Google speaks the OpenAI chat-completions shape, so one code
# path serves them all; only the endpoint and the credential differ.
_OPENAI_COMPATIBLE = {
    "groq": ("https://api.groq.com/openai/v1/chat/completions", "groq_api_key"),
    "mistral": ("https://api.mistral.ai/v1/chat/completions", "mistral_api_key"),
    "openrouter": ("https://openrouter.ai/api/v1/chat/completions", "open_router_api_key"),
    # Gateways probed 2026-09-16 with this runtime's JSON request shape and a
    # 22k-token prompt; endpoints taken from each provider's own documentation.
    "xkiro": ("https://api.xkiro.com/v1/chat/completions", "x_kiro_api_key"),
    "vyce": ("https://vyceai.com/v1/chat/completions", "vyce_ai_api_key"),
    "tokenforge": ("https://tokenforge.ai.studio/v1/chat/completions", "token_forge_api_key"),
    "nvidia": ("https://integrate.api.nvidia.com/v1/chat/completions", "nvidia_api_key"),
    "kilo": ("https://api.kilo.ai/api/gateway/chat/completions", "kilo_api_key"),
    "cohere": ("https://api.cohere.ai/compatibility/v1/chat/completions", "cohere_api_key"),
    "cloudflare": (
        "https://api.cloudflare.com/client/v4/accounts/{account}/ai/v1/chat/completions",
        "cloudflare_worker_ai_api",
    ),
}
_CLOUDFLARE_ACCOUNT = re.compile(r"[0-9a-f]{32}")
# Gateway defaults for output length are provider-specific and can truncate a
# Developer's full-file content; state the budget explicitly, as for OpenRouter.
_EXPLICIT_OUTPUT_BUDGET = frozenset({"xkiro", "vyce", "tokenforge", "nvidia", "kilo", "cohere", "cloudflare"})

# Both logical providers use Google's official API. Keeping the second route
# distinct gives its credential and cooldown independent state while ensuring
# the key can never be sent to an OpenAI-compatible destination.
_GOOGLE_CREDENTIALS = {
    "google": "gemini_api_key",
    "google2": "gemini_api_key_2",
}

# Selected from observed role-level results, not catalogue size. See the model
# evaluation in banca-demo-support. Primaries span three providers and the first
# fallback always crosses providers. Google quotas can be model scoped: a 3.6 quota
# failure must not disable a working 3.5 fallback. Testing/Reviewer are deterministic.
_ROLE_CHAINS: dict[AgentRole, tuple[tuple[str, str], ...]] = {
    # Gateway entries were evaluated on 2026-09-16 through this runtime on ASET's
    # own tasks (Product spec, Developer target plan, Developer authoring of real
    # FlaskApiProduct sources, Security review) and in run apply-523385f8, the day
    # Mistral answered 429/503, OpenRouter's Nemotron relayed "overloaded" and
    # Gemini 3.5 answered 503 on both keys. xKiro's deepseek-v4.1-flash passed all
    # four tasks; deepseek-v4-pro passed Security 3/3 and Architecture 2/2. xKiro's
    # free tier is 500k tokens a day per account, so it follows the existing
    # primary and first fallback. Vyce ignores response_format and fences its
    # JSON; once one fenced block was accepted, deepseek-v4-flash passed Product
    # and Security and agnes-3.0-flash passed Developer authoring (not planning).
    # NVIDIA's free endpoints timed out on almost every model; its Nemotron 3
    # Super passed Product and Security and keeps that model off one provider.
    AgentRole.PRODUCT: (
        ("groq", "openai/gpt-oss-120b"),
        ("mistral", "mistral-small-latest"),
        ("xkiro", "deepseek/deepseek-v4.1-flash:free"),
        ("openrouter", "nvidia/nemotron-3-super-120b-a12b:free"),
        ("vyce", "deepseek-v4-flash"),
        ("nvidia", "nvidia/nemotron-3-super-120b-a12b"),
        ("google", "gemini-3.5-flash"),
    ),
    AgentRole.ARCHITECTURE: (
        ("mistral", "mistral-medium-latest"),
        ("groq", "openai/gpt-oss-120b"),
        ("xkiro", "deepseek/deepseek-v4-pro"),
        ("xkiro", "deepseek/deepseek-v4.1-flash:free"),
        # Nemotron spent 117-129 s of this role's deadline in apply-82aaa8c3.
        ("vyce", "agnes-3.0-flash"),
        ("openrouter", "nvidia/nemotron-3-super-120b-a12b:free"),
        ("google", "gemini-3.5-flash"),
    ),
    # Codestral and Small passed the isolated recovery acceptance test. Medium was
    # 0/10 on Developer in the historical runs, although reliable on Architecture.
    # Groq can reject full source payloads with HTTP 413, but does so quickly.
    # Gemini is last after the new 90s timeout; do not spend its wait before Small.
    AgentRole.DEVELOPER: (
        ("mistral", "codestral-latest"),
        ("groq", "openai/gpt-oss-120b"),
        ("xkiro", "deepseek/deepseek-v4.1-flash:free"),
        ("xkiro", "qwen/qwen3-coder-plus:free"),
        ("mistral", "mistral-small-latest"),
        ("vyce", "agnes-3.0-flash"),
        ("google", "gemini-3.5-flash"),
    ),
    AgentRole.SECURITY: (
        ("openrouter", "nvidia/nemotron-3-super-120b-a12b:free"),
        ("groq", "openai/gpt-oss-120b"),
        ("xkiro", "deepseek/deepseek-v4-pro"),
        ("mistral", "mistral-small-latest"),
        ("xkiro", "deepseek/deepseek-v4.1-flash:free"),
        ("vyce", "deepseek-v4-flash"),
        ("nvidia", "nvidia/nemotron-3-super-120b-a12b"),
        ("google", "gemini-3.5-flash"),
    ),
}

# SambaNova was removed, not demoted: all seven models in its catalogue answer
# HTTP 402 ("a payment method is required") on this account, so it has no free tier to
# fall back to and every attempt would be a wasted round trip.

# Probed with the real request shape and deliberately absent from every chain:
#   openai/gpt-oss-120b:free       HTTP 404, no longer offered free by OpenRouter
#   nvidia/nemotron-3-ultra:free   answers 200 with malformed JSON, twice out of two
#   thinkingmachines/inkling:free  HTTP 403, paid plans only
#   z-ai/glm-5.2:free              HTTP 429 from the upstream provider
#   google/gemma-4-*:free          HTTP 429 from the upstream provider
#   ministral-3b-latest            returns valid JSON that omits required fields
#   mistral-large-latest           read timeout
#   gemini-2.5-flash               HTTP 404, no longer available to new users
#   gemini-3.1-flash-lite          failed schema validation on 40% of its responses

_CLOUD_MAP = {
    role: (chain[0][0], chain[0][1]) for role, chain in _ROLE_CHAINS.items()
}
_CLOUD_MAP[AgentRole.TESTING] = ("groq", "openai/gpt-oss-20b")
_CLOUD_MAP[AgentRole.REVIEWER] = ("groq", "openai/gpt-oss-120b")


_FENCED_JSON = re.compile(r"```(?:json)?[ \t]*\n(.*?)\n[ \t]*```", re.DOTALL)


def _json_payload(raw: str) -> str:
    """The answer itself, or its one fenced JSON block.

    Some gateways ignore response_format and wrap the object in a fence, with or
    without prose around it. Exactly one block is unambiguous; anything else is
    returned unchanged and fails validation as before. Schema and governed facts
    are validated after this either way.
    """
    try:
        json.loads(raw)
        return raw
    except ValueError:
        blocks = _FENCED_JSON.findall(raw)
        return blocks[0] if len(blocks) == 1 else raw


class _GovernedContradiction(ValueError):
    def __init__(self, candidate: dict[str, Any], actual: BaseModel) -> None:
        values = actual.model_dump(mode="json")
        self.fields = sorted(key for key, value in candidate.items() if values.get(key) != value)
        # A target plan is expected to differ from its candidate: the model fills
        # the proposal fields. The validator's fixed message is the actual cause.
        self.reason = None
        if isinstance(actual, DeveloperTargetPlan):
            try:
                validate_target_plan(DeveloperTargetPlan.model_validate(candidate), actual,
                                     all_paths=set(candidate.get("inventory_paths", [])))
            except ValueError as exc:
                self.reason = str(exc)
        super().__init__("governed artifact contradiction")


class _IncompleteOutput(ValueError):
    pass


class _IneffectiveRemediation(ValueError):
    pass


class _ProviderReportedError(ValueError):
    """An upstream failure relayed inside a success response.

    Only the numeric code is kept: the message and metadata are provider text.
    """

    def __init__(self, code: int) -> None:
        super().__init__(code)
        self.code = code


def _missing_response_field_detail(exc: KeyError) -> str:
    # Only protocol field names are safe to disclose. KeyError may originate
    # inside a client/transport and carry arbitrary data rather than a field.
    key = exc.args[0] if len(exc.args) == 1 else None
    known_fields = {"candidates", "choices", "content", "message", "parts", "text"}
    field = repr(key) if type(key) is str and key in known_fields else "[REDACTED]"
    return f"KeyError: missing response field {field}"


@dataclass
class AttemptBudget:
    settings: Settings
    retries: dict[str, int] = field(default_factory=dict)
    repairs: dict[str, int] = field(default_factory=dict)

    def consume_retry(self, stage: str) -> bool:
        used = self.retries.get(stage, 0)
        if used >= self.settings.max_local_retries:
            return False
        self.retries[stage] = used + 1
        return True

    def consume_repair(self, stage: str) -> bool:
        used = self.repairs.get(stage, 0)
        if used >= self.settings.max_local_repairs:
            return False
        self.repairs[stage] = used + 1
        return True


@dataclass
class CloudBudget:
    """Bounds cloud usage when cloud is a *fallback*.

    When cloud is the configured primary runtime (``cloud_first``), the caps
    below describe an emergency-contingency budget, not the steady-state
    workload of six agents per run, so ``unlimited`` disables the cap while
    still recording counts for observability/telemetry.
    """

    settings: Settings
    by_agent: dict[AgentRole, int] = field(default_factory=dict)
    run_count: int = 0
    unlimited: bool = False

    def consume(self, role: AgentRole) -> bool:
        if not self.unlimited:
            if self.run_count >= self.settings.max_cloud_escalations_per_run:
                return False
            used = self.by_agent.get(role, 0)
            if used >= self.settings.max_cloud_escalations_per_agent:
                return False
        self.by_agent[role] = self.by_agent.get(role, 0) + 1
        self.run_count += 1
        return True


class CloudRouter:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def for_role(self, role: AgentRole) -> ModelSelection:
        provider, model = _CLOUD_MAP[role]
        return ModelSelection(role, "CLOUD_FALLBACK", provider, model)

    def _override(self, role: AgentRole) -> tuple[tuple[str, str], ...]:
        """Per-role override from settings, as "provider:model,provider:model"."""
        raw = getattr(self._settings, f"cloud_chain_{role.value.lower()}", "") or ""
        parsed = []
        for item in raw.split(","):
            item = item.strip()
            if not item or ":" not in item:
                continue
            provider, _, model = item.partition(":")
            parsed.append((provider.strip(), model.strip()))
        return tuple(parsed)

    def selection_chain(self, role: AgentRole) -> tuple[ModelSelection, ...]:
        """Every cloud model to try for a role, in order, before giving up.

        Cross providers early to limit correlated outages, but keep validated models
        only. Rate limits may be scoped to a model, account, or upstream provider.
        """
        pairs = self._override(role) or _ROLE_CHAINS.get(role)
        if not pairs:
            provider, model = _CLOUD_MAP[role]
            alternate = (
                "openai/gpt-oss-120b"
                if model == "openai/gpt-oss-20b"
                else "openai/gpt-oss-20b"
            )
            return (
                ModelSelection(role, "CLOUD_FALLBACK", provider, model),
                ModelSelection(role, "CLOUD_FALLBACK", provider, alternate),
            )
        seen, chain = set(), []
        for provider, model in pairs:
            if (provider, model) in seen:
                continue
            seen.add((provider, model))
            chain.append(ModelSelection(role, "CLOUD_FALLBACK", provider, model))
        return tuple(chain)

    def enabled_for(self, selection: ModelSelection) -> bool:
        if selection.provider in _GOOGLE_CREDENTIALS:
            key = getattr(self._settings, _GOOGLE_CREDENTIALS[selection.provider], None)
        else:
            entry = _OPENAI_COMPATIBLE.get(selection.provider)
            key = getattr(self._settings, entry[1], None) if entry else None
            if entry and "{account}" in entry[0]:
                # The account id is interpolated into the URL the token is sent to.
                account = self._settings.cloudflare_account_id or ""
                key = key if _CLOUDFLARE_ACCOUNT.fullmatch(account) else None
        return self._settings.cloud_enabled and bool(key)


def _http_category(status: int) -> tuple[str, bool]:
    """Classify a provider HTTP status into a sanitized, actionable cause.

    Never inspect the response body here: only the status code is safe to
    surface without risking a leaked credential or provider-specific detail.
    """
    if status in {401, 403}:
        return "authentication", False
    if status == 404:
        return "model_unavailable", False
    if status == 429:
        return "rate_limit", True
    if status >= 500:
        return "provider_unavailable", True
    return "request_rejected", False


def is_cloud_eligible(error: ErrorCode) -> bool:
    return error in {
        ErrorCode.LLM_AVAILABILITY_ERROR,
        ErrorCode.LLM_QUALITY_ERROR,
        ErrorCode.SECURITY_CONFLICT,
        ErrorCode.AGENT_TIMEOUT,
    }


def build_cloud_context(
    agent: AgentRole,
    task: str,
    requirement: str,
    structured_input: dict[str, object],
    **kwargs: object,
) -> CloudFallbackContext:
    # Redact first, then check what is left. A detected secret becomes
    # [REDACTED] and the context travels; anything the detector still objects to
    # is refused exactly as before.
    task = redacted_for_cloud(task)
    requirement = redacted_for_cloud(requirement)
    structured_input = redacted_for_cloud(structured_input)
    kwargs = redacted_for_cloud(kwargs)
    require_safe_cloud_context(task)
    require_safe_cloud_context(requirement)
    require_safe_cloud_context(structured_input)
    require_safe_cloud_context(kwargs)
    return CloudFallbackContext(
        agent=agent,
        task=task,
        relevant_requirement=requirement,
        structured_input=structured_input,
        validation_error=kwargs.get("validation_error")
        if isinstance(kwargs.get("validation_error"), str)
        else None,
        rag_fragments=list(kwargs.get("rag_fragments", [])),
        code_fragments=list(kwargs.get("code_fragments", [])),
        deterministic_evidence=list(kwargs.get("deterministic_evidence", [])),
    )


class CloudModelRuntime:
    """Validated runtime for Gemini, Groq, Mistral and OpenRouter.

    Usable either as the *fallback* runtime (bounded by ``CloudBudget``, the
    historical role) or as the *primary* runtime for a cloud-first
    configuration (``primary=True``), in which case the per-agent/per-run
    escalation caps are disabled since four model-invoking agents per run is the expected
    steady-state workload, not an emergency contingency.
    """

    def __init__(
        self, settings: Settings, *, client: httpx.Client | None = None,
        trace: Any | None = None, primary: bool = False,
    ) -> None:
        self.settings = settings
        self.router = CloudRouter(settings)
        self.budget = CloudBudget(settings, unlimited=primary)
        self.client = client
        self.trace = trace
        self.primary = primary
        self.attempts: list[ModelExecutionInfo] = []
        self._unavailable_until: dict[tuple[str, str], float] = {}

    def _cooling_until(self, selection: ModelSelection) -> float:
        return max(
            self._unavailable_until.get((selection.provider, "*"), 0),
            self._unavailable_until.get((selection.provider, selection.model), 0),
        )

    def invoke_artifact(
        self,
        role: AgentRole,
        envelope: ContextEnvelope,
        candidate: BaseModel,
        *,
        fallback_reason: str = "CLOUD_FIRST",
        _attempt: int = 0,
        _deadline: float | None = None,
    ) -> tuple[BaseModel, ModelExecutionInfo]:
        chain = self.router.selection_chain(role)
        developer = role is AgentRole.DEVELOPER
        role_timeout = (
            self.settings.developer_role_timeout_seconds if developer
            else self.settings.cloud_role_timeout_seconds
        )
        deadline = _deadline if _deadline is not None else time.monotonic() + role_timeout
        # The budget bounds *escalations*, not the retries within one escalation: every
        # model in the chain is one attempt at the same escalation, so it is consumed
        # once, on entry, and never again as the chain is walked. It must be charged
        # before the credential skip below, otherwise an unconfigured first provider
        # would advance the cursor past this check and escalate for free.
        if _attempt == 0 and not self.budget.consume(role):
            raise RuntimeError("CLOUD_FALLBACK_UNAVAILABLE: disabled, missing credential, or budget")
        # Skip entries whose provider has no usable credential rather than aborting the
        # whole chain on the first unconfigured one.
        start = _attempt
        while True:
            _attempt = start
            while _attempt < len(chain) and (
                not self.router.enabled_for(chain[_attempt])
                or self._cooling_until(chain[_attempt]) > time.monotonic()
            ):
                _attempt += 1
            if _attempt < len(chain):
                break
            # Every usable model is cooling down. Waiting for the earliest one,
            # within the role deadline, is an attempt; failing at once made a
            # stage retry touch nothing. A credential failure never expires.
            resume = min(
                (self._cooling_until(item) for item in chain[start:] if self.router.enabled_for(item)),
                default=float("inf"),
            )
            if resume >= deadline:
                raise RuntimeError("CLOUD_FALLBACK_UNAVAILABLE: disabled, missing credential, or budget")
            time.sleep(max(0.0, resume - time.monotonic()))
        selection = chain[_attempt]
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("CLOUD_FALLBACK_UNAVAILABLE: role deadline exceeded")
        request_timeout = min(
            self.settings.developer_llm_timeout_seconds if developer else self.settings.llm_timeout_seconds,
            remaining,
        )
        candidate_dict = candidate.model_dump(mode="json")
        output_schema = governed_output_schema(type(candidate), candidate_dict)
        system_prompt, user_prompt = build_role_prompts(
            role, envelope, output_schema, candidate_dict
        )
        safe_context = build_cloud_context(
            role, envelope.current_task,
            str(envelope.state_projection.get("requirement", "")),
            {"candidate": candidate_dict},
            deterministic_evidence=[item.chunk_id for item in envelope.rag_evidence],
        )
        system_prompt = redacted_for_cloud(system_prompt)
        user_prompt = redacted_for_cloud(user_prompt)
        require_safe_cloud_context(system_prompt)
        require_safe_cloud_context(user_prompt)
        owns_client = self.client is None
        client = self.client or httpx.Client(timeout=request_timeout)
        started = time.perf_counter()
        try:
            if selection.provider in _GOOGLE_CREDENTIALS:
                credential = _GOOGLE_CREDENTIALS[selection.provider]
                response = client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{selection.model}:generateContent",
                    headers={"x-goog-api-key": getattr(self.settings, credential, None) or ""},
                    timeout=request_timeout,
                    json={
                        "systemInstruction": {"parts": [{"text": system_prompt}]},
                        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
                        "generationConfig": {
                            "temperature": 0,
                            "responseMimeType": "application/json",
                            "responseJsonSchema": output_schema,
                        },
                    },
                )
                response.raise_for_status()
                payload = response.json()
                raw = payload["candidates"][0]["content"]["parts"][0]["text"]
                usage = payload.get("usageMetadata")
            else:
                endpoint, credential = _OPENAI_COMPATIBLE[selection.provider]
                endpoint = endpoint.replace("{account}", self.settings.cloudflare_account_id or "")
                schema_mode = (selection.provider == "mistral" or
                    (selection.provider == "openrouter" and selection.model != "minimax/minimax-m3:free"))
                response_format = ({"type": "json_schema", "json_schema": {
                    "name": type(candidate).__name__, "schema": output_schema, "strict": True,
                }} if schema_mode else {"type": "json_object"})
                provider_options = ({"provider": {
                    "require_parameters": True, "max_price": {"prompt": 0, "completion": 0},
                }, "max_tokens": 16000 if role is AgentRole.DEVELOPER else 4096,
                    "reasoning": {"effort": "low", "exclude": True},
                } if selection.provider == "openrouter" else {
                    "max_tokens": 16000 if role is AgentRole.DEVELOPER else 4096,
                } if selection.provider in _EXPLICIT_OUTPUT_BUDGET else {})
                response = client.post(
                    endpoint,
                    headers={
                        "Authorization": f"Bearer {getattr(self.settings, credential, None) or ''}"
                    },
                    timeout=request_timeout,
                    json={
                        "model": selection.model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        "temperature": 0,
                        "response_format": response_format,
                        **provider_options,
                    },
                )
                response.raise_for_status()
                payload = response.json()
                relayed = payload.get("error") if isinstance(payload, dict) else None
                if "choices" not in payload and isinstance(relayed, dict) and type(relayed.get("code")) is int:
                    raise _ProviderReportedError(relayed["code"])
                if payload["choices"][0].get("finish_reason") == "length":
                    raise _IncompleteOutput("model output reached its token limit")
                raw = payload["choices"][0]["message"]["content"]
                usage = payload.get("usage")
            artifact = type(candidate).model_validate_json(_json_payload(raw))
            if not _preserves_governed_facts(candidate.model_dump(mode="json"), artifact):
                raise _GovernedContradiction(candidate_dict, artifact)
            remediation_error = _ineffective_remediation_error(
                role, envelope, artifact
            )
            if remediation_error is not None:
                raise _IneffectiveRemediation(remediation_error)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            category, retryable = _http_category(status)
            if status in {401, 402, 403, 429, 503}:
                cooldown = 30.0
                hint = exc.response.headers.get("Retry-After")
                if hint:
                    try:
                        cooldown = max(0, float(hint))
                    except ValueError:
                        try:
                            cooldown = max(0, (parsedate_to_datetime(hint) - datetime.now(timezone.utc)).total_seconds())
                        except (ValueError, TypeError, OverflowError):
                            pass
                if status in {401, 402, 403}:
                    cooldown = float("inf")
                # A quota/capacity failure can be model-specific (observed with
                # Gemini 3.6 vs 3.5). Only credential/payment errors disable the
                # whole provider; preserve healthy alternate models.
                key = (selection.provider, "*" if status in {401, 402, 403} else selection.model)
                self._unavailable_until[key] = time.monotonic() + cooldown
            error = f"CLOUD_FALLBACK_UNAVAILABLE: {category} (HTTP {status})"
            info = ModelExecutionInfo(
                agent=role, provider=selection.provider, requested_model=selection.model,
                actual_model=None, model_profile=selection.model_profile,
                fallback_used=not self.primary,
                fallback_reason=None if self.primary else fallback_reason,
                degraded=True,
                latency_ms=int((time.perf_counter() - started) * 1000),
                structured_output_success=False, error=error,
                http_status=status, error_category=category, retryable=retryable,
            )
            self.attempts.append(info)
            if self.trace is not None:
                self.trace.record(
                    f"{role.value} cloud {'primary' if self.primary else 'fallback'}",
                    as_type="generation",
                    metadata=info.model_dump(mode="json"), level="ERROR",
                    status_message=error,
                )
            if _attempt + 1 < len(chain):
                return self.invoke_artifact(
                    role, envelope, candidate, fallback_reason=fallback_reason,
                    _attempt=_attempt + 1,
                    _deadline=deadline,
                )
            raise RuntimeError(error) from exc
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError, ValidationError) as exc:
            contradiction = isinstance(exc, _GovernedContradiction)
            ineffective = isinstance(exc, _IneffectiveRemediation)
            relayed_category = (
                _http_category(exc.code)[0] if isinstance(exc, _ProviderReportedError) else None
            )
            detail = (
                f"{relayed_category} (provider error {exc.code})"
                if relayed_category else
                f"target plan rejected: {exc.reason}"
                if contradiction and exc.reason else
                f"governed fields differ: {', '.join(exc.fields)}"
                if contradiction else
                "unchanged developer remediation"
                if ineffective else
                "schema validation: " + ", ".join(sorted({e["type"] for e in exc.errors(include_input=False)}))
                if isinstance(exc, ValidationError) else
                _missing_response_field_detail(exc)
                if isinstance(exc, KeyError) else type(exc).__name__
            )
            error = (
                "LLM_QUALITY_ERROR: unchanged developer remediation"
                if ineffective
                else f"CLOUD_FALLBACK_UNAVAILABLE: {detail}"
            )
            info = ModelExecutionInfo(
                agent=role, provider=selection.provider, requested_model=selection.model,
                actual_model=None, model_profile=selection.model_profile,
                fallback_used=not self.primary,
                fallback_reason=None if self.primary else fallback_reason,
                degraded=True,
                latency_ms=int((time.perf_counter() - started) * 1000),
                structured_output_success=False, error=error,
                error_category=relayed_category or (
                    "governed_contradiction" if contradiction else
                    "ineffective_remediation" if ineffective else
                    "incomplete_output" if isinstance(exc, _IncompleteOutput) else
                    "timeout" if isinstance(exc, httpx.TimeoutException) else
                    "schema_validation" if isinstance(exc, ValidationError) else "invalid_response"
                ),
                retryable=True,
            )
            self.attempts.append(info)
            if self.trace is not None:
                self.trace.record(
                    f"{role.value} cloud {'primary' if self.primary else 'fallback'}",
                    as_type="generation",
                    metadata=info.model_dump(mode="json"), level="ERROR",
                    status_message=error,
                )
            if _attempt + 1 < len(chain):
                try:
                    return self.invoke_artifact(
                        role, envelope, candidate, fallback_reason=fallback_reason,
                        _attempt=_attempt + 1,
                        _deadline=deadline,
                    )
                except RuntimeError as fallback_error:
                    # A later failure otherwise chains this unsanitized KeyError.
                    if isinstance(exc, KeyError):
                        raise fallback_error from None
                    raise
            # Keep arbitrary KeyError arguments out of rendered tracebacks too.
            cause = None if isinstance(exc, KeyError) else exc
            raise RuntimeError(error) from cause
        finally:
            if owns_client:
                client.close()
        info = ModelExecutionInfo(
            agent=role, provider=selection.provider, requested_model=selection.model,
            actual_model=selection.model, model_profile=selection.model_profile,
            # This runtime serves both slots. Reporting a fallback from the
            # primary one made every cloud-first run look degraded, and the
            # trace beside it already said 'primary' -- the record
            # contradicted itself.
            fallback_used=not self.primary,
            fallback_reason=None if self.primary else fallback_reason,
            latency_ms=int((time.perf_counter() - started) * 1000), usage=usage,
            structured_output_success=True,
        )
        self.attempts.append(info)
        if self.trace is not None:
            self.trace.record(
                f"{role.value} cloud {'primary' if self.primary else 'fallback'}",
                as_type="generation",
                input={"system_prompt": system_prompt, "user_prompt": user_prompt},
                output={"response": raw}, model=selection.model,
                metadata={
                    **info.model_dump(mode="json"),
                    "safe_context": safe_context.model_dump(mode="json"),
                },
                usage_details=usage,
            )
        return artifact, info
