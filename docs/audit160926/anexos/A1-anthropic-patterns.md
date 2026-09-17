> Papel de trabajo de la auditoría del 2026-09-16 (docs/audit160926), conservado tal como lo entregó su auditor, salvo rutas locales sustituidas por `~` y `<scratchpad>`. No es documentación vigente: las conclusiones adjudicadas están en las páginas de la auditoría y en el registro de hallazgos.

# A1 — ASET audited against Anthropic's "Building effective agents"

Auditor: A1. Date: 2026-09-16. Repo: `gh-run-testing` @ 92742b7. I did not modify the repo.
Runtime evidence:
- Langfuse export `~/Downloads/1789609787428-lf-events-export-…json`: 2839 observations, 17 traces.
- 16 raw ghcycle reports dated 2026-09-16 (`evaluation/benchmarks/ghcycle/results/raw/*-dry-20260916*-run.json`).

I computed every aggregate with Python over those files and printed only the aggregates. Paths are relative to the repo root.

---

## 0. Executive classification

**ASET is a workflow. It is not a multi-agent system in Anthropic's sense.** No LLM chooses a transition, a tool, a tool argument, or when to stop.

- **Framework.** The "StateGraph" is real LangGraph 1.2.11 (`graph/stategraph.py:8-10`, `.venv/.../langgraph-1.2.11.dist-info`). Every edge is a pure Python predicate (`graph/routers.py:1`, "Pure deterministic graph routing functions"; `stategraph.py:893-946`).
- **Tools.** Code calls every MCP tool (`stategraph.py:287-557`). In the Langfuse window, all 1649 TOOL observations were started by the orchestrator and none by a model. The model never sees a tool schema. `allowed_tools` is computed (`models/context.py:217`) but never rendered into a prompt (`llm/prompting.py:148-191`).
- **What the six "agents" actually are:**

| Role | Deterministic Python produces | LLM call? | What the LLM is allowed to change |
|---|---|---|---|
| Product | keyword heuristic (`agents/product.py:13-19`) | yes, 1 | may *add* rules/criteria; governed lists must be kept (`llm/runtime.py:326-355`) |
| Architecture | full proposal from ranked reads (`agents/architecture.py:205`) | yes, 1 | **nothing**: `actual == candidate` (`llm/runtime.py:293-297`) |
| Developer | target-plan candidate + write scope | yes, 2 (plan, author) | plan fields (validated by `validate_target_plan`), and `file_contents` (full files) |
| Security | scanner- and keyword-driven review (`agents/security.py:71-201`) | yes, 1 | governed status/severity/findings/sources must be kept (`runtime.py:336-374`) |
| Testing | deterministic gate | **no** (`stategraph.py:600-603`) | — |
| Reviewer | deterministic gate (`agents/reviewer.py:170-415`) | **no** (`stategraph.py:600-603`) | — |

**Runtime proof that two LLM steps are pure echo.** 81 of 81 successful Architecture and Security generations returned JSON byte-for-byte equal to the candidate artifact in their prompt. To check this I parsed `Candidate artifact:` from `user_prompt` and compared it with the parsed `response`.

In practice ASET is **a deterministic prompt chain with programmatic gates** plus **one generator (Developer) inside an evaluator-optimizer loop** whose evaluator is code. That is a defensible architecture. The problems are that:
- the LLM calls around the generator add failure surface without adding value;
- the evaluator's criteria are partly non-objective;
- the loop often does not deliver the ground truth to the generator.

---

## (a) Actual control flow

The legend shows who decides each edge. **[C]** means Python code; **[LLM]** marks a model call inside a node. No edge is decided by a model.

