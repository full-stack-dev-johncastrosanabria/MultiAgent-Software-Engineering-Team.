> Papel de trabajo de la auditoría del 2026-09-16 (docs/audit160926), conservado tal como lo entregó su auditor, salvo rutas locales sustituidas por `~` y `<scratchpad>`. No es documentación vigente: las conclusiones adjudicadas están en las páginas de la auditoría y en el registro de hallazgos.

# A4 — Evidence & metrics audit (ASET, `gh-run-testing @ 92742b7`)

Auditor A4 · 2026-09-16/17 · read-only · all numbers computed with Python over the files named; only aggregates reproduced.

## 0. Sources, method, corrections to the brief

- `evaluation/` tree (all families, §1). ghcycle: `run_cycle.py` read in full; 26 scored `results/*.json` + `shallow-push.json`; 27 raw `results/raw/*-run.json` (git-ignored, `.gitignore:52`).
- Langfuse export `~/Downloads/1789609787428-lf-events-export-…json` (2,839 observations, 17 traces). Trace→run mapping by `trace_id` in raw reports (16/17 matched; `b798793c96` = `spring-demo-dry-20260916c`, see F12).
- `docs/status.md` (736 lines) cross-checked claim by claim (§6). Git history for dates/commits. A5's junit files in scratchpad used only as a cross-reference for test counts.
- **Corrections to the brief** (confidence 0.95):
  - There are **26** scored ghcycle runs, not 25: 8 tracked, **18** untracked. `shallow-push.json` is a probe, not a run.
  - 3 raw reports have no scored JSON: `flaskapiproduct-dry`, `-dry-2` and `-dry-3` from 09-12. The scored `flaskapiproduct-dry.json` was committed in `c2ddea3`/`8ab29ef` and later removed. 2 scored runs have no raw report because they crashed.
  - The brief's error counts (503=42, ReadTimeout=22, 400=18, HTTPStatusError=52) include SPAN mirrors. The 421 `ERROR` observations break down as 290 GENERATION + 79 `TOOL_ERROR` spans + 26 `cloud fallback error` + 26 `LLM_AVAILABILITY_ERROR` spans. De-duplicated generation-level counts are in §4.3.

---

## 1. Evidence inventory (all of `evaluation/`)

| # | Family (path) | Claim it supports | Date / commit | Reproducible? | Stale vs HEAD 92742b7? | Cited correctly in docs/status.md? |
|---|---|---|---|---|---|---|
| 1 | ghcycle scored, tracked (8): `benchmarks/ghcycle/results/{flaskapiproduct,spring-demo,spring-demo-dry,propflow,propflow-dry,banking,banking-dry,flaskapiproduct-corrected-20260914a}.json` | 4-repo GitHub campaign fails acceptance; 0/8 all stages | Runs 09-12→09-14. Committed `eaeee71` (09-13); corrected run 09-14 | **Partial.** `run_cycle.py` is present, but no ASET commit SHA, spec/test-spec text, model chain, timestamps or target-repo SHA are recorded (`run_cycle.py:239-246`). LLM nondeterminism is not controlled | **Yes.** Predates `d6b503c` (09-14) and the 31 commits of 09-16 | **Yes.** Stage table and tool counts 97/31/36/102/103/95/67 match exactly. The vacuous `delivery` PASS is acknowledged (L81-85) |
| 2 | `ghcycle/results/shallow-push.json` + `probe_shallow_push.py` | Depth-1 push accepted, branch and checkout cleaned. Proves git transport only | 09-13 `af0d764` | Yes: script + `tests/unit/test_ghcycle_shallow_push.py`. Needs GitHub credentials | Low | Yes (L144-151), scope stated honestly |
| 3 | ghcycle scored, **untracked** (18): `flaskapiproduct-dry-20260916{a..k}`, `spring-demo-dry-20260916{a..f}`, `propflow-fixes-dry-20260913` | 0/18 all stages. The 09-16 campaign against two requirements | 09-13 (1), 09-16 10:49→18:11 (17) | Partial, as in #1. Each run interleaves 1:1 with a different commit (§5, F10) | Newest evidence, but the last 3 commits (`4ff4ae2`, `31defca`, `92742b7`) have **no** run | **Not cited.** status.md is silent on the 09-16 campaign |
| 4 | ghcycle raw (27, git-ignored): `results/raw/*-run.json` | Full run receipts (route, review, model_usage, tool_outcomes, applied_diff) | 09-12→09-16 | No for third parties (local, unredacted by design, `run_cycle.py:209-211`) | – | "reportes crudos … locales e ignorados" ✓ |
| 5 | `benchmarks/multistack/baselines.json` | Independent (non-ASET) baseline of 3 external repos: commands, exit 0, test counts | 2026-09-05, `3ad9a22` | Yes: source SHAs + commands recorded. Needs the external repos | Independent of ASET code, so staleness is low | Not cited (only a generic mention of the cases, L720) |
| 6 | `multistack/cases/{ingresos,interview,northgate}.md`, `fixtures/multinetwork/compose.yaml`, `run_trial.py` | Benchmark inputs | 09-04 | Inputs; `tests/unit/test_multistack_trial.py` | n/a | L720 ✓ |
| 7 | `multistack/gemini-key2-probes.json` | gemini-3.1-flash-lite structured probe; role validation run `apply-7f67441d…` ended HUMAN_REVIEW_REQUIRED | 09-04/09-06 | Partial (credential; model catalogue drifts) | **Yes.** 09-16 chains use gemini-3.5/3.6-flash, and google succeeds 1/25 | Not cited |
| 8 | adr14: `benchmarks/adr14/verify_run_daemon.py` + `reports/runs/adr14-trial-{1..4}/report.json` (+ `workspace/` copies of 111/52/55/83 files) | Closed dind network per run. Trial 4 `SUCCESS`, 75 `test_cases`, container and network removed | 09-09/10, `e98baaa` | Yes (script; source hashes recorded; external `order-ms`) | Moderate (container/quality code changed 09-14/16) | L616-622 ✓ (75 test cases, SUCCESS verified). **L162 cites `evaluation/benchmarks/adr14/results/report.json`, which does not exist** ✗ |
| 9 | `benchmarks/adr16/results/report.json` | Labels + sweep 5/5; collateral 0 | 09-11 `3b8681d`/`82136b5` | Yes (script). **The JSON has no date or commit** | Probably low (label logic) | L451 "5 de 5" ✓ |
| 10 | `benchmarks/adr17/results/{measurement,verification}.json` | Volume vs bind vs host cost (7 reps); workspace 9/9 | 09-11 `da2ba30`/`3b8681d` | Yes (scripts). No date or commit in the JSON | **Yes.** `da8558f` (09-16) moved node toolchains to a native volume | 9/9 ✓. **L405-410 table**: volume "0.000 s" for list/search/write are negative net values clamped to 0 (median 0.125 s < noop 0.154 s), so noise is presented as zero cost ✗ |
| 11 | `benchmarks/adr18/results/verification.json` | Infrastructure prerequisite 11/11 | 09-11 | Yes. No date or commit | Moderate (`356c19f`, `d6d9a9d` changed services 09-16) | L453 "11 de 11" ✓ |
| 12 | `reports/curated/` (9): `scenarios(.json/-live)`, `aggregate(-live)`, `multimodel-live(-local)`, `full-pytest.{txt,xml}`, `e2e-pytest.txt` | Five fixed scenarios (3 APPROVED / 2 REJECTED); multimodel run APPROVED with local qwen / groq / google; pytest summary | Committed 09-09 `4e4951f`. The XML timestamp is **2026-08-25 on a Windows host, 103 tests** | Partial (`scripts/run_evaluation.py`, `run_multimodel.py`; live runs need models) | **Very stale.** 103 tests then vs 1,270 collected by A5 at HEAD. qwen-local models return 0/26 in current traces. The .txt files are warning tails only, no summary line | Not cited. `tests/e2e/test_multimodel_evidence.py` and `test_live_evaluation_evidence.py` assert on these frozen JSONs, so they test the fixture, not the system |
| 13 | `reports/runs/*.json` (9) | `apply-run.json` APPROVED 100 (demo `calculadora-qa-demo`, all local qwen); `apply-run-ui.json` APPROVED (demo, cloud); `apply-run-dryrun` HRR; `e2e-flask(-container)`, `flask-retry-clean`, `interview-t1`, `kafka-retry` all HRR | Committed 09-09 `4e4951f` | No: older schema without `tool_outcomes`; no commit or spec | Yes | Not cited |
| 14 | `reports/traces/` (**1,747 tracked** offline traces; 230 `live=true`) | Per-run event logs | Committed 09-09 `2fbce12` | No | Yes. New traces go to `reports/generated/traces` (`apply_run.py:333`) | Not cited; not described in `reports/README.md`'s lifecycle list |
| 15 | `reports/generated/traces/` (294, ignored `.gitignore:19`) | Transient | – | – | – | – |
| 16 | `apply-debugger-flask-writes{,-v2..-v8}.json`: **8 files, byte-identical** in `reports/` and `evidence/archived/flask-low-stock-2026-09-03/` | FlaskApiProduct low-stock feature: **3/8 APPROVED** (v4 at iteration 0 in 100 s; v7 and v8 after 3 iterations, with earlier `run_tests` FAILs); 5/8 REJECTED | Runs 09-03; committed 09-09 | No: no spec, commit or `tool_outcomes`. Reviewer subscores are all 100.0 | Yes (pre-deterministic gates) | **Not cited anywhere in docs.** The only historical *accepted* work on an external repo. Duplicated |
| 17 | `reports/ui-audit-2026-08-27.md` + 2 PNG (**git-ignored**, `.gitignore:20`) | UI smoke on macOS: folder-picker dialog partly off-screen; Windows pending | 08-27 | Manual | Yes | Not cited |
| 18 | Langfuse export (outside repo) | 17 traces of the 09-16 campaign | 09-16 16:49Z → 09-17 00:11Z | Export only. **Trace `090b36dae8` (flask-k) is incomplete**: 147 TOOL observations vs 180 raw `tool_outcomes`, and the HITL span is missing | Covers everything except the last 3 commits | Not cited |

