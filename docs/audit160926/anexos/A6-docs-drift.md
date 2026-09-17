> Papel de trabajo de la auditoría del 2026-09-16 (docs/audit160926), conservado tal como lo entregó su auditor, salvo rutas locales sustituidas por `~` y `<scratchpad>`. No es documentación vigente: las conclusiones adjudicadas están en las páginas de la auditoría y en el registro de hallazgos.

# A6: Documentation governance and drift audit

Auditor A6, read-only. Repo `MultiAgent-Software-Engineering-Team.`, branch `gh-run-testing` @ `92742b7`.
Methods used: living-docs-governance (roles: Constitution, Map, Status, History; one owner per fact; delete-zone) and update-docs (compare docs with their sources of truth, check staleness).

## 0. Commands run (evidence base)

| Check | Command | Result |
|---|---|---|
| Documentation contract | `#!/bin/bash` script: unset every upper-cased `Settings.model_fields` key and `LANGFUSE_HOST`, `export DELIVERY_BACKEND=none`, `PYTHONPATH=src .venv/bin/python -m pytest tests/integration/test_documentation.py tests/mcp/test_quality.py::test_quality_container_contract_is_documented -q -p no:cacheprovider` | **8 passed**. These tests only check links, owners, the ADR index and archive hashes. They check no factual claims (counts, CLI, providers, limits). |
| CLI surface | `env -i ... .venv/bin/python -m engineering_team.cli --help` and `run-project --help` | Commands: `run`, `run-project`, `reset-project`, **`docker-sweep`**. `run-project` flags: `--spec`, **`--repo`**, **`--clone-depth`** (default 1), `--test-spec`, `--authorize-writes/--dry-run`, `--confirm-delivery` (requires `DELIVERY_BACKEND=gh`), **`--report-path`**. |
| Settings vs `.env.example` | Python `Settings.model_fields` dump (names only, secret defaults redacted), regex over `.env.example` | 56 fields. 10 are missing from `.env.example`: `MAX_REMEDIATION_ITERATIONS, QUALITY_CONTAINER_IMAGE, QUALITY_RUN_DAEMON_IMAGE, QUALITY_RUN_DAEMON_IMAGES, QUALITY_STACK, QUALITY_COMPONENT_PATH, DELIVERY_BACKEND, GITHUB_MCP_IMAGE, DEVELOPER_ROLE_TIMEOUT_SECONDS` (appears only in a comment, `.env.example:68`), `MODEL_HEALTH_PATH`. `.env.example` has no names that are not Settings fields. |
| Ruff | `.venv/bin/python -m ruff check src/engineering_team` | 2 findings: `agents/security.py:59` SIM103 and `mcp/quality.py:1545` PYI034. status.md cites them at :68 and :1357. |
| Test files | `git ls-files tests` matching `test_*.py`; `grep 'def test_'` | 91 files, 1033 test functions |
| PROJECT_STATE.md | `git check-ignore -v PROJECT_STATE.md` | `.gitignore:26:PROJECT_STATE.md`: **not versioned**. 203 lines, mtime 2026-09-16 18:38. |
| Commits after last status edit | `git rev-list --count 90ba069..HEAD`; `git log --name-only 90ba069..HEAD \| grep .md` | 30 commits. **None touched any `.md`.** |
| Untracked ghcycle results | JSON parse of `results/*20260916*.json`, `propflow-fixes-dry-20260913.json`, and `results/raw/*-run.json` | See §3.2 |

---

## 1. Role map

| Doc | Governance role | Declared owner of | Assessment |
|---|---|---|---|
| `AGENTS.md` | **Constitution** + top-level map (where things live, owner table, agent rules) | Rules for agents, document owners | Good. One incomplete row (prompts, D-20). |
| `CLAUDE.md`, `.github/copilot-instructions.md` | Harness adapters → Constitution | Nothing (pointers only) | Good: 3 lines each, pointers only. |
| `README.md` | Product front page (not a governance role) | Nothing by its own rules. It says evidence belongs to status. | **Holds many facts with a second owner** (config defaults, CLI, test count, ADR count, iteration limit). Most drift is here. |
| `docs/README.md` | **Map** (task → module → tests) | "¿Dónde cambio esto y qué pruebo?" | Missing rows for code added on 2026-09-16. |
| `docs/architecture/overview.md` | Architecture: current composition (Map sub-role) | Composition and limits | Stale since 2026-09-10 (35 commits to described code since then). |
| `docs/architecture/decisions/README.md` + 0001–0018 | Decisions (the "why") | Durable decisions | Index consistent with records. ADR 0008 contradicts code (D-17). |
| `docs/operations.md` | Operations (how to install, configure, run) | Install, config, CLI, API/frontend | Delegates providers and chains to code. CLI and config are incomplete. |
| `docs/testing.md` | Operations for checks | Checks and how to run them | Does not describe the clean-env requirement, which the suite needs to pass. |
| `docs/status.md` | **Status** (evidence ledger + delete-zone) | Verified vs not verified; do-not-recreate zone | **Role is mixed.** About 70% of its 736 lines are dated verification logs (history-shaped). Stale after 2026-09-14. |
| `docs/history.md` | **History** | Documentation decisions and retirements | Last entry 2026-09-13. Also carries engineering narratives that repeat status. |
| `evaluation/README.md`, `benchmarks/README.md`, `reports/README.md`, `evidence/README.md` | Local maps for the evaluation tree (English) | Layout of evaluation assets | Written 2026-09-09. They do not list ghcycle, the adr14/16/17/18 runners, or the tracked top-level report files. |
| `PROJECT_STATE.md` (git-ignored) | Personal handoff | Nothing (ADR index says ADRs outrank it) | Has sections "Arquitectura vigente", "Decisiones" and "Cosas que NO hacer". These are shadow Constitution/Architecture/Delete-zone roles, mostly dated 2026-09-01..06. |
| Code comments in `llm/cloud.py:35-38, 63-79, 139-152` and commit bodies | *De facto* Status + Delete-zone for LLM providers | Provider probe results, excluded models, removed SambaNova | **Evidence lives outside its owner** (G-2). |

### 1.1 Facts with more than one owner (duplication)

