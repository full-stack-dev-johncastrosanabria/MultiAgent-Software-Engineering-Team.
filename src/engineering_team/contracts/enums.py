from enum import StrEnum


class AgentRole(StrEnum):
    PRODUCT = "Product"
    ARCHITECTURE = "Architecture"
    DEVELOPER = "Developer"
    SECURITY = "Security"
    TESTING = "Testing"
    REVIEWER = "Reviewer"


class ReviewerStatus(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class SecuritySeverity(StrEnum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class SecurityStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"


class ActionMode(StrEnum):
    PROPOSED = "PROPOSED"
    APPLIED = "APPLIED"


class ToolStatus(StrEnum):
    SUCCESS = "SUCCESS"
    FAIL = "FAIL"
    DENIED = "DENIED"
    UNAVAILABLE = "UNAVAILABLE"


class RemediationCategory(StrEnum):
    ARCHITECTURE = "ARCHITECTURE"
    IMPLEMENTATION = "IMPLEMENTATION"
    SECURITY = "SECURITY"
    TESTING = "TESTING"


class RouteTarget(StrEnum):
    ARCHITECTURE = "Architecture"
    DEVELOPER = "Developer"
    TESTING = "Testing"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"


class ErrorCode(StrEnum):
    LLM_AVAILABILITY_ERROR = "LLM_AVAILABILITY_ERROR"
    LLM_QUALITY_ERROR = "LLM_QUALITY_ERROR"
    SECURITY_CONFLICT = "SECURITY_CONFLICT"
    TOOL_ERROR = "TOOL_ERROR"
    RAG_ERROR = "RAG_ERROR"
    CLOUD_FALLBACK_UNAVAILABLE = "CLOUD_FALLBACK_UNAVAILABLE"
    MCP_ERROR = "MCP_ERROR"
    # A dependency the project needs never became ready. Distinct from
    # TOOL_ERROR on purpose: the code under test was never given a chance to
    # run, so reporting it as a failing test points remediation at the wrong
    # thing -- the misleading headline finding 7 describes.
    INFRASTRUCTURE_ERROR = "INFRASTRUCTURE_ERROR"
    AGENT_TIMEOUT = "AGENT_TIMEOUT"


class StopCause(StrEnum):
    # Why a run stopped, named once by the graph from its own typed state.
    # The audit had to reconstruct this afterwards from the last error's text,
    # which is how a refused answer came to be reported as a provider outage.
    # One vocabulary, defined here, so the graph and the scorer cannot drift.
    APPROVED = "approved"
    PROVIDER_CHAIN_EXHAUSTED = "provider_chain_exhausted"
    ITERATION_LIMIT = "iteration_limit"
    STAGNATION = "stagnation"
    MCP_UNAVAILABLE = "mcp_unavailable"
    # The provider answered and this system refused the content: a governed
    # contradiction, a rejected target plan, a truncated generation. Folding
    # these into PROVIDER_CHAIN_EXHAUSTED is exactly the A-09 defect -- one in
    # four "chain unavailable" events in the 2026-09-16 campaign was ours.
    LLM_QUALITY_REJECTED = "llm_quality_rejected"
    # Same name apply_run.py already gives this outcome in its evidence dict.
    DESTRUCTIVE_AUTHORIZATION_BLOCKED = "destructive_authorization_blocked"
    WRITE_FAILED = "write_failed"
    # Never produced inside the graph: a crashed run never reaches the node
    # that names its cause. It exists for the scorer, which sees the exit code.
    CRASH = "crash"
    UNKNOWN = "unknown"
