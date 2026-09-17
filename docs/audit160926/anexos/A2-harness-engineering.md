> Papel de trabajo de la auditoría del 2026-09-16 (docs/audit160926), conservado tal como lo entregó su auditor, salvo rutas locales sustituidas por `~` y `<scratchpad>`. No es documentación vigente: las conclusiones adjudicadas están en las páginas de la auditoría y en el registro de hallazgos.

# A2 — ASET measured against "Harness Engineering" (framework B)

Auditor A2 · 2026-09-16 · repo `gh-run-testing @ 92742b7` · read-only

## 0. Method and evidence base

- **Code**: `src/engineering_team/` read directly (graph, agents, contracts, llm, mcp, runs, observability). Paths below are `path:line` at 92742b7.
- **Traces**: Langfuse export `~/Downloads/1789609787428-lf-events-export-…json` (2839 observations, 17 traces, 2026-09-16 16:49Z → 2026-09-17 00:11Z), processed with Python in a sandbox. Only aggregates appear here.
- **Benchmarks**: 27 raw reports in `evaluation/benchmarks/ghcycle/results/raw/*-run.json` and the scored `results/*.json`, parsed with Python.
- **History**: `git log --since=2026-09-10` (58 commits; 31 on 2026-09-16), `git show --stat` for each one.
- **Timing caveat**: the last trace ends at 00:11Z. Commits `4ff4ae2` (model-health ledger, 00:15Z) and `92742b7` (PROJECT FACTS, 00:21Z) came **after** every traced run. Neither has run evidence. `workspace/model-health.json` does not exist.
- The 16 root traces cover two requirements: FlaskApiProduct `?q=` filter (11 runs, ghcycle a–k) and spring-demo blank-name → 400 (6 runs, a–f; one trace has no root).

---

## 1. Headline metrics (§18, computed from evidence)

| Metric (§18) | Value | How it was measured |
|---|---|---|
| First-pass acceptance | **0 / 16** traced runs; **0 / 27** raw ghcycle runs; **0 / 42** Reviewer decisions APPROVED | root `output.status`; raw `review.status`; `Reviewer` agent observations |
| Plausible false rejections | ≥1 run: spring `apply-de2851ce` (trace `38863321ef`) had **5/5 green suites** that included `createProductWithBlankNameShouldReturn400` and `…EmptyName…Return400`, and was rejected 4× by a lexical coverage gate | `MCP call` run_tests `test_cases` + Reviewer `problems` |
| Recovery after test failure | **0 / 13** runs with a failing `run_tests` ever went green again | ordered run_tests statuses per trace |
| Recovery after model failure | "model stage retry" recovered **6 / 16**. Local (Ollama) fallback **0 / 26** | retry events → same-agent output before HRR; `provider=ollama` generations |
| Why runs stopped | **10/16 LLM availability** (Developer 6, Security 2, Architecture 2) · 5/16 iteration or stagnation limit · 1 MCP UNAVAILABLE (WorkspaceSyncError, known Docker bind-mount flake) · 1 trace with no terminal node | last route or error before `HUMAN_REVIEW_REQUIRED` |
| Repeated failure rate | **22 / 27 (81 %)** remediation transitions repeated the previous failure class (coarse tags: Boot-3 import, `assert 5 == 1`, incomplete evidence, coverage gap, security tooling). The harness saw a repeat (`repeated_failures ≥ 2`) on only **7** of them | Reviewer problems tagged per iteration; `remediation route` metadata |
| Human interventions per task | Every run ends `HUMAN_REVIEW_REQUIRED`, and `REVIEW_REQUIRED` is terminal (`runs/store.py:26`). The operator relaunched Flask 11× and Spring 6× in one day, with 31 harness commits in between. Trusted outcomes per unit of attention = **0** | results a–k, a–f; git log |
| Unsupported completion claims | 0 (nothing was approved). **Receipt inaccuracy: 7 / 15** raw runs with writes report an `applied_diff` whose files ≠ final `changed_files` | raw `applied_diff` vs `changed_files` |
| Time to verified outcome | Undefined (no verified outcome). 177 min of run wall-clock across 17 traces, mean 10.4 min per run | trace min start → max end |
| Generation failure rate | **290 / 478 (61 %)** generations errored. 171 of the 290 were on Architecture/Security, whose output must equal or preserve a deterministic candidate | GENERATION `level=ERROR` by role |
| Provider structured-success | cohere 58/63 · groq 46/95 · mistral 64/152 · xkiro 8/38 · vyce 3/11 · openrouter 4/56 · google 1/25 (google2 0/4) · cloudflare 3/4 · kilo 1/3 · nvidia 0/1 · ollama 0/26 | `metadata.provider × structured_output_success` |
| Cost | Langfuse `totalCost` 0.0472 USD comes from **one** `gemini-3.5-flash` generation that Langfuse priced itself. 477/478 generations cost 0. ASET records no cost (`grep cost_details/total_cost/price` → only OpenRouter `max_price: 0`, `llm/cloud.py:539`) | `totalCost`, `modelId` per generation |

