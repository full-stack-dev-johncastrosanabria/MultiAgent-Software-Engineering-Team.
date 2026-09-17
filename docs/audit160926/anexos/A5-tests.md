> Papel de trabajo de la auditoría del 2026-09-16 (docs/audit160926), conservado tal como lo entregó su auditor, salvo rutas locales sustituidas por `~` y `<scratchpad>`. No es documentación vigente: las conclusiones adjudicadas están en las páginas de la auditoría y en el registro de hallazgos.

# A5: Test audit of ASET (branch gh-run-testing @ 92742b7)

Auditor A5 (tests). Dates: 2026-09-16 to 17. I changed nothing in the repo (see §7).

## 1. Environment

| Item | Value |
|---|---|
| Python | 3.14.7 (`.venv/bin/python`, same as `/Library/Frameworks/.../3.14/bin/python3`) |
| pytest / ruff | 8.4.2 / 0.16.5 (venv). chromadb 1.5.9, langgraph 1.2.11, mcp 2.1.1, sentence-transformers 6.0.0 |
| Package import | `src/engineering_team` (editable install into `.venv`); `config._ENV_FILE` is anchored to `<repo>/.env` (config.py:13) |
| Settings fields | 56 `model_fields`, plus alias `LANGFUSE_HOST` (AliasChoices at config.py:120). The script unsets 56 + `LANGFUSE_HOST` + `RUN_LIVE_MULTIMODEL` = 58 names |
| Settings-named vars exported in the audit shell | **0** (so for this shell the unset recipe does nothing) |
| Docker | CLI at `/usr/local/bin/docker`. **Daemon unreachable**: `docker version` gives "failed to connect to the docker API at unix:///Users/.../.docker/run/docker.sock ... no such file or directory". No Docker Desktop, colima or orbstack process running |
| Ollama | reachable (`GET :11434/api/tags` returned 200). No test I ran used it |
| Type checker | none configured or installed (no mypy or pyright; nothing in pyproject) |
| Pre-commit hook | **not installed**: `.git/hooks` has only `*.sample`, `core.hooksPath` is unset, and no docs or scripts install one |

## 2. Commands run

Clean-environment wrapper: `scratchpad/a5_run_pytest.sh`, a `#!/bin/bash` script. It derives the upper-cased `Settings.model_fields` keys with `python -c`, unsets each one, then runs `export DELIVERY_BACKEND=none`. It runs `pytest ... -p no:cacheprovider -rfEs --junitxml`. After the run it lists repo files newer than a marker (excluding .git, `__pycache__`, .venv, node_modules and .worktrees).

| Label | Command | Where |
|---|---|---|
| gate | `a5_run_pytest.sh gate tests/unit tests/mcp -q` | repo |
| groupb | `a5_run_pytest.sh groupb tests/graph tests/integration tests/test_run_api.py tests/rag -q` | repo |
| e2e | `a5_run_e2e.sh` (same env recipe) → `pytest tests/e2e` | **scratch copy** `scratchpad/e2e-sandbox` holding tests/e2e, knowledge/, demo-projects/{sample_app,calculadora-qa-demo}, evaluation/reports/curated. A copy was needed because `EvaluationHarness` writes traces to the cwd-relative `evaluation/reports/generated/traces` (evaluation.py:108) |
| hermetic | `a5_run_hermetic.sh hermetic tests -q` | scratch copy of the repo **without `.env`**, .venv, workspace or node_modules. `PYTHONPATH=<copy>/src`, so `_ENV_FILE` does not exist. No `DELIVERY_BACKEND` export. This is a cross-check that results do not depend on `.env` |
| probe6 | `PYTHONPATH=scratchpad/plugins a5_run_pytest.sh probe6 -p a5_nodaemon <6 test ids>` | repo. A scratch pytest plugin monkeypatches **only** `ContainerRunner.require_available` to a no-op, to classify those 6 failures |
| ruff | `.venv/bin/ruff check src tests --no-cache --statistics` | repo |
| diff | `git diff --check` and `git diff --cached --check` | repo |

