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
| 8 | high | Architecture designs from four files and cannot ask for a fifth | **fixed** — `2856069`; Flask v9 made the route, test and model visible, marked evidence sufficient and never returned to Architecture |
| 13 | high | Reviewer does not distinguish a regression from a new failing test | **fixed** — `a82ec93`, `9ad580e`; the Flask retry labelled the two formerly passing tests as `REGRESSION` before the new endpoint failures |
| 14 | high | Apply authorizes only file paths named literally in the requirement | **fixed** — the fourth Flask run wrote the inspected `app/routes/products.py` together with `tests/test_products.py`, without expanding the scope to the auxiliary `CHANGELOG.md` |
| 15 | high | Cold Quality provisioning expires before a real project reaches tests | **fixed** — with the separate bounded 600-second Quality budget, the fourth Flask run reached Security, Testing and Reviewer; its later failure was functional, not an install timeout |
| 16 | high | A transient model outage ends a run before its deterministic gates | **fixed** — `1fcaf0d`; Flask v9 recovered from real provider failures and reached Testing and Reviewer three times |
| 17 | high | Developer receives failing test names but not the failing assertions | **fixed** — Reviewer now attaches bounded, redacted pytest diagnostics while ContextEnvelope preserves role isolation and a 6 KiB total budget |
| 18 | high | Developer repeats an identical defect across all three remediation cycles even with the failed assertion in hand | **open** — a clean FlaskApiProduct clone with finding 17 in place still stopped at `HUMAN_REVIEW_REQUIRED`; see the narrative below |
| 19 | high | Profile per component ([ADR 4](../decisions/0004-profile-per-component.md)) is unit-tested but never reached by a real run | **fixed** — `quality_stack`/`quality_component_path` now travel from `Settings` through `MCPQualityClient`'s subprocess arguments to `QualityMCP`, exactly as `quality_runner`/`quality_container_image` already did; a non-Python external repository with no root manifest, given an explicit stack and component subdirectory, now reaches Security instead of failing before any agent runs |
| 20 | high | Security's dependency and vulnerability scans are hardcoded to `pip`/`ruff` regardless of the component's profile | **open** — with finding 19 fixed, a JVM component reaches Security and fails there: `scan_dependencies` and `run_security_scan` assume a Python interpreter exists inside the component's own container image; see the narrative below |

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

**Finding 16 came from the sixth Flask run.** Product and Architecture completed,
but Developer saw a connection failure and then a cloud read timeout. The graph
immediately stopped at `HUMAN_REVIEW_REQUIRED`, so no test or reviewer result
existed and a pull request would have been dishonest. A stage now retries once
only for connection and timeout errors, before any write. It does not create a
new remediation cycle or loosen delivery: a second failure remains a human-review
stop. The focused tests cover both a primary-only failure and a primary-plus-cloud
failure. Flask v9 supplied the external proof: after real provider failures the
workflow recovered, reached Testing and Reviewer three times and stopped for
functional failures rather than provider availability.

**Finding 8 needed a third external validation.** Flask v8 made seven of 27
ranked paths visible under the 16 KiB budget and item overhead. Generic `stock`
hits placed `app/routes/products.py` behind analytics and AI helpers, so Developer
changed `init_db.py` and tests while the requested endpoint remained absent and
returned 404. The correction does not raise the global prompt budget: an explicit
HTTP task reserves its named test plus conventional route/controller and
model/domain boundaries. When Reviewer returns to Architecture, those boundaries
remain and every remaining slot rotates to previously unseen evidence. The
50-percent candidate threshold remains only for work with no deterministic task
boundaries. Unit regressions cover both the first selection and the remediation
rotation. Flask v9 then made `app/routes/products.py`, `tests/test_products.py`
and `app/models/product.py` visible, declared the evidence sufficient and kept
all three Reviewer returns on Developer. The endpoint's remaining test failures
are a separate implementation defect, not an Architecture loop.

**Finding 17 is the information lost after finding 13's classification.**
Testing keeps the complete pytest output, including assertion values. Reviewer
extracts the failed identifiers so it can label regressions and new failures,
then uses only those labels as `problems`. Developer does not receive
`test_results` or Testing tools, so its remediation context contains names but
not the bounded `expected/actual` diagnostic. In Flask v9 one generated test
asked for threshold 7 while expecting stock 8 to be excluded; another hid the
typed-default behaviour of Werkzeug. Three remediations could not see either
contradiction. The repair must preserve deterministic Reviewer and role
isolation while attaching a bounded, secret-redacted assertion excerpt to each
failed identifier. It now does: regressions consume diagnostic budget before new
failures, parametrized IDs and repeated test names remain associated with their
own blocks, captured output is excluded, and Developer receives neither Testing
tools nor complete `TestResult`/`ToolResult` payloads. Redaction happens before
every truncation and preserves valid quoted JSON. The remaining evidence is an
external Flask rerun that converges without operator repair.