**Harness overhead by component** (17 traces, 177 min wall-clock):

| Component | Minutes | Share | Does it change the verdict? |
|---|---|---|---|
| Developer LLM (planner + author) | 46.2 | 26 % | Yes, it authors the code |
| **Security LLM** (told to "copy every candidate key and value exactly") | **37.6** | **21 %** | No: status, severity and HITL are guarded (`llm/runtime.py:339-343`, `prompting.py:361`) |
| **Security scans** (`run_security_scan` 23.6 + `scan_dependencies` 8.0), 44× each | **31.6** | **18 %** | Rarely: 41/44 scans report the same pre-existing CVEs |
| **Architecture LLM** (output must `== candidate`) | **15.5** | **9 %** | No (`llm/runtime.py:293-297`) |
| run_tests | 4.5 | 2.5 % | Yes, this is the ground truth |
| Product LLM | 0.8 | <1 % | Changes the acceptance terms (see C3) |

---

## 2. Scorecard — the 19 sections

| § | Section | Verdict | Key evidence | Gap | Smallest fix |
|---|---|---|---|---|---|
| 1 | Model ≠ agent | **Partial** | The harness owns context, tools, state and permissions. The model only authors JSON; the graph performs every tool call (`graph/stategraph.py:248-887`) | Recovery and proof of completion are weak (§8, §10). 0 accepted outcomes | Fix C1–C3 first; the harness shape is right |
| 2 | Task contract | **Partial** | Must-not-change is enforced in code: original tests protected, manifests not editable, credential and build paths refused (`contracts/developer_plan.py:106-201`). Approval-required actions: `authorize_writes` (`stategraph.py:797-824`), `confirm_delivery` + APPROVED + backend (`apply_run.py:691-696`) | Outcome and completion evidence are not operator-owned. `--test-spec` is appended as free text (`apply_run.py:322-323`). `ProductAgent` is a keyword stub with demo password-reset rules (`agents/product.py:14-19`). The Product LLM authors acceptance criteria in varying languages (Spanish rules in `38863321ef`, English in `e949a73ed9`, **empty** in `a2cb449e2a`), and those rules then drive the coverage gate | Compile the test spec into a typed `AcceptanceContract` (named test obligations plus must-not-change) before Product. Freeze it: the LLM may not rewrite it |
| 3 | Map, not manual (context) | **Partial** | Per-role projection (`models/context.py:28-63`), byte budgets, redaction, bounded remediation (6 KB) | (a) On Architecture-routed remediation the **Developer gets no diagnostics**: `context.py:149` attaches them only when `return_to == agent`. Developer prompts in `a2cb449e2a` and `090b36dae8` never contain "MANDATORY" or the failing `5 == 1`. (b) Baseline CVE JSON (≤2 KB) is placed first in problems (`agents/reviewer.py:210-220,276-287`) and eats the Developer's 4 KB diagnostic budget. (c) Planner prompt grows 33 KB → 83 KB across 5 iterations (`a2cb449e2a`). (d) The RAG corpus is 6 generic guideline docs, re-embedded every run (`apply_run.py:357`); 38/128 retrievals were empty | Always pass failing-test diagnostics to the Developer. Move baseline findings out of `problems`. Cap planner inventory per iteration |
| 4 | Tool gateway | **Strong** | The model never calls tools. Role allowlists (`mcp/repository.py:25-26,74-173`; `mcp/quality.py:1121,1278`), traversal and secret-path refusal, listing and read bounds, MCP timeouts (`mcp/client.py:98-155`), DENIED/UNAVAILABLE/FAIL statuses, `evidence_reference`, containerized runner (ADR 0015) | Role is a caller-asserted string (acceptable: the caller is code). Write and run_tests inputs are logged as `"safe"`. No result caching for identical scans | Log `path`/`filter` in `input_summary` for writes and run_tests. Memoize security scans by manifest hash |
| 5 | Brain / hands / history | **Partial** | Brain = typed `EngineeringState` (`contracts/state.py:29-72`) plus deterministic routers (`graph/routers.py`). Hands = MCP servers in containers. History = Langfuse, RunStore events, offline traces | **Not resumable**: checkpointer only when `interactive_hitl` (`stategraph.py:1033`), which production never sets (`apply_run.py:374-384`). Interrupted runs → FAILED (`run_api.py:119-127`) | `SqliteSaver` keyed by `run_id`, plus a resume endpoint |
| 6 | Memory as durable explicit state | **Partial** | Explicit typed state. Append-only evidence lists. Atomic RunStore snapshots (`runs/store.py:221-234`) | Cross-run memory = `model-health.json`, which is **unvalidated** (see M1), keyed `role\|provider\|model` with no stack or repo (`llm/model_health.py:86-87`), stored at a cwd-relative path (`config.py:93`), and fed by suite FAILs of any cause (`stategraph.py:529-546`). Result: cross-stack contamination. Within a run, `tool_results` grows unbounded and the Reviewer receives all of it (`context.py:134-136`) | Key the ledger by stack. Record authoring outcomes only for change-induced failures. Anchor the path to the repo root |
| 7 | Completion from environment, cheapest checks first | **Partial** | "Done" is decided by code over real tool results: Testing and Reviewer skip the model (`stategraph.py:600-603`), with baseline tests (`apply_run.py:388,427-450`), non-empty diff and write evidence (`reviewer.py:29-164`) | **Ordering is inverted**: Developer → Security (dependency-check up to 324 s) → Testing (compile) (`stategraph.py:1000-1011`). The `testing_only` shortcut is unreachable because `security_surface_changed` matches the substring `"api"`, including the default `"no API change declared"` (`agents/developer.py:461,506-509`). Python output is `ast.parse`-checked; Java is not compiled before the scan | Run tests/compile before Security. Run the security scan once as a baseline and re-scan only on a manifest change |
| 8 | Adversarial verification | **Partial** | The Reviewer is deterministic, has an explicit rejection ladder (RAG → security → failing tests → implementation evidence → coverage) and may only reject, never repair (`reviewer.py:167-415`). Model cannot change status (`runtime.py:341`) | The rubric is **lexical**: a dimension is covered if words ≥6 chars from LLM-authored rules appear in test names or bodies (`agents/testing.py:70-92`; `reviewer.py:363-384`). Green suites were rejected (C3). No independent re-verification of the final tree. ghcycle `spec` just trusts the verdict (`run_cycle.py:169-171`) | Map coverage to test identifiers the target plan declared for each acceptance obligation. Re-run the suite on the final tree in the scorer |
| 9 | Policy outside the loop | **Partial** | Write, delivery, role and path policy are all in code. Redaction and refusal happen before cloud (`llm/cloud.py:489-503`, ADR 0013). Delivery needs two keys and APPROVED | **Source egress is ungoverned**: repo files go to up to 11 providers, including free gateways (xkiro, vyce, tokenforge, kilo; `llm/cloud.py:111-131`). The chains are changed by commit with no per-project allowlist or approval. **No spend policy**: the budget is unlimited in cloud-first (`cloud.py:407`); Vyce "records spend" (commit `762ec08`) | `ALLOWED_CLOUD_PROVIDERS` per project, required for private repos. Per-run token or cost cap |
| 10 | Recovery by failure class | **Weak** | Error codes exist (`contracts/enums.py:57-70`). Per-role deadline, cooldown/Retry-After (`cloud.py:446-479,587-600`). Byte-identical remediation is refused (`runtime.py:259-279`). Iteration cap of 5 plus a fingerprint breaker (`routers.py:40-66`) | The fingerprint hashes volatile free text (`routers.py:17-25`): "27 of 34 files…", scanner JSON, test output. 81 % repeats vs 7 detections. Architecture routing cannot converge (C1). An environment flake (WorkspaceSyncError) ends a 13-min run with no retry (`stategraph.py:218-246,561-570`; raw `flaskapiproduct-dry-20260916k`). Local fallback fails instantly 26/26 with no preflight. There is no baseline-vs-change split for security scans except a manifest-untouched heuristic (`agents/security.py:86-127`) | Fingerprint = (category, sorted failing test ids, error type). Retry UNAVAILABLE once. Preflight runtimes |
| 11 | Instructions → infrastructure | **Partial** | Many prompt rules are enforced in code: exact `file_contents` keys (`runtime.py:312-318`), newline and whitespace normalization (`mcp/repository.py:141-161`), byte-identical remediation, protected tests, manifests not editable, Reviewer/Security cannot re-route (`routers.py:53-61`) | Still prompt-only: "API missing on classpath → stop using it" (`context.py:100-103`), the Boot-4 API facts (`project_facts.py:28-40`), "every referenced class must exist" (`prompting.py:85`), "never change a numeric oracle" | Add a cheap test-compile gate right after authoring that returns the failure to the Developer without a full Reviewer cycle |
| 12 | Observe the run | **Partial** | Route transitions, MCP outputs, RAG retrieval, model attempts with `error_category`, stage retries, HITL events are all traced; secrets redacted (`observability/langfuse.py:21-30`) | Failed cloud generations carry no prompt (only 26/290 failed gens have `input`; `cloud.py:603-611,660-667`). No cost. Approvals (`authorize_writes`, `confirm_delivery`) are not on the root trace (metadata = `run_id` only). run_tests arguments not recorded | Add usage→cost, the approval flags and prompt hashes for failed attempts |
| 13 | Change receipt | **Partial** | `run_on_project` builds the receipt from state, not from a model summary: route history, tool outcomes, model usage, errors, files written (`apply_run.py:643-687`) | `applied_diff` = **first** `get_diff` (`apply_run.py:634-637`) while `get_diff` is cumulative (`mcp/repository.py:171-192`). 7/15 receipts are wrong. No "unresolved risk" section (baseline CVEs are mixed into Reviewer problems). `files_written` repeats across iterations | `next(reversed(...))`. Add `unresolved_risks` and `baseline_findings` |
| 14 | Every failure upgrades the harness | **Partial** | 47/55 commits since 09-10 touch tests. Commit messages cite run ids. ADRs record decisions | On 09-16, 12/31 commits churn model/provider chains, 3 tweak the lexical gate so a model can satisfy it (`766e1e5`, `928503b`, `1b054ef`), and a rotation was reverted 52 min later on n=2 runs (`d8cd3f3` → `31defca`). `docs/status.md` has 0 commits since 09-16. No replayable eval set: ghcycle is live and nondeterministic | Replay a frozen set of recorded failures (fixtures from traces) as regression tests for routing and gating, not only unit strings |
| 15 | Harnesses decay — build to delete | **Weak** | The Testing and Reviewer model bypass (`stategraph.py:600-603`) shows the team *can* delete a ceremony | Echo LLM calls, local fallback, unreachable `security_hitl`, test-only guardrails and RAG remain with no measured value (§5 below) | Apply the deletion list |
| 16 | Minimum viable harness L1–L6 | **L3 reached; L4–L6 partial or weak** | see §3 | — | — |
| 17 | Reusable harness spec | **Partial** | ADRs 0001–0018, typed contracts, `AGENTS.md`, `docs/architecture/overview.md` | The acceptance and verification rubric lives only in keyword tables (`testing.py:30-63`, `security.py:141-183`). The recovery policy (which failure goes where, how many times) is spread across routers, runtime, cloud and settings | One `harness-policy` module or doc per failure class: classifier, owner, retry condition, budget |
| 18 | Measure accepted work | **Weak** | ghcycle scores stages (`run_cycle.py:98-193`) | The harness computes none of first-pass acceptance, recovery rate, repeated failure rate, interventions, time to verified outcome or per-component overhead. All of §1 above had to be derived offline | Emit these 7 metrics per run in the receipt and aggregate them in ghcycle |
| 19 | When not to use a heavy harness | **Weak** | — | No triage: a ~10-line `?q=` filter runs 6 roles, containers, OWASP dependency-check (≤324 s per call, 5× per run), a RAG re-index and up to 5 cycles | Fast path: small scoped change → plan, author, compile, test, review. Skip Architecture, Security LLM and RAG unless a manifest or auth surface changes |

