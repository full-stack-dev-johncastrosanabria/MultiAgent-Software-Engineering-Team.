# 15. The process sandbox is retired: the container is the only boundary

Date: 2026-09-10. Status: accepted.
Closes the follow-up left open by: [ADR 14](0014-a-docker-api-that-is-not-the-hosts.md)
Supersedes the decision in: [ADR 10](0010-integration-tests-need-the-host-docker-api.md),
whose refusal to mount the host socket is unchanged and still in force.

## Context

ADR 2 chose the container and expected the process sandbox to stay as a
fallback. ADR 10 found a class of component the container could not host —
suites that drive containers themselves — and made the process sandbox the
supported path for it. ADR 14 removed that reason by giving the run its own
Docker daemon, and said so in its own consequences: *"once a container backend
serves the Testcontainers class, the argument that kept the process sandbox
alive is gone, and retiring it becomes a deliberate follow-up rather than a
loss."* This is that follow-up.

What was left was two implementations of one contract, only one of which every
run used. `ProcessRunner` was about 1,100 lines carrying `sandbox-exec` on
macOS, Bubblewrap on Linux, and an explicit refusal on Windows; the container
backend is about 450 and behaves the same on all three. Keeping both meant every
change to the gate had to be argued twice, and every test had to say which
boundary it meant — which, as it turned out, most of them did not say at all.

## Decision

Delete the process backend. `CommandRunner` has one implementation,
`ContainerRunner`, and every command a target project runs — install, lint,
build, test, dependency check, security scan, schema migration — executes inside
a Docker container.

`mcp/runner.py` is gone. The contract stays where ADR 3's split put it,
in `mcp/command.py`, which is what made this deletion a removal rather than a
rewrite: nothing outside the deleted module had to learn a new interface.

Docker is now a hard dependency of running the gate at all. That is the trade
this record accepts: one boundary that behaves identically everywhere, in
exchange for a system that cannot run a quality gate on a host without Docker.

## What this does not claim

**No platform coverage is widened by this record.** ADR 14 argued that a
run-scoped daemon makes `container` sufficient on macOS, Linux and Windows, and
deleting the alternative does not execute that argument anywhere. What has been
run is still macOS arm64 with Docker Desktop, exactly as
[status](../../status.md) states. Linux and Windows remain untested, and the
difference is that a failure there is now a failure of the only path rather than
of the preferred one.

**Nothing here was validated on Windows.** The process backend refused Windows
outright, so removing it cannot make Windows worse; it also does not make it
work. The claim "Docker is what is multiplatform" is why this direction was
chosen, not something this record measured.

## Consequences

Retiring the fallback made the container path the one every test exercises, and
four defects that had been invisible behind the process sandbox surfaced at
once. Each is fixed in the same change, and each had a test that either did not
exist or passed vacuously.

**ruff was handed a host path.** `_ruff_configuration` passed the absolute host
location of `pyproject.toml` to `--config`. That path does not exist inside the
container, so ruff refused with `invalid value for --config` and every Python
component came back FAIL for a reason naming neither the project nor the
boundary. The name now travels relative to the working directory, which is the
component root either way. The pre-existing test passed vacuously: it asserted
only that the output lacked one specific string and that the status was not
UNAVAILABLE, and a FAIL satisfies both.

**The mount point made the project a package.** Mounted at `/aset/workspace`, a
project whose root carries an `__init__.py` was read by pytest as a package;
collection walked up to `/aset` and the project's own modules stopped resolving.
The sample application's suite failed on `from app.service import ...`, and the
evaluation scenarios ran their repair loop over a project that was green. On the
host the same tree collected only because a run directory is named after a run
id and never spells a package name. The mount is now `/aset/project-root`, which
cannot be one.

**A project that constrains nothing had no interpreter.** ADR 2 refused to
choose an image when neither a declaration nor the pins decided one. That
refusal cost nothing while the process sandbox could run such a project on the
operator's interpreter; with the container as the only boundary it means no gate
at all. Such a project now gets the newest interpreter this repository ships an
image for. Finding 11 is untouched: a project whose pins do constrain the choice
is still decided by them.

**An open-ended floor was read as a claim.** `requires-python = ">=3.10"` — what
this repository itself declares — selected 3.15, which no image carries, so the
run refused before it started. A floor is not a statement that the newest
interpreter in existence was tested. The range stays authoritative, and within
it the choice is the newest version a container can actually carry. A
declaration that admits nothing offered is still refused, by name.

The suite got slower and more honest. Tests that used to patch a process now
start real containers; wall time for `tests/unit` and `tests/mcp` rose from
about 197 s to about 227 s. That is the cost of testing the boundary that ships.

A deprecated Apple interface leaves the critical path. `sandbox-exec` is
documented by Apple as deprecated, and ADR 14 counted that as one of two reasons
the process backend was not a stable floor.

The way back is git. This is a deletion of working, reviewed code, and the
argument for it rests on ADR 14's mechanism holding up on hosts nobody has run
it on yet. If it does not, the backend is recoverable from history — but it
would come back as a decision, with the platform evidence that is missing today,
not as a silent fallback.