Other checks:
- `evaluation/README.md` → `scripts/run_evaluation.py` exists ✓.
- `reports/README.md` says `generated/` is ignored ✓, but it omits `reports/traces/` and the root-level `apply-debugger*` duplicates.

---

## 2. `run_cycle.py` scoring correctness

| # | Issue | Evidence | Effect | Conf. |
|---|---|---|---|---|
| S1 | `infrastructure.passed` is true whenever `not delivered` | `run_cycle.py:113-118` | 21/26 runs get a vacuous PASS | 0.95 |
| S2 | `delivery.passed = (not delivered) or PR url`. `skipped=true` sits beside `passed=true` | `run_cycle.py:174-180` | 21/26 vacuous PASS. status.md acknowledges it (L81), but the scorer is unchanged and the 18 new JSONs still carry it | 0.95 |
| S3 | `clone.passed = bool(evidence)`: "a report exists", not "the clone worked" | `run_cycle.py:109-112` | `spring-demo-dry-20260916c` cloned and ran 3 iterations (trace `b798793c96`, 117 tool calls). It then crashed with `ValueError: sensitive content is not allowed in cloud context` in Architecture, and was **scored clone=FAIL**. Only `propflow-fixes-dry-20260913` is a real clone failure (DNS in sandbox) | 0.9 |
| S4 | "N files written" counts write *operations* | `run_cycle.py:171`; `apply_run.py:658` | flask-j "11 files" = 4 distinct files; spring-f 9 = 6; spring-d 7 = 2 | 0.95 |
| S5 | Hygiene is global, not run-scoped (owner label only) | `run_cycle.py:59-95` | flask-k hygiene FAIL lists `container/aset-spring-eval-mysql` and `network/aset-spring-eval-default` from a different evaluation. False red under concurrency or residue | 0.8 |
| S6 | `spec` detail prints `reviewer said None` when the graph never reached Reviewer | `run_cycle.py:171` | flask-a and flask-b (LLM exhaustion at iteration 0) look like a review defect. The stop cause is not recorded anywhere in the summary | 0.9 |
| S7 | The summary records no ASET commit, spec text, model chain, start/end time or target SHA | `run_cycle.py:239-246` | Scored results cannot be attributed to a code version. On 09-16 commits landed between and *during* runs (§5) | 0.9 |
| S8 | `cli_stderr_tail` is mostly HF-hub warnings and progress bars | scored JSON | The crash signal survives only because it is the last 2,000 chars | 0.6 |

---

## 3. ghcycle per-run table (from `results/raw`)

Classes:
- **CVE**: pre-existing dependency advisories.
- **assert**: test assertion failure.
- **ENOTDIR**: Docker bind-mount npm flake.
- **sym**: compile error, missing symbol produced by incomplete change or project refs.
- **projref**: .NET `ProjectReference` outside the mount (F-7).
- **boot3api**: agent-authored tests import Spring Boot 3 test packages in a Boot 4 project.
- **trunc**: cause lost to the 600-char tail excerpt.
- **wsync**: WorkspaceSyncError UNAVAILABLE.
- **noex**: older reports with no excerpt.

"Stop cause" is a heuristic from errors and iterations; for the 09-16 cohort it matches A2 exactly (10/5/1).