e2e prerequisites I checked before running: no conftest.py anywhere under tests/. `test_multimodel_evidence` and `test_live_evaluation_evidence` only read the tracked JSON in `evaluation/reports/curated/`, because the fixture exists and `RUN_LIVE_MULTIMODEL` was unset. `test_chat_apply_flow` uses a fake executor. `test_evaluation_scenarios` uses deterministic agents plus the MCP quality client. No paid cloud models or GitHub writes, so e2e was safe to run.

## 3. Results

### 3.1 Per run (JUnit XML)

| Run | Tests | Pass | Fail | Skip | Error | pytest time | Wall |
|---|---|---|---|---|---|---|---|
| gate (unit+mcp) | 1157 | 1112 | 22 | 23 | 0 | 43.6 s | 46 s |
| groupb (graph+integration+run_api+rag) | 107 | 106 | 1 | 0 | 0 | 33.9 s | 36 s |
| e2e | 6 | 3 | 3 | 0 | 0 | 22.7 s | 24 s |
| **Total (with .env + DELIVERY_BACKEND=none)** | **1270** | **1221** | **26** | **23** | **0** | 100.2 s | 106 s |
| hermetic (no .env, full `tests`) | 1270 | 1221 | 26 | 23 | 0 | 82.7 s | 86 s |

The hermetic run failed the exact same 26 test ids. **So `.env` has no effect on the results today.**

### 3.2 Per group (hermetic XML; identical to the split runs)

| Group | Pass | Fail | Skip |
|---|---|---|---|
| tests/unit | 848 | 0 | 0 |
| tests/mcp | 264 | 22 | 23 |
| tests/graph | 9 | 0 | 0 |
| tests/integration | 39 | 1 | 0 |
| tests/test_run_api.py | 47 | 0 | 0 |
| tests/rag | 11 | 0 | 0 |
| tests/e2e | 3 | 3 | 0 |

### 3.3 Skips (23): all opt-in or need Docker images

- `mcp/test_container.py`: 9 (`ASET_CONTAINER_TEST_IMAGE` / `_PYTHON_IMAGE` not set)
- `mcp/test_service_stack.py`: 6 (need a running daemon, base image, or postgres:16-alpine)
- `mcp/test_stack_execution.py`: 4 (jvm, node or dotnet profile image not present)
- `mcp/test_run_daemon_live.py`: 2 (`ASET_RUN_DAEMON_LIVE!=1`)
- `mcp/test_workspace_contract.py`: 1
- `mcp/test_workspace_runner.py`: 1

### 3.4 Failures (26). Every one traces to the missing Docker daemon; none is a code defect or a flaky test