---

## 3. Maturity L1–L6

| Level | Assessment | Evidence | What is missing |
|---|---|---|---|
| **L1 bounded task** | **Partial** | Iteration cap 5 (`config.py:35`), role deadlines (`config.py:86,90`), bounded write targets (`developer_plan.py:11,135-136`), plan read budget of 24 files / 192 KB (`stategraph.py:750`, `developer_plan.py:199`) | Outcome and acceptance are LLM-authored and unstable (C3, M5). No spend budget |
| **L2 legible environment** | **Partial** | Inventory, bounded reads, project facts (new), baseline tests, stack profiles | Architecture sees at most ~7 files (16 KB / 2 KB slices, `repository_evidence.py:16-26`). PROJECT FACTS is unvalidated and hardcoded from one probe. Generic RAG |
| **L3 controlled actions** | **Strong** | Model has no tool access. Role allowlists, plan validation, write authorization, two-key delivery, containers, redaction | Source egress policy (H6) |
| **L4 durable execution** | **Weak** | RunStore snapshots and events persist | No checkpoint/resume. Interrupted → FAILED. HRR is terminal. An availability error after 10 minutes means starting over |
| **L5 evidence** | **Partial** | The environment decides; deterministic Reviewer; baseline tests; diff and write evidence | Lexical coverage gate, inverted check order, wrong receipt diff, baseline CVEs not separated in the receipt |
| **L6 recovery and learning** | **Weak** | Error codes, cooldowns, byte-identical guard, model-health ledger (unvalidated), strong test discipline on commits | Breaker blind to repeats. Architecture loop non-convergent. 0/13 test-failure recoveries. Learning happens per run in commits (provider churn), not through replayed failure classes |

