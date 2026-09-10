# 17. The project lives in the run, not on the operator's disk

Date: 2026-09-10. Status: accepted, not implemented.
Depends on: [ADR 3](0003-split-quality-mcp.md) for the shape of the split,
[ADR 15](0015-container-only.md) for where commands already run,
[ADR 16](0016-every-docker-resource-carries-its-run.md) for how what it creates is reaped.

**Nothing in this record is implemented yet.** It states a direction and the
work it requires. Today the project is copied onto the host, and
[status](../../status.md) is the account of that.

## Context

ASET works on a copy, never on the original. `create_run_copy` walks the source
directory with `shutil.copytree`, skipping `.venv`, `.git` and `__pycache__`,
and writes the result under `workspace/runs/<run_id>`. `clone_repository` is the
same arrangement with a URL as the source. Both land on the operator's
filesystem, and `RepositoryMCP` — the tool all six agents read and write
through — is plain Python IO against that host path.

Nothing collects those directories. On 2026-09-10 the host held 923 MB across
96 run directories, none of which had been removed. The largest was 356 MB.

The composition matters more than the total. In one `order-ms` trial the run
workspace was 80 MB, of which `target/` was 79 MB. **Ninety-nine per cent of
what accumulates is build output, not source.** The copy is small; what the run
produces inside it is not, and that output is worthless the moment the run ends.

The operator's objection is that a machine used for work should not silently
fill with copies of projects it is not editing. A run is meant to be
disposable: it succeeds and becomes a pull request, or it fails and is
discarded. Neither outcome needs a directory left on disk.

## Decision

The project lives in a run-scoped named volume, not on the host.

The run creates a volume, clones or copies the project into it, mounts it at
`/aset/project-root` — the path [ADR 15](0015-container-only.md) already
established — and removes it at the end. Build output is created inside the
volume and dies with it. Nothing about the target project touches the operator's
disk.

This cannot be done by changing a path, and that is the substance of the record.
`RepositoryMCP` is bound to the host filesystem by construction: `self.root =
Path(root).resolve()`, then `open`, `write_text`, `iterdir`. A project inside a
volume is not reachable that way. What the change requires is a `Workspace`
contract — read a file, write a file, list, diff — with the host directory as
one implementation and the volume as the other. That is the twin of what
[ADR 3](0003-split-quality-mcp.md) did for `CommandRunner`, and it is the reason
that split is worth citing: it is the precedent showing the extraction is
mechanical once the contract is named.

**The clone credential is an exception, and is stated as one.** ASET's standing
rule is that a container reaches nothing: [ADR 14](0014-a-docker-api-that-is-not-the-hosts.md)
gives the run a daemon with no route out, and services run on an `--internal`
network. A clone needs the network and a GitHub token. That token goes to the
clone container and to no other. It is not written into the volume, not present
in any quality container's environment, and not readable from the mounted
project. The clone container exists for the length of the clone and is removed.
Every other container in the run keeps the egress it has today, which is none.

The clone is `--depth 1`. Bandwidth and time are the reason; the cost is that
`git log` and `git blame` see nothing, so no agent may reason from history. What
delivery needs is a branch and a diff ([ADR 6](0006-github-origin-pull-request-delivery.md)),
and a shallow clone provides both. If an agent is ever given a task that
genuinely requires history, this is the line to revisit, and it should be
revisited by name rather than by quietly deepening the clone.

## What this does not claim

**No measurement supports this yet.** The 923 MB is evidence of the problem, not
of the fix. Whether a volume-backed workspace is faster, slower or the same on
macOS with Docker Desktop — where bind mounts are famously not free, and named
volumes are usually better, but neither has been timed here — is unknown, and
the first implementation must measure it before this record can be called
validated.

**The host copy is not deleted by this record.** `create_run_copy` remains the
implementation used until the contract exists and the volume path is proven. A
direction is not a migration.

## Consequences

The developer's disk stops growing with each run, which is the point.

Diffing gets harder before it gets easier. Delivery computes a diff against the
project as it stood; with the project inside a volume, that comparison happens
in a container, and the diff has to come back out. This is the part most likely
to be underestimated.

Debugging a failed run loses something real. Today an operator can open
`workspace/runs/<run_id>` and read what the agents wrote. When the volume is
removed at the end of the run, that is gone. Whatever is worth keeping from a
failed run — the diff, the logs, the evidence — has to be extracted
deliberately, before teardown, rather than found afterwards by luck. An
implementation that removes the volume without providing that extraction is
worse than what exists today.