```mermaid
flowchart TD
  S([START]) --> P
  subgraph P["Product node"]
    P1["ProductAgent.execute (keyword heuristic)"] --> P2["[LLM] cloud chain 10 models → local Ollama fallback<br/>elaborate spec, governed lists kept"]
  end
  P -->|"[C] human_review_required?"| H
  P -->|"[C] else"| A
  subgraph A["Architecture node"]
    A0["[C] RAG retrieve"] --> A1["[C] MCP list_files, search_code×3 (terms from code), read_file ≤24 (ranked by code)"]
    A1 --> A2["[C] ArchitectureAgent.execute + evidence_sufficiency ratio"]
    A2 --> A3["[LLM] echo: output MUST == candidate"]
  end
  A -->|"[C]"| H
  A -->|"[C]"| D
  subgraph D["Developer node"]
    D1["[C] MCP list_files, search_code×6, read_file ×4 + deps ≤4"] --> D2["[C] plan_candidate + project_facts"]
    D2 --> D3["[LLM] DeveloperTargetPlan"]
    D3 --> D4["[C] validate_target_plan gate; read planned paths ≤192KB"]
    D4 --> D5["[LLM] author full files as JSON strings (file_contents)"]
    D5 --> D6["[C] scope gate, ast.parse(.py), authorize_writes gate"]
    D6 --> D7["[C] MCP update_file/create_file, get_diff"]
  end
  D -->|"[C] testing_only & no security surface"| T
  D -->|"[C] else"| SEC
  D -->|"[C]"| H
  subgraph SEC["Security node"]
    S1["[C] MCP scan_dependencies, run_security_scan (containers)"] --> S2["[C] SecurityAgent.execute"] --> S3["[LLM] near-echo: status/severity/findings kept"]
  end
  SEC -->|"[C] CRITICAL"| SH[security_hitl]
  SEC -->|"[C] else"| T
  SEC -->|"[C]"| H
  subgraph T["Testing node — no LLM"]
    T1["[C] MCP run_tests (container, full suite)"] --> T2["[C] TestingAgent lexical coverage mapping"]
  end
  T -->|"[C]"| R
  T -->|"[C]"| H
  subgraph R["Reviewer node — no LLM"]
    R1["[C] rule cascade: RAG_ERROR → Security FAIL → tests fail (+ arch evidence_sufficient=False ⇒ ARCHITECTURE) → impl evidence → coverage gate → APPROVED"]
  end
  R -->|"[C] APPROVED"| F[FinalReport] --> E([END])
  R -->|"[C] iteration≥5 / repeats≥3 / invalid target"| H[HUMAN_REVIEW_REQUIRED]
  R -->|"[C] category ARCHITECTURE or repeats==2"| A
  R -->|"[C] else"| D
  H -->|"interactive_hitl (tests only)"| D
  H -->|"production"| E
  SH --> E
```

What happens inside every `[LLM]` box (`stategraph.py:604-682`, `llm/cloud.py:428-721`):

```
for stage_attempt in 0..model_stage_retries(=1):
    primary = CloudModelRuntime(primary=True, budget unlimited)
        chain = health.ordered(role, _ROLE_CHAINS[role])      # 10–11 provider/model pairs
        for model in chain (skip no-credential / cooling; sleep until earliest cooldown ≤ role deadline):
            POST (temperature 0, json_schema|json_object, reasoning low+excluded)
            parse (accept one fenced block) → schema → governed-facts → ineffective-remediation
            on any failure: record metadata only, recurse to next model
    on failure → LocalModelRuntime (Ollama, think=False): 1 retry + 1 repair
    on failure → stage retry (whole thing again) → else human_review_required=True
```

The loop in numbers:
- **Logical LLM calls.** First pass has 5 (Product 1, Architecture 1, Developer 2, Security 1). A remediation routed to Architecture adds 4; one routed to Developer adds 3. The worst case is 5 + 5×4 = 25.
- **Physical attempts in the raw runs.** Across the 16 raw 2026-09-16 runs, `model_usage` has a median of 30 entries and a maximum of 51.
- **Success rate in Langfuse.** 14–51 GENERATION observations per trace; 188 of 478 (39%) were successful.

---

## (b) Pattern mapping