| # | Fact | Where stated | Conflict? | Canonical owner (proposal) |
|---|---|---|---|---|
| DUP-1 | Defaults of `LOCAL_FIRST` / `CLOUD_ENABLED` | README.md:106-107 (`false`/`true`), operations.md:21 (`True`/`False`), `.env.example:4,53` | **Yes.** README gives `.env.example` values as "Por omisión". | operations.md. README should link to it. |
| DUP-2 | CLI commands and flags | README.md:84-93, overview.md:12,85-86, operations.md:27-36 | All three stale in the same way (no `docker-sweep`, `--repo`, `--clone-depth`, `--report-path`) | operations.md, pointing to `--help` |
| DUP-3 | Reviewer iteration limit | README.md:44-45, overview.md:127,141-143 | Both wrong (D-1, D-8) | overview.md, with a link to `routers.py` |
| DUP-4 | ADR count | README.md:144 ("Catorce"), docs/README.md:29 ("dieciocho, uno reemplazado"), ADR index | **Yes** | ADR index. Others should state no count. |
| DUP-5 | Test layout / count | README.md:121 ("72 archivos"), AGENTS.md:28, testing.md | **Yes** (91 actual) | testing.md, without a count |
| DUP-6 | Stack profile phases | README.md:40-42, overview.md:184-187 | Consistent | overview.md |
| DUP-7 | Dated verification narratives (ADR 16/17/18 verification, sandbox retirement, Docker cleanup) | status.md:242-528 and history.md:12-208 | Snapshot counts differ by date (history.md:37-38 "9 de 9" for ADR 18 vs status.md:453 "11 de 11"; `results/verification.json` has 11/11) | history.md for the narrative. Status keeps only the current verdict and the last evidence. |
| DUP-8 | Clean-env procedure for tests | status.md:26-27, 168-170, 236, 245-246 (4 times) | Not in testing.md at all | testing.md |
| DUP-9 | Evaluation layout | status.md:195, evaluation/README.md, evaluation/reports/README.md | Minor | evaluation/README.md |
| DUP-10 | Provider strategy per role | `.env.example` comment block (lines 32-38), `llm/cloud.py` comments | No doc owner at all | overview.md (composition) + status.md (probe evidence) |

### 1.2 Missing roles / owners

1. **LLM providers, role chains, model-health ledger, Developer timeouts.** No active doc owns them. overview.md:32 lists 4 providers; the code has 12 logical providers. operations.md:21 sends the reader to the code. This subsystem took 17 of the 31 commits on 2026-09-16.
2. **Current-capability matrix in Status.** status.md has no table of the form "capability → last evidence (date, commit, command) → verdict". The reader has to rebuild the current state from dated narratives.
3. **History entries after 2026-09-13.** The 2026-09-14 transport and provenance fix and the 2026-09-16 work (providers, target planning, declared stack, model health, revert) are missing.
4. **Delete-zone entries for retirements that exist only in code or commits:** blind rotation of the Developer chain on later remediations (d8cd3f3, reverted by 31defca); SambaNova provider (`cloud.py:139-141`); deliberately excluded models (`cloud.py:143-152`); the six unused `prompts/*/user.md` files (decision pending).
5. **Decision record for the baseline dependency-risk policy (F-8).** It is implemented since 67d3e21 (2026-09-07) and tightened in d6b503c (2026-09-14). It appears only in status.md prose, and it contradicts ADR 0008 (D-17).

---

## 2. Staleness table

"Code commits since" = `git rev-list --count <last doc commit>..HEAD -- <described paths>`.

| Doc | Last doc commit | Described code (paths) | Last code change | Code commits since doc | Verdict |
|---|---|---|---|---|---|
| README.md | f09ffd4 2026-09-10 | cli, config, .env.example, graph, stacks, pyproject, tests, ADRs | 92742b7 2026-09-16 | 50 | **Stale** (D-1..D-7) |
| AGENTS.md | 4e4951f 2026-09-09 | top-level tree | 92742b7 2026-09-16 | 63 (tree-wide) | Mostly holds. One row incomplete (D-20). |
| docs/README.md | eaeee71 2026-09-13 | src, tests, benchmarks | 92742b7 2026-09-16 | 33 | Incomplete (D-19) |
| docs/architecture/overview.md | f09ffd4 2026-09-10 | cli, graph, llm, mcp, stacks, contracts, apply_run | 92742b7 2026-09-16 | 35 | **Stale** (D-8..D-12) |
| docs/operations.md | f09ffd4 2026-09-10 | cli, config, .env.example, llm, quality, frontend | 92742b7 2026-09-16 | 27 | **Stale** (D-13..D-15) |
| docs/testing.md | 4e4951f 2026-09-09 | tests, pyproject, frontend/package.json | 92742b7 2026-09-16 | 52 | Incomplete (D-16) |
| docs/status.md | 90ba069 2026-09-16 10:12 -0600 | src, tests, benchmarks | 92742b7 2026-09-16 18:21 | 30 (no doc touched) | **Stale** (§3, S-1..S-10) |
| docs/history.md | eaeee71 2026-09-13 | src, docs | 92742b7 2026-09-16 | 33 | Stale (H-1) |
| decisions/README.md | da2ba30 2026-09-11 | decisions/ | 044a8da 2026-09-11 | 2 | Current |
| ADR 0008 | 31eeb93 2026-09-03 | agents/security.py, agents/reviewer.py, stacks.py | 766e1e5 2026-09-16 | 12 | **Contradicted** (D-17) |
| ADR 0015 | f09ffd4 2026-09-10 | mcp/container.py, command.py, workspace_runner.py | da8558f 2026-09-16 | 3 | Incomplete (D-18) |
| ADR 0017 | da2ba30 2026-09-11 | workspace/, workspace_runner.py, repository.py | da8558f 2026-09-16 | 1 | Incomplete (D-18) |
| evaluation/README.md | 4e4951f 2026-09-09 | evaluation/, scripts/ | 90ba069 2026-09-16 | 17 | Incomplete (D-21) |
| evaluation/benchmarks/README.md | 4e4951f 2026-09-09 | evaluation/benchmarks | 90ba069 2026-09-16 | 14 | Incomplete (D-21) |
| evaluation/reports/README.md | 4e4951f 2026-09-09 | evaluation/reports | 689d5b0 2026-09-10 | 3 | Incomplete (D-22) |
| evaluation/evidence/README.md | 4e4951f 2026-09-09 | evaluation/evidence | 4e4951f | 0 | Current |
| CLAUDE.md, copilot-instructions | 2026-09-09 | pointers only | n/a | n/a | Current |

---

## 3. status.md: what happened after its last recorded evidence

### 3.1 Commits since 2026-09-13 (33)

`git log --since=2026-09-13 --format='%h %ad %s' --date=short`. One commit on 09-13, one on 09-14, 31 on 09-16. Only `90ba069` touched status.md.

