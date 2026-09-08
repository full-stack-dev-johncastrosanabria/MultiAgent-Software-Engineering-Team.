# Ingresos multistack series: twelve trials to a delivered change

This evidence is sanitized: identifiers, SHAs and reproducible commands, no
credentials, prompts or model responses. It records what ADR 9 asked for —
establish infrastructure readiness before reading an agent result as an agent
result — and what running that against a real repository actually cost.

Target: `PruebaNuevosIngresosBackend` at `d536f9d`, a Spring Boot 4.1.1
prerequisite commit. Change under test: reject nonpositive quantity and
null/zero/negative unit price in `Order.nuevo`, preserving HALF_UP rounding to
two decimals. Write allowlist: `Order.java` and `OrderTest.java` only.

## Outcome

Trial 10 (`apply-2c3c8e9b`, `b7180fe`) approved first: score 100, every subscore
100, zero remediation cycles, 382 seconds, both writes inside the allowlist,
`pom.xml` untouched, and its route reached `FinalReport` without a single return
to the Developer.

Trial 12 (`apply-bd79ab5a`, `990b894`) took that configuration and armed
delivery. It approved at 100 across every subscore after one remediation cycle,
in 456 seconds, and opened the pull request -- the first time work left this
system the way ADR 6 describes.

Trials 5 through 9 measured no agent behaviour at all. Each ended on a defect in
this harness, and each defect was closed before the next trial could reach
further than the last. The agents were never the bottleneck; the machinery
around them was.

## What each trial actually established

| Trial | Reached | Closed by |
|---|---|---|
| 5 | Reviewer gate | — (baseline security misrouting) |
| 6 | never started | evidence capture defect, cause unrecoverable |
| 6b | — | Testcontainers without a Docker API |
| 7 | Security, 53 s | `fp-quality-env-nonpython` |
| 8 | Testing, 753 s | `fp-sandbox-signal-jvm-attach`, `fp-agent-first-pass-gap` |
| 8b | Security, 58 s | `fp-mcp-isolated-loads-main` |
| 8b v9 | Reviewer ×3 | `fp-t8b-v9-owasp-order-ms` |
| 9 | Reviewer ×3 | trial 6 closed NOT_REPRODUCIBLE |
| 10 | **APPROVED** | — |
| 11 | Reviewer, 640 s | executed the payment-ms regression trial 10 had not |
| 12 | **APPROVED + delivered** | — |

## Defects this series closed

**The scratch directory only existed as a side effect of building a virtual
environment.** A jvm or node component reached the sandbox with no environment
and failed before running anything. Separated in `81b36e7`: every profile gets
the directory, only Python gets the interpreter inside it.

**Mockito could not attach to its own JVM under the sandbox.** Its inline mock
maker — the default since Mockito 5 — signals the target process and reaches it
over a Unix socket, and the sandbox grants neither. `order-ms` reported 24 errors
where the host reported one. Loading the same jar with `-javaagent` is the path
Mockito's own warning names; `25238a3`.

**Forking was only ever granted alongside network access.** `mvn` is a shell
script, so an offline Maven phase died on `fork: Operation not permitted` before
a single test ran. The two permissions are unrelated and each toolchain now
declares whether its launcher forks; `25238a3`.

**The MCP children resolved their own `engineering_team`.** Spawned with `-I`,
which ignores `PYTHONPATH`, they loaded the installed checkout — twenty commits
behind the branch under test — while the parent ran the worktree. Both the
Quality and the Repository client were affected, in every trial of the series.
Pinned in `a310464`, asserted in `7906680`.

**Baseline CVEs were classified by tool name.** `run_security_scan` is ruff on
Python but OWASP dependency-check on the JVM, npm audit on Node, govulncheck on
Go. A list written from the Python case rejected `order-ms` over CVEs published
before the change, in a pom it never opened. The profile now declares which of
its phases read third-party code and the result carries the answer; `b7180fe`.

**The JVM scanner aborted over a .NET analyzer.** dependency-check tried to run
its AssemblyAnalyzer, found no dotnet runtime, and with `failOnError` turned its
own absence into a failed scan — masking the CVEs it had just found; `b65af76`.

