# 17. The project lives in the run, not on the operator's disk

Date: 2026-09-10. Status: accepted, partially implemented.
Depends on: [ADR 3](0003-split-quality-mcp.md) for the shape of the split,
[ADR 15](0015-container-only.md) for where commands already run,
[ADR 16](0016-every-docker-resource-carries-its-run.md) for how what it creates is reaped.

**Correction, 2026-09-11:** this record was accepted as "not implemented". The
contract it asks for now exists -- `workspace/contract.py` holds `Workspace`,
`HostWorkspace` and `VolumeWorkspace`, and `RepositoryMCP` reads and writes
through it instead of through the host filesystem -- and the measurement this
record demanded has been taken. What is *not* done is the migration: a run still
works on a host copy made by `create_run_copy`, exactly as this record said it
would until the volume path was proven. The implementation note at the end says
where the line falls. [Status](../../status.md) remains the account of what a
host actually shows.

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

**No measurement supports this yet.** *(Superseded 2026-09-11 -- see the
implementation note. The measurement has been taken and supports the direction;
the paragraph is kept because it is the condition the record was accepted
under.)* The 923 MB is evidence of the problem, not
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


## Implementation note, 2026-09-11

**The measurement this record demanded has been taken, and it supports the
direction.** `evaluation/benchmarks/adr17/measure_workspace.py` runs the same
file-heavy workload -- 600 small files; list, content search, 200 reads, 200
writes -- three ways: natively on the host, inside a container over a bind mount
of a host directory, and inside a container over a named volume. Seven repeats,
medians, on macOS-27.0-arm64-arm-64bit-Mach-O with Docker 29.7.2. Raw results are in
`evaluation/benchmarks/adr17/results/measurement.json`.

The first finding is that the question this record worried about is not the
expensive one. Starting the container costs about 0.15 s, and that figure is
the same for both mounts. Once it is subtracted, the volume is at or below the
noise floor for listing, searching and writing, where the bind mount pays
0.103 s to search and 0.054 s to write:

| operation | host | bind mount | named volume |
|---|---|---|---|
| list | 0.004 s | 0.012 s | 0.000 s |
| search | 0.031 s | 0.103 s | 0.000 s |
| 200 reads | 0.363 s | 0.022 s | 0.031 s |
| 200 writes | 0.014 s | 0.054 s | 0.000 s |

So the volume is not slower than what a container does today; on this host it is
faster than the bind mount for every operation measured. Populating it costs
0.25 s once.

**What the table does not say.** The host column is the floor, not a candidate --
[ADR 15](0015-container-only.md) does not allow a target-project command to run
there. Its slowest row, 200 reads, is slow for a reason unrelated to storage:
spawning 200 processes is expensive on macOS and cheap on Linux, so that cell
compares operating systems rather than mounts. And a synthetic 600-file tree is
not a Maven build; this measures the shape of work ASET's own tools do to a
project, not the shape of the project's build.

**What is implemented.** The contract, both implementations, the shallow clone
with the token passed through the environment rather than argv, and the
extraction this record's last paragraph required: `VolumeWorkspace.extract` copies
named files out to the host before teardown, by name and never implicitly, so a
failed run can still be read afterwards. `RepositoryMCP` now takes either a root
or a workspace, and every policy decision -- which roles may write, what a diff
is -- stayed in it rather than being duplicated per implementation.

**What is not.** No run uses `VolumeWorkspace` yet. `create_run_copy` still
produces the directory a run works in, and `MCPRepositoryClient` is still handed
a host path. Nothing above changes that, and this record said it should not: a
direction is not a migration. The remaining work is the switch itself, and the
consequence this record flagged as most likely to be underestimated -- getting
the diff back out -- turned out to be already handled, because `get_diff`
compares remembered contents through the contract rather than shelling out to
git.

One decision taken during implementation and worth recording: a file whose bytes
are not valid UTF-8 is now **refused** rather than returned as a lossy copy. The
previous host-only code decoded with a replacement character, which handed an
agent text that differed from the file it claimed to be reading.