| Anthropic pattern | ASET location | Justified by the task? | Simpler alternative | Evidence |
|---|---|---|---|---|
| **Augmented LLM** (retrieval, tools, memory) | Code injects RAG and MCP results into the prompt (`stategraph.py:266-557`, `prompting.py:129-340`). The model has no tools and no memory; typed state is the memory (`contracts/state.py:29`). | Yes. Orchestrated retrieval suits a bounded code-change task. | — | 1649 of 1649 tool calls came from the orchestrator |
| **Prompt chaining + programmatic gates** | Product → Architecture → Developer(plan → author) → Security, with gates: `validate_target_plan` (`stategraph.py:730-751`), `_preserves_governed_facts` (`runtime.py:282-375`), write-scope check (`stategraph.py:783-796`), `ast.parse` (`runtime.py:319-324`), destructive authorization (`stategraph.py:803-824`). | **Partly.** The Developer plan→author chain with gates is well justified. The Architecture and Security steps are not "chain steps" at all, because the LLM may not change their output. | Delete the Architecture and Security LLM calls; keep the deterministic artifacts. Keep the Product LLM only if its elaboration is measured to help. | 81 of 81 Architecture+Security successes were identical to the candidate; 4 of 17 traces ended on an echo-step model failure (§d F2) |
| **Routing** | `developer_next` (testing_only vs full, `stategraph.py:893-910`), `security_route` (`routers.py:69-70`), `review_route` (`routers.py:40-66`). All are code-classified. | Yes. The categories come from deterministic Reviewer rules, so an LLM classifier would add nothing. | — (already simple) | `tests/graph/test_routers.py` |
| **Parallelization** (sectioning/voting) | None. Security and Testing run sequentially (`stategraph.py:1000-1011`). There is no voting. | Voting is not needed (tests are the oracle). Sectioning scans and tests could save wall time, but ordering matters for `security_hitl`. | Optional: run `scan_dependencies` concurrently with `run_tests` and join before Reviewer. | Runs take 2.5–22.6 min (`duration_seconds`, raw reports) |
| **Orchestrator-workers** | Not present. The closest is `DeveloperTargetPlan`: the LLM proposes read/edit/new paths and code executes them (`stategraph.py:687-779`). That is plan-then-execute, not dynamic worker dispatch. | Correctly avoided for single-requirement changes. | — | — |
| **Evaluator-optimizer** | Generator: Developer LLM. Evaluator: deterministic Testing + Reviewer. Loop ≤ 5 (`config.py:35`), stagnation breaker (`routers.py:62-65`). | **Yes in principle.** Tests are a clear criterion. **In practice** the criteria include non-objective lexical and structural gates (F3, F4), and the loop drops the evaluator's feedback on 26 of 42 transitions (F1). | Evaluate on *tests only* (baseline regressions + acceptance tests). Make coverage and architecture-sufficiency advisory. Always pass failing-test diagnostics to the Developer. | 0 of 42 Reviewer decisions APPROVED; spring-demo-d had tests SUCCESS in 5 of 5 iterations and was rejected 5× |
| **Autonomous agent loop** | Not present. No LLM-directed tool loop and no model-chosen stopping. | Honestly avoided. ASET's "agents" label overstates what exists. | If exploration is ever needed, a single coding agent with read/search/edit/test tools in the existing sandbox would replace roughly 1,000 lines of ranking heuristics (`stategraph.py:287-446`, `agents/developer.py`, `repository_evidence.py`). | — |
| **Model fallback chains** (not an Anthropic pattern; an availability layer) | 12 provider endpoints; 10–11-model chain per role; cooldowns; health ledger; local fallback; stage retry (`llm/cloud.py:29-158`, `llm/model_health.py`, `stategraph.py:604-682`). | Motivated by free-tier 429/503. Not justified by outcomes: 290 of 478 attempts failed, and the local fallback succeeded 0 of 26 times. | One paid, reliable model per role with a short retry. Alternatively, remove the echo roles, which would cut chain demand by about 55% of attempts. | §c P1 |

---

## (c) Scorecard (0–5)

### Principle 1 — Simplicity: **1 / 5**

**Moving parts counted in code:**
- **Graph.** 6 role nodes and 3 terminal nodes. One 640-line node factory with 21 `role is/in AgentRole` branches (`stategraph.py:248-888`) holds all per-role orchestration.
- **LLM call sites.** 5 per first pass, up to 25 logical per run; median 30 and maximum 51 physical attempts per raw run.
- **Providers and models.** 10 OpenAI-compatible endpoints plus 2 Google keys (12 logical providers). 10 are used in chains, with 18 distinct provider/model pairs and 10–11 entries per role chain (`cloud.py:67-137`). `tokenforge` is configured but in no chain (`cloud.py:39,53`).
- **Recovery and fallback layers, stacked:**
  1. fenced-JSON salvage (`cloud.py:164-177`)
  2. provider-relayed error decoding (`cloud.py:567-569`)
  3. per-model cooldown with `Retry-After` and in-node `time.sleep` (`cloud.py:466-475, 585-602`)
  4. model-health reordering ledger (`model_health.py`, `cloud.py:439-440`)
  5. recursive chain walk (`cloud.py:622-627, 679-690`)
  6. local Ollama fallback with retry and repair (`runtime.py:84-231`)
  7. stage retry (`stategraph.py:605-667`)
  8. remediation loop ≤5 (`config.py:35`)
  9. fingerprint stagnation breaker with forced Architecture reroute (`routers.py:62-65`)
  10. Architecture unseen-file rotation (`stategraph.py:339-357`)
- **Budgets.** The cloud budget is disabled in the default cloud-first mode (`cloud.py:246-269, 407`; `apply_run.py:344-349`).

**Is the complexity earned?** No measured improvement:
- ghcycle: 0 of 25 `all_stages_passed` (brief; `docs/status.md:5-10`).
- Raw 2026-09-16 runs: 16 of 16 ended `HUMAN_REVIEW_REQUIRED`.
- Langfuse window: 0 of 42 Reviewer approvals.
- Layer yields: the local fallback succeeded 0 of 26 times; stage retries recovered 6 of 16 stages, and 10 of 16 still ended in human review.