| Commit | Area | Reflected in docs? |
|---|---|---|
| 92742b7 feat(developer): state the project's declared stack before planning and authoring (`project_facts.py`) | Developer context | No |
| 31defca revert(developer): stop rotating the model chain blindly on later remediations | LLM / retirement | No (delete-zone candidate) |
| 4ff4ae2 feat(llm): remember which models keep failing a role and try them last (`llm/model_health.py`, `MODEL_HEALTH_PATH`) | LLM | No |
| 2a11002 fix(developer): always read the edited component's conftest.py | Developer | No |
| 279e98d fix(developer): let a plan create a new source file beside existing sources | Developer | No |
| d8cd3f3 fix(developer): try the next model on later remediations and explain missing-symbol compile errors (rotation half reverted by 31defca) | Developer / LLM | No |
| ba8b375 fix(developer): accept a remediation plan that only writes a test | Developer | No |
| 766e1e5 fix(testing): count a test's display-name annotation as part of its evidence | Testing gate | No |
| 41463de, 78b487e fix(guardrails): redaction of HTML-decorated / documented shell credentials | Guardrails (ADR 13) | No |
| 1b054ef fix(reviewer): name the terms a business rule gap is looking for | Reviewer | No |
| 928503b fix(testing): count an attempt as security only when it is a failed or login attempt | Testing | No |
| 004b612, c2d29d2, cc19be6, f70c32a, 7af574e, 51aa5c1, 9d27bcd, 762ec08 feat/fix(llm): providers xKiro, Vyce, TokenForge, NVIDIA, Kilo, Cohere, Cloudflare Workers AI; chain membership; Cohere 8000-token cap; Developer timeouts | LLM | **No.** overview.md:32 still lists 4 providers. |
| 52c5560 fix(llm): accept one fenced JSON answer from gateways that ignore response_format | LLM | No |
| 0b58d07 fix(llm): wait for the earliest provider cooldown | LLM | No |
| eaa0aa3 fix(llm): classify provider errors relayed inside a success response | LLM | No |
| 10a94e5 fix(developer): let remediation edit the tests this run wrote | Developer | No |
| b99c939 fix(quality): pass the Maven advisory report directory by its real property | Quality | No |
| 356c19f, d6d9a9d fix(services): DB credentials for every stack; EF provider from .NET project files | Services (ADR 12) | No |
| da8558f fix(quality): run node toolchains on a native volume and keep .git read-only (`mcp/workspace_runner.py`) | Quality / boundary (ADR 15, 17) | No |
| d617652 fix(quality): run authored test projects and report undeclared unchanged suites (`mcp/test_scope.py`) | Quality / testing gate (ADR 11) | No |
| **37c7400 feat(developer): plan bounded write targets for requirements that name no files** (`contracts/developer_plan.py`) | Developer | **No, and status.md:73-77 still says it is missing** |
| 90ba069 fix(quality): preserve complete bounded scanner evidence | Quality | Yes (status.md:62-71) |
| d6b503c (09-14) fix(quality): preserve repository workspace and verify advisory provenance | Quality / F-8 | Yes (status.md:34-58) |
| 1b1177b (09-13) fix(llm): report missing response fields without exposing exception data | F-9 | Yes (status.md:22-24) |

### 3.2 Untracked result files not reflected in status.md

18 untracked scored files: `flaskapiproduct-dry-20260916{a..k}` (11), `spring-demo-dry-20260916{a..f}` (6), `propflow-fixes-dry-20260913` (1). Raw reports (`results/raw/<name>-run.json`) exist for 16 of the 17 dated 09-16 files. There is no raw report for `spring-demo-dry-20260916c` or `propflow-fixes-dry-20260913`.

| Scored stage (18 files) | Result |
|---|---|
| all_stages_passed | 0/18 |
| execute | FAIL 18/18 |
| spec | FAIL 18/18 |
| delivery | "PASS" 18/18. All are dry runs, so this means **skipped** (status.md:81-83 rule). |
| clone | FAIL 2/18. `spring-demo-dry-20260916c`: CLI rc=1 with `ValueError: sensitive content is not allowed in cloud context` during Architecture, so the scorer blames clone for a guardrail refusal. `propflow-fixes-dry-20260913`: `Could not resolve host: github.com`. |
| hygiene | FAIL 3/18 (flask a, flask k, propflow-fixes) |

From the 16 raw reports (conf 0.9):

- All 16 end `HUMAN_REVIEW_REQUIRED`.
- 15/16 have `action_mode=APPLIED` with 1–3 proposed/changed files in the temporary checkout. The exception is flask b: 0 files, route length 4.
- `iterations`: flask a=0, b=0, c/d/e/g/i=1, h=2, f=3, k=4, j=5; spring a=3, b=2, d/e/f=5. Four runs reached the default limit of 5.
- `run_security_scan` failed in 15/16. `run_tests` failed in 13/16.
- Run `flaskapiproduct-dry-20260916a` (10:52) started 5 minutes after 37c7400 (10:47 -0600) and already produced 2 files.

**Consequence:** status.md:73-77 ("Las tres propuestas quedaron en `PROPOSED`, sin `file_contents`. Falta habilitar la resolución de destinos …") is **superseded**. Target planning exists (37c7400 + 279e98d, ba8b375, 10a94e5, 2a11002) and runs now author files. None of those runs passed tests or review, and none opened a PR.

### 3.3 Structure vs role

- 736 lines. Lines 1–197 cover the current campaign (27%). Lines 199–710 are dated "Comprobaciones del …" logs and platform/trial narratives (70%). Lines 711–736 are SpecKit, preserved resources and the delete-zone.
- The dated logs are append-only records with in-place "Corrección fechada" patches (e.g. :277 corrected by :341, :314 corrected by :363, :599 corrected inline). That is the History role inside the Status doc.
- Misplaced blocks: :191-197 (the 2026-09-08 reorganization base `4294b9ef` on branch `grok-multistack-validation`) sit inside "Verificación del cierre" of the 2026-09-13 campaign. :199 "Comprobaciones de esta revisión" is undated and refers to the 2026-09-08 migration.
- Line-number citations rot: `agents/security.py:68` is now :59, `mcp/quality.py:1357` is now :1545, `config.py:47-59` is now `validate_run_daemon` at :46-61.
- The anchor `status.md#campaña-github-del-2026-09-13--aceptación-no-cumplida` is used by docs/README.md:17 and history.md:5. The doc tests do not verify anchors, so any retitle must update both.

---

## 4. Drift items

Severity: **must-fix** = wrong or misleading; **should-fix** = incomplete. Replacement text is Spanish in each doc's style, except ADRs, which are English.

### 4.1 README.md