Framework B says complexity should be earned by observed failure. ASET has L3-grade multi-agent machinery (6 roles, RAG, 11 providers, a model-health ledger) sitting on L4–L6 foundations that do not yet turn one failure into a recovery.

---

## 4. Findings (severity-ranked)

### CRITICAL

**C1 — The Architecture remediation route cannot converge, and it blinds the Developer.** Confidence **0.9**
- *Mechanism.*
  - When Architecture evidence is judged insufficient, the Reviewer sends every test failure to Architecture (`agents/reviewer.py:241-262`, ADR 0007).
  - Sufficiency needs read/ranked ≥ 0.5 (`repository_evidence.py:501,541-552`). The visible window is fixed at about 7 files: `MAX_ARCHITECTURE_READ_BYTES` 16 KB with `MIN_ARCHITECTURE_SLICE_BYTES` 2 KB (`repository_evidence.py:19,26`; slicing at `stategraph.py:468-490`).
  - Remediation feedback adds search terms (`stategraph.py:305-311`), so `ranked` grows.
  - The Architecture LLM must return the candidate unchanged (`llm/runtime.py:293-297`), so nothing new reaches the design.
  - Meanwhile the Developer's envelope attaches diagnostics only when `return_to == Developer` (`models/context.py:149-209`), so the failing assertion never reaches the only role that edits code.