| # | Test | Root cause (1 line) | Class |
|---|---|---|---|
| 1 | mcp/test_protocol.py::test_quality_run_tests_executes_through_real_stdio_mcp_session | `run_tests` returns UNAVAILABLE: "quality container runtime is unavailable: daemon did not answer" (container.py:142/146) | Docker unavailable, no skip guard |
| 2–17 | mcp/test_quality.py: 16 tests (`preserves_failed_test_result`, `getter_preserves_last_real_result`, `installs_declared_project_dependencies_once_before_pytest`, `installs_dependencies_outside_the_shared_interpreter`, `environment_does_not_inherit_shared_site_packages`, `close_removes_environment_and_is_idempotent`, `all_quality_commands_use_the_same_isolated_environment`, `prefers_hashed_lock_and_installs_project_without_deps`, `real_project_modules_cannot_shadow_quality_toolchain`, `venv_creation_is_an_interruptible_isolated_subprocess`, `install_phase_can_download_over_real_pypi_tls`, `only_pip_install_subprocesses_receive_network_access`, `ruff_config_stays_inside_the_sandboxed_project`, `a_project_at_the_mount_root_still_imports_its_own_modules`, `ruff_reads_the_project_configuration_from_inside_the_container`, `tools_install_uses_the_complete_declared_lock`) | UNAVAILABLE or RuntimeError from the live daemon probe, or `prepare_environment` needing a real daemon and image | Docker unavailable, no skip guard |
| 18–22 | mcp/test_quality.py::`project_is_installed_even_without_runtime_dependencies`, `environment_creation_is_thread_safe`, `concurrent_tests_wait_for_dependency_installation`, `project_and_tool_installs_share_one_mutation_lock`, `uses_one_end_to_end_deadline_across_setup_phases` | These are **mock-based** tests: `_patch_executor` patches `ContainerRunner.execute`, but `QualityMCP._interpreter` first calls the unpatched `self._runner.require_available()` (quality.py:282), which shells out to `docker version`. They show no Docker message, only `wait(timeout=1)` False, `len([])==0` or IndexError. **probe6: 5 of 6 PASS once only `require_available` is neutralised**. The 6th (`tools_install_uses_the_complete_declared_lock`, #17) still needs `prepare_environment` against a real daemon | Docker unavailable, **test-design defect** (unit test coupled to a live daemon) |
| 23 | integration/test_workflow.py::test_real_mcp_protocol_failure_changes_reviewer_route_and_is_remediated | `MCPQualityClient(tmp_path)` uses the container runner, so `scan_dependencies` and `run_security_scan` are UNAVAILABLE and the route is Product→Architecture→Developer→Security→HUMAN_REVIEW_REQUIRED. Testing never runs, so `failed[0]` raises IndexError at test_workflow.py:242. Reproduced with `scratchpad/repro/repro_mcp.py` | Docker unavailable, no guard; the IndexError hides the cause |
| 24 | e2e/test_evaluation_scenarios.py::test_exactly_five_scenarios_execute_with_fixed_expected_outcomes | Observed all HUMAN_REVIEW_REQUIRED instead of APPROVED×3/REJECTED×2. All 7 trace files written contain "container runtime is unavailable: daemon did not answer" (8 times each) | Docker unavailable, no guard |
| 25 | e2e/…::test_evaluation_records_model_usage_needed_by_live_aggregate | `Security` missing from the agents set, because the run stopped at Security | Docker unavailable |
| 26 | e2e/…::test_evaluation_counts_a_successfully_repaired_local_invocation | `4 == 5` model-usage entries, same cause | Docker unavailable |

Flakiness: the gate+groupb+e2e runs and the hermetic run produced identical failure sets, so no flake was observed. Candidates (not observed): 21 `threading.Thread/Event` uses and 14 `wait(timeout=…)` calls (mcp/test_quality.py 14/8, test_run_api.py 5/5, unit/test_run_store.py), plus 17 timing-style asserts. Warning: a chromadb DeprecationWarning (`asyncio.iscoroutinefunction`, removal in Python 3.16).

**Docker leftovers**: `docker ps -a / volume ls / network ls --filter label=aset.owner=aset` could not be queried (daemon unreachable). My runs could not have created containers.

## 4. Lint, types, whitespace

- **ruff** (exit 1): 3 findings. `SIM103` at src/engineering_team/agents/security.py:59, `PYI034` at src/engineering_team/mcp/quality.py:1545, `PIE807` at tests/unit/test_ghcycle_scoring.py:35 (fixable). status.md:178-180 lists the two src findings as pre-existing at `security.py:68` and `quality.py:1357` (the lines have moved). The tests finding is new. pyproject has no `select`, so the rule set is ruff 0.16.5's default (413 enabled rules per `--show-settings`) and changes whenever ruff is upgraded.
- **Type checker**: none configured or installed.
- **`git diff --check`**: exit 0 (cached: exit 0).

## 5. Invariant coverage matrix (static reading plus the runs)

Strength: **S** = direct behavioural tests including negative cases. **M** = unit-level or partial. **W** = mocks or snapshots only, or key negative case missing. **—** = none found.

| Invariant | Tests (evidence) | Strength | Gap |
|---|---|---|---|
| Max remediation iterations | graph/test_routers.py:24 (`iteration=3,max=3` → HUMAN_REVIEW_REQUIRED); integration/test_workflow.py `test_third_rejected_cycle_stops_without_a_fourth_cycle` (iteration==3, reviewer.calls==3); unit/test_config.py:48 (configurable, ≥1) | S | Wiring from Settings to the graph (apply_run.py:383) is untested: test_apply_infrastructure replaces `build_engineering_graph` with `lambda **k`. Tests use a scripted Reviewer, not a failing Security/Testing loop like the 5-iteration Langfuse loops |
| Stagnation circuit breaker | test_routers.py:37; test_workflow.py `test_repeated_failure_routes_through_architecture_then_stops_early` | M | Only repeated **Reviewer** rejections; no test for repeated identical Security FAIL (e.g. baseline CVEs) |
| Stage retry / local retry-repair / cloud escalation budgets | unit/test_cloud_fallback.py:160 (`AttemptBudget`, `CloudBudget` non-primary: 1/agent, 3/run); test_workflow.py:580/591/665 (transient retry once; escalation counters) | M | **Primary (cloud-first) runtime builds `CloudBudget(settings, unlimited=primary)`** (cloud.py:407). No test asserts any attempt or spend bound for cloud-first; 11 tests construct `primary=True` without checking the bound. Only role deadlines are tested (test_cloud_runtime.py:262/403/479/563) |
| HUMAN_REVIEW_REQUIRED routing | graph/test_hitl.py (4: pause, terminate, checkpoint, resume); test_routers.py:56 (critical security → security_hitl); test_workflow.py:259 (repository MCP unavailable → HUMAN_REVIEW_REQUIRED, no review, no fallback); test_run_api.py:580/775/1026 | S | none major |
| Role→tool allowlist | mcp/test_quality.py:105 and :217 (PRODUCT denied for 5 tools, and no subprocess or env is created); mcp/test_repository.py:18 and mcp/test_protocol.py:82 (ARCHITECTURE write denied over stdio); unit/test_reviewer_evidence_gate.py:165 (run_tests not attributed to TESTING is rejected) | M | Not a role×tool matrix: nothing checks that SECURITY/TESTING/REVIEWER cannot write, or that each quality tool's `allowed` set matches policy (quality.py:458…1279, repository.py:25-26) |
| Path restriction / sandbox escape | workspace_contract.py:43 (`../escape`, `/etc/passwd`, `.env`, `app/.env.local`); test_repository.py:18; test_protocol.py:82 (traversal plus `.env` over real MCP); component_workspace.py:47 (absolute/parent/symlink); workspace_runner.py:67/107/135 (symlink snapshot/archive); apply_infrastructure.py:193; test_evidence.py:127; container.py:175 (.git symlink not mounted); delivery.py:92 | S | `HostWorkspace.path` symlink-escape check (contract.py:110-112, "outside workspace denied") has no direct test |
| Secret redaction before cloud calls | unit/test_cloud_redaction.py (18); test_cloud_context_guard.py (7); test_guardrails.py (25); test_cloud_redaction.py:171 (a refused context sends no HTTP request); test_cloud_runtime.py:56/97/433 (provider errors and trace metadata redacted) | M-S | No test plants a secret in an envelope and asserts the **outbound HTTP body** (MockTransport `request.content`) lacks it on the success path. Redaction lives at cloud.py:367-369 and is only tested as a function |
| Fallback chain + "governed fields differ" | test_cloud_fallback.py (21: fixed mapping, providers cross, no duplicate model, keyless provider skipped, tool/RAG errors never trigger cloud); test_cloud_runtime.py:599 (fenced answer rewriting `source_requirement` → "governed fields differ"); test_model_runtime.py (8 calls to `_preserves_governed_facts`), test_developer_target_plan.py (4), test_architecture_grounding.py (2) | M | The governed-facts rules for **SecurityReview** (status, highest_severity, requires_hitl, findings, sources, checklist FAIL) plus TestResult and ReviewerDecision (runtime.py:329-373) have no direct test; only Product, Implementation, Architecture and TargetPlan are exercised. Chain tests are **snapshots** of provider order with dated empirical docstrings (e.g. test_cloud_fallback.py:266-342 "Evaluated 2026-09-16…", `chains[DEVELOPER][2] == ("xkiro", …)`) |
| Model-health memory isolation | unit/test_model_health.py (9, all `tmp_path/health.json`) | M | **No test writes the real workspace ledger**: no repo file changed in any run, and `workspace/model-health.json` does not exist. But `model_health_path` defaults to the **cwd-relative** `"workspace/model-health.json"` (config.py:93), unlike the anchored `_ENV_FILE`, and the apply_run wiring (apply_run.py:345-355) has no test (`model_health_path` appears in no test) |
| Security-scan baseline vs change | unit/test_security_dependency_scope.py (7: untouched-manifest CVEs are baseline; an edited manifest blocks; a linter is never baseline; an unconfirmed failure is never baseline); test_security_scan_provenance.py (8 fns, parametrised: incomplete or truncated scans never confirm); test_regression_reporting.py (16); test_reviewer_evidence_gate.py:415/431 | S (unit) | No graph-level test that baseline CVEs stop driving Developer remediation. Langfuse shows `run_security_scan` FAIL 44/44 while the loop repeats |
| Delivery gating (no PR unless gates pass) | unit/test_apply_run_delivery.py:15 (default none), :58 (confirm+APPROVED+gh → push/open with fake backend), :114 (no confirm → no push), :161 (refusal recorded); unit/test_delivery.py (31: default branch never targeted, `aset/` namespace, argument-like branch, path escape, secret refusal, token never on argv); test_infrastructure_prerequisite.py (23, ADR 18 ordering) | M | The condition is `authorize_writes and confirm_delivery and review APPROVED` (apply_run.py:691-695). **No negative test** for confirm=True + gh backend + REJECTED/HUMAN_REVIEW_REQUIRED review, or for `authorize_writes=False`. Every delivery path uses fake push/open backends; no real PR (ghcycle 0/25) |
| ghcycle scoring (run_cycle.py) | unit/test_ghcycle_scoring.py (15: 13 × `_score`, 2 × `_listed`; execute red on UNAVAILABLE / no run_tests / last FAIL / human review; spec red on reject; delivery red without PR url; hygiene red when docker query fails) | M | `main()` (run_cycle.py:196-256: `all_stages_passed`, redaction, results write) is untested. 11/13 `_score` cases use `delivered=False`. The dry-run semantics (`delivery.passed = not delivered`, `infrastructure.passed` when not delivered) are asserted only indirectly |
| Tests not writing to repo / live services | none (no conftest.py); 72/116 `Settings(` calls use `_env_file=None`, **44 read the real `.env`** | W | `LangfuseTracer` reads `LANGFUSE_PUBLIC_KEY/SECRET_KEY` straight from `os.environ` (observability/langfuse.py:128-133). `EvaluationHarness` defaults to that tracer (evaluation.py:108) and e2e `test_evaluation_scenarios` passes no tracer. So with the operator's Langfuse keys exported, that e2e test would emit live traces, and from repo cwd it writes to `evaluation/reports/generated/traces` (7 files per run here) |

### Tests that are mocks, fakes or snapshots only, for components described as validated

- **e2e "live" evidence tests execute nothing.** They assert tracked JSON from 2026-09-09: `test_live_evaluation_evidence.py` reads `evaluation/reports/curated/{scenarios,aggregate}-live.json`, and `test_multimodel_evidence.py` reads `multimodel-live-local.json`. They pass whatever the code does. With `RUN_LIVE_MULTIMODEL=1` or the fixture missing, `test_multimodel_evidence` runs live Ollama and **overwrites the tracked fixture** (relative `report_path`, test_multimodel_evidence.py:16/29-33).
- **Delivery and ADR 18 infrastructure-first delivery** have fake `push`/`open` backends only (test_apply_run_delivery.py:58-113; test_infrastructure_prerequisite.py:214-284). status.md:429 itself says "lo verificado es la suite".
- **Shared run daemon `owns_daemon=False`**: unit tests only. status.md:670-675 concedes it and the live tests are opt-in skips.
- **Cloud provider chains**: MockTransport plus order snapshots. The "passed the governed tasks" evidence lives in docstrings, not in tests.

### Tests that assert documentation (ossification risk)

- `mcp/test_quality.py:836 test_quality_container_contract_is_documented` asserts literal strings in docs/operations.md (`[QualityMCP](../src/...)`, `QUALITY_RUNNER=container`, `[Settings](...)`). Rewording the docs breaks the gate.
- `integration/test_documentation.py` (7 tests) checks structure, not wording: owners reachable, links resolve, ADR index equals directory, archive sha256 manifest, retired paths not recreated. That is acceptable, but every new doc page has to be registered in the test.

## 6. Comparison with claims

| Claim (source) | What I measured | Verdict |
|---|---|---|
| "952 PASS, 26 FAIL y 20 SKIP … 26 fallos dependían del daemon Docker … **978 PASS, 20 SKIP**" (docs/status.md:170-174, Task 7 selection) | Without a daemon: 1221 PASS / 26 FAIL / 23 SKIP over **1270** tests. The fail count is also 26, and all 26 are Docker-caused | Consistent in kind (Docker-only failures), but **not reproducible as stated**: the "Task 7 selection" is not given as a command, collection has grown (998 vs 1270), and I could not rerun with a daemon |
| "La suite integrada del 2026-09-14 terminó con **1038 aprobadas y 17 omitidas**" (status.md:56) | 1270 collected, 23 skipped. Since the last status.md commit (90ba069) there are **30 commits**, and **19 test files changed (+1801 lines)** | Stale; the counts no longer describe HEAD |
| "**111 pruebas focales** pasan y ocho de integración se omiten sin su imagen" (status.md:70-71); "156 focales" (:26); "73 focales" (:55) | "Focal" selections are not named as commands; can't reproduce. Skips needing images: 9 in test_container + 4 in stack_execution + 2 workspace | Unverifiable |
| PROJECT_STATE.md handoff: "**143 focales PASS; 1 test preexistente de ProcessRunner FAIL en Python 3.14**" (PROJECT_STATE.md:31) | `ProcessRunner` no longer exists in `src/` or `tests/`: retired in f09ffd4 (ADR 0015) and mentioned only in ADRs 0010/0014/0015. No test failed on Python 3.14.7 except the 26 Docker ones | **Stale or unreproducible** (confidence 0.85). PROJECT_STATE.md is git-ignored (.gitignore:26) |
| Memory: "pre-commit hook runs `pytest tests/unit tests/mcp` and blocks the commit" | No hook installed in this clone. With no daemon that selection has 22 failures | The gate is **not enforced**, and it can only be green on a host with a running Docker daemon plus images |
| "Suite red because of shell env / .env" (memory) | 0 Settings-named vars exported here. With `.env` (plus DELIVERY_BACKEND=none) and without `.env` (no override): identical 1221/26/23 | Not currently a factor in this shell |

## 7. Repo integrity

- `git status --short` after all runs shows the 20 pre-existing untracked entries (.tgrep/, .vscode/, 11 flaskapiproduct-dry-20260916[a-k].json, 6 spring-demo-dry-20260916[a-f].json, propflow-fixes-dry-20260913.json) **plus `docs/audit160926/03-patrones-anthropic.md`**. That file is dated Sep 17 00:36:11, after my last run ended (00:34:47). It is a Markdown audit document, not pytest output, so I did not create it; it most likely came from another auditor or the coordinator. Check its origin.
- Marker-based `find -newer`: **0 repo files modified** by the gate, groupb, probe6 or hermetic runs (outside `__pycache__`). e2e ran in a scratch copy.
- Scratch artifacts: `a5-*.log/.xml`, `a5_run_*.sh`, `plugins/a5_nodaemon.py`, `repro/repro_mcp.py`, `e2e-sandbox/`, `hermetic/repo` (≈769 MB copy; can be deleted).

## 8. Findings (severity-ranked)

**HIGH**

1. **The gate suite depends on a live Docker daemon and fails instead of skipping** (confidence 0.9). 26 tests hard-fail without a daemon: 22 inside `tests/unit tests/mcp`, 1 integration, 3 e2e. None has a skip guard. Five mock-based unit tests fail only because `ContainerRunner.require_available` (container.py:125-146) is not patched by `_patch_executor` (tests/mcp/test_quality.py:38-60); they pass once it is (probe6: 5/6 PASS). Combined with **no installed pre-commit hook**, a red suite is normal on any host without Docker. That trains "red = Docker" and hides real regressions (the integration failure shows as `IndexError` at test_workflow.py:242). Fix: patch the probe in the mock tests, and give real-daemon tests a `needs_docker` skipif that checks `docker version`, as test_service_stack.py:43-55 already does.

**MEDIUM**

2. **Delivery gate negative cases untested** (0.75). apply_run.py:691-695 is never exercised with confirm=True plus a gh backend and a non-APPROVED review, or with `authorize_writes=False`. All delivery tests use fake backends; ghcycle shows 0 real PRs.
3. **Cloud-first escalation budget is unlimited and no bound is tested** (0.8). `CloudBudget(unlimited=primary)` at cloud.py:407. Only the non-primary budget is tested (test_cloud_fallback.py:160); spend is bounded only by role deadlines and remediation iterations.
4. **Governed-fact guards for SecurityReview, TestResult and ReviewerDecision are untested** (0.75). runtime.py:329-373. These are the fields whose rewriting would let a model downgrade a security FAIL.
5. **Redaction is tested as a function, not on the wire** (0.7). No MockTransport assertion that a planted secret is absent from the outbound request body on the success path.
6. **Test claims in status.md and PROJECT_STATE.md are stale or unreproducible** (0.85). The ProcessRunner FAIL refers to a deleted class; focal counts have no commands; 30 commits and 19 test files since the last status update.
7. **Test isolation is ad hoc** (0.8). No conftest.py; 44/116 `Settings(` constructions read the real `.env`; `LangfuseTracer` takes keys from `os.environ` (langfuse.py:128-133); the e2e harness writes to a cwd-relative trace dir (evaluation.py:108, also apply_run.py:333); `model_health_path` is cwd-relative (config.py:93) and its wiring is untested.
8. **Snapshot "evidence" tests ossify artifacts and configuration** (0.8). The two e2e live-evidence tests assert 2026-09-09 JSON and can overwrite a tracked fixture. Chain-order tests pin list indices justified by dated docstrings.
9. **Baseline-vs-change security classification is covered only at unit level** (0.65). No graph test prevents the Security→Developer loop on pre-existing CVEs, which is what Langfuse shows.

**LOW**

10. The role×tool allowlist is not tested as a matrix; the `HostWorkspace` symlink-escape branch (contract.py:110-112) has no direct test.
11. The doc-string test `test_quality_container_contract_is_documented` couples docs wording to the gate.
12. ruff reports 3 findings (1 new in tests; src line numbers in status.md are stale); ruff rules are implicit version defaults; no type checker.
13. `run_cycle.main()` (all_stages_passed aggregation, redaction and write) is untested; ghcycle dry-run delivery semantics are only indirectly asserted.
14. The Settings→graph wiring of `max_remediation_iterations` (apply_run.py:383) is untested; stagnation is tested only for Reviewer rejections.