| run | deliver | outcome (iters, route len, duration, raw mtime) | reviewer / score / category | reason | action, writes/distinct files | run_tests | tool failures by class | LLM calls / errored | stop cause |
|---|---|---|---|---|---|---|---|---|---|
| banking | Y | HRR it=3 rh=16 692s (09-13 06:57) | REJECTED/40 SECURITY | security findings require code remediation | PROPOSED 0w/0f | 3×, last=FAIL | CVE:3 sym:3 | 11/2 | stagnation @ Reviewer |
| banking-dry | N | HRR it=5 rh=24 443s (09-12 22:37) | REJECTED/40 SECURITY | security findings require code remediation | PROPOSED 0w/0f | 5×, last=FAIL | CVE:6 sym:5 | 15/2 | iteration limit (5) |
| flaskapiproduct | Y | HRR it=5 rh=24 279s (09-12 17:22) | REJECTED/40 SECURITY | security findings require code remediation | PROPOSED 0w/0f | 5×, last=FAIL | ENOTDIR:5 CVE:5 trunc:2 | 15/2 | iteration limit (5) |
| flaskapiproduct-corrected-20260914a | Y | HRR it=3 rh=16 237s (09-14 06:52) | REJECTED/40 SECURITY | security findings require code remediation | PROPOSED 0w/0f | 3×, last=FAIL (backend 62 passed; client npm) | CVE:3 ENOTDIR:2 trunc:1 | 16/7 | LLM availability @ Reviewer route |
| flaskapiproduct-dry-20260916a | N | HRR it=0 rh=5 148s (09-16 10:52) | None | – | APPLIED 2w/2f | 0× | CVE:1 | 14/10 | LLM availability @ Security |
| flaskapiproduct-dry-20260916b | N | HRR it=0 rh=4 200s (09-16 11:04) | None | – | None 0w/0f | 0× | – | 14/11 | LLM availability @ Developer |
| flaskapiproduct-dry-20260916c | N | HRR it=1 rh=9 634s (09-16 11:19) | REJECTED/40 ARCHITECTURE | tests fail against a design built on incomplete evidence | APPLIED 2w/2f | 1×, FAIL | CVE:1 assert:1 | 16/10 | LLM availability @ Developer |
| flaskapiproduct-dry-20260916d | N | HRR it=1 rh=8 264s (09-16 11:27) | REJECTED/40 ARCHITECTURE | idem | APPLIED 2w/2f | 1×, FAIL | CVE:1 assert:1 | 22/17 | LLM availability @ Architecture |
| flaskapiproduct-dry-20260916e | N | HRR it=1 rh=9 399s (09-16 11:36) | REJECTED/40 ARCHITECTURE | idem | APPLIED 2w/2f | 1×, FAIL | CVE:1 assert:1 | 34/28 | LLM availability @ Developer |
| flaskapiproduct-dry-20260916f | N | HRR it=3 rh=19 844s (09-16 12:06) | REJECTED/40 ARCHITECTURE | idem | APPLIED 6w/3f | 3×, FAIL | CVE:3 assert:3 | 51/37 | LLM availability @ Developer |
| flaskapiproduct-dry-20260916g | N | HRR it=1 rh=9 267s (09-16 12:25) | REJECTED/40 ARCHITECTURE | idem | APPLIED 2w/2f | 1×, FAIL | CVE:1 assert:1 | 26/20 | LLM availability @ Developer |
| flaskapiproduct-dry-20260916h | N | HRR it=2 rh=13 517s (09-16 12:57) | REJECTED/40 ARCHITECTURE | idem | APPLIED 4w/2f | 2×, FAIL | CVE:2 assert:2 | 28/19 | LLM availability @ Architecture |
| flaskapiproduct-dry-20260916i | N | HRR it=1 rh=10 1353s (09-16 13:22) | REJECTED/40 ARCHITECTURE | idem | APPLIED 4w/3f | 1×, FAIL | CVE:2 assert:1 | 30/22 | LLM availability @ Security |
| flaskapiproduct-dry-20260916j | N | HRR it=5 rh=27 651s (09-16 17:55) | REJECTED/40 ARCHITECTURE | idem | APPLIED 11w/4f | 5×, FAIL | CVE:5 assert:5 | 33/12 | iteration limit (5) |
| flaskapiproduct-dry-20260916k | N | HRR it=4 rh=25 781s (09-16 18:11) | REJECTED/40 ARCHITECTURE | idem | APPLIED 9w/4f | 4×, FAIL | CVE:4 assert:4 wsync:2 | 38/18 | MCP UNAVAILABLE (WorkspaceSync) |
| propflow | Y | HRR it=5 rh=24 923s (09-13 06:44) | REJECTED/40 SECURITY | security findings require code remediation | PROPOSED 0w/0f | 5×, FAIL | CVE:5 projref:5 ENOTDIR:2 | 26/13 | iteration limit (5) |
| propflow-dry | N | HRR it=5 rh=24 493s (09-12 22:29) | REJECTED/40 SECURITY | idem | PROPOSED 0w/0f | 5×, FAIL | CVE:5 projref:4 ENOTDIR:3 | 16/3 | iteration limit (5) |
| propflow-fixes-dry-20260913 | N | **CRASH, no raw** | – | – | – | – | – | – | DNS clone failure in sandbox (environment); hygiene FAIL = docker permission denied |
| spring-demo | Y | HRR it=1 rh=8 420s (09-12 22:12) | REJECTED/45 TESTING | failed tests require implementation remediation | PROPOSED 0w/0f | 1×, FAIL | CVE:1 trunc:1 | 16/12 | LLM availability @ Developer |
| spring-demo-dry | N | HRR it=1 rh=8 461s (09-12 17:37) | REJECTED/45 TESTING | idem | PROPOSED 0w/0f | 1×, FAIL | CVE:1 trunc:1 | 16/12 | LLM availability @ Developer |
| spring-demo-dry-20260916a | N | HRR it=3 rh=16 333s (09-16 13:29) | REJECTED/40 **SECURITY** | security findings require code remediation | APPLIED 6w/4f | 3×, FAIL | CVE:3 trunc:3 | 14/2 | stagnation @ Reviewer |
| spring-demo-dry-20260916b | N | HRR it=2 rh=13 1045s (09-16 16:18) | REJECTED/45 TESTING | testing evidence gate requires a real successful run and complete coverage | APPLIED 4w/3f | 2×, **SUCCESS** | CVE:2 | 39/29 | LLM availability @ Developer |
| spring-demo-dry-20260916c | N | **CRASH, no raw** (trace `b798793c96`) | – | – | 3 writes (trace) | 3×, FAIL (boot3api) | CVE:3 boot3api:3 (trace) | 29 gens / 17 err | guardrail `ValueError` at Architecture it=3 |
| spring-demo-dry-20260916d | N | HRR it=5 rh=24 888s (09-16 17:02) | REJECTED/45 TESTING | idem (lexical business_rule gate) | APPLIED 7w/2f | 5×, **SUCCESS** | CVE:5 | 34/16 | iteration limit (5) |
| spring-demo-dry-20260916e | N | HRR it=5 rh=23 715s (09-16 17:20) | REJECTED/45 TESTING | failed tests require implementation remediation | APPLIED 7w/3f | 5×, FAIL | CVE:5 boot3api:5 | 24/7 | iteration limit (5) |
| spring-demo-dry-20260916f | N | HRR it=5 rh=26 892s (09-16 17:41) | REJECTED/40 ARCHITECTURE | tests fail against a design built on incomplete evidence | APPLIED 9w/6f | 5×, FAIL | CVE:5 sym:3 boot3api:2 | 40/20 | iteration limit (5) |
| *flaskapiproduct-dry (raw only)* | N | HRR it=5 rh=24 367s (09-12 10:39) | REJECTED/40 SECURITY | idem | PROPOSED 0w/0f | 5×, FAIL | noex:12 | 16/3 | iteration limit |
| *flaskapiproduct-dry-2 (raw only)* | N | HRR it=5 rh=24 444s (09-12 11:11) | REJECTED/40 SECURITY | idem | PROPOSED 0w/0f | 5×, FAIL | noex:12 | 15/2 | iteration limit |
| *flaskapiproduct-dry-3 (raw only)* | N | HRR it=5 rh=23 378s (09-12 11:20) | REJECTED/40 SECURITY | idem | PROPOSED 0w/0f | 5×, FAIL | CVE:5 ENOTDIR:4 trunc:4 | 15/3 | iteration limit |

