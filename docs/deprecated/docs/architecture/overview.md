# Architecture

`engineering_team.cli` is the composition root. It constructs adapters and a
single LangGraph `StateGraph`; no agent selects a node or model. Contracts and
configuration form the inner boundary, agents consume `ContextEnvelope`
projections, and adapters (`llm`, `rag`, `mcp`, `workspace`, `observability`)
depend inward without importing graph logic.

`EngineeringState` preserves validated stage artifacts, RAG evidence,
ToolResults, ModelExecutionInfo, errors, iteration, trace correlation and the
FinalReport. Nodes return patches and do not mutate the state in place.

Context isolation is explicit: Product sees only run/requirement; Architecture
receives product output and architecture/API evidence; Developer receives the
bounded design and repository context; Security sees only security/OWASP
evidence and scan results; Testing sees testing/coding evidence and quality
results; Reviewer receives validated summaries and provenance, never raw
repository contents or tool permissions.

Workspaces are copied to `workspace/runs/<run_id>` and Repository MCP resolves
every path beneath that copy. By default (`local_first=true`) cloud is a
sanitized, bounded contingency: Ollama runs every agent and Gemini/Groq only
step in, budget-capped, after a local failure. Setting `CLOUD_ENABLED=true`
and `LOCAL_FIRST=false` reverses the priority — `CloudModelRuntime` becomes
the primary runtime for all six agents (still schema-constrained and
governed-facts-checked, still routed per role through the fixed
Gemini/Groq map) and `LocalModelRuntime`/Ollama becomes the safety-net
fallback if a cloud call fails. Either way, cloud never becomes the
orchestrator: LangGraph routing, guardrails, and governed facts are identical
regardless of which runtime executes a node. Both runtimes build their
prompts from the same role-specific `prompts/<role>/system.md` files via
`engineering_team.llm.prompting`, so provider choice never changes what an
agent is allowed to do.

RAG ingestion uses LangChain Document and RecursiveCharacterTextSplitter as a
small integration layer before Sentence Transformers and persistent Chroma.
Tool execution crosses the official MCP stdio protocol through
`MCPRepositoryClient`/`MCPQualityClient` into independently exposed Repository
and Quality MCP Server surfaces. Quality is divided deliberately: the quality
operations are independent from the runner that executes them, and a stack
profile supplies the commands and image for one component rather than assuming a
repository is Python. The active profiles are Python, JVM/Maven, .NET,
Node/TypeScript and Go.

The container runner is the product boundary for target-project commands. It
can provide the toolchain the target declares, which an operator process cannot:
FlaskApiProduct was verified with Python 3.12 in a container while the operator
used Python 3.14. The process runner and its Darwin/Linux sandbox remain for
local compatibility; Windows uses Docker rather than a separate process sandbox.
The selected runner and image are passed as explicit MCP server arguments, not
inherited environment variables.

`ServiceStack` gives a run its own infrastructure lifetime. A declared Compose
file is primary; ASET starts only `image:` services, removes host ports and
makes declared networks internal. When no Compose exists, topology inference can
derive PostgreSQL, MySQL or MongoDB from project configuration; SQLite yields no
service. A startup or readiness failure is `INFRASTRUCTURE_ERROR`, not evidence
that the target code is defective.

Delivery is separate from Apply. A confirmed proposal can be placed on a new
`aset/` branch and opened as a pull request; the default branch is never a
delivery target. The first real code-change delivery is
[FlaskApiProduct PR #1](https://github.com/full-stack-dev-johncastrosanabria/FlaskApiProduct/pull/1).
ASET selected the right files and reached Testing and Reviewer, but stopped at
`HUMAN_REVIEW_REQUIRED`; an operator corrected the final implementation, reran
the gates and opened the pull request. This proves the branch and review path,
not yet an autonomous clone-to-PR product flow. The UI still accepts local paths
today. GitHub URLs, runner and service visibility, and reviewed PR presentation
are the next frontend capability, tracked in the roadmap rather than implied by
the current UI.
