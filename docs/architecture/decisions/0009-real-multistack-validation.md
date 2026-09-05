# 9. Validate infrastructure before expanding model tasks

Date: 2026-09-05. Status: accepted for the multistack benchmark.

## Context

The real apply path does not instantiate the existing ServiceStack. Northgate's
compose branch supplies only PostgreSQL and MongoDB; Interview has no Compose;
Ingresos already declares its services. A nominal agent approval cannot establish
infrastructure readiness, passing tests, or remote merge readiness.

## Council positions

- Architect: establish infrastructure readiness, then a narrow business change per
  repository. Separate environmental defects from model errors.
- Skeptic: use the minimum reproducible environment; otherwise infrastructure work
  can replace the actual ASET experiment. Native toolchains can be legitimate evidence.
- Pragmatist: narrow changes make scarce, spaced API attempts diagnosable. Complete
  application containerization need not precede every first backend experiment.
- Critic: do not treat a backend success as evidence for frontend, migrations, Kafka,
  or full Compose startup; each needs its own observable check.

## Decision

Fix the production infrastructure connection and prepare bounded backend specs first.
Run real models only after prerequisites can execute. Record backend tests, frontend
checks, infrastructure readiness, app smoke and remote PR state independently. Preserve
the user's full Northgate startup requirement as work still to complete.

All live experiments, including credential generation probes, are serialized with at
least 180 seconds after the preceding experiment finishes. Local deterministic tests
and read-only repository inspections may proceed during the interval.

The strongest dissent is against letting infrastructure repair expand without a stop.
The response is a concrete gate: the selected behavior's tests must run reproducibly,
then proceed to the ASET experiment. No existing tests may be disabled to meet it.

## Consequences

Narrow backend success is useful evidence but does not justify a claim of full-stack
readiness. Any manual prerequisite change is identified separately from ASET-authored
output. Fresh clones protect unrelated local work and pin the source of each result.