- *Evidence.*
  - Trace `a2cb449e2a` (apply-470d0440): the Architecture gap went "27 of 34 (21 %)" → "56 of 67 (16 %)" → "60 of 67 (10 %)" → "59 of 67" → "60 of 67". 5 iterations, all routed to Architecture, `repeated_failures=1` each time.
  - Developer prompts in `a2cb449e2a` and `090b36dae8`: `MANDATORY` absent, `5 == 1` absent in all 18 author and planner prompts.
  - 9/9 FlaskApiProduct traces that reached the Reviewer were routed to Architecture.
- *Smallest fix.* (1) In `build_context`, always attach test diagnostics for the Developer, whoever `return_to` is. (2) In `reviewer.py:241`, route to Architecture only if the previous Architecture pass *increased* the visible required boundaries. Otherwise route to the Developer.

**C2 — The stagnation breaker hashes volatile text, so repeated failures run to the iteration cap.** Confidence **0.85**
- *Mechanism.* `remediation_fingerprint` hashes `reason + problems` (`graph/routers.py:17-25`). Problems include coverage counts, scanner JSON tails and raw test output, which change every cycle.
- *Evidence.*
  - 22 of 27 remediation transitions repeated the failure class; `repeated_failures ≥ 2` fired 7 times.
  - `f9ca92d099` (apply-f8a92e20): the same Boot-3 import error (`boot.test.autoconfigure.web.servlet` / `boot.test.mock.mockito`) in 5/5 iterations, `rep1` every time.
  - The test `tests/graph/test_routers.py::test_repeated_failure_expands_context_then_stops_if_still_unchanged` only uses byte-identical decisions.
- *Smallest fix.* Fingerprint = `(remediation_category, sorted(failing test ids), first error type/symbol)`. Add a regression test built from two real problem lists from `f9ca92d099`.