| ID | Sev | Location | Current text (short) | Evidence of reality | Proposed replacement | Conf |
|---|---|---|---|---|---|---|
| D-1 | **must** | README.md:43-45 | "el tercer rechazo del Reviewer detiene la automatización en lugar de reintentar indefinidamente" | `config.py:35` `max_remediation_iterations: int = Field(default=5, ge=1)`; `apply_run.py:383` passes it; `graph/routers.py:51-52` stops when `iteration >= max_iterations`; `routers.py:62` stops at 3 identical trailing fingerprints; `routers.py:64-65` sends a 2nd repeated implementation failure to Architecture; `tests/integration/test_workflow.py:94-125`; raw runs j, spring d/e/f reached `iterations=5` | "Cualquier etapa puede terminar en `HUMAN_REVIEW_REQUIRED`. La remediación está acotada: el rechazo número `MAX_REMEDIATION_ITERATIONS` (5 por omisión), o el tercero consecutivo con la misma huella de fallo, detiene la automatización en lugar de reintentar indefinidamente." | 0.95 |
| D-2 | **must** | README.md:100-102 | "`.env.example` documenta el conjunto" | 10 Settings fields absent from `.env.example` (§0) | "Todo se configura por variables de entorno leídas en [`config.py`](src/engineering_team/config.py): cada campo de `Settings` en mayúsculas. `.env.example` recoge las de uso habitual; la lista completa está en `Settings`." (Alternative: add the 10 names to `.env.example` and keep the sentence.) | 0.95 |
| D-3 | **must** | README.md:104-107 | Column "Por omisión": `LOCAL_FIRST` `false`, `CLOUD_ENABLED` `true` | `Settings` defaults `local_first=True`, `cloud_enabled=False`; `.env.example:4,53` have `false`/`true`; operations.md:21 states the class defaults (DUP-1) | Rename the column to "En `.env.example`" and add under the table: "Sin `.env`, los valores de clase son `LOCAL_FIRST=true` y `CLOUD_ENABLED=false`; ver [operaciones](docs/operations.md)." Or delete the table and keep only the link (single owner). | 0.95 |
| D-4 | **must** | README.md:121 | "La suite tiene 72 archivos organizados por alcance" | 91 `test_*.py` files (`git ls-files tests`) | "La suite se organiza por alcance: `tests/unit/`, `tests/mcp/`, `tests/graph/`, `tests/integration/`, `tests/rag/` y `tests/e2e/`, más `tests/test_run_api.py`." (no count) | 1.0 |
| D-5 | **must** | README.md:144 | "Catorce decisiones aceptadas" | Index lists 18 records, 17 accepted, 1 superseded (`decisions/README.md:12-31`); docs/README.md:29 says eighteen | "Por qué el sistema es así: dieciocho registros, uno reemplazado" | 1.0 |
| D-6 | should | README.md:84-88 | CLI table has `run`, `run-project`, `reset-project` only | `cli.py:122` `docker-sweep`; `run-project --help` shows `--repo`, `--clone-depth`, `--report-path` | Replace the `run-project` row: "`run-project PATH --spec \"...\"` \| Ejecuta sobre un repositorio real; admite `--test-spec`, `--repo URL` (clon temporal que no sobrevive al run, excluyente con `PATH`), `--clone-depth` y `--report-path`". Add the row: "`docker-sweep` \| Retira los recursos Docker etiquetados por ASET que ningún run vivo posee; `--build-cache` poda además la caché del daemon". | 0.95 |
| D-7 | should | README.md:70-75 | Extras: `dev`, `rag` (chromadb, langchain-text-splitters, sentence-transformers), `observability`, `sample-app` | `pyproject.toml:21-42`: `rag` also has `langchain-core`; extra `quality-toolchain` exists (pinned pytest/ruff and deps, checked by `tests/mcp/test_quality.py:768`) | Add `langchain-core` to `rag`. Add the row "`quality-toolchain` \| pytest, ruff y dependencias fijadas \| Toolchain Python bloqueado de la compuerta de calidad". | 0.85 |

### 4.2 docs/architecture/overview.md

| ID | Sev | Location | Current text | Evidence | Proposed replacement | Conf |
|---|---|---|---|---|---|---|
| D-8 | **must** (confirmed by lead) | overview.md:141-143 (+ mermaid :127) | "La iteración sube exactamente una vez por rechazo aceptado, de modo que el tercer rechazo termina la automatización y no puede empezar un cuarto ciclo." / edge "tercer rechazo · ruta inválida" | `config.py:35` default 5; `stategraph.py:163,871,929-934`; `routers.py:51-52` (limit), `:62` (3 identical fingerprints), `:64-65` (second repeated implementation failure → Architecture). The "3" applies only to identical trailing fingerprints. | "El Reviewer recomienda; la validación determinista elige la arista. La iteración sube exactamente una vez por rechazo; al alcanzar `max_remediation_iterations` (`MAX_REMEDIATION_ITERATIONS`, 5 por omisión) el grafo sale a `HUMAN_REVIEW_REQUIRED` y no empieza otro ciclo. Además, cada rechazo deja una huella (`remediation_fingerprint`): el segundo rechazo consecutivo idéntico de implementación vuelve a Architecture en lugar de Developer, y el tercero sale a revisión humana antes del límite." In the mermaid, change the edge label to `"límite de iteraciones · huella repetida 3 veces · ruta inválida"` and add `R -->|"2ª huella repetida de implementación"| A`. | 0.95 |
| D-9 | **must** | overview.md:12 and :85-86 | Mermaid `run · run-project · reset-project`; "La CLI expone `run`, `run-project` y `reset-project`." | `cli.py:22,36,112,122`; `--help` output | Mermaid: `cli.py<br/>run · run-project · reset-project · docker-sweep`. Text: "La [CLI](../../src/engineering_team/cli.py) expone `run`, `run-project`, `reset-project` y `docker-sweep`. `run-project` trabaja sobre una ruta o, con `--repo`, sobre un clon temporal ([ephemeral_checkout.py](../../src/engineering_team/ephemeral_checkout.py)) que se elimina al terminar, y delega en …" | 0.95 |
| D-10 | **must** | overview.md:32 | `llm/cloud.py<br/>groq · mistral · openrouter · google` | `llm/cloud.py:31-47` (`_OPENAI_COMPATIBLE`: groq, mistral, openrouter, xkiro, vyce, tokenforge, nvidia, kilo, cohere, cloudflare), `:58-61` (google, google2), `:67-137` (per-role chains; tokenforge is in no chain), `:157-158` (Testing/Reviewer map) | Mermaid: `CL["llm/cloud.py<br/>cadenas por rol · OpenAI-compatible + Google"]`. See D-11 for the prose. | 1.0 |
| D-11 | should (high) | overview.md:148-156 ("Contexto y modelos") | Describes only prompting, repository_evidence and RAG | 37c7400 `contracts/developer_plan.py` (`validate_target_plan`:106+); 92742b7 `project_facts.py` wired at `stategraph.py:725-726`, `prompting.py:194`; 4ff4ae2 `llm/model_health.py` wired at `apply_run.py:345-347`, `cloud.py:416-440`; 762ec08 Developer timeouts `cloud.py:443,481`; `stategraph.py:600-603` Testing/Reviewer call no model | Add after :156: "Solo Product, Architecture, Developer y Security invocan modelos; Testing y Reviewer son compuertas deterministas sobre evidencia MCP ([stategraph.py](../../src/engineering_team/graph/stategraph.py)). [cloud.py](../../src/engineering_team/llm/cloud.py) define una cadena ordenada de proveedor y modelo por rol —proveedores compatibles con OpenAI (Groq, Mistral, OpenRouter, xKiro, Vyce, TokenForge, NVIDIA, Kilo, Cohere, Cloudflare Workers AI) y Google— sobreescribible con `CLOUD_CHAIN_<ROL>`. [model_health.py](../../src/engineering_team/llm/model_health.py) lleva un registro local (`MODEL_HEALTH_PATH`, ignorado por Git) de los resultados recientes de cada modelo por rol y relega al final de su cadena, sin retirarlo, al que acumula fallos. Cuando un requisito no nombra archivos, Developer pide primero un `DeveloperTargetPlan` que Python valida contra el inventario del repositorio antes de leer o escribir ([developer_plan.py](../../src/engineering_team/contracts/developer_plan.py)): no edita tests originales y los archivos nuevos quedan acotados a su componente. Planificador y autor reciben además los hechos declarados del proyecto —versiones de manifiestos e imports de los tests existentes— desde [project_facts.py](../../src/engineering_team/project_facts.py). Developer tiene plazos propios (`DEVELOPER_LLM_TIMEOUT_SECONDS`, `DEVELOPER_ROLE_TIMEOUT_SECONDS`)." | 0.9 |
| D-12 | should | overview.md:173-177 | "[container.py] es su única implementación: todo comando de calidad corre dentro de un contenedor Docker." | da8558f: `mcp/workspace_runner.py:254` `class NativeWorkspaceRunner(ContainerRunner)`; `mcp/quality.py:107` selects it for `quality_stack == "node"`; `container.py:292-300` mounts `.git` read-only | "…[container.py] es su única implementación: todo comando de calidad corre dentro de un contenedor Docker. Para componentes `node`, [workspace_runner.py](../../src/engineering_team/mcp/workspace_runner.py) especializa ese runner: el repositorio vive en un volumen nativo por runner y solo vuelven deltas comprobados, porque el bind mount de Docker Desktop falla con la extracción concurrente de npm. En ambos casos `.git` es de solo lectura dentro del contenedor." | 0.9 |

