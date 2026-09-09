# 11. The operator states which tests the gate runs

Date: 2026-09-08. Status: accepted.

## Context

`InterviewCleanApi` ships twenty xUnit tests. Sixteen need a migrated MySQL and
nothing else; they pass under the process sandbox. The other four drive Chrome
through Selenium, and they cannot run inside the boundary at all.

The reason is narrow and worth recording, because it is not the reason we
expected. Chrome asks the operating system for a temporary directory to hold
its user data directory. On macOS it resolves that through
`confstr(_CS_DARWIN_USER_TEMP_DIR)`, which returns `/var/folders/…/T` and
ignores `TMPDIR` — so pointing `TMPDIR` at the run's own scratch, which the
sandbox grants, changes nothing. The denied root is reached anyway and every
browser test fails in a millisecond with `session not created … cannot create
temp dir for user data dir`.

Two fixes were considered and rejected. Granting `/var/folders/…/T` would open
the user's temporary directory to every command the gate runs, which is most of
what the boundary exists to keep closed. Passing `--user-data-dir` belongs to
the repository's test code, and the harness does not get to edit the suite it
is measuring.

Measured, on this repository: the sixteen non-browser tests pass under the
sandbox; the four browser tests fail in 121 seconds; the unfiltered gate ran
for 2079 seconds and failed. A gate that can never be green is not a signal.

## Decision

An operator may narrow the gate with `QUALITY_TEST_FILTER`, in the toolchain's
own filter syntax. A profile declares how it narrows a run
(`test_filter_template`) or declares nothing; today `dotnet` uses `--filter`
and `python` uses `-k`.

A stack that declares no filter syntax **refuses** the run when a filter is
set, before doing any work, rather than executing the whole suite. Running more
than the operator asked for is the one failure mode a narrowed gate must not
have: it reports green over tests nobody chose to run.

Narrowing is never inferred. The harness does not detect Selenium and quietly
drop those tests, because "which tests count" is a claim about what the run
proves, and that claim belongs to a person.

## Consequences

The evidence a run publishes describes the suite that was actually executed. A
narrowed gate is honest about being narrow, and the filter is recorded with the
run rather than living in someone's shell history.

This does not make browser tests run. It states where they do not. The suite in
`InterviewCleanApi` also asserts nothing when its front-end servers are down —
each test returns early — so the four tests were never evidence under the
boundary even when Chrome did start.

Related: ADR 10 refuses a Testcontainers suite on the container runner for the
same reason and in the same shape — before the work, naming the boundary.
