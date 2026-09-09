# Real multistack validation

User request: one successful ASET run per destination repository, with reproducible
Docker infrastructure, a functional specification, meaningful tests, and a reviewable
pull request. Northgate's existing `aset/compose-mongo-postgres` branch is an explicit
input. Model experiments must be separated by at least 180 seconds after completion.

## Success contract

- ASET's `clone_repository` obtains a fresh remote checkout; record URL, base ref/SHA.
- Record infrastructure configuration, readiness, test commands, exits and test counts.
- A real configured cloud model supplies the changed source through ASET's StateGraph.
- Testing and Reviewer remain deterministic. Never weaken tests to get approval.
- A local `APPROVED` is insufficient: inspect the diff and independently verify the
  changed behavior and relevant existing tests, then publish the authorized PR.
- Report backend, frontend, app smoke and remote checks separately, including omissions.
- No merge is authorized. Preserve pre-existing local checkouts and unrelated reports.
- Never emit API keys or real credentials. A model catalogue entry is not proof of
  usable quota or valid structured generation.

## Initial architecture position

Establish infrastructure readiness before a narrow backend behavior change in each
repository. This makes failures attributable, limits simultaneous model obligations,
and produces a reproducible prerequisite for subsequent frontend work. The main risk
is under-delivering application containerization; full Northgate startup and explicit
coverage of each repository's infrastructure remain acceptance work.

## Global Constraints

- LangGraph (`graph/stategraph.py`) is the only orchestrator.
- Testing and Reviewer are deterministic gates and must not call a model.
- Wait at least 180 seconds between live experiments; serialize all credential probes
  and ASET runs under the root agent's coordination.
- Dependencies belong only in `pyproject.toml`; Python targets 3.10 and Ruff line 100.
- All target changes happen in fresh clones; all ASET fixes in this isolated worktree.
- Preserve test rigor and record the exact source SHA with every test result.

## Task 1: Credential fallback and reproducible experiments

Probe `GEMINI_API_KEY_2` with bounded structured generation requests. Implement a
credential fallback only with meaningful tests covering transient/auth errors, separate
credential cooldowns, deadlines, and secret redaction. Build a persistent experiment
record and an enforceable 180-second interval for repo runs and probes. The primary key
must continue to work; secondary-key use must be observable by alias, never value.

## Task 2: Infrastructure and specs

Use fresh clones of InterviewCleanApi/main, NorthgateTollPlaza (inspect both main and
aset/compose-mongo-postgres), and PruebaNuevosIngresosBackend/main. Commit concise specs
with meaningful acceptance cases. Exercise ASET's infrastructure against the real repos
and fix reproducible problems with focused regression tests. Verify Northgate databases
and applications can start together. Record any prerequisite target changes separately
from model-authored changes.

## Task 3: Three real runs

Execute the specs sequentially with a minimum 180-second gap after each experiment.
Capture sanitized model evidence, independent test logs/counts, diffs, and runtime smoke
results. Review every result; fix underlying failures before another attempt. Keep
attempts bounded and never relabel a failed/manual run as autonomous success.

## Task 4: Review and delivery

Review the complete ASET diff and each target diff independently. Publish authorized
target PRs, record URLs and exact check states, and persist evidence and architectural
decisions in their canonical versioned locations. Keep the goal active until all three
success contracts are met or a real external blocker satisfies the goal stop rules.