**Tuning churn:**
- 33 commits since 2026-09-13, 31 of them on 2026-09-16.
- +2101/−279 lines in `src/`, +2468 in `tests/`, +74 in `docs/`.
- `llm/cloud.py` changed in 17 of its 22 lifetime commits after 2026-09-13.
- `d8cd3f3` (17:25, "try the next model on later remediations") was reverted by `31defca` (18:17, 52 min later) on the evidence of two runs.
- Chain orders are justified in commit messages with 2–4 probe samples (`762ec08`: "passed Security 3/3 and Architecture 2/2"). The comments cite an evaluation that exists only under `docs/deprecated/demo-projects/banca-demo-support/MODEL_EVALUATION.md` (no authority). I found no committed harness that reproduces the 2026-09-16 gateway probes; confidence 0.7, since a grep miss is not proof of absence.

### Principle 2 — Transparency: **3 / 5**

Strengths:
- Typed contracts for every stage (`contracts/models.py:23-244`), including the plan contract (`contracts/developer_plan.py`).
- Route events carry from/to/iteration/repeated_failures (`stategraph.py:893-946`), plus per-cycle `review_history` (`stategraph.py:867-869`).
- The Developer target plan is traced (`stategraph.py:764-768`).
- Successful generations record full system prompt, user prompt and raw response: 188 of 188 have both input and output.
- The run projection keeps decisions per cycle (`run_events.py:237-290`).

Weaknesses:
- **Failed cloud generations record metadata only** (`cloud.py:615-621, 672-678`). 264 of 290 failed generations have no prompt and no response, so "governed fields differ" (27 Security, 19 Developer, 9 Architecture) cannot be inspected.
- **Errors are misclassified.** A chain failure raises `CLOUD_FALLBACK_UNAVAILABLE: <last model's error>` (`cloud.py:649-653, 693`). The graph maps any message not prefixed `LLM_QUALITY_ERROR`/`AGENT_TIMEOUT` to `LLM_AVAILABILITY_ERROR` and marks it retryable (`stategraph.py:614-632`). Quality failures such as contradictions therefore surface as the *last* model's 503 or timeout. Langfuse: all 26 `LLM_AVAILABILITY_ERROR` spans carry `CLOUD_FALLBACK_UNAVAILABLE: …` messages.
- **Tool inputs are masked.** `search_code` input is always `query=bounded` (`mcp/server.py:45`; 427 observations). Writes, tests and scans show `input_summary="safe"` (`mcp/repository.py:63`, `mcp/quality.py:745`). You cannot tell from the trace what was searched.
- **21 of 44 multi-component scan results** have no `evidence_reference` (CompositeQuality aggregation).
- **Doc drift:**
  - `docs/architecture/overview.md:141-143` says the third rejection ends automation, but the default is 5 (`config.py:35`) and Langfuse shows `iteration=5` terminations.
  - `overview.md:32` lists 4 cloud providers; there are 12.
- **Dead or contradictory prompt artifacts:**
  - Reviewer and Testing `system.md` are never sent to a model.
  - The 6 `user.md` templates are never loaded (no loader in `src/`; `prompting.py:64` reads only `system.md`).

### Principle 3 — Agent-computer interface: **2 / 5**

The design choice to keep tools behind the orchestrator is sound for a workflow: validation, path restriction and timeouts all sit outside the model. The *model-facing* interface, however, contradicts Appendix 2.

1. **Format overhead: code inside JSON, full-file rewrites.**
   - The author must return complete files as JSON string values keyed by path, with `const` schema pins (`prompting.py:35-49, 94-116`).
   - Measured on 44 successful authoring responses: median 7.8 KB and 190 escaped `\n`; maximum 16.9 KB and 390.
   - The prompt has to warn "JSON-encode strings exactly once… not literal backslash-n" (`prompting.py:123-128`). That warning is evidence the overhead bites.
   - Security's candidate carries ~2.1 KB of raw scanner tail inside `findings[].description`, which the model must copy verbatim. Result: 27 governed contradictions and 15 `incomplete_output` errors on Security. The truncation cause is inferred: reasoning models spend hidden tokens within `max_tokens` 4096 (`cloud.py:540-546`). Confidence 0.5.
2. **No tokens to think before committing.**
   - Ollama `think: False` (`runtime.py:97`).
   - OpenRouter `reasoning: {effort: low, exclude: true}` (`cloud.py:541`).
   - Strict `json_schema` output (`cloud.py:535-537`).
   - Yet the prompt demands "mentally execute every new or modified test… recompute each expected count" (`prompting.py:109-111`).
