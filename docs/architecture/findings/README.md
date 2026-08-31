# Findings

Defects in how the agents behave, as opposed to defects in a line of code. The
record is [agent-architecture-audit.json](agent-architecture-audit.json); this
index says where each one stands.

| # | Severity | Finding | Status |
|---|---|---|---|
| 1 | critical | Reviewer approves without the coverage evidence it requires | **fixed** — `e6f9319` |
| 2 | critical | Architecture is not grounded in the repository it inspected | **fixed** — `dd36bf1`, `f14e7b6`, `95cc463` |
| 3 | high | Project dependencies install into the shared interpreter | **fixed** — nothing runs the operator's interpreter any more; each QualityMCP provisions its own environment from `sys._base_executable`, and a test asserts no command reaches `sys.executable`. The two races that review found against the *sandbox* are a different question, and they dissolve under [ADR 2](../decisions/0002-container-runner.md), whose container runner is now implemented and verified |
| 4 | high | Repository MCP indexes ignored artefacts without limit | **fixed** — `6fe08e4` |
| 5 | medium | Telemetry confuses primary execution with fallback | **fixed** — the cloud runtime reports a fallback only when it is one, and the local runtime records the reason it is given instead of accepting and dropping it |
| 6 | medium | Visible history reconstructs past decisions from the latest revision | **fixed** — the state records every reviewer decision, and the report shows each cycle its own; where no history exists it says nothing rather than borrowing |
| 7 | critical | The Developer can empty files and cannot see what it wrote | **fixed** — the projection carries `implementation`, and the prompt retains the previously authored code in both proposal and Apply modes; a projected value alone is otherwise only "present" |
| 12 | high | Configuration never reaches the MCP server that acts on it | **fixed** — the runner and image travel as explicit arguments; the SDK forwards only five environment variables and a test now says so |
| 11 | high | The ephemeral environment imposes the operator's Python on the project | **fixed** — the container image follows the interpreter derived from the project's pins, verified against FlaskApiProduct: 32 seconds, Python 3.12, every dependency from a wheel, 62 tests passing. Previously **partly fixed** — the failure now says so: an install that fell back to a source build is reported as INFRASTRUCTURE_ERROR naming the interpreter, instead of a wall of ninja output read as a code defect. Declared requirements are read where a project states one. Actually *providing* a different interpreter still needs a version-matched container image |
| 10 | critical | The ephemeral environment installs only projects that ship a pyproject.toml | **fixed** — a project that declares its dependencies in requirements.txt gets them, and the installable manifests are tied to the ones detection recognises |
| 9 | critical | The cloud-context guardrail blocks any project that reads environment variables | **fixed** — `.env` is matched as a file reference and not as a substring of `os.environ` |
| 8 | high | Architecture designs from four files and cannot ask for a fifth | **fixed** — a byte budget replaced the file count, and the prompt now states how much evidence was withheld |
| 13 | high | Reviewer does not distinguish a regression from a new failing test | **fixed** — `a82ec93`, `9ad580e`; the Flask retry labelled the two formerly passing tests as `REGRESSION` before the new endpoint failures |
| 14 | high | Apply authorizes only file paths named literally in the requirement | **in progress** — the second repair makes the orchestrator select and reread the relevant source even with an auxiliary `CHANGELOG.md`; it awaits the third clean Flask run |
| 15 | high | Cold Quality provisioning expires before a real project reaches tests | **in progress** — Quality used the same 120-second budget as ordinary MCP calls, leaving roughly 115 seconds for the first dependency install. `QUALITY_TIMEOUT_SECONDS` now supplies a separate bounded 600-second budget; it awaits the next clean Flask external run |

## Two things worth remembering

**Findings 9 and 10 were both invisible to the whole test suite, and both were
found in the same run.** They share a shape: the system refused or failed for a
reason that had nothing to do with the work, and reported it as though it did.
Nine blocked the Developer with a message about secrets over a comment; ten let
the tests run without the project's dependencies and called the resulting
ModuleNotFoundError a code defect, looping the Developer three times over it.

**Finding 9 was invisible to the whole test suite.** Every fixture in this
project is written by this project, and none of them reads configuration from the
environment in the text that travels to a provider. It took pointing the system at
somebody else's repository, for real, to find that the Developer stage could not
run at all against most Python projects.

**Finding 5 was found because the record contradicted itself.** The trace beside
each cloud attempt already said "primary" or "fallback" correctly; only the
`ModelExecutionInfo` was wrong. A single source would have hidden it.

**Finding 6 could not be fixed by reading harder.** The state kept only the
latest reviewer decision, so the data to show what an earlier cycle decided did
not exist. The fix had to record it. Where an older run has no history, the
report now shows nothing for that cycle instead of the terminal decision — saying
nothing beats saying something untrue.

**Finding 3 is the reason ADR 2 exists.** Four rounds of review against the
process sandbox each closed a gap and revealed another. The decision to move to a
container was not a preference; it came from the shape of what kept being wrong.

**Finding 7 was not where the audit said it was.** The audit blamed the missing
`implementation` in the Developer's projection. That is real, but fixing it alone
changes nothing: `build_role_prompts` collapses every projected value except
`run_id` and `requirement` to "present"/"absent". The mechanism is that the graph
writes to the workspace only for `ActionMode.APPLIED`, so after a `PROPOSED` pass
the Developer re-reads the original files and sees no trace of its own work.

**Finding 7 is why counts are not evidence.** The rewrite it describes deleted
four tests and added five, so the total rose from 18 to 19. Anything checking
test counts would have reported an improvement. Only comparing symbols showed the
fifteen that vanished.

**Finding 13 was found by the same real Flask run, but is not the same defect as
finding 7.** The Developer preserved the implementation this time. Its new tests
instead leaked products into the shared fixture and broke
`test_get_products_empty` and `test_filter_products_by_price`, which had passed
before the change. Reviewer reported one undifferentiated list of failures, so
the Developer had no signal that it had broken existing behaviour. The remedy is
to record passing test identifiers before the first write and label failures as
`REGRESSION` or `NEW FAILURE`; without a baseline it must claim neither.

**Finding 14 was exposed by the corrected Flask retry.** Once Reviewer labelled
the broken old tests correctly, Developer still changed only
`tests/test_products.py`: Apply had treated the test path written in the request
as the complete write allowlist, even though Repository MCP had read the products
route. That makes a feature impossible whenever its requirement names its test
but not its implementation. The repair is deliberately narrow: only a test-only
allowlist may gain one source file, and that file must have been successfully
read and score positively against the specification and Architecture proposal.
Its first repair exposed one more boundary: `CHANGELOG.md` appeared beside the
test in the deterministic candidate, which made the allowlist no longer
literally test-only and again suppressed the products route. Auxiliary
documentation must not count as an implementation target when deciding whether
a source file is still missing. The selection and Developer-role reread now run
in the orchestrator before it governs the candidate, so model context ordering
cannot replace that writable scope. The integration test reproduces the exact
three paths; the next Flask run remains the external proof.

**Finding 15 was exposed by that same third Flask run.** The orchestrator chose
and reread `app/routes/products.py`, then Developer produced both the endpoint
and its test. Before Testing could decide anything, the first
`pip install -r requirements.txt` exhausted the 120-second MCP deadline. That
is an infrastructure budget exhausted during cold provisioning, not evidence
that Flask code is wrong. Quality now has its own configurable, finite
`QUALITY_TIMEOUT_SECONDS` budget (600 seconds by default); repository MCP and
model calls retain their existing shorter budgets. A fourth clean external run
must reach Testing and Reviewer before findings 14 and 15 can close.
