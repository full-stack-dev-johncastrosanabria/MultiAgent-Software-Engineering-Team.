# Roadmap

Where the product is going, and what each step is for. [overview.md](overview.md)
describes what exists today; this describes what does not yet.

## The destination

Point the system at a repository it has never seen, and have it clone the
project, stand up whatever that project needs in order to run, make the change
that was asked for, prove the change with tests it actually executed, and deliver
the result as a pull request a human can review.

Three things follow from that sentence, and they are what the capabilities below
are for. The project is *someone else's*, so nothing about its stack can be
assumed. It has to *run*, so its databases and brokers have to exist. And the
result is *delivered*, not applied, so the human stays the one who merges.

## Where it stands

Working: a single LangGraph orchestrator over six roles, deterministic routing,
evidence gates that reject work no test demonstrates, a container runner whose
boundary is verified against a real daemon, profiles for Python, JVM, .NET,
Node and Go, and services isolated per run. The runner can select the Python
version a project needs rather than reusing the operator's interpreter.

Still to prove as one product flow: a real code-change pull request after all
gates pass, the declared Compose path against Kafka, non-Python remediation in
a target repository, and the large multi-component case. The UI still accepts a
local path only; it does not yet let a user choose a GitHub repository or review
delivery evidence in one place.

## The evidence

Six real repositories, reviewed in full before writing this. They are the reason
the capabilities are shaped the way they are, and not a guess about what a
project might look like.

| Repository | Backend | Frontend | Services | Declares its own topology |
|---|---|---|---|---|
| PruebaNuevosIngresosBackend | Java 21, 2 Maven microservices | TypeScript | Postgres 17 + **Kafka** | yes — compose, with healthchecks and ordering |
| NorthgateTollPlaza | Java 21, 2 Maven services | Angular 21 | Postgres + MongoDB | no — `test.sh` expects `brew services start` |
| Banking | C# net10.0 | Angular 21 | Postgres via EF Core | no — `localhost:5432` |
| BusinessAI-Analytics | Java 17 across 7 services + FastAPI | React | MySQL | no |
| InterviewCleanApi | C# net10.0 | Vue + Angular + React | MySQL | no |
| FlaskApiProduct | Flask | TypeScript | SQLite | not applicable |

Four facts came out of that table, and each one killed an assumption:

**None of the six is a single stack.** Every one is a backend and a frontend in
one repository, and BusinessAI-Analytics is Java *and* Python. A profile per
repository does not exist as a concept.

**Five of six do not declare their topology.** They assume services already
running on a developer's machine, which is precisely what an autonomous agent
does not have.

**It is not databases, it is services.** The first repository ships Kafka. An
axis designed around databases would have to be reopened immediately.

**These repositories break limits the system has today.** BusinessAI-Analytics
has 388 files; Architecture reads four of them, which is one percent
([finding 8](findings/README.md)).

## Capabilities, in order

### 1. Runner selected by configuration
Choose process sandbox or container explicitly, and record which one ran in the
run's evidence. Auto-detection is rejected: a boundary that varies silently by
machine reproduces [finding 5](findings/README.md), where telemetry could not
distinguish a primary path from a fallback.

*Status: done. `quality_runner` and `quality_container_image`, honoured at
`build_quality_server`. There is no fallback: an unknown runner, or a container
without an image, raises. Constructing a QualityMCP without settings keeps the
process sandbox, so the suite does not start depending on each machine's `.env`.*

`QUALITY_TIMEOUT_SECONDS` is a separate, finite budget for one QualityMCP
operation. It defaults to 600 seconds because a cold container must first fetch
the project's dependencies; repository MCP and model timeouts remain shorter.
The next FlaskApiProduct proof uses that budget before treating an install delay
as a defect in the target project.

### 2. Profile per component
[ADR 4](decisions/0004-profile-per-component.md). A component is a directory with a build manifest — `pom.xml`, `package.json`,
`*.csproj`, `requirements.txt`. Detection is file existence, so it stays
deterministic and no routing decision comes from model text. Each component
carries its image and its install, lint, test and build commands.

*Status: done. Detection is file existence, verified against the real trees of
all six repositories: 3, 4, 6, 10, 8 and 2 components. Five profiles -- Python, JVM, .NET, Node and Go -- name a
digest-pinned image and their own commands, and QualityMCP routes through them.
The 443 tests that predate profiles still pass, which is the evidence that
routing Python through one did not change what Python does.*