**C3 — The acceptance gate is lexical over LLM-authored, language-unstable rules, and it rejected green suites.** Confidence **0.8** (the change's full semantic correctness was not independently verified)
- *Mechanism.* TestingAgent derives required dimensions from Product-LLM `business_rules` and `acceptance_criteria` (`agents/testing.py:120-133`). `business_rule` counts as covered only if a word ≥6 chars from those rules appears in a passing test's id or source excerpt (`testing.py:70-92,146-170`). The Reviewer rejects any gap (`reviewer.py:363-384,399-408`).
- *Evidence.*
  - `38863321ef` (spring-demo-dry-20260916d, apply-de2851ce): run_tests **SUCCESS ×5**, including `createProductWithBlankNameShouldReturn400` and `createProductWithEmptyNameShouldReturn400`.
  - It was rejected 4× with "business_rule has no evidence … must mention one of: blanco, carácter, contener, contiene, espacios, indicando, nombre, obligatorio, rechazar, requerido, solicitud". The rules were written in Spanish by the Product LLM; the Java tests use English identifiers.
  - `e949a73ed9`: same requirement, English rules, rejected for `business_rule` + `security`.
  - The harness response was to teach the model the words (`1b054ef`, `766e1e5`), not to fix the gate.
- *Smallest fix.* Have the target plan declare, for each acceptance obligation, the test identifier that proves it. Coverage = that identifier passed. Drop the substring match for `business_rule`.

### HIGH

**H1 — LLM calls on deterministic roles cost 30 % of wall-clock and end runs.** Confidence **0.9**
- *Mechanism.*
  - Architecture's model output must equal the candidate (`llm/runtime.py:293-297`).
  - Security, like every non-Developer non-Product role, is told to "Copy every candidate key and value exactly" (`llm/prompting.py:361`); its status, severity and HITL flag are guarded (`runtime.py:339-343`).
  - The graph already skips the model for Testing and Reviewer for exactly this reason (`stategraph.py:600-603`).
- *Evidence.*
  - 53.1 model-minutes (Security 37.6 + Architecture 15.5).
  - 171/290 failed generations: Architecture rate_limit 66; Security governed_contradiction 27 and incomplete_output 15.
  - 4/16 runs terminated by these calls: `ed7dbfd1e6`, `15dcd59512` (Security); `6f8b73c6b1`, `93970a62e2` (Architecture).
- *Smallest fix.* Add `AgentRole.ARCHITECTURE, AgentRole.SECURITY` to the bypass set at `stategraph.py:600`.

**H2 — Model availability, not the task, decides most outcomes; fallbacks don't change conditions.** Confidence **0.85**
- *Evidence.*
  - 10/16 runs ended on `LLM_AVAILABILITY_ERROR`.
  - The cloud-first secondary runtime is `LocalModelRuntime` (`apply_run.py:348-350`). It failed 26/26 instantly (`HTTPStatusError`), with no preflight.
  - Stage retry recovered 6/16 on the same chain after cooldown (`cloud.py:462-475`).
  - The cloud budget is `unlimited` when primary (`cloud.py:407`, `CloudBudget.consume` at `:260`).
- *Smallest fix.* Health-check Ollama at run start and set `secondary_runtime=None` if it is down. Make an availability failure a checkpointed pause (needs H3) instead of terminal HRR.

**H3 — No durable checkpoint or resume.** Confidence **0.9**
- *Evidence.*
  - `InMemorySaver` only when `interactive_hitl` (`stategraph.py:1033`). Production never sets it (`apply_run.py:374-384`); it is exercised only in `tests/graph/test_hitl.py::test_langgraph_hitl_is_checkpointed_and_resumable`.
  - `REVIEW_REQUIRED` has no outgoing transitions (`runs/store.py:26`). Interrupted runs are marked FAILED (`run_api.py:119-127`).
  - Trace `b798793c96` stopped after 3 iterations with no root output and could not be resumed.
- *Smallest fix.* `SqliteSaver(workspace/runs/_records/<run_id>.sqlite)` with `thread_id=run_id`, plus `POST /runs/{id}/resume`.

**H4 — The expensive check runs before the cheap one, and repeats on unchanged inputs.** Confidence **0.85**
- *Mechanism.*
  - Edges Developer → Security → Testing (`stategraph.py:1000-1011`).
  - The `testing_only` path is gated by `security_surface_changed`, which is true whenever `"api"` is a substring of requirement + apis. The fallback string `"no API change declared"` itself contains it (`agents/developer.py:461,506-509`), so the scan re-runs every iteration.
  - No pre-change security baseline exists (compare `baseline_tests`, `apply_run.py:388`).
- *Evidence.* 44 `run_security_scan` (23.6 min, max 324 s) + 44 `scan_dependencies` (8.0 min). 41/44 scans carry `confirmed_dependency_findings` for untouched manifests.
- *Smallest fix.* A baseline scan before the first write. Re-scan only if `changed_files` touches a manifest (`agents/security.py:64-65`). Replace the substring test with a word-boundary or explicit auth-surface signal.

**H5 — The change receipt reports the wrong diff.** Confidence **0.9**
- *Mechanism.* `diff_result = next(item for item in tool_results if item.tool_name == "get_diff")` takes the first diff (`apply_run.py:634-637`). `get_diff` is cumulative (`mcp/repository.py:171-192`) and `tool_results` accumulates across iterations.
- *Evidence.* 7/15 raw runs with writes have mismatched files. Example: `flaskapiproduct-dry-20260916f`: `changed_files=[app/models/product.py]`, `applied_diff` files `[app/routes/products.py, tests/test_product_filtering.py]`. Also 16i, 16j, 16k, spring 16a, 16b, 16f.
- *Smallest fix.* `next((… for item in reversed(state["tool_results"]) …), None)`, plus a test with two `get_diff` results.

**H6 — Repository source leaves the machine under no policy, with no spend tracking.** Confidence **0.8** (policy intent not documented)
- *Evidence.*
  - Default chains send source files to mistral, groq, xkiro, cohere, kilo, cloudflare, vyce, google, openrouter and nvidia (`llm/cloud.py:111-131`), and provider lists change by commit (`9d27bcd`, `7af574e`, `cc19be6`, `004b612`).
  - Redaction covers credentials only (`cloud.py:489-503`).
  - No cost fields exist in `ModelExecutionInfo` or the trace. The 0.047 USD is Langfuse's own price for one Gemini call.
- *Smallest fix.* A `cloud_allowed_providers` setting that is required, and checked in `CloudRouter.enabled_for` (`cloud.py:318`). Record `usage` × a price table into `ModelExecutionInfo.cost_usd`, with a per-run cap.

### MEDIUM

**M1 — The model-health ledger is unvalidated durable state that can contaminate across stacks.** Confidence **0.75**
- Committed at 00:15Z, after the last traced run (00:11Z). `workspace/model-health.json` is absent.
- Key is `role|provider|model` with no stack (`llm/model_health.py:86-87`).
- `record_authoring` counts any suite FAIL (`stategraph.py:529-546`), including environment failures and Architecture-routed iterations where the author never saw diagnostics (C1).
- The window is count-based with no time decay (`model_health.py:35-39,101-106`). The path is cwd-relative (`config.py:93`), unlike the anchored `.env` (`config.py:13`).
- It replaced the reverted rotation (`31defca`) with no run evidence.
- *Fix:* key by `(role, stack)`, record only change-induced failures, anchor the path, and A/B it on ghcycle before trusting it.

**M2 — Baseline security noise consumes the remediation channel.** Confidence **0.8**
- The Reviewer puts `baseline_visible_problems` first (`reviewer.py:210-220,276-287`), and they carry up to 2 KB of scanner JSON (`security.py:106-118`).
- They flow into the Developer's diagnostics budget (`context.py:157-206`). CVE/cvss text is present in Developer prompts of `f9ca92d099` and `38863321ef`.
- They also make every fingerprint volatile (C2).
- *Fix:* keep baseline findings out of `problems`; put them in `unresolved_risks` in the receipt.

**M3 — The Boot-4 knowledge fix is prompt-only and generalizes one probe.** Confidence **0.7**
- `project_facts.py:28-40` hardcodes classpath facts from one `Class.forName` probe of spring-demo and applies them to every Boot-4 parent.
- Delivery is a ≤4 KB prompt block (`project_facts.py:185-188`); no deterministic check exists.
- Before `92742b7`, the Spring author read `pom.xml` raw and repeated the Boot-3 imports 5× (`f9ca92d099`, where `PROJECT FACTS` is absent from all prompts).
- *Fix:* a compile gate right after authoring (`mvn -q test-compile` / `dotnet build` / `python -m compileall`), with the error fed straight back to the Developer. It is cheaper than a full Security → Testing → Reviewer cycle and works for any version.

**M4 — The task contract is an LLM artifact.** Confidence **0.8**
- `ProductAgent` hardcodes demo rules ("Reset link expires after 15 minutes", `agents/product.py:14-19`).
- The operator's test spec is appended as prose (`apply_run.py:322-323`).
- The Product LLM may add or replace acceptance criteria (only a superset is enforced, `runtime.py:345-355`). Criteria language and count vary per run (C3).

**M5 — Recovery ignores environment failure classes.** Confidence **0.75**
- `WorkspaceSyncError` (the known Docker bind-mount flake) returns UNAVAILABLE → `required_mcp_missing` → HRR, with no retry (`stategraph.py:218-246,561-570`).
- Raw `flaskapiproduct-dry-20260916k` lost a 13-min, 4-iteration run this way.
- A model 503 gets a stage retry; an infrastructure flake does not.

**M6 — Observability gaps.** Confidence **0.8**
- Failed cloud generations record metadata but no prompt (`cloud.py:603-611,660-667`): only 26/290 failed generations have `input`.
- The root trace metadata has only `run_id`: no `authorize_writes`, `confirm_delivery` or settings snapshot.
- No cost. `run_tests` records `input_summary="safe"`.

**M7 — The flywheel is mostly per-run patching.** Confidence **0.75**
- Of 31 commits on 09-16:
  - 12 model/provider chain changes (`9d27bcd`, `762ec08`, `7af574e`, `f70c32a`, `51aa5c1`, `cc19be6`, `c2d29d2`, `004b612`, `52c5560`, `eaa0aa3`, `0b58d07`, `4ff4ae2`)
  - 3 lexical-gate tweaks (`766e1e5`, `928503b`, `1b054ef`)
  - 8 Developer planning/prompt changes
  - 1 feature reverted after 52 min on n=2 (`d8cd3f3` → `31defca`)
- Tests accompany 47/55 commits, which is good. But they pin lists and strings; none replays a recorded failing run through the router or gate.
- `docs/status.md` was not updated for any of it.

### LOW

- **L1 — Test-only or unreachable harness code.**
  - `graph/hitl.py` and `guardrails/routes.py`/`timeouts.py` are referenced only from tests.
  - `build_walking_graph` (`stategraph.py:111-126`) is test-only.
  - `security_hitl` is unreachable: SecurityAgent never emits CRITICAL (`agents/security.py:113-200`) and the model cannot change severity (`runtime.py:339`), so `routers.py:69-70` only fires via `tests/graph/test_hitl.py` overrides.
  - Confidence 0.85.
- **L2 — RAG re-indexes on every run** (`apply_run.py:357`, which loads HF weights per the ghcycle stderr) over 6 generic docs (`knowledge/`). 38/128 retrievals were empty. A RAG failure *rejects* the run (`reviewer.py:178-187`). Confidence 0.7.
- **L3 — Security HITL triggers are keyword lists** in two languages (`agents/security.py:141-183`). Confidence 0.6.
- **L4 — ghcycle scoring** marks a skipped delivery as passed (`run_cycle.py:174-180`) and trusts the Reviewer for `spec`. `hygiene` failed in `flaskapiproduct-dry-20260916k` with leftover `aset-spring-eval-mysql` resources. Confidence 0.7.

---

## 5. Build to delete

| # | Component | Failure it prevents | Observed cost | Verdict |
|---|---|---|---|---|
| 1 | **Architecture LLM call** (`runtime.py:293-297` requires `actual == candidate`) | None: the output is discarded unless identical | 15.5 min, 91 failed generations, 2 runs killed | **Delete** (add to the bypass at `stategraph.py:600`) |
| 2 | **Security LLM call** ("copy every key"; status, severity and HITL guarded) | In theory, extra findings; none observed that changed a route | 37.6 min, 68 failed generations (27 governed contradictions), 2 runs killed | **Delete** or run it advisory and asynchronously |
| 3 | **LocalModelRuntime as the cloud-first fallback** | Provider outage | 0/26 successes | **Delete** from cloud-first, or gate it on a preflight |
| 4 | `security_hitl` node, CRITICAL branch in `security_route`, `interactive_hitl` + `InMemorySaver` path, `graph/hitl.py` | Nothing in production: unreachable | Graph complexity; false sense of resumability | **Delete** (replace with a real checkpointer, H3) |
| 5 | `guardrails/routes.py`, `guardrails/timeouts.py`, `build_walking_graph` | Nothing: test-only | Maintenance | **Delete** |
| 6 | `ProductAgent` keyword rules (password reset, "latest five") | Demo scenarios | Wrong defaults in real repos | **Delete** the rules; replace with the operator contract |
| 7 | Per-iteration `run_security_scan` + `scan_dependencies` on unchanged manifests | Regressions from dependency changes | 31.6 min (18 %) | **Replace** with a baseline scan plus manifest-delta re-scan |
| 8 | Lexical `business_rule` / marker coverage (`testing.py:30-92`) and its patches (`766e1e5`, `928503b`, `1b054ef`) | "Green but irrelevant tests" | ≥4 false rejections in one run; keeps attracting patches | **Replace** with plan-declared test obligations |
| 9 | ADR 0007 ratio-based Architecture re-routing | Designs built on thin evidence | 9/9 Flask traces stuck in a non-convergent loop | **Reframe** (required boundaries only) or delete the ratio branch |
| 10 | Providers with <10 % structured success in traces: openrouter (4/56), google (1/25), google2 (0/4), nvidia (0/1) | Outages elsewhere in the chain | Chain latency, 429 cooldown waits, egress surface | **Delete** from chains; keep cohere (58/63) and groq/mistral |
| 11 | `model-health.json` ledger | Stale chain ordering | Unmeasured; cross-stack contamination risk | **Keep behind a flag** until a replayed A/B shows benefit, else delete |
| 12 | RAG over `knowledge/` for Architecture/Security/Testing, with re-index per run | Ungrounded design or security text | Per-run embedding load; RAG_ERROR can reject runs; mostly consumed by echo roles | **Ablate**: keep only if acceptance changes without it |

**Earned and worth keeping** (each prevents an observed failure, cheaply): deterministic Testing and Reviewer; target-plan validation (protected tests, manifests, credential paths); write authorization; two-key delivery; redaction before cloud; baseline tests; the byte-identical remediation guard; whitespace normalization at write; per-role deadlines and Retry-After cooldowns.

---

## 6. Direct answers to the lead's questions

- **Does the Developer know Spring Boot 4 vs 3?** Before `92742b7`, only as raw `pom.xml` text. Planned reads add manifests of edited roots (`developer_plan.py:189-198`), and the model still wrote Boot-3 imports 5/5 times (`f9ca92d099`). After `92742b7` it gets a ≤4 KB PROJECT FACTS prompt block with hardcoded Boot-4 API notes. This is prompt-only and has no run evidence yet.
- **Is `model-health.json` durable state or contamination?** It is durable cross-run state with contamination risk: no stack key, environment failures counted as authoring failures, count-based window with no decay, cwd-relative path. It is also unvalidated: no file exists and no traced run used it.
- **Can a run resume from a checkpoint?** No (H3).
- **Does the reviewer have a rejection rubric and permission to reject without repairing?** Yes: it is deterministic and reject-only. But its coverage rubric is lexical (C3), and it re-uses the same evidence rather than independently re-verifying.
- **Is "done" decided by environment or model?** By the environment (run_tests, diff, write evidence) through code. The one exception is the coverage dimensions, which come from Product-LLM text.
- **Does the harness classify baseline vs change-induced, and environment vs code?** Tests: yes, via `baseline_tests` + `classify_failures`. Security: only a heuristic (`manifests untouched ∧ findings confirmed`, `agents/security.py:86-127`), which worked in 41/44 scans; the scans still re-ran, still logged TOOL_ERROR, and still polluted the Reviewer problems. Environment vs code: MCP UNAVAILABLE → HRR with no retry; a suite FAIL caused by the environment is recorded against the author model. The repeated Reviewer→Architecture/Developer cycles are loops, not classified recovery (C1, C2).
- **Is cost tracking real?** No (H6).

## 7. Reproduction notes

- Trace aggregates: Python over the export. Group by `traceId`; parse `output`/`metadata` JSON; use names `route`, `remediation route`, `Reviewer`, `MCP call`, `* cloud primary`, `model stage retry`, `HUMAN_REVIEW_REQUIRED`.
- Receipt mismatch: for each `results/raw/*-run.json`, compare `re.findall(r'^\+\+\+ b/(\S+)', applied_diff)` with `changed_files` when `files_written` is non-empty.
- Commit classification: `git show --stat --format= <sha> | grep -c tests/` for each commit since 2026-09-10.