### 4.3 docs/operations.md

| ID | Sev | Location | Current text | Evidence | Proposed replacement | Conf |
|---|---|---|---|---|---|---|
| D-13 | should (high) | operations.md:21 | "Proveedores y cadenas se implementan en [llm] y deben revisarse antes de ejecutar con modelos." | Settings credential fields `groq_api_key, mistral_api_key, open_router_api_key, gemini_api_key, gemini_api_key_2, x_kiro_api_key, vyce_ai_api_key, token_forge_api_key, nvidia_api_key, kilo_api_key, cohere_api_key, cloudflare_worker_ai_api, cloudflare_account_id`; `cloud_chain_*` read at `cloud.py:282`; timeouts `llm_timeout_seconds, cloud_role_timeout_seconds, developer_llm_timeout_seconds, developer_role_timeout_seconds, ollama_timeout_seconds`; `model_health_path` | Replace with: "Las cadenas por rol están en [cloud.py](../src/engineering_team/llm/cloud.py); `CLOUD_CHAIN_PRODUCT`, `CLOUD_CHAIN_ARCHITECTURE`, `CLOUD_CHAIN_DEVELOPER` y `CLOUD_CHAIN_SECURITY` las sobreescriben con `proveedor:modelo` separados por comas. Cada proveedor se habilita con su credencial (`GROQ_API_KEY`, `MISTRAL_API_KEY`, `OPEN_ROUTER_API_KEY`, `GEMINI_API_KEY`, `GEMINI_API_KEY_2`, `X_KIRO_API_KEY`, `VYCE_AI_API_KEY`, `TOKEN_FORGE_API_KEY`, `NVIDIA_API_KEY`, `KILO_API_KEY`, `COHERE_API_KEY`, `CLOUDFLARE_WORKER_AI_API` con `CLOUDFLARE_ACCOUNT_ID`); sin credencial el proveedor se omite. Plazos: `LLM_TIMEOUT_SECONDS`, `CLOUD_ROLE_TIMEOUT_SECONDS`, `OLLAMA_TIMEOUT_SECONDS` y, solo para Developer, `DEVELOPER_LLM_TIMEOUT_SECONDS` y `DEVELOPER_ROLE_TIMEOUT_SECONDS`. `MODEL_HEALTH_PATH` (por omisión `workspace/model-health.json`) guarda el historial que reordena las cadenas; si no se puede leer o escribir, el run continúa. Que un proveedor esté en una cadena no demuestra que responda hoy; ver [estado](status.md)." | 0.9 |
| D-14 | should | operations.md:34 (+ new paragraph) | "`run-project` recibe una ruta y `--spec`; admite `--test-spec`. … La entrega requiere otra opción, `--confirm-delivery`, el backend `gh` …" | `run-project --help`; `cli.py:122-135`; `config.py` `delivery_backend='none'`, `max_remediation_iterations=5` | "`run-project` recibe una ruta, o `--repo URL` para clonar a un temporal que se elimina al terminar (`--clone-depth`, 1 por omisión; 0 clona la historia completa), y `--spec`; admite `--test-spec` y `--report-path`. … La entrega requiere `--confirm-delivery`, `DELIVERY_BACKEND=gh` y las condiciones de [apply_run.py]. `MAX_REMEDIATION_ITERATIONS` (5 por omisión) acota los ciclos de remediación." New paragraph: "`docker-sweep` retira los recursos Docker con `aset.owner=aset` que ningún run vivo posee ([decisión 16](architecture/decisions/0016-every-docker-resource-carries-its-run.md)); `--build-cache` poda la caché de build del daemon entero." | 0.95 |
| D-15 | should | operations.md:40 | "Los campos `quality_stack`, `quality_component_path`, `quality_test_filter` y `quality_timeout_seconds` están en Settings." | Settings also has `quality_container_image`, `quality_run_daemon_image`, `quality_run_daemon_images` (validated at `config.py:46-61`) | Append: "`quality_run_daemon_image` (fijada por digest) y `quality_run_daemon_images` activan el daemon Docker por run de la [decisión 14](architecture/decisions/0014-a-docker-api-that-is-not-the-hosts.md); `config.py` rechaza cualquier otra combinación." | 0.85 |

### 4.4 docs/testing.md, docs/README.md, AGENTS.md