**Were the original tests preserved?**
- Every `applied_diff` that touches tests adds **new** test files (`--- /dev/null`, +82…+92 lines) and removes 0 lines from existing tests. One Developer plan was rejected as "target plan attempts to modify original tests" (trace).
- This is **not fully verifiable**. `applied_diff` is the capped `get_diff` summary: spring-f's diff shows 1 of 6 written files, and A2 found 7/15 receipts where diff files ≠ `changed_files`.
- The flask-corrected run executed 62 original backend tests green in 3/3 iterations. No PR diff exists. Confidence 0.6.

**Where the Spring compile errors come from.** They are in agent-authored files (`ProductRequestDtoTest.java`, `ProductValidationTest.java`, `ProductControllerTest.java`; raw `files_written` + trace writes), not in the baseline. spring-b and spring-d ran the suite green.

### 3.1 Root-cause Pareto (26 scored runs, 138 non-SUCCESS tool outcomes)

| Class | Instances | % | Cum % | Runs affected | Nature |
|---|---|---|---|---|---|
| SEC_BASELINE_DEP_CVE (`run_security_scan`/`scan_dependencies`) | 70 | 51 % | 51 % | **23/23** runs that reached Security | Pre-existing; the change cannot fix it |
| TEST_ASSERTION (Flask `?q=` filter not effective, e.g. `assert 5 == 0`) | 19 | 14 % | 64 % | 9 | Agent implementation |
| INFRA_BIND_MOUNT_FLAKE (npm `ENOTDIR`/`ENOENT`) | 12 | 9 % | 73 % | 4 | Environment (known Mac flake) |
| TEST_COMPILE_MISSING_SYMBOL (`InvalidProductNameException` ×3; Banking `CS0246`/`CS0103`) | 11 | 8 % | 81 % | 3 | Agent incomplete change (Spring); project refs (Banking, F-7) |
| PROJECT_REF_OUTSIDE_MOUNT (PropFlow "Skipping project … not found") | 9 | 7 % | 88 % | 2 | Harness (F-7), fixed after these runs; **no rerun** |
| TEST_CAUSE_TRUNCATED (600-char tail kept Maven autoconfig report / Mockito agent warnings / "client: FAIL") | 8 | 6 % | 93 % | 5 | Observability loss |
| TEST_COMPILE_FRAMEWORK_API (Boot-3 test packages, `@MockBean` on Boot 4) | 7 | 5 % | 99 % | 2 (+3 in crashed spring-c) | Agent lacks stack knowledge |
| INFRA_WORKSPACE_SYNC (UNAVAILABLE) | 2 | 1 % | 100 % | 1 | Environment/infra |

**Stop causes** (24 runs with raw + 2 crashes):

| Stop cause | Runs |
|---|---|
| LLM provider chain exhausted | **13** |
| Iteration limit (5) | 8 |
| Stagnation | 2 |
| MCP UNAVAILABLE | 1 |
| Crash, environment (DNS) | 1 |
| Crash, guardrail `ValueError` | 1 |

Reading: the top *failure* class is the pre-existing CVE baseline, and the top *stop* class is LLM availability.

---

## 4. Langfuse metrics (17 traces, 09-16)

### 4.1 Per trace

"HEAD at start" is the latest commit timestamped at or before the trace start (commit times −06:00; traces Z).

| trace | run | ≈HEAD at start | wall s | LLM s (failed attempts) | tool s: deps/sec-scan/tests | unattributed s | gens (err) | iters | consecutive repeats: same failing tests / identical test output / same CVE set / identical diff | unchanged-remediation errors |
|---|---|---|---|---|---|---|---|---|---|---|
| ed7dbfd1e6 | flask-a | d6d9a9d | 162 | 89 (35) | 3/3/0 | 66 | 14 (10) | 0 | –/–/–/– | 0 |
| 5980c6dbfa | flask-b | d6d9a9d | 209 | 157 (142) | 0/0/0 | 52 | 14 (11) | 0 | –/–/–/– | 0 |
| b94c5359fe | flask-c | d6d9a9d (eaa0aa3 lands mid-run) | 668 | 97 (50) | 17/10/51 | **493** | 16 (10) | 1 | 0/0/0/0 | 0 |
| 6f8b73c6b1 | flask-d | 0b58d07 | 274 | 191 (123) | 1/3/3 | 76 | 22 (17) | 1 | 0/0/0/0 | 0 |
| 1fb8c0d488 | flask-e | 0b58d07 | 406 | 346 (269) | 2/2/7 | 50 | 34 (28) | 1 | 0/0/0/0 | 0 |
| c6d65a00d2 | flask-f | 9d27bcd | 858 | 746 (532) | 10/8/13 | 81 | 51 (37) | 3 | 1/0/2/1 | 0 |
| 7c8ebbdc30 | flask-g | 762ec08 | 282 | 207 (173) | 2/2/4 | 67 | 26 (20) | 1 | 0/0/0/0 | 0 |
| 93970a62e2 | flask-h | 52c5560 | 527 | 433 (368) | 10/6/9 | 69 | 28 (19) | 2 | 0/0/1/0 | 0 |
| 15dcd59512 | flask-i | 51aa5c1 (7af574e mid-run) | 1366 | 325 (231) | 204/131/22 | **684** | 30 (22) | 1 | 0/0/1/0 | 0 |
| d29547c7b7 | spring-a | 7af574e | 339 | 117 (1) | 28/104/17 | 73 | 14 (2) | 3 | 2/2/2/1 | 0 |
| e949a73ed9 | spring-b | b99c939 (c2d29d2, 004b612 mid-run) | 1056 | 510 (416) | 55/336/18 | 136 | 39 (29) | 2 | tests green/–/1/1 | 4 |
| b798793c96 | spring-c (crash) | 1b054ef | 491 | 268 (167) | 26/177/18 | 2 | 29 (17) | 3 (partial) | 2/2/2/1 | 1 |
| 38863321ef | spring-d | 78b487e/41463de | 899 | 519 (219) | 31/218/41 | 89 | 34 (16) | 5 | tests green/–/4/3 | 1 |
| f9ca92d099 | spring-e | ba8b375 | 725 | 375 (184) | 38/209/16 | 86 | 24 (7) | 5 | **4/4/4/4** | **0** |
| 1885fc593d | spring-f | d8cd3f3 | 899 | 585 (241) | 36/186/16 | 76 | 40 (20) | 5 | 3/1/4/0 | 1 |
| a2cb449e2a | flask-j | 279e98d | 666 | 547 (191) | 10/10/20 | 79 | 33 (12) | 5 | 1/0/4/0 | 0 |
| 090b36dae8 | flask-k | 2a11002 | 798 | 495 (195) | 9/8/16 | 270 | 30 (13) | 4 | 1/0/3/0 | 0 |
| **Total** | | | **10,624 (177 min)** | **6,010 (3,536)** | **481/1,414/270** | 2,449 | 478 (290) | | 14 of 22 FAIL→FAIL pairs / 9 / **28 of 28** / 11 of 28 | 7 |