One hypothesis was refuted rather than confirmed: `kafka-init` in the `--wait`
set was a plausible reading of `classify_services`, and Compose 5.5.1 reports a
completed one-shot as healthy. Trial 9 later found `ServiceStack` starting
cleanly, which closes trial 6 as NOT_REPRODUCIBLE. Its launcher environment was
never recorded and is not reconstructed here.

## Baseline

`d536f9d` on the host, JDK 21.0.10, no ASET: 66 tests, 0 failures, 1 error, and
that error is Testcontainers finding no Docker daemon at that moment. The
component's suite was never broken; every extra failure inside the pipeline came
from the pipeline.

## The nine oracles

The pipeline does not read `acceptance_cases`. Nothing in `src/` refers to them,
so the Reviewer scores what it measured, not what the manifest specified. This
table was assembled from surefire output, not produced by the system.

| # | Oracle | Evidence | Trial |
|---|---|---|---|
| 1 | `quantity=0` throws | `quantity0Throws…` | 10 |
| 2 | `quantity=-1` throws | `quantityNegativeThrows…` | 10 |
| 3 | `unitPrice=null` throws | `unitPriceNullThrows…` | 10 |
| 4 | `unitPrice=0` throws | `unitPriceZeroThrows…` | 10 |
| 5 | `unitPrice=-0.01` throws | `unitPriceNegativeThrows…` | 10 |
| 6 | 3 × 10.333 → 31.00, price kept | `quantity3AndUnitPrice10_333…` | 10 |
| 7 | 1 × 0.005 → 0.01 | `quantity1AndUnitPrice0_005…` | 10 |
| 8 | existing creation and transition tests still pass | `OrderTest` 12/0 in a suite of 78/0 | 10 |
| 9 | full order-ms suite + payment-ms regression, real PG/Kafka | order-ms 78/0 incl. `OrderFlowIntegrationTest` 6/0; **payment-ms 8/0** | 10, 11 |

Trial 10 left the ninth without evidence: it ran single-target, so `payment-ms`
produced no surefire output at all. Trial 11 ran the same change with the
fan-out and executed it — 8 tests, no failures, no errors, the first time
`payment-ms` ran in the series. `real PG/Kafka` is satisfied under the process
runner through Testcontainers, not through `ServiceStack` (ADR 10).

Trial 11 did not approve, and what stopped it was outside the experiment: the
fan-out includes `frontend`, and `testing` scored zero over a component the
manifest never claimed. `component` is `order-ms` and the allowlist names two
files in it. Both JVM components were green in the same run.

The first reading of that failure was that `ng test` wanted a browser the
sandbox has no way to provide. That was wrong, and measuring it is what showed
so: Angular 21's builder already runs vitest against jsdom. The suite failed to
compile -- `codePointAt` returns `number | undefined` where `Uint8Array.from`
requires `number` -- so TS2769 stopped the bundle and no spec ran at all. Fixed
upstream; nine tests now pass headless in under a second.

Its remediation cycle then hit `HTTPStatusError` from the model provider and the
Developer returned its previous answer unchanged, which is how the run ended in
human review rather than a third cycle.

So the oracles hold on evidence, across two runs of the same change, and the
approval in trial 10 is a separate fact: the change the agents wrote passes the
tests the agents wrote, under a real Maven, with the allowlist respected. Both
statements are true and neither implies the other, because nothing in the system
connects the manifest's oracles to the gate.

## Delivery, end to end

ADR 6 makes a pull request the way work leaves the system, and all four of its
conditions have to hold together: `authorize_writes`, `confirm_delivery`, an
approved review, and a configured backend. Trial 11 armed them for the first
time and did not deliver, because the review was not approved — the gate behaving
as written, with `delivery_error` absent because the block never ran.

Trial 12 took trial 10's configuration, single-target `jvm`/`order-ms` under the
process sandbox, and armed the same delivery. It approved with every subscore at
100 after one remediation cycle, and pushed:

```
delivery_branch: aset/apply-bd79ab5a-110e-48c0-8a43-0b494df5038e
delivery_pr_url: .../PruebaNuevosIngresosBackend/pull/2
delivery_error: None
```