**Finding 18 is that rerun, and it did not converge.** A fresh clone of
FlaskApiProduct (`main` @ `4cc7fc2`, PR #1 still open and unmerged) ran the same
low-stock specification end to end in the container runner
(`apply-1a667318-c715-4581-8f25-dd7bd8090e2c`, Python 3.12.14, 295 seconds).
It reached Testing and Reviewer three times and stopped at
`HUMAN_REVIEW_REQUIRED` with an identical `REJECTED` verdict on every cycle
(`remediation_category: TESTING`, never `APPROVED`) — finding 17's bounded
assertions were present in every remediation, and Developer still reproduced
the same two defects at cycle three that were visible at cycle one. First, it
edited the shared `autouse` `setup` fixture in `tests/test_products.py` to
insert three baseline products so the new low-stock test would have data,
which broke three previously passing tests that asserted an empty or specific
count (`test_get_products_empty`, `test_filter_products_by_price`,
`test_filter_products_by_category`) — Reviewer correctly labelled these
`REGRESSION`, proving finding 13's fix works, but Developer never moved the
new fixtures into the new test methods instead of the shared one. Second, its
own generated assertion compared `restock_value` to a float
(`500.00 * (10 - 5)`) while the route computed it from `product.cost`, a
SQLAlchemy `Numeric` column that loads as `Decimal`; Flask's default JSON
provider serializes an unconverted `Decimal` as a string, so the response held
`"2500.00"` against an expected `2500.0`. The same file's own `to_dict()`
already casts `float(self.cost)` for exactly this reason, one function away
from where Developer wrote the route. Both defects, and the failed-assertion
text describing them, were shown to Developer at every one of the three
cycles without correction. This is now the open question finding 17 could not
answer: bounded, correct diagnostic context does not by itself guarantee
convergence within `MAX_ITERATIONS=3`, at least for this Developer model
chain. The evidence is
[`evaluation/reports/flask-retry-clean.json`](../../../evaluation/reports/flask-retry-clean.json)
and its matching trace; no code in this repository was changed to produce it,
and no fix is proposed here — the next step is to decide whether the answer is
a narrower Developer prompt, a fixture-isolation rule, a serialization
convention surfaced as evidence, or a documented limit on what three
model-driven cycles can be expected to repair unattended.

**Finding 19 is [ADR 4](../decisions/0004-profile-per-component.md) validated
only where a test could construct it.** `QualityMCP.__init__` accepted an
explicit `profile` argument and `build_runner()` could derive a pinned image
from a stack, but only `tests/mcp/test_runner_selection.py` ever supplied that
argument directly. `build_quality_server()`, the MCP server subprocess
(`mcp/server.py`), and `MCPQualityClient` (`mcp/client.py`) had no way to carry
a stack or a component subdirectory across the stdio boundary, so every real
`run-project` invocation constructed `QualityMCP` with its unconditional
`PROFILES["python"]` default. `detect_components()` (`components.py`) — fully
deterministic, ADR-4-compliant, unit-tested — had zero callers outside its own
module. This surfaced concretely against a real external repository: a fresh
clone of PruebaNuevosIngresosBackend (Java/Maven, no root `pom.xml`, two
independent modules `order-ms`/`payment-ms`) failed immediately with
`ValueError: no container image is configured and none could be derived from
this project`, before Product or any agent ran — `select_interpreter()` is
Python-only and there was no other path to an image. The fix follows the
project's stated convention rather than adding one: `quality_stack` and
`quality_component_path`, two new explicit `Settings` fields, travel exactly
the way `quality_runner`/`quality_container_image` already do — as CLI
arguments to the MCP server subprocess (`--stack`, `--component-root`), not as
anything auto-detected from repository contents. `build_runner()` now derives
a non-Python image from `profile_for(settings.quality_stack).image` when none
is given explicitly, and `main()` resolves the quality server's working root
to `--root`/`--component-root` while leaving the Repository server (Developer
read/write) rooted at the whole repository. With this in place, the same
PruebaNuevosIngresosBackend clone, given `QUALITY_STACK=jvm
QUALITY_COMPONENT_PATH=order-ms`, proceeded through Product, Architecture and
Developer and reached Security (`apply-1b94a85d-cc5b-4118-a879-0632eb9c6d5f`) —
see finding 20 for where it stopped next. `detect_components()` remains
unwired; explicit configuration was chosen over auto-detection to stay
consistent with the project's stated position that no routing decision comes
from inferred repository shape, matching `quality_runner`'s own precedent.

**Finding 20 is what finding 19's fix uncovered one stage later.** Once a JVM
component could reach Security, both `scan_dependencies` and
`run_security_scan` (`mcp/quality.py`) failed with `isolated environment
unavailable: RuntimeError: venv creation failed in container: mkdir: cannot
create directory '/root': Permission denied` and `exec: python: not found`.
Unlike `run_tests()` and `run_linter()`, which branch on `self.profile.name`
and dispatch to the profile's own command template, `scan_dependencies` and
`run_security_scan` have no such branch: they unconditionally derive a Python
interpreter (`self._interpreter(...)`) and invoke `pip check` and `ruff check`
respectively, regardless of the component's actual stack. `StackProfile`
(`stacks.py`) has `test_template`, `lint_template`, `build_template` and
`install_template`, but no equivalent for a dependency or vulnerability scan —
"profile per component" was completed for the test/lint path but never
extended to Security's tools. The `maven:3.9-eclipse-temurin-21` image the JVM
profile pins carries no `python` binary and runs as a non-root user, so both
tool calls fail before Security can produce a verdict, and the run stops at
`HUMAN_REVIEW_REQUIRED` after only `Product → Architecture → Developer →
Security`, without ever reaching Testing or Reviewer. The evidence is
[`evaluation/reports/kafka-retry.json`](../../../evaluation/reports/kafka-retry.json).
No fix is proposed here: choosing what "scan dependencies" and "run a security
scan" mean for Maven, npm, dotnet and Go (`mvn dependency-check`, `npm audit`,
`dotnet list package --vulnerable`, `govulncheck`, or an explicit no-op with a
documented reason) is an architecture decision for those stacks, not a
mechanical extension of the wiring finding 19 already fixed, and belongs in an
ADR before code changes it.