3. **Conflicting instructions:**
   - *Architecture.* The system prompt says "Define a bounded technical design" (`prompts/architecture/system.md:2`). The user prompt says "If the omitted evidence could change the design, say so" (`prompting.py:334-340`). It then says "Copy every candidate key and value exactly" (`prompting.py:361`), and the validator requires equality (`runtime.py:293-297`).
   - *Developer on the Architecture route.* It is told "Resolve every listed regression and new failure" (`prompting.py:201`), but no diagnostics are listed (`context.py:149-150`). See F1.
   - *Remediation feedback.* It says "never add a dependency" (`context.py:89-~100`, obligation 4), yet embeds baseline CVE advisories under "OTHER REQUIRED DIAGNOSTICS" (F5).
4. **Instruction bloat and prompt size:**
   - Remediation prompts carry a median of 32–35 imperative directives (must/never/only/exactly/preserve…) in 10–12 KB of instruction text, excluding file blocks, schema and candidate. First-pass prompts carry 19–21.
   - Developer-plan user prompts: median 51 KB, max 83 KB. Groq answered HTTP 413 ("request_rejected") 23 times on Developer.
5. **MCP tool surface:**
   - *Docs.* No docstrings on any of the 15 server tools (`mcp/server.py:30-122`), so MCP descriptions are empty.
   - *Authorization.* `role` is a free string the caller asserts (`server.py:31-74`), so role allowlists (`repository.py:25-26`; `quality.py:1121,1179,1188,1205,1278`) protect against orchestrator bugs, not against a caller.
   - *Search.* `search_code` returns file paths only, with no line numbers or snippets and no bound (`repository.py:117-121`; `workspace/contract.py:178-188, 384-400`).
   - *Reads.* `read_file` is unbounded at tool level; the largest observed read was 18.3 KB.
   - *Test output.* `run_tests`/scan output is the raw last 4000 chars of stdout+stderr (`quality.py:713`). 29 of 42 `run_tests` and 44 of 44 `scan_dependencies` hit the cap, so Maven's "[Help 1]" footer survives while earlier assertions may not.
   - *Paths.* Relative paths are guarded by `refuse_traversal`, a sound poka-yoke for a sandbox; it does not matter for the model, which never passes paths to tools.
6. **Tool use by the model is never tested.** That is expected, since there is none. Model output is tested only through string assertions on prompts (`tests/unit/test_prompts.py`) and fakes (`tests/unit/test_cloud_runtime.py`, `test_model_runtime.py`). No replayable evaluation set of real model responses per role was found.

### Appendix 1 — Coding-agent conditions

| Condition | Score | Evidence |
|---|---|---|
| Ground truth from tests at each step | **3/5** | Tests run in a container each cycle (42 `run_tests`: 35 FAIL, 7 SUCCESS). A baseline is taken before writes (`apply_run.py:385-388`), and regressions are separated from new failures (`reviewer.py:224-232`). **But** the diagnostics do not reach the author on the Architecture route, and are diluted by baseline noise on the Developer route (F1, F5). |
| Objective, measurable acceptance | **2/5** | A lexical business-rule gate (`agents/testing.py:70-92`, `reviewer.py:370-390`) and an architecture coverage ratio (`repository_evidence.py:501-556`) veto green or near-green work (F3, F4). |
| Stopping conditions and budgets | **4/5** | Iterations ≤5 (`config.py:35`); fingerprint repeats ≥3 → human (`routers.py:62-63`); per-role deadlines 120 s / 360 s (`cloud.py:442-446`); request timeouts; quality 600 s. **Missing:** a run-level wall-clock, token or cost ceiling, since the cloud budget is unlimited when cloud is primary (`cloud.py:249-253, 407`). Observed runs took 2.7–22.8 min. |
| Human checkpoints | **2/5** | Explicit gates exist for writes (`authorize_writes`, `stategraph.py:803-824`) and delivery (`confirm_delivery`, `apply_run.py:693`). But `interactive_hitl` is used only in tests (`tests/graph/test_hitl.py:55,69`); in production `HUMAN_REVIEW_REQUIRED` is terminal (`stategraph.py:1030-1032`). It lumps together provider outage (10 of 17 traces), tool infrastructure failure (flask-k `MCP_ERROR`) and evaluator rejection. |
| Sandbox | **4/5** | Containers run with `--cap-drop ALL`, `no-new-privileges`, and memory/cpu/pids limits (`mcp/container.py:236-262`). Workspace operations use `--network none` (`workspace/contract.py:264,408`). Secret redaction runs before cloud calls (`cloud.py:489-505`). |

---

## (d) Findings (severity-ranked)