- **Wall-clock:** median 667 s over 16 rooted runs, mean 625 s over 17, max 1,366 s.
- **Trace `b798793c96`:** no CHAIN root, no HITL span, last observation 22:36:59.780. The Reviewer#3 → Architecture remediation route is the last AGENT transition, followed by the process-level `ValueError` from the cloud-context guardrail (scored JSON stderr, `spring-demo-dry-20260916c.json`). **It was interrupted by an unhandled exception, not stopped by the harness.** Confidence 0.9.

### 4.2 By role (GENERATION observations)

| Role | Gens | Structured success | Error rate | `fallback_used=true` | Latency p50 / p95 ms | LLM time s (on failed attempts) | Tokens (successes only) | Top error categories |
|---|---|---|---|---|---|---|---|---|
| Developer | 209 | 90 (43 %) | 57 % | **0** | 7,981 / 45,250 | 2,774 (1,267) | 1,058,801 (68 %) | 429 (27), ollama HTTPStatusError (14), 413 (17), timeout (13), 503 (12), target-plan rejected (10), ineffective remediation (7) |
| Architecture | 137 | 39 (28 %) | 72 % | 0 | 1,028 / 20,149 | 929 (591) | 295,200 | **429 (66**, mistral-medium 46/46), governed-fields differ (9), 413 (6), 503 (5) |
| Security | 115 | 42 (37 %) | 63 % | 0 | 16,106 / 55,396 | 2,259 (**1,678 = 74 %**) | 166,890 | **governed fields differ: findings (26+)**, incomplete output (15), 400 (7), 429 (5), 503 (5) |
| Product | 17 | 17 (100 %) | 0 % | 0 | 2,920 / 3,330 | 49 | 35,028 | – |
| Testing / Reviewer | 0 (42 AGENT obs each) | deterministic | – | – | – | – | – | – |

### 4.3 By provider/model (de-duplicated error categories = `metadata.error_category`/`http_status`)

| Provider | Model | Attempts | Success | % | Top errors | Latency p50/p95 all (ms) | p50/p95 success (ms) | Tokens |
|---|---|---|---|---|---|---|---|---|
| groq | openai/gpt-oss-120b | 95 | 46 | 48 % | **413 ×23** (non-retryable), 429 ×14, 400 ×8, incomplete ×3 | 2,730/7,509 | 3,017/6,892 | 212,203 |
| mistral | codestral-latest | 87 | 64 | 74 % | governed ×9, timeout ×7, ineffective ×5 | 10,185/45,230 | 10,185/33,229 | 697,356 |
| cohere | command-a-03-2025 | 63 | 58 | **92 %** | governed ×5 | 15,851/33,300 | 16,106/33,300 | 477,511 |
| openrouter | nvidia/nemotron-3-super-120b-a12b:free | 56 | 4 | 7 % | governed ×29, incomplete ×13, provider_unavailable ×8, invalid_response ×2 | 33,232/73,167 | 8,954/19,283 | 13,789 |
| mistral | mistral-medium-latest | 46 | 0 | 0 % | **429 ×46** | 686/1,060 | – | 0 |
| google | gemini-3.5-flash | 21 | 1 | 5 % | 503 ×13, timeout ×4, 400 ×3 | 10,012/55,073 | 13,182 | (priced 0.0472 USD) |
| mistral | mistral-small-latest | 19 | 0 | 0 % | 429 ×19 | 669/1,494 | – | 0 |
| ollama | qwen3.5:9b | 19 | 0 | 0 % | HTTPStatusError (uncategorized) | 49/213 | – | 0 |
| xkiro | deepseek-v4.1-flash:free | 12 | 0 | 0 % | 429 ×8, 500 ×4 | 2,049/3,388 | – | 0 |
| xkiro | deepseek-v4-pro | 10 | 5 | 50 % | 429 ×5 | 2,874/25,408 | 13,382/25,408 | 34,911 |
| xkiro | qwen3-coder-plus:free | 9 | 2 | 22 % | 429 ×5, governed ×2 | 2,863/22,087 | 15,611/18,975 | 39,656 |
| ollama | qwen3.5:4b | 7 | 0 | 0 % | HTTPStatusError | 56/254 | – | 0 |
| vyce | agnes-3.0-flash | 6 | 3 | 50 % | ineffective ×2, governed ×1 | 10,511/17,351 | 8,561/10,511 | 18,235 |
| xkiro | mistralai/codestral-2508 | 5 | 1 | 20 % | timeout ×2, governed ×2 | 39,539/45,208 | 34,583 | 11,184 |
| google2 / google | gemini-3.6-flash | 4 + 4 | 0 | 0 % | 503 ×6, 400 ×2 | ~7–8 s / 22–30 s | – | 0 |
| kilo | nemotron-3-super:free | 3 | 1 | 33 % | governed ×2 | 53,942/75,853 | 75,853 | 8,356 |
| vyce | deepseek-v4-flash / v4.1 | 3 + 2 | 0 | 0 % | schema ×2, governed ×1, timeout ×2 | – | – | 0 |
| cloudflare | @cf gpt-oss-120b / nemotron-3-120b | 2 + 2 | 1 + 2 | 75 % | governed ×1 | 15–25 s | 20–28 s | 30,401 |
| xkiro | mistral-medium-3.5 | 2 | 0 | 0 % | governed ×2 | – | – | 0 |
| nvidia | nemotron-3-super-120b-a12b | 1 | 0 | 0 % | 503 | 38,563 | – | 0 |

