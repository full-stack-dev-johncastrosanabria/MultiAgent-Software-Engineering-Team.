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
evidence gates that reject work no test demonstrates, an ephemeral environment
per project, and a container runner whose boundary is verified against a real
daemon. Every command a target project runs is isolated.

Not working: everything about being pointed at a project that is not Python and
does not already run on this laptop.

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

### 2. Profile per component
[ADR 4](decisions/0004-profile-per-component.md). A component is a directory with a build manifest — `pom.xml`, `package.json`,
`*.csproj`, `requirements.txt`. Detection is file existence, so it stays
deterministic and no routing decision comes from model text. Each component
carries its image and its install, lint, test and build commands.

*Status: done. Detection is file existence, verified against the real trees of
all six repositories: 3, 4, 6, 10, 8 and 2 components. Four profiles name a
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
the pull request is
[ADR 6](decisions/0006-github-origin-pull-request-delivery.md) and is not
implemented.*

### 5. GitHub as origin, pull request as delivery
[ADR 6](decisions/0006-github-origin-pull-request-delivery.md). Cloning is the run copy — `create_run_copy` already copies a directory into
`workspace/runs/<run_id>`, and a clone is the same thing with a different source.
Delivery inverts more cleanly than it looks: today Apply writes to the source
tree after human confirmation, with hashes and restore. A branch and a pull
request are reviewable by construction, and git provides what the hashes were for.

*Status: not started.*

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

### 7. Read limits that can be widened
[Finding 8](findings/README.md). Not a runner concern, but it blocks the largest
repositories, so it has to land before the last step of the proving sequence.

*Status: done. A byte budget replaced the file count: twenty small modules now
all arrive where four did before, large files are admitted while a useful slice
remains, and the prompt states how much evidence was withheld so a partial design
can be declared partial.*

## Proving sequence

Each repository is chosen for what it forces, and the order is chosen so that
nothing is built before something proves it is needed.

**1. FlaskApiProduct** — Python and SQLite, no services at all. The shortest path
to a real pull request end to end: clone, dependencies, change, tests, PR. It
exercises capabilities 1 and 5 without needing the service layer to exist.

**2. PruebaNuevosIngresosBackend** — ships compose. The service layer arrives by
reading the project's own declaration rather than inferring one, and it brings
Kafka, so the axis is born as services rather than as databases. Exercises 3 and 4.

**3. Banking or NorthgateTollPlaza** — the topology has to be inferred. The hard
case, attempted only once the easy one works. Both add a non-Python backend, so
capability 2 gets its second and third profile here.

**4. BusinessAI-Analytics** — last. Seven services and 388 files; it requires
capability 7 first, and it is the real test of capability 6.

## What is deliberately not here

Windows support arrives with the container runner rather than as its own effort;
the process sandbox's fail-closed refusal is a temporary stance, not a policy.

Performance is not a capability yet. Nothing here is fast, and making it fast
before it is correct would be optimizing a shape that is still moving.