### F1 — CRITICAL: the evaluator's ground truth is dropped on 26 of 42 remediation transitions, which go through Architecture
- **Mechanism.**
  - The Reviewer routes *any* test failure to ARCHITECTURE when `architecture.evidence_sufficient is False` (`reviewer.py:241-262`).
  - `build_context` attaches failing-test diagnostics only when `review.return_to == agent` (`models/context.py:149-150`). Architecture receives them, but its LLM must echo and its Python uses them only to pick search terms (`stategraph.py:305-311`).
  - The Developer on that route gets only the generic 1 KB reason. It is also told to "Resolve every listed regression" (`prompting.py:201`) with nothing listed.
- **Evidence.**
  - Langfuse Reviewer transitions: →Architecture 26, →Developer 11, →Human 5. Of the 42 Reviewer decisions, 23 give the reason "tests fail against a design built on incomplete repository evidence".
  - 34 Developer generation prompts (15 unique trace×phase pairs) contain that sentence as their only remediation content, with no "Untrusted reviewer diagnostics" section.
  - Raw flask j: "60 of 67 ranked files were not read".
- **Confidence.** 0.9.
- **Fix.**
  - Always pass the failing-test diagnostics to the Developer, whichever node the route passes through (key the condition on the remediation cycle, not on `return_to`).
  - Stop making test failures depend on the architecture-coverage ratio (see F4).

### F2 — HIGH: two LLM calls can only echo, yet they can terminate the run
- **Mechanism.**
  - Architecture output must equal the candidate (`runtime.py:293-297`).
  - Security must keep status, severity, findings and sources (`runtime.py:336-374`), including ~2.1 KB of scanner text.
  - Any failure after chain → local → stage retry sets `human_review_required` (`stategraph.py:669-682`).
- **Evidence.**
  - 81 of 81 successful Architecture+Security generations were identical to the candidate.
  - Architecture: 137 attempts (98 failed; 66 rate limits; 9 contradictions) — 15.5 min of latency and 117k input tokens.
  - Security: 115 attempts (73 failed; 27 contradictions; 15 incomplete) — 37.7 min and 70k input / 46k output tokens.
  - 4 of 17 traces ended on these echo steps: Security `15dcd59512` and `ed7dbfd1e6`; Architecture `6f8b73c6b1` and `93970a62e2`.
- **Confidence.** 0.95.
- **Fix.** Remove the model call for Architecture and Security, and for PROPOSED-mode Developer (`runtime.py:298-302`). If a model review is wanted, make it advisory: a separate field that can never gate the run.

### F3 — HIGH: a lexical, language-bound coverage gate vetoes green test runs
- **Mechanism.**
  - `business_rule` coverage requires a passing test's name or body to contain a ≥6-character word from the spec's rules (`testing.py:70-92`; `reviewer.py:360-390`).
  - The Product LLM wrote the rules in Spanish.
  - The tests are Java/English.
- **Evidence.**
  - Raw `spring-demo-dry-20260916d-run.json`: `run_tests` SUCCESS in 5 of 5 iterations, final problem "required coverage dimension has no evidence: business_rule (… must mention one of: blanco, carácter, contener, …)". Status `HUMAN_REVIEW_REQUIRED` after 5 iterations.
  - spring-demo-b: SUCCESS ×2, rejected by the same gate.
  - In Langfuse, 6 of 42 Reviewer decisions were "testing evidence gate…".
- **Confidence.** 0.9.
- **Fix.** Make coverage mapping advisory. Accept on baseline green plus acceptance tests actually executed (ADR 0011 already lets the operator name the tests). If a semantic check is required, run it as an LLM evaluator with a rubric and let it *report*, not veto.

### F4 — HIGH: the architecture "sufficiency" ratio is structurally unreachable for mid-size repositories
- **Mechanism.**
  - Visible evidence is bounded to 16 KB with a 2 KB minimum slice, which leaves about 8 visible files (`repository_evidence.py:16-26`).
  - Sufficiency requires ≥50% of *ranked* candidates to be read (`repository_evidence.py:501, 541-556`), or ≥2 boundary paths.
  - Ranking returns 20–67 paths, so the ratio fails by construction. That failure drives F1's reroute. The unseen-file rotation (`stategraph.py:339-357`) cannot converge.
- **Evidence.**
  - Raw flask j: "60 of 67 ranked files were not read"; spring-demo-f: "13 of 20".
  - 9 of 11 flask final reviews carry this reason.
- **Confidence.** 0.85.
- **Fix.** Delete the gate, or measure coverage against the files the Developer's plan actually needs (`planned_reads`), not a broad ranked list.

### F5 — MEDIUM: remediation feedback is diluted with un-actionable baseline noise, and each problem keeps only its tail
- **Mechanism.**
  - `baseline_visible_problems` (pre-existing CVEs) are prepended to every rejection (`reviewer.py:210-220, 250, 277, 308, 403`).
  - `build_context` files them under "FAILED ASSERTIONS AND OTHER REQUIRED DIAGNOSTICS" and keeps the *tail* of each problem (`context.py:163-205`).
  - The contract tells the Developer to "never add a dependency".