**Generation-level error categories (sum 290):**

| Category | Count |
|---|---|
| rate_limit / 429 | 98 |
| governed_contradiction | 55 (includes "findings" ×26 and target-plan rejections ×11) |
| ollama HTTPStatusError (no category) | 26 |
| request_rejected / 413 | 23 |
| provider_unavailable / 503 | 21 |
| incomplete_output | 16 |
| timeout (ReadTimeout) | 15 |
| request_rejected / 400 | 13 |
| provider_unavailable, relayed | 8 |
| ineffective_remediation ("LLM_QUALITY_ERROR: unchanged developer remediation") | 7 |
| provider_unavailable / 500 | 4 |
| schema_validation | 2 |
| invalid_response (`KeyError: missing response field 'choices'`, the F-9 detail working) | 2 |

"Role deadline exceeded" appears 7× in `model stage retry` spans.

### 4.4 RAG retrieval (128 RETRIEVER observations)

- **Callers:** Security 44, Testing 42, Architecture 42. Status OK 128/128. Latency 0 ms (not timed).
- **Only 6 distinct queries** (the raw spec text per role × task), so each iteration retrieves exactly the same chunks. Retrieval adds no new information across remediation loops.
- **38/128 (30 %) return 0 results.** Architecture/Flask is 28/28 empty and Architecture/Spring 10/14 empty.
- The rest return the same 4 generic guideline chunks (scores 0.60–0.77). Sources: `owasp-api-security.md` 111, `testing-strategy.md` 84, `security-guidelines.md` 65, `api-design-guidelines.md` 54, `coding-standards.md` 42, `architecture-guidelines.md` 4.
- **Irrelevant hits:** Testing for the Java/Spring task retrieves "Coding Standards / C# and .NET 10 Development Standards" 23/23 times. Security for Flask retrieves "Password Hashing" every time.
- No project code, framework version facts or Boot 4 test API guidance is ever retrieved. That matches the TEST_COMPILE_FRAMEWORK_API root cause. Confidence 0.85.

### 4.5 Tokens, cost, telemetry coverage