The agents wrote two files, both inside the allowlist, and `order-ms` finished at
78 tests with no failures and no errors, `OrderTest` among them at 12. The run
had a real failure on its first pass — `run_tests: FAIL` is in the errors — and
the second cycle cleared it, which is the remediation loop doing its job rather
than a clean run flattering the system.

One property of that pull request is worth stating so nobody misreads it. Its
diff shows twenty files, because the delivery branch descends from `d536f9d`,
which is not on `main`: the diff carries the Spring Boot 4 prerequisite along
with the change. `files_written` is the honest count, and it is two.

## The CVEs have no upgrade to take

`run_security_scan` fails on `order-ms` over CVE-2026-41115 in kafka-clients
4.2.1 and CVE-2026-75838 in the DOMPurify 3.4.12 that Swagger UI bundles. Both
are real. Neither has a published fix, and this was measured rather than
assumed:

- kafka-clients 4.3.0 is the newest release on Maven Central, and
  dependency-check flags it for the same CVE.
- Swagger UI is already newest. springdoc 3.1.0 resolves `org.webjars:swagger-ui`
  5.32.11 on its own. Forcing the version Maven Central's search API reports as
  latest — 5.25.3 — is a *downgrade* whose bundle carries DOMPurify 3.2.4 and
  six additional CVEs.

So the finding stands and the remedy does not exist yet. That is the case the
baseline classification was built for: the risk stays visible in the Reviewer's
problems, and the gate does not send a Developer to patch a version nobody has
published. Scanning the whole component turns up twenty distinct CVEs at CVSS 7
or above; the two named here are simply the ones the trials reported.

## Open, with no owner

- A fan-out run gates on components the manifest does not claim. Trial 11 scored
  `testing` zero over `frontend` while both components the experiment named were
  green. Either the gate should weigh the component under test, or a manifest
  naming one component should select it — the second is what trial 10 did, and
  it is why trial 10 approved.

Three items that were open here are now closed, and the record of how is worth
keeping because two of them were closed by finding the diagnosis wrong.

`JAVA_HOME` now reaches the command. It is passed through when the sandbox can
read it and dropped when it cannot, so a JDK under HOME still does not get named
and then refused. Verified inside the boundary: `java -version` reports 21.0.10,
the version the launcher selects, where it used to report 25.

The container runner refuses a Testcontainers suite before the work rather than
during it. The component's own manifest declares the dependency, so the refusal
arrives in zero milliseconds naming both the cause and ADR 10, instead of a
`ContainerFetchException` after minutes — which is how the same boundary got
read as a flake three times.

`ng test` was never blocked on a browser. Angular 21's unit-test builder already
runs vitest against jsdom, both already in `devDependencies`. The suite failed to
*compile*: `codePointAt` returns `number | undefined` where `Uint8Array.from`
requires `number`, so TS2769 stopped the bundle and no spec ran at all. With
`charCodeAt` the three files and nine tests pass in under a second, headless.
Fixed upstream in `PruebaNuevosIngresosBackend`.

## A note on method

Two commits in this series landed on a red suite because only focal tests were
run, and both times the full run caught it afterwards. A bare `pytest` inside a
worktree resolves `engineering_team` to the main checkout, so it reports on code
the commit does not contain. Every verification here used:

```bash
PYTHONPATH=src ../../.venv/bin/python -m pytest tests/unit tests/mcp
```

## Reproduce

```bash
PYTHONPATH=src ../../.venv/bin/python -m pytest tests/unit tests/mcp
PYTHONPATH=src ../../.venv/bin/python -m pytest tests/mcp/test_jvm_sandbox_toolchain.py
PYTHONPATH=src ../../.venv/bin/python -m pytest tests/mcp/test_quality_scratch_environment.py
PYTHONPATH=src ../../.venv/bin/python -m pytest tests/mcp/test_mcp_client_source_pin.py
PYTHONPATH=src ../../.venv/bin/python -m pytest tests/unit/test_security_dependency_scope.py
```

Trial reports live under `workspace/evaluation/grok-trial-*/evidence/`, outside
this repository.