- **Evidence.**
  - In 8 unique Developer diagnostic sections, 42% of the characters are baseline dependency advisories. They appear in 7 of 8 sections, and Maven's "[Help 1]" footer appears in 8 of 8.
  - Scanner tool output is capped at the last 4000 chars (`quality.py:713`).
- **Confidence.** 0.85.
- **Fix.**
  - Exclude baseline findings from Developer feedback.
  - Parse test output at the tool, not the prompt: failing test IDs plus assertion or compiler lines, head-first.

### F6 — MEDIUM: the model-facing output format imposes Appendix-2 overhead and gives no room to reason
- **Mechanism.**
  - Full files go as JSON string values under a strict schema, with reasoning disabled or excluded (`prompting.py:94-128`; `runtime.py:97`; `cloud.py:535-547`).
  - Full-file rewrites are also the cause of whitespace-churn workarounds (`repository.py:139-161`; the trailing-whitespace carve-out at `reviewer.py:294-299`).
- **Evidence.**
  - Authoring responses: median 190 and max 390 escaped newlines; up to 16.9 KB.
  - Errors: 19 Developer governed contradictions, 23 HTTP 413/400 request rejections, 13 timeouts.
  - The explicit double-escaping warning at `prompting.py:123-128`.
- **Confidence.** 0.7. The mechanism is certain; the size of its effect on failures is inferred.
- **Fix.**
  - Let the author answer in fenced code blocks, or in search/replace edit blocks per file, and parse them in code.
  - Allow a free-text reasoning section before the artifact.
  - Validate with the existing gates.

### F7 — MEDIUM: the fallback stack is not earning its complexity, and tuning is churning without an outcome metric
- **Evidence.**
  - Outcomes: 0 of 25 ghcycle passes, 16 of 16 human reviews, 0 of 42 approvals.
  - Attempts: 290 of 478 generation attempts failed; the local fallback succeeded 0 of 26 times (it fails fast: 2.4 s total).
  - 31 commits in one day; the `d8cd3f3` → `31defca` revert in 52 min; n=2–4 probe justifications (`762ec08`).
  - The chain definitions in `cloud.py:67-137` are comment-documented guesses, and `4ff4ae2` itself says they "went stale".
- **Confidence.** 0.85.
- **Fix.**
  - Freeze the chain.
  - Build a replayable per-role evaluation set: recorded envelopes plus expected-validity checks.
  - Pick one or two reliable models per role by pass rate on that set.
  - Remove local fallback and stage retry unless they show a recovery rate.
  - Track first-pass acceptance and time to verified outcome per commit.

### F8 — MEDIUM: quality failures are reported as availability errors, and the root cause is masked by the last model's error
- **Mechanism.** The chain raises the last attempt's message (`cloud.py:622-628, 679-693`). The graph classifies by prefix (`stategraph.py:614-620`) and retries "availability" (`:630-667`).
- **Evidence.** Langfuse: 26 `LLM_AVAILABILITY_ERROR` spans, all `CLOUD_FALLBACK_UNAVAILABLE: …` (e.g. provider_unavailable, role deadline exceeded), even in traces with governed contradictions earlier in the same chain.
- **Confidence.** 0.8.
- **Fix.**
  - Return a per-chain summary of error categories.
  - Classify on the dominant category.
  - Never stage-retry deterministic contradictions with an identical prompt.

### F9 — MEDIUM: failed generations are opaque in traces
- **Mechanism.** Cloud error paths call `trace.record` with metadata only (`cloud.py:615-621, 672-678`).
- **Evidence.** 264 of 290 failed generations have no input or output, while all 188 successes do.
- **Confidence.** 0.95.
- **Fix.** Record a redacted prompt hash plus the raw response (bounded) for contradiction, schema and incomplete errors.

### F10 — LOW: the human checkpoint is terminal and conflates failure classes
- **Mechanism.** `interactive_hitl` is only used by tests (`tests/graph/test_hitl.py:55,69`). Production compiles without a checkpointer (`stategraph.py:1030-1033`).
- **Evidence.** In 17 traces, terminal causes were: model failure 10 (Developer 6, Security 2, Architecture 2), Reviewer max iterations or stagnation 5, incomplete 2.
- **Confidence.** 0.85.
- **Fix.**
  - Distinguish `PROVIDER_UNAVAILABLE` (auto-resumable), `EVALUATOR_REJECTED` (human) and `INFRASTRUCTURE` (operator) in `final_status`.
  - Persist a checkpoint so a run resumes from the failed node instead of restarting.