**One difference worth stating rather than hiding.** Python installs from a
hashed lock and then tests offline. Maven, dotnet and npm resolve dependencies
while they build, so their test phase is granted network. This was measured:
`dependency:go-offline` completes and a following offline `mvn test` still fails,
so a restore phase cannot honestly promise an offline test phase for those
ecosystems. Their caches live on the shared volume, so the network is used on the
first run and largely idle afterwards. Closing the gap properly means vendoring
dependencies into the image or the workspace, which is its own piece of work.

### 3. Services per run
[ADR 5](decisions/0005-services-per-run.md). Services live for the run, not for a command, on an internal network where the
project reaches its own services and nothing else. Verified: on a `--internal`
network a container resolves its siblings by name and cannot reach the internet.
Readiness is a health check, never a sleep — Postgres starts in about a second,
SQL Server documents 2 GB of RAM and takes far longer.

A service that fails to start must be evidence in its own right. Otherwise the
tests fail, the gate reads "tests failed", and an infrastructure problem is
reported as a code problem — the misleading-headline failure of
[finding 7](findings/README.md).

*Status: done. Compose owns the lifecycle -- it already knows the images, the
healthchecks and the ordering, and `--wait` blocks until healthy rather than
sleeping for a guess. What ASET adds is an override that closes every declared
network and removes every published port, and the decision to start
infrastructure only. A service that never becomes ready raises with
INFRASTRUCTURE_ERROR, so it is never reported as a failing test.*

### 4. The project's own compose as the primary source
[ADR 5](decisions/0005-services-per-run.md). Where a repository ships a compose file, use it rather than inferring a topology.
It already carries healthchecks, startup order and images. Where it does not,
derive an overlay that lives on the ASET side, because requiring a file in every
target repository contradicts the premise of being pointed at projects that
already exist.

The missing topology is itself a deliverable: a derived compose that makes a
project run without `brew services` is a genuinely useful pull request, and it
does not change a line of the project's code.

*Status: done, both halves. Where a repository ships a compose file that file is
the topology: verified against PruebaNuevosIngresosBackend, whose Postgres, Kafka
and init container come up healthy in eight seconds on a run-scoped internal
network, reachable by the names it gave them, with no port on the host and no
route out.*

*Where none exists the topology is derived from the connection strings the
project already declares, and the project's own file always wins. All five
repositories without one were verified: Postgres for Banking, Postgres and
MongoDB for NorthgateTollPlaza, MySQL for InterviewCleanApi and
BusinessAI-Analytics, and correctly nothing at all for FlaskApiProduct, which is
on SQLite. Two artefacts come out — the run's, closed and with the project
redirected off `localhost` by the variables its framework documents, and the
developer's, with ports where their configuration already looks and credentials
parameterised so no plaintext secret is proposed into anyone's history. Opening
the pull request is covered by
[ADR 6](decisions/0006-github-origin-pull-request-delivery.md).*

### 5. GitHub as origin, pull request as delivery
[ADR 6](decisions/0006-github-origin-pull-request-delivery.md). Cloning is the run copy — `create_run_copy` already copies a directory into
`workspace/runs/<run_id>`, and a clone is the same thing with a different source.
Delivery inverts more cleanly than it looks: today Apply writes to the source
tree after human confirmation, with hashes and restore. A branch and a pull
request are reviewable by construction, and git provides what the hashes were for.

*Status: done for the infrastructure proposal. Cloning is the run copy, and work
leaves as a branch under `aset/` plus a pull request. Nothing is pushed without an
explicit confirmation, the default branch is never a target, and no force exists
anywhere in the path: a second delivery builds on the branch it made. Verified by
opening a real pull request on NorthgateTollPlaza, which had no compose file and
whose test.sh told the reader to install Postgres and MongoDB by hand.*

*Code-change pull requests are not enabled. Finding 7 is the reason: a rewrite
that empties files is contained today because nothing is applied, and that
containment is the thing a delivery path removes.*

### 6. Evidence per component
A run over BusinessAI-Analytics produces results for ten components. The gates
read the latest result of each, keyed by the evidence reference a QualityMCP
stamps when it is given a component name.

*Status: done. Both gates previously read `run_tests[-1]`, so a failing component
disappeared the moment a later one passed. Reading every result instead was wrong
in the other direction: `tool_results` accumulates across remediation cycles, and
a failure a later cycle had already fixed kept counting — five workflow tests
caught that. The verdict is now the latest result per component, which for a
single-component run is exactly the previous behaviour.*

### 7. Reading that widens, and knows when it did not
[Finding 8](findings/README.md) and [ADR 7](decisions/0007-declared-coverage-decides-remediation.md).

