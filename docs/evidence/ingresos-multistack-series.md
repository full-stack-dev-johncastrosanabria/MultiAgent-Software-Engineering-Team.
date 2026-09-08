# Ingresos multistack series: eleven trials to one approval

This evidence is sanitized: identifiers, SHAs and reproducible commands, no
credentials, prompts or model responses. It records what ADR 9 asked for —
establish infrastructure readiness before reading an agent result as an agent
result — and what running that against a real repository actually cost.

Target: `PruebaNuevosIngresosBackend` at `d536f9d`, a Spring Boot 4.1.1
prerequisite commit. Change under test: reject nonpositive quantity and
null/zero/negative unit price in `Order.nuevo`, preserving HALF_UP rounding to
two decimals. Write allowlist: `Order.java` and `OrderTest.java` only.

## Outcome

Trial 10 (`apply-2c3c8e9b`, `b7180fe`) approved: score 100, every subscore 100,
zero remediation cycles, 382 seconds, both writes inside the allowlist, `pom.xml`
untouched. Its route reached `FinalReport` without a single return to the
Developer.

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

## The approval attests to less than the manifest asks

The pipeline does not read `acceptance_cases`. Nothing in `src/` refers to them,
so the Reviewer scored what it measured, not what the manifest specified. Of the
nine declared oracles, eight have execution evidence in trial 10's surefire
output; `suite_regression` asks for `payment-ms` regression, and trial 10 ran
single-target — `payment-ms` has no surefire output in that workspace at all.

Read the approval as: the change the agents wrote passes the tests the agents
wrote, under a real Maven, with the declared allowlist respected. That is a real
result. It is not the same claim as "the nine oracles hold", and the difference
is worth keeping visible.

## Open, with no owner

- `fp-t9-testcontainers-no-docker-api`: integration tests inside the quality
  container cannot reach the Docker API. Three appearances (6b, 9). Mounting the
  host socket was considered and refused.
- `JAVA_HOME` is not in the runner's passthrough environment, so Maven resolves
  whatever JDK the rebuilt `PATH` offers — Java 25 in these runs, not the 21 the
  launcher selected. Not a cause of any defect above; an integrity gap in what
  the evidence can claim about the toolchain that ran.
- `run_security_scan` still fails on `order-ms`, now for the reason it should:
  CVE-2026-41115 in kafka-clients and CVE-2026-75838 in swagger-ui are real and
  unpatched at `d536f9d`.

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