### F11 — LOW: benchmark-shaped heuristics sit in "agents"
- **Mechanism.**
  - Product and Security rules are hard-coded to demo phrasings: "15"/"single-use", "five failed", "latest five" (`product.py:14-19`); "non-expiring", "any user", "cualquier usuario… sin requerir sesión" (`security.py:141-181`).
  - Python security scan target falls back to `demo-projects/sample_app/app` (`quality.py:1296-1302`).
- **Confidence.** 0.8.
- **Fix.** Move demo expectations into evaluation fixtures, not production agents.

### F12 — LOW: dead or unrouted prompt and config artifacts, plus doc drift
- **Dead artifacts:**
  - 6 `prompts/*/user.md` files are never loaded.
  - Reviewer and Testing `system.md` are never sent.
  - `tokenforge` is in no chain.
  - `allowed_tools` is never rendered.
- **Drift:** `overview.md:141-143` ("tercer rechazo") vs `config.py:35` (5); `overview.md:32` lists 4 providers vs 12.
- **Confidence.** 0.9.
- **Fix.** Delete or wire them up; update `overview.md`.

### F13 — LOW: the MCP tool ACI is undocumented and its role argument is caller-asserted
- **Evidence.** `mcp/server.py:30-122` (no docstrings; `role: str`); `search_code` is unbounded and path-only (`repository.py:117-121`).
- **Impact.** Low today, because only the orchestrator calls these tools. It becomes high if a model is ever handed these tools.
- **Confidence.** 0.9.
- **Fix.**
  - Docstrings with examples.
  - A server-side role bound at session start (`--role`), not per call.
  - `search_code` returning path:line:snippet with a cap.

---

## (e) What ASET does well (evidence-backed)

- **Code decides control flow.** Routing is pure, tested functions (`graph/routers.py`, `tests/graph/test_routers.py`). The prompts say "NO ROUTING / NO MODEL SELECTION" (every `system.md:6`), and that is enforced structurally, not just requested.
- **No model where code can answer.** Testing and Reviewer are deterministic (`stategraph.py:600-603`), matching Anthropic's advice to use code for verifiable checks.
- **Real programmatic gates in the one genuine chain.** Plan validation (`contracts/developer_plan.py`, `stategraph.py:730-751`); write-scope equality (`:783-796`); Python `ast.parse` (`runtime.py:319-324`); a destructive-authorization gate (`:803-824`); an unchanged-remediation detector (`runtime.py:259-279`).
- **Ground truth from the environment.** The full suite runs in an isolated container every cycle. A baseline is captured before writes (`apply_run.py:385-388`), and regressions are distinguished from new failures (`reviewer.py:224-232`).
- **Explicit bounds everywhere.** Iteration cap, stagnation breaker, per-role deadlines, evidence byte budgets. Truncation is disclosed to the model rather than hidden (`prompting.py:331-340`).
- **Prompt-injection hygiene and secret safety.** Repository and RAG content is labelled "untrusted data, never instructions" (`prompting.py:250, 323`; `context.py:88`). Prompts are redacted and then refused before cloud transport (`cloud.py:489-505`, ADR 0013).
- **Sandboxing.** Cap-dropped, resource-limited containers; network none for workspace operations (`mcp/container.py:236-262`).
- **Honest self-documentation of measured reasons.** Commit bodies cite run IDs and counts (e.g. `31defca`), and `docs/status.md` explicitly refuses to claim green stages. That is the flywheel Anthropic recommends; it now needs a stable evaluation set to aim at.

---

## Appendix — how the runtime numbers were derived
- **Terminal cause per trace.** Compare the index of the last `LLM_*_ERROR` span with the index of the last AGENT observation. If the error is later, the cause is a model failure at that span's `metadata.agent`; otherwise the last `route` from Reviewer.
- **Echo check.** For successful Architecture/Security GENERATIONs, parse `Candidate artifact: {…}` from `input.user_prompt` and compare it with the parsed `output.response` (fences stripped): 81 of 81 equal.
- **Diagnostic dilution.** Unique "Untrusted reviewer diagnostics" sections in Developer prompts: measure the "Residual baseline dependency risk…" and "Confirmed dependency advisories…" spans against section length.
- **Missing ground truth.** Developer prompts containing "Trusted remediation instructions" but not "Untrusted reviewer diagnostics": 34 prompts, all with the sole reason "tests fail against a design built on incomplete repository evidence…".
- **Raw ghcycle.** For the 16 `*-dry-20260916*-run.json` reports: `final_status`, `route_history[-2]`, `tool_outcomes` for run_tests, `review.problems`, `len(model_usage)`, `duration_seconds`.