*Status: done. The fixed cap of four files became a byte budget over
twenty-four ranked candidates, split by size so a repository of small modules
arrives whole. Coverage is then measured by the graph and stamped onto the
proposal in three states, where silence is distinct from sufficiency. A test
failure over declared-thin evidence is routed back to Architecture rather than to
the Developer, and the Reviewer's feedback contributes terms to the next
selection so a second pass does not read the same files.*

*What remains is the budget itself. Twenty-four candidates against a 16 KB
payload is a deliberate compromise, not a limit of the design: raising it costs
context on every architecture call, and the honest way to move it is to measure
what coverage actually buys on a large repository rather than to guess upward.*

### 8. Frontend as a delivery control

The UI has to grow from a local-run launcher into a truthful delivery surface:
accept a GitHub repository URL, ask for the requested change, show the selected
runner, profiles and service topology, and present the resulting branch,
evidence and pull request. It must show uncertainty and infrastructure failures
as such; a button must never imply that code was pushed or a PR opened when the
backend only produced a proposal.

*Status: planned. This follows the real code-change PR proof, so the frontend
binds to stable backend evidence instead of creating a second workflow.*

## Proving sequence

Each repository is chosen for what it forces, and the order is chosen so that
nothing is built before something proves it is needed.

**1. FlaskApiProduct** — complete the first real code-change pull request. The
runner, dependencies and Python version now work. The Flask retry has proved
that Reviewer distinguishes regressions from new failures; its next gate is the
same request on a clean branch after Apply was taught to authorize the inspected
products route as well as its explicitly named test. The first repair exposed
an auxiliary `CHANGELOG.md` target that still suppressed the route, so the next
clean run verifies that documentation does not count as the implementation.
The orchestrator now selects and rereads that source before governing the
candidate; only a green run produces
the first code-change pull request.

**2. PruebaNuevosIngresosBackend** — validate declared Compose against the
actual Java services, Postgres and Kafka. This proves that the project-owned
topology, healthchecks and run-scoped cleanup work through the workflow rather
than only in a focused service test.

**3. Banking or NorthgateTollPlaza** — validate non-Python profiles and inferred
topology in a real target. Banking exercises .NET plus Postgres; Northgate adds
Java, MongoDB and a frontend. Both prove that the profile is a component property
rather than a repository assumption.

**4. BusinessAI-Analytics** — last. Seven services and 388 files make it the
real test of evidence per component and the Architecture reading budget. It runs
only after the first three steps produce useful, unambiguous evidence.

**5. Measure the Architecture budget** — use the large repositories to compare
coverage, withheld evidence and routing outcomes before increasing the 16 KB
budget. The target is a measured trade-off, not a larger arbitrary constant.

**6. Frontend delivery control** — after the backend flow is proven, accept a
GitHub URL and requested change in the UI, then expose the selected execution
plan, live evidence, branch and pull request without weakening confirmation.

## What one real run taught

Pointing the system at FlaskApiProduct — clone, requirement, tests, three
remediation cycles, 243 seconds — produced three findings the entire suite had
missed, all of the same shape: the system failed for a reason unrelated to the
work and reported it as though it were the work.

The cloud guardrail refused every project whose code reads an environment
variable, because `os.environ` contains the four characters `.env`. The
environment installed nothing for a project declaring dependencies in
requirements.txt, and the resulting ModuleNotFoundError was routed to the
Developer three times. Finally, the operator's Python 3.14 could not install a
dependency pinned for Python 3.12. All three are now fixed: the guardrail matches
the file name rather than an identifier, requirements.txt is installed, and the
container image is derived from supported wheel tags. The corrected run used
Python 3.12 and executed 62 FlaskApiProduct tests.

The first retry proved finding 13's repair: Reviewer reported
`test_get_products_empty` and `test_filter_products_by_price` as `REGRESSION`
before the new endpoint failures. It then exposed finding 14: Apply had allowed
only `tests/test_products.py`, because that was the only literal file path in
the request. Developer could create tests but could not change the inspected
products route. Apply now adds one relevant, successfully inspected source file
when no source target exists. The first repair treated auxiliary documentation
as a source target, so `CHANGELOG.md` still blocked the route. The next clean
run moved the selection and reread into the orchestrator before the candidate is
governed. The next clean run must prove that the endpoint and isolated fixtures
converge before any branch is pushed.

## What is deliberately not here

Windows support arrives through Docker Desktop and the container runner rather
than as its own process-sandbox effort. The process runner remains a local
compatibility option, not the cross-platform product boundary.

Performance is not a capability yet. Nothing here is fast, and making it fast
before it is correct would be optimizing a shape that is still moving.