- **Tokens** are recorded on 188/478 generations (successes only): 1,555,919 total, of which prompt 1,299,399. Failed attempts have no token or cost accounting, including 23 prompts rejected as too large (413).
- **Cost:** `totalCost>0` on **1/478** generations (Langfuse's own gemini pricing = the whole 0.0472 USD). Cost tracking is effectively unpopulated.
- **`fallback_used`** is false on 478/478, although 452 generations ran under profile `CLOUD_FALLBACK` and 106 stage groups used the chain. The cloud runtime is primary, so `fallback_used=not self.primary` is always false (`llm/cloud.py:607,657,704`). Dead telemetry. Confidence 0.9.
- **TOOL observations** have `latencyMs=0`; duration exists only inside the output JSON `duration_ms`. All 1,649 TOOL observations are flat children of the root, not of AGENT spans, so tool→agent→iteration attribution requires timestamp inference.
- **Export completeness:** flask-k trace is missing 33 TOOL observations and its HUMAN_REVIEW_REQUIRED span. HITL spans total 15, roots 16.
- **HUMAN_REVIEW_REQUIRED reasons:** the CHAIN output has no reason field and the HITL span only `{hitl, iteration}`. The reason must be inferred (§3 stop causes). HITL iteration distribution: 0:2, 1:5, 2:2, 3:2, 5:4 (4 = k, span missing).

---

## 5. Harness metrics (framework B §18), reconciled with A2 §1

| Metric | A4 value | A2 value | Reconciliation |
|---|---|---|---|
| Accepted work rate | 0/26 scored ghcycle; 0/24 raw-backed; 0/16 rooted traces. **Historical: 3/8 APPROVED** (`apply-debugger-flask-writes` v4/v7/v8, FlaskApiProduct, 09-03) and 2 APPROVED on the in-repo demo (`reports/runs/apply-run*.json`) under the pre-09-09 harness | 0/16, 0/27, 0/42 reviewer decisions | **Agree** on current. A4 adds that accepted work existed under the older harness; the regression is uncited |
| First-pass acceptance | 0 current; 1/8 historical (v4, iteration 0) | 0 | Agree |
| Repeated failure rate | Same CVE set on **28/28** consecutive rescans. Same failing-test set on 14/22 consecutive FAIL pairs (64 %); byte-identical test output 9/22. Identical diff on 11/28 consecutive pairs (39 %) | 22/27 (81 %) remediation transitions repeat the failure class; harness flagged 7 | Consistent (different granularity). **Disagreement:** A2 "41/44 scans report the same CVEs"; A4 finds **44/44** (Flask 21 scans all hash `3846c6`, Spring 23 all `528467`). A2 likely excluded spring-c's 3 scans. Confidence 0.85 |
| Detection of no-change retries | 7 `unchanged developer remediation` errors, counted per provider attempt (spring-b 4). **spring-e: 4 consecutive identical diffs + identical compile errors, 0 detections** | `repeated_failures≥2` on 7 | Agree on the gap; A4 adds the spring-e counterexample |
| Recovery after tool failure | run_tests: 0/13 traced runs, 0/23 raw runs ever went green after a FAIL. Security: 0/26 | 0/13 | Agree |
| Recovery after model failure | Per stage group (consecutive attempts, same role): **96/106 (91 %)** recovered via the provider chain. Ollama 0/26 | "model stage retry" 6/16; Ollama 0/26 | Different definitions, both true. The chain recovers most per-call failures; once a whole chain is exhausted, the stage retry rarely recovers, and 13/24 raw runs ended there |
| Human interventions per task | 1.0 (every run ends HRR). 09-16: 17 relaunches, 31 commits (1.8 harness changes per run) | Same | Agree |
| Unsupported completion claims | Run level: 0 (nothing approved). **Scorer level:** 21/26 vacuous `infrastructure`/`delivery` PASS; 1 misattributed clone FAIL; "files written" inflated in 10/15 runs with writes. **Doc level:** "978 PASS … ningún fallo pendiente" and "1038 aprobadas" have no artifact (§6) | 0; receipt inaccuracy 7/15 | Agree; A4 adds scorer and doc levels |
| Time to outcome | Median 667 s (rooted traces); ghcycle raw median 461 s, 4.19 h over 27 runs. Time to *verified* outcome undefined | 177 min, mean 10.4 min | Agree (A4 sum 10,624 s = 177 min) |
| Overhead by component (17 traces, 10,624 s) | LLM wait 6,010 s (**57 %**), of which **failed attempts 3,536 s (33 % of all wall-clock)**. Tools 2,165 s (20 %): security scan 1,414 (13 %; first scan per run 1,093, repeats 321), deps 481 (4.5 %), tests 270 (2.5 %). Unattributed (container setup, workspace sync, embeddings) 2,449 s (23 %), flask-i 684 s and flask-c 493 s | Developer 46.2 min, Security LLM 37.6, scans 31.6, Architecture 15.5, run_tests 4.5 | Agree to ±0.1 min (Security LLM 2,259 s, Developer 2,774 s, Architecture 929 s). A4 adds the failed-attempt share and the unattributed 23 % |
| Cost / tokens | 1/478 priced; 1.556 M tokens on successes only | 0.0472 USD from 1 generation | Agree |

**Commit/run interleaving on 09-16** (`git log`, local −06:00 vs trace Z):
- 31 commits and 17 runs alternate almost 1:1.
- Commits landed **during** flask-c (`eaa0aa3`), flask-i (`7af574e`) and spring-b (`c2d29d2`, `004b612`).
- No run records its commit.
- `4ff4ae2`, `31defca` (revert) and `92742b7` came after the last trace (00:11Z) and have **zero** run evidence.

---

## 6. docs/status.md claim cross-check

| L# | Claim | Evidence found | Verdict |
|---|---|---|---|
| 87-100 | Seven results: stage table; HRR, REJECTED, 0 applied files, 0 UNAVAILABLE; tool counts 97/31/36/102/103/95/67 | Scored and raw JSON match exactly | ✓ Supported |
| 59-62 | Corrected run: clone/infra/hygiene green, execute/spec/delivery red; 3 iterations ran 62 original backend tests green; client ENOTDIR/ENOENT, then no detail | Raw: "62 passed" in all 3 run_tests excerpts; 2 ENOTDIR/ENOENT + 1 "client: FAIL" without detail | ✓ Supported |
| 73-77 | The three proposals stayed PROPOSED without file_contents | Raw `action_mode=PROPOSED`, 0 writes | ✓ Supported |
| 63-71 | npm audit JSON truncated at 4,096 bytes; transport now keeps 4 MiB for structured scanners; 111 focal tests pass | Code: `mcp/command.py:19-20` (`_OUTPUT_LIMIT=4096`, `_STRUCTURED_OUTPUT_LIMIT=4*1024*1024`), `mcp/test_evidence.py:15`. 09-16 Flask scans carry full GHSA advisories. The 111-test count has no artifact | ✓ Code-supported; test count unsupported |
| 41-55 | F-8: provenance aggregation fixed (09-14); pre-existing advisories classified as baseline risk | On 09-16, Flask runs (Security role) and spring-b onward show "Residual baseline dependency risk … manifests were not modified". **spring-demo-dry-20260916a (13:29, after d6b503c) was still REJECTED/SECURITY: "security validation tool did not pass"**. Maven only worked after `b99c939` (09-16 15:55, "pass the Maven advisory report directory by its real property"). The scan stays FAIL by design, and every run still counts it as `TOOL_ERROR` (28/28 identical rescans) | ⚠ **Overstated.** The fix was incomplete for Maven until 09-16 and does not stop the loop |
| 19-32, 34-36 | F-7: sibling-module mount fixed; 156 focal tests; Banking 71 original tests pass in Docker | No ghcycle rerun of PropFlow or Banking after the fix (last runs 09-12/13 show `projref`/`sym`). No artifact for the 71-test run or the 156 tests | ⚠ **Unsupported by persisted evidence** |
| 22-24, 124 | F-9: KeyError reports protocol keys only | Trace: `CLOUD_FALLBACK_UNAVAILABLE: KeyError: missing response field 'choices'` ×2 | ✓ Supported |
| 56-58 | Integrated suite 09-14: 1,038 passed, 17 skipped | No junit or log in repo. Static count at HEAD: 1,024 `def test_` in 91 files + 83 `parametrize`. A5 at HEAD: 1,270 tests, **26 failures**, 23 skipped (hermetic) | ⚠ Unsupported, not reproducible at HEAD |
| 166-174 | Task 7: 952 PASS + 26 retried = **978 PASS, 20 SKIP, no pending failure** | No artifact, no commit SHA, "Task 7 selection" undefined in repo. `reports/curated/full-pytest.xml` is 103 tests (2026-08-25, Windows) | ⚠ **Unsupported** (narrative only) |
| 102 | MySQL observed `healthy` per the ledger capture | No capture in repo | ⚠ Unsupported |
| 162 | "Does not regenerate `evaluation/benchmarks/adr14/results/report.json`" | The file and directory do not exist; adr14 reports live in `reports/runs/adr14-trial-*` | ✗ Broken reference |
| 191 | "Base inspeccionada: 4294b9e…, rama grok-multistack-validation" | Current branch `gh-run-testing @ 92742b7` | ✗ Stale header |
| 399-410 | ADR 17 medians; volume list/search/write = 0.000 s | `measurement.json` `net_seconds` = 0.0 because medians are below the noop median (volume list 0.1252 < noop 0.1545), i.e. clamped negatives | ⚠ Noise shown as zero |
| 451-453 | adr16 5/5, adr17 9/9, adr18 11/11 | JSON `checks[].passed` all true | ✓ Supported, but the JSON has no date/commit and predates 09-16 workspace/services changes |
| 616-622 | adr14 trial 4 SUCCESS, 75 tests, 0 failures | `adr14-trial-4/report.json`: `status=SUCCESS`, 75 `test_cases`, container and network removed | ✓ Supported |
| (whole doc) | Latest campaign narrative | 09-16 dry runs (17), 31 commits and new providers are absent; only "revisión independiente del 16 de septiembre" is mentioned | ✗ Stale ledger |

---

## 7. Findings (severity-ranked)

### HIGH

**F1. No accepted work in any current-harness evidence; tests never recover.** Confidence 0.95.
- 0/26 scored ghcycle runs, 0/16 rooted traces, 0/24 raw reviews APPROVED. 100 % end HUMAN_REVIEW_REQUIRED.
- 0/23 raw runs with a failing `run_tests` ever reached green, and 0/26 security FAIL runs recovered.
- 2 Spring runs (b, d) had green suites 7/7 and were still rejected (see F8).
- Historical acceptance (3/8 on FlaskApiProduct 09-03) exists but is uncited, so the regression is invisible in docs.
- Evidence: §3 table; `evidence/archived/flask-low-stock-2026-09-03/*.json`.

**F2. The pre-existing dependency CVE baseline is the #1 failure class, and the loop retries it without changing any condition.** Confidence 0.9.
- 70/138 (51 %) failure instances; 23/23 runs that reached Security; 44/44 traced scans.
- The CVE set is identical on 28/28 consecutive rescans.
- Cost: 1,414 s of scan time (13 % of wall-clock), 321 s of it on pure repeats.
- The Security LLM spends 1,678 of its 2,259 s on attempts rejected because they contradict the deterministic findings ("governed fields differ: findings").
- Pre-09-16 reviews routed SECURITY → Developer, a class the Developer cannot fix (e.g. banking/propflow "security findings require code remediation").
- Evidence: §3.1, §4.1, §4.2; raw `review.remediation_category`.

**F3. LLM availability, not reasoning or the iteration budget, ends most runs.** Confidence 0.85.
- 13/24 raw-backed runs and 10/16 rooted 09-16 runs stopped after chain exhaustion.
- 290/478 (61 %) generations failed; 57 % of wall-clock is LLM wait, and 33 % of total wall-clock is spent on attempts that fail.
- Chronic non-recovering configurations:
  - mistral-medium 46/46 429 (Architecture chain head);
  - mistral-small 19/19 429;
  - groq gpt-oss-120b with 23 non-retryable 413s repeated across runs;
  - local Ollama 0/26 in ~50 ms (server not reachable, yet kept in chains);
  - openrouter nemotron 4/56.
- Evidence: §4.2–4.3.

**F4. The ghcycle scorer produces vacuous or misattributed stages and unattributable results.** Confidence 0.85.
- `infrastructure` and `delivery` pass whenever not delivered (21/26).
- `clone` means "a report exists": spring-c's guardrail crash in Architecture was scored clone=FAIL.
- "files written" counts operations, not files.
- Hygiene is not run-scoped: flask-k failed on another eval's `aset-spring-eval-mysql`.
- No commit SHA, spec text, model chain or timestamps are recorded.
- Evidence: §2 S1–S8, `run_cycle.py:109-180,239-246`.

**F5. Diagnostic evidence is lossy exactly where root cause lives.** Confidence 0.85.
- Tool error excerpts keep only the last 600 chars (`apply_run.py:565,597`). Maven tails keep the autoconfig report or Mockito warnings, and the root cause is lost in 8 instances across 5 runs (the class status.md labels F-11).
- `applied_diff` is a capped summary that omits written files (spring-f shows 1 of 6), so test preservation cannot be proven from receipts.
- Langfuse `run_tests` output is capped at 4,000 chars.
- TOOL observations are untimed (`latencyMs=0`) and flat under the root.

### MEDIUM

**F6. No-change retries go undetected.** Confidence 0.75.
- The same failing-test set repeats on 14/22 consecutive FAIL pairs, and identical diffs appear on 11/28 consecutive pairs.
- spring-e: 5 identical diffs and 5 identical Boot 3 compile errors, 0 "unchanged remediation" detections.
- The detector only compares the `file_contents` dict with the previous implementation (`llm/runtime.py:262-279`). The 7 detections it did make are counted per provider attempt.
- RAG queries are identical every iteration (6 distinct queries), so no new context arrives either.

**F7. Stack knowledge gap is the test-failure root cause, and the fix is unvalidated.** Confidence 0.75.
- Agent-authored Spring tests use Boot 3 test packages and `@MockBean` on a Boot 4 project (7 instances + 3 in spring-c); `InvalidProductNameException` was referenced but never created (3).
- RAG retrieves "C# and .NET 10 Development Standards" 23/23 times for the Java task; Architecture retrievals are empty in 38/42 calls.
- `92742b7` ("state the project's declared stack") targets this but has **no run evidence**.

**F8. A lexical coverage gate rejects green suites.** Confidence 0.7; agrees with A2.
- spring-b and spring-d had `run_tests` SUCCESS in every iteration and were still REJECTED.
- The reason: "a passing test's name or body must mention one of: blanco, carácter, contener…", i.e. Spanish spec terms matched against English Java test names (`agents/reviewer.py:374-383`).
- Reviewer subscores take only {0, 40, 45, 70, 75} in 26 raw runs, so they carry little information.

**F9. status.md numeric claims lack artifacts, and the ledger is stale.** Confidence 0.8.
- No artifact for 978 PASS / 20 SKIP, 1,038/17, 156/111/73 focal tests, or Banking 71 tests; no commit SHA.
- A5 at HEAD observes 1,270 tests with 26 failures (hermetic run), which cannot be reconciled.
- F-8 is overstated for Maven before `b99c939`.
- F-7 has no rerun.
- Broken `adr14/results/report.json` reference and stale base header.
- ADR 17 volume "0.000 s" is noise.
- The 09-16 campaign is not recorded.
- Evidence: §6.

**F10. One change per run, with no replication.** Confidence 0.8.
- 31 commits interleaved with 17 runs; 4 commits landed mid-run; the last 3 commits are untested.
- Each change is judged on n=1 under provider variance that status.md itself calls out (F-8-variabilidad).

**F11. Telemetry fields are dead or partial.** Confidence 0.85.
- `fallback_used` false 478/478 (`llm/cloud.py:607`).
- Cost populated 1/478; tokens only on successes.
- The flask-k export is incomplete (33 tools and the HITL span missing).
- HITL has no machine-readable reason.
- ERROR counts are inflated ×1.45 by mirror spans (421 vs 290 generation errors).

**F12. A guardrail refusal crashes the run instead of degrading it.** Confidence 0.8.
- spring-c: `ValueError: sensitive content is not allowed in cloud context` at Architecture, iteration 3.
- Result: no raw report, no root span (trace `b798793c96`, 188 obs, 491 s), 3 iterations of work lost, scorer blames clone.
- Commits `78b487e`/`41463de` improve redaction; that the unhandled path now degrades gracefully is unverified.

### LOW

**F13. Evidence hygiene problems.** Confidence 0.7.
- 8 `apply-debugger*` JSONs duplicated byte-for-byte in `reports/` and `evidence/archived/`.
- 1,747 tracked offline traces are undocumented in `reports/README.md`.
- "Curated" pytest snapshots are 08-25 Windows outputs of 103 tests; `.txt` has no summary line.
- e2e tests assert on frozen curated JSON.
- ADR result JSONs carry no date or commit.
- `ui-audit` is git-ignored but lives in the reports tree.

**F14. Environment-induced failures should be excluded from product metrics.** Confidence 0.8.
- Bind-mount ENOTDIR (12 instances, 4 runs; known Mac flake).
- WorkspaceSyncError (2).
- DNS clone failure and docker-permission hygiene in `propflow-fixes-dry-20260913` (sandbox).
- Hygiene leftovers in 2/24 runs (one cross-eval).
- None are ASET reasoning failures, but none are separated by the scorer.