| ID | Sev | Location | Current text | Evidence | Proposed replacement | Conf |
|---|---|---|---|---|---|---|
| D-16 | should (high) | testing.md:26 | "La suite completa se invoca con `python3 -m pytest`. Algunos grupos requieren …" | status.md:223 (the operator's `.env` overrides Settings defaults); status.md:168-170, 236, 245-246 (unset Settings env vars, `DELIVERY_BACKEND=none`); no conftest or script in the repo does this (`tests/conftest.py` absent) | Add: "Los tests de defaults leen el entorno: `Settings` carga variables con los nombres de sus campos en mayúsculas y un `.env` desde la raíz. Para medir el código y no el shell, ejecutar la suite en un proceso sin esas variables y con `DELIVERY_BACKEND=none`, sin modificar `.env`. En zsh, usar un script `bash`: zsh no separa palabras en `$VAR`." | 0.85 |
| D-19 | should | docs/README.md:9 (+ new rows) | "Ajustar modelos y contexto" links only `llm/`, `repository_evidence.py`; tests prompts/runtime/grounding | New modules and tests: `llm/model_health.py` + `tests/unit/test_model_health.py`; `contracts/developer_plan.py` + `tests/unit/test_developer_target_plan.py`; `project_facts.py` + `tests/unit/test_project_facts.py`; `tests/unit/test_cloud_runtime.py`, `tests/unit/test_cloud_fallback.py`; `mcp/workspace_runner.py` + `tests/mcp/test_workspace_runner.py`; `mcp/test_scope.py` + `tests/unit/test_test_applicability.py` | Row 9: add "[cadenas y proveedores](../src/engineering_team/llm/cloud.py), [salud de modelos](../src/engineering_team/llm/model_health.py)" and the tests "[cloud runtime](../tests/unit/test_cloud_runtime.py), [fallback](../tests/unit/test_cloud_fallback.py), [salud de modelos](../tests/unit/test_model_health.py)". New row: "Cambiar qué archivos puede tocar Developer o qué sabe del stack \| [Plan de destinos](../src/engineering_team/contracts/developer_plan.py), [hechos del proyecto](../src/engineering_team/project_facts.py) \| [Plan](../tests/unit/test_developer_target_plan.py), [hechos](../tests/unit/test_project_facts.py)". New row: "Cambiar la ejecución de toolchains node o el alcance de suites \| [Volumen nativo](../src/engineering_team/mcp/workspace_runner.py), [alcance de tests](../src/engineering_team/mcp/test_scope.py) \| [Runner](../tests/mcp/test_workspace_runner.py), [aplicabilidad](../tests/unit/test_test_applicability.py)". | 0.9 |
| D-20 | should (confirmed by lead) | AGENTS.md:27 | "`src/engineering_team/prompts/` \| Un `system.md` por rol, cargado en ejecución" | Six `prompts/*/user.md` exist (`ls prompts/*/user.md` → 6); `llm/prompting.py:63-64` reads only `system.md`; no Python reference to `user.md` in src/scripts/evaluation/demo-projects/tests; status.md:718 already notes no literal reference was found | "`src/engineering_team/prompts/` \| Un `system.md` por rol, cargado en ejecución por `llm/prompting.py`. Los seis `user.md` no se cargan: el mensaje de usuario se construye en código \| Recurso del programa, no documentación". Then decide: retire `user.md` (add to the delete-zone) or wire it in. | 0.9 |

### 4.5 ADRs

| ID | Sev | Location | Current text | Evidence | Proposed replacement | Conf |
|---|---|---|---|---|---|---|
| D-17 | **must** | ADR 0008:42-46 | "A missing command, unavailable advisory service, scanner error, or detected policy-level finding does not become success: the `ToolResult` fails or is unavailable and the deterministic Security/Reviewer gates block approval." | `agents/security.py:84-127, 184-192`: when every failed tool is a FAIL of a dependency scan with `confirmed_dependency_findings` and the change touches no dependency manifest, Security returns `PASS` with a HIGH "baseline dependencies" finding. `agents/reviewer.py:208-219, 409-415`: Reviewer can return `APPROVED` with those findings in `problems`. Tests: `tests/unit/test_security_dependency_scope.py:59,75,130,180`. Introduced 67d3e21 (2026-09-07), tightened d6b503c (2026-09-14). status.md:41-55 describes the policy; status.md:123 still says "decisión pendiente". | Append a dated correction after line 46 (English, ADR style): "**Correction, 2026-09-17:** the approval half of this paragraph no longer holds for one case. When every failing tool is a dependency scan whose advisories the producer confirmed, and the change modifies no dependency manifest, Security records the findings as residual baseline risk (`HIGH`, status `PASS`) and Reviewer may approve with them listed as problems (`agents/security.py`, `agents/reviewer.py`). The scanner `ToolResult` still fails and stays visible; a scanner error, missing command, unconfirmed or truncated report, or a touched manifest still blocks. This exception was introduced on 2026-09-07 and required confirmed advisories from 2026-09-14." Or record it as ADR 0019 and link it from 0008. | 0.9 |
| D-18 | should | ADR 0015 (Consequences) / ADR 0017 (implementation status) | ADR 15: container is the only runner, with no mention of a node variant. ADR 17: "partially implemented" as of 2026-09-11. | da8558f `mcp/workspace_runner.py` (`NativeWorkspaceRunner`, node only, per-runner volume, `.git` read-only); `VolumeWorkspace` is still unused by any run (grep shows no use outside `workspace/contract.py`) | ADR 17, dated note: "**Note, 2026-09-16:** for `node` components only, quality commands now run against a per-runner native volume holding the repository (`mcp/workspace_runner.py`), with sources pushed before each command and checked deltas returned. This is a command-execution measure against bind-mount failures, not `VolumeWorkspace`: the project still lives on the host and no run uses `VolumeWorkspace`." ADR 15: a one-line pointer to the same fact. | 0.85 |

### 4.6 evaluation READMEs

| ID | Sev | Location | Current text | Evidence | Proposed replacement | Conf |
|---|---|---|---|---|---|---|
| D-21 | should | evaluation/benchmarks/README.md:3; evaluation/README.md:5-14 | "The multistack runner supports the cases `ingresos`, `interview` and `northgate`." (no other runners) | Tracked runners: `ghcycle/run_cycle.py`, `ghcycle/probe_shallow_push.py`, `adr14/verify_run_daemon.py`, `adr16/verify_labels_and_sweep.py`, `adr17/measure_workspace.py`, `adr17/verify_workspace.py`, `adr18/verify_infrastructure_prerequisite.py`; `.gitignore:52` ignores `ghcycle/results/raw/` | benchmarks/README.md, add: "Other runners: `ghcycle/` measures the full GitHub cycle against real repositories (scored results in `results/`, raw reports in the git-ignored `results/raw/`); `adr14/`, `adr16/`, `adr17/` and `adr18/` verify those decisions against a real Docker daemon and write their evidence to `results/`." Add matching rows to evaluation/README.md. | 0.9 |
| D-22 | should | evaluation/reports/README.md:3-7 | Lifecycle is `curated/`, `runs/`, `generated/` only | Tracked top-level `apply-debugger-flask-writes*.json` (9 files) and `traces/*.json` (many), added 2026-09-09 | Add: "`traces/` and the top-level `apply-debugger-flask-writes*.json` predate this layout and are kept as run evidence; new reports go under `runs/`." | 0.8 |

### 4.7 docs/status.md

| ID | Sev | Location | Current text | Evidence | Proposed replacement | Conf |
|---|---|---|---|---|---|---|
| S-1 | **must** | status.md:73-77 | "…Developer solo activa la autoría si resuelve destinos explícitos. Las tres propuestas quedaron en `PROPOSED`, sin `file_contents`. Falta habilitar la resolución de destinos desde evidencia del repositorio para requisitos humanos, conservando los tests originales. Ningún PR nuevo quedó entregado." | 37c7400 `contracts/developer_plan.py:106+` (+279e98d, ba8b375, 10a94e5, 2a11002); 15/16 raw dry runs of 2026-09-16 have `action_mode=APPLIED` with 1–3 files; all ended `HUMAN_REVIEW_REQUIRED` | "La misma traza demostró otra causa: los requisitos de la campaña no nombran archivos y Developer solo activaba la autoría con destinos explícitos. **Corrección, 2026-09-16:** `37c7400` añade un plan de destinos (`DeveloperTargetPlan`) que Python valida contra el inventario del repositorio antes de leer o escribir, sin editar tests originales. En 15 de las 16 corridas en seco del 16 de septiembre con reporte crudo, Developer escribió entre uno y tres archivos en el checkout temporal; ninguna aprobó tests ni revisión y ningún PR quedó entregado." | 0.9 |
| S-2 | **must** | status.md:3-15 (section intro) | "La tabla conserva la medición de `eaeee71`; las correcciones posteriores no convierten esos resultados en aprobados." (no later measurement mentioned) | 18 untracked scored files (§3.2); 30 undocumented commits since 90ba069 | Add after :15 a subsection "### Corridas en seco del 2026-09-13 al 2026-09-16". Text: "Tras `90ba069` se repitieron corridas en seco sin entrega: once sobre FlaskApiProduct (`flaskapiproduct-dry-20260916a` a `k`), seis sobre spring-demo (`spring-demo-dry-20260916a` a `f`) y una sobre PropFlow (`propflow-fixes-dry-20260913`). **Los JSON no están versionados** y dos no tienen reporte crudo. Ninguna completa las seis etapas: execute y spec fallan en las dieciocho; delivery figura en verde solo por estar omitida. `clone` falla en dos, pero en `spring-demo-dry-20260916c` la causa real fue el rechazo del guardarraíl `sensitive content is not allowed in cloud context` durante Architecture, no el clon, y en `propflow-fixes-dry-20260913` la resolución DNS de github.com. Las dieciséis con reporte crudo terminan en `HUMAN_REVIEW_REQUIRED`; cuatro agotan las cinco iteraciones. `run_security_scan` falla en quince y `run_tests` en trece. Entre corridas cambiaron el código de proveedores, remediación y contexto de Developer (treinta commits); cada resultado vale solo para su commit." Recommend also versioning the 18 JSON or recording why they stay local. | 0.9 |
| S-3 | should | status.md:56-58 | "La suite integrada del 2026-09-14 terminó con 1038 pruebas aprobadas y 17 omitidas…" | Latest full-suite evidence predates 31 commits; 1033 test functions now | Add: "No hay ejecución de la suite completa registrada sobre `92742b7`; los treinta commits del 2026-09-16 solo tienen sus tests focales en los mensajes de commit." | 0.85 |
| S-4 | should | status.md:123 (F-8 row) | "decisión pendiente sobre baseline frente al cambio" | status.md:41-44 "Esa política ya existe"; code in D-17 | Append to the cell: "*Actualización: la política está implementada (`agents/security.py`) desde el 2026-09-07 y exige advisories confirmados desde el 2026-09-14; falta registrarla en la [decisión 8](architecture/decisions/0008-security-evidence-per-stack.md).*" | 0.85 |
| S-5 | **must** | status.md:191-197 | "Base inspeccionada: `4294b9ef…`, rama `grok-multistack-validation`. Reorganización aprobada el 2026-09-08…" plus evaluation-layout paragraphs, inside "Verificación del cierre" (2026-09-13) | These describe the 2026-09-08 documentation migration (history.md:242) | Move :191-197 under S-6's retitled section, which becomes "## Comprobaciones del 2026-09-08 (reorganización documental)". | 0.9 |
| S-6 | **must** | status.md:199 | "## Comprobaciones de esta revisión" | Undated; the rows refer to the 2026-09-08 migration (runner.py since deleted, per :209) | "## Comprobaciones del 2026-09-08 (reorganización documental)" | 0.9 |
| S-7 | should | status.md:277 | "…**ninguna de las cuales está implementada**." | ADR 16 implemented 2026-09-10 (status.md:341); ADRs 17 and 18 partially implemented 2026-09-11 (:385) | Append: "*(Corrección fechada: la 16 quedó implementada el mismo día y la 17 y la 18, parcialmente, el 2026-09-11; ver abajo.)*" | 0.9 |
| S-8 | should | status.md:180, :598 | `agents/security.py:68` SIM103, `mcp/quality.py:1357` PYI034; `config.py:47-59` | Ruff today: `security.py:59`, `quality.py:1545`; validator at `config.py:46-61` | Cite symbols instead: "`agents/security.py` (SIM103) y `CompositeQuality.__enter__` en `mcp/quality.py` (PYI034)"; "`Settings.validate_run_daemon` en `config.py`". | 0.95 |
| S-9 | should | status.md:421-427 | "Ningún run usa `VolumeWorkspace`…" | Still true; da8558f adds the node native volume (D-18) | Append: "*Nota del 2026-09-16: los componentes `node` ejecutan sus comandos sobre un volumen nativo por runner (`mcp/workspace_runner.py`); no es `VolumeWorkspace` y el proyecto sigue en el host.*" | 0.85 |
| S-10 | should (high) | status.md (new section) | No evidence entry for the providers added on 2026-09-16 | Probe evidence exists only in `llm/cloud.py:35-38, 63-79, 139-152` comments and commit bodies (762ec08, 52c5560, 004b612, c2d29d2, f70c32a) | New section "## Proveedores de modelos (2026-09-16)": "Se añadieron xKiro, Vyce, TokenForge, NVIDIA, Kilo, Cohere y Cloudflare Workers AI como proveedores compatibles con OpenAI. La inclusión en cadenas se basa en sondas del 2026-09-16 con las tareas de ASET (spec de Product, plan y autoría de Developer, revisión de Security) y en la corrida `apply-523385f8`; los resultados detallados están en los mensajes de `762ec08`, `52c5560` y `004b612`. TokenForge no figura en ninguna cadena. **No verificado:** disponibilidad sostenida, cuotas gratuitas (xKiro declara 500k tokens diarios por cuenta), latencia bajo carga. La traza de Langfuse del 16–17 de septiembre registra 429, 503, 413 y timeouts como fallos más frecuentes del fallback. Que un modelo esté en la cadena no demuestra que responda." | 0.85 |
| S-11 | should | status.md:725-734 (delete-zone) | No entries for LLM retirements | 31defca (revert of d8cd3f3 rotation); `cloud.py:139-141` (SambaNova); `cloud.py:143-152` (excluded models) | Add rows: "Rotar la cadena del Developer en remediaciones posteriores (`d8cd3f3`) \| Relegar por fallos registrados ([model_health.py](../src/engineering_team/llm/model_health.py)) \| Solo con medición que muestre mejora; en `apply-470d0440` y `apply-892eee7d` la rotación subió los fallos a diez"; "Proveedor SambaNova \| Ninguno \| Un nivel gratuito verificable (todo su catálogo respondió HTTP 402)"; "Modelos excluidos listados en `llm/cloud.py` \| Cadenas vigentes \| Nueva sonda con la forma real de la petición". | 0.85 |

### 4.8 docs/history.md

| ID | Sev | Location | Current text | Evidence | Proposed replacement | Conf |
|---|---|---|---|---|---|---|
| H-1 | should | history.md:2 (insert above the 2026-09-13 entry) | Last entry 2026-09-13 | §3.1 | "## 2026-09-16 — Developer escribe sin rutas nombradas y las cadenas de modelos crecen\n\nLos requisitos humanos no nombran archivos; Developer planifica ahora destinos acotados que Python valida (`37c7400`) y recibe los hechos declarados del stack (`92742b7`). Se añadieron siete proveedores compatibles con OpenAI y un historial local de salud por modelo que relega, sin retirar, a los que fallan (`4ff4ae2`). La rotación ciega de modelos en remediaciones (`d8cd3f3`) se revirtió (`31defca`) por empeorar resultados medidos. Las corridas en seco de ese día y sus límites están en [estado](status.md).\n\n## 2026-09-14 — Evidencia completa de escáneres y procedencia de advisories\n\nEl transporte retiene hasta 4 MiB por stream para escáneres estructurados y la excepción de dependencias previas exige advisories confirmados (`d6b503c`, `90ba069`). Detalle y verificación en [estado](status.md)." | 0.8 |

---

## 5. Governance findings (severity-ranked)

| # | Severity | Finding | Evidence | Recommendation | Conf |
|---|---|---|---|---|---|
| G-1 | **High** | **Documentation has not followed a 31-commit feature day.** 30 commits after the last status.md edit touched no `.md`. overview.md, operations.md and README.md have gone 27–50 commits without an update. Wrong claims include providers (4 listed, 12 actual), the iteration limit, the CLI surface, and "target resolution missing". | §2, §3.1 | Adopt a lightweight rule in AGENTS.md: a `feat:` commit or an evidence-changing `fix:` updates its owner doc, or the commit body states why not. Add an owner-doc check to the existing commit hook. | 0.9 |
| G-2 | **High** | **Evidence and retirements live in code comments and commit bodies instead of the Status/Delete-zone owner** (`llm/cloud.py:35-38, 63-79, 139-152`; the 762ec08/52c5560/31defca bodies). `.env.example` comments act as the provider-strategy doc. | §1.2 items 1 and 4 | Move the probe verdicts to status.md (S-10) and the retirements to the delete-zone (S-11). Code comments keep only the *why* for local code. | 0.85 |
| G-3 | **High** | **ADR 0008 is contradicted by implemented policy.** The baseline dependency-risk exception (Security PASS, Reviewer may approve) has had no decision record since 2026-09-07. status.md:123 still calls it pending while :41-44 says it exists. | D-17, S-4 | Dated correction in ADR 0008 or a new ADR 0019. This matches the "ADRs in git are the durable record" convention in `decisions/README.md:3-6`. | 0.9 |
| G-4 | **Medium** | **status.md mixes Status and History.** 736 lines, about 70% dated logs patched with "Corrección fechada", misplaced blocks (S-5, S-6), and no current-capability matrix. A reader cannot tell the current state without reading the whole ledger. | §3.3 | Put a table at the top: capability → last evidence (date, commit, command, result file) → verdict (verificado / no verificado / fallando) → pendiente. Move the dated "Comprobaciones del …" sections to history.md (or `evaluation/evidence/`) with a link. Keep the delete-zone in status. | 0.85 |
| G-5 | **Medium** | **Duplicated facts drift apart.** DUP-1 (config defaults contradict each other), DUP-4 (ADR count), DUP-5 (test count), DUP-2/3 (CLI, limits in three docs). README repeats owner facts with literal numbers. | §1.1 | README keeps only a pitch, requirements and links. Delete the numeric counts. Keep CLI/config tables in operations.md only, ideally generated from `--help` and `Settings.model_fields`. | 0.9 |
| G-6 | **Medium** | **The doc contract tests verify structure, not truth.** `test_documentation.py` passes (8/8) while D-1..D-5 and D-8..D-10 are wrong. | §0 | Add cheap contract tests: every `Settings` field is named in `.env.example` or operations.md; every Typer command is named in operations.md; every `_OPENAI_COMPATIBLE`/`_GOOGLE_CREDENTIALS` provider is named in overview.md; no literal count of ADRs or tests in README. This follows the brief's "move repeatedly important rules down the ladder to tests". | 0.8 |
| G-7 | **Medium** | **Unversioned evidence.** 18 scored ghcycle results (2026-09-13/16) are untracked, and two have no raw report. The latest campaign evidence cannot be reproduced from git, and status.md does not say they exist. | §3.2 | Version the scored JSON (raw stays ignored by policy) or record in status.md why they stay local. Also fix the ghcycle scorer: it attributes a guardrail refusal (spring-demo c) to `clone`. | 0.85 |
| G-8 | **Medium** | **Test-execution precondition missing from its owner.** The clean-env requirement appears four times in status.md, is absent from testing.md, and no conftest or script in the repo enforces it. | D-16, DUP-8 | Document it in testing.md. Better: add a `scripts/` runner or a `tests/conftest.py` fixture that isolates `Settings` from the shell and `.env`. | 0.8 |
| G-9 | **Low–Medium** | **PROJECT_STATE.md is git-ignored but carries shadow Constitution/Architecture/Decisions/Delete-zone sections** ("Arquitectura vigente", "Decisiones", "Cosas que NO hacer"), dated mostly 2026-09-01..06 and flagged stale by the session hook. The ADR index already ranks it below ADRs. | `git check-ignore -v` → `.gitignore:26`; headings at lines 11, 37, 97, 151 | Per the project's rule on what gets versioned (personal tooling is not versioned), keep it untracked. Trim it to handoff and protocol (§1, §6) and replace §2–§4 with links to AGENTS.md, overview.md, the ADRs and the status delete-zone, so agents stop loading stale architecture. | 0.75 |
| G-10 | **Low** | **Dead prompt resources.** Six `prompts/*/user.md` are never loaded (`prompting.py:63-64` reads only `system.md`). AGENTS.md:27 implies prompts equal `system.md`; status.md:718 only says no reference was found. | D-20 | Decide: delete them (and add them to the delete-zone) or wire them in. Until then, state in AGENTS.md that they are not loaded. | 0.85 |
| G-11 | **Low** | **Line-number citations rot** in status.md (S-8) and in the F-7 adjudication (`apply_run.py:226-233`, `mcp/container.py:258`, `llm/cloud.py:469`), pinned to base `8baf9af`. | Ruff output; S-8 | Prefer symbol names, or `path@commit:line`. | 0.9 |
| G-12 | **Low** | **Language mix.** Governance docs are in Spanish; the ADR index, the ADRs and the evaluation READMEs are in English. Not wrong, but the style guidance for replacements differs by directory. | n/a | State the convention in AGENTS.md ("ADRs y READMEs de `evaluation/` en inglés"). | 0.7 |

### Confirmations (no drift)

- `docs/deprecated/` is linked only as a non-authoritative archive (AGENTS.md:65, docs/README.md:35, decisions/README.md:117, history.md:246, status.md:736).
- Run API routes in `run_api.py:279-362` match overview.md:93-94. Vite proxy `/api` and `/ws` to :8000 matches operations.md:59. Frontend scripts `test`, `typecheck` and `build` exist.
- Five stack profiles match (`stacks.py:212-369`). Migration steps exist (`stacks.py:90-105`).
- ADR index statuses match each record's header.
- `QUALITY_RUNNER=container` is the only value (operations.md:40 is correct).
- CLAUDE.md and copilot-instructions are correct adapters.
