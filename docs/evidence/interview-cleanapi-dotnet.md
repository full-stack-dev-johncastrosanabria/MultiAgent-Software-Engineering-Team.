# InterviewCleanApi: what it took to run a .NET 10 repository under the boundary

Third repository in the multistack series, after `PruebaNuevosIngresosBackend`.
Target: `full-stack-dev-johncastrosanabria/InterviewCleanApi` at `c86d970` —
.NET 10 Clean Architecture, MySQL, JWT, xUnit, Selenium, three front-ends.

## Host baseline

Measured before touching the harness, because the previous series showed how
expensive it is to debug a harness against a repository whose own state is
unknown.

| Condition | Result |
| --- | --- |
| No database | suite fails: every controller test needs MySQL |
| MySQL 8.4 on `localhost:3306` + `dotnet ef database update` | 16/16 green, 8.8s |
| Same, run again immediately | 14/16 — two failures, then green again |

The alternation is not flakiness in the usual sense and it is not pollution
that accumulates. `Delete_WithoutAdminRole_ReturnsForbidden` deletes
`/api/products/1` and asserts `403 Forbidden` or `404 NotFound`. It gets `204
NoContent` whenever product 1 happens to exist, because a non-admin token
successfully deletes it — the test's own comment concedes that "role-based
authorization is not enforced in test environment". The delete then removes the
row, so the next run reads `404` and passes. The suite shares one database and
has no per-test isolation, so the gate is only deterministic from a freshly
migrated schema.

Two things follow. The finding is real and belongs to the repository, not the
harness: authorization is not enforced on delete, and the test is written to
tolerate that. And any run of the gate has to start from a clean schema.

## Six blockers between `dotnet test` and the process sandbox

Each was found by measuring the failure, not by reading the previous one's fix.
Every one of them surfaced only after the one above it was cleared.

| # | Symptom | Cause | Fix |
| --- | --- | --- | --- |
| 1 | `open("/tmp/.dotnet/shm") == -1, EPERM` in NuGet's migration runner | the runtime keeps cross-process state at a fixed path outside the workspace | a profile declares the paths it writes (`toolchain_writable_paths`) |
| 2 | grant emitted, still denied | seatbelt matches resolved paths, and `/tmp` is a symlink to `/private/tmp` on macOS | resolve each path before emitting the rule |
| 3 | files writable, directory `open` still denied | the grant was only in `file-write*` | emit the same subpaths in `file-read*` too |
| 4 | `mkdir("/tmp/.dotnet/lockfiles/…") EPERM` | the grant named `shm`, not the directory .NET owns | declare `/tmp/.dotnet` |
| 5 | `SocketException (13)` in MSBuild `StartLocalNode` | MSBuild reuses worker nodes over a socket in an ungranted directory | `MSBUILDDISABLENODEREUSE=1` and `-m:1` in the profile |
| 6 | `MSB4018: CreateAppHost failed` / `System.OverflowException` at `Interop.Sys.IsMemberOfGroup` | macOS resolves a group list through opendirectoryd, and `(deny default)` covers that mach lookup | allow the three `opendirectoryd` global names |

Blocker 6 is the one worth remembering. A denied identity lookup does not reach
the caller as a permission error. .NET reads the refusal as "buffer too small",
doubles the buffer, and overflows a checked multiply — so the build dies with an
arithmetic error that names neither the sandbox nor the lookup. Three readings
of that stack trace were wrong before a probe settled it: `getgrouplist` under
the profile raises, and returns 16 groups once the lookup is allowed. The first
probe was wrong too, because `/usr/bin/id -G` uses the `getgroups` syscall,
which the sandbox never blocked — it took `id -Gn`, whose group *names* went
unresolved, to show the directory service was unreachable at all.

The regression test is behavioural rather than a string assertion on the
profile: it runs `os.getgrouplist` under the real sandbox and fails without the
grant.

## The scratch directory promised two directories it never made

`prepare_scratch` sets `HOME` to `{environment}/home` and `TMPDIR` to
`{environment}/tmp`, and its own docstring says both live there. Neither was
ever created. Nothing noticed for the length of two repositories, because
Python's `tempfile` invents a missing `TMPDIR` and every toolchain we had run
until now does something equivalent.

Chrome does not. It was the first thing to ask the environment for the
directory the environment claimed to have.

## Where the browser suite stops

Creating the directories did not make the Selenium tests pass, and the second
measurement is the useful one. Chrome resolves its temporary directory through
`confstr(_CS_DARWIN_USER_TEMP_DIR)` on macOS, which returns `/var/folders/…/T`
and ignores `TMPDIR` entirely — so a granted scratch directory it never looks
at cannot help. All four browser tests fail in 121 seconds with `session not
created … cannot create temp dir for user data dir`.

| Gate | Result |
| --- | --- |
| Whole suite, unfiltered | FAIL after 2079s |
| Browser tests only | 0/4, 121s |
| Non-browser tests only | rc 0, 632s |

Granting `/var/folders/…/T` was rejected: that is the user's temporary
directory, opened to every command the gate runs. Passing `--user-data-dir`
would work, but it belongs to the repository's test code, and the harness does
not edit the suite it is measuring. ADR 11 records the decision that follows —
the operator states which tests the gate runs, and a stack that cannot express
a filter refuses rather than quietly running everything.

Worth noting for whoever owns the repository: these four tests assert nothing
when the front-end servers are down. Each one checks `IsServerRunning` and
returns early — but only *after* the constructor has already built a
`ChromeDriver`. The precondition check sits behind the expensive step it was
meant to guard, so the suite pays for a browser it then declines to use.

## The gate is green once, not repeatedly

A consequence of the delete test that matters for an autonomous run. On a
freshly migrated schema the suite passes. The `Create` tests then leave products
behind, so product 1 exists when the next execution reaches
`Delete_WithoutAdminRole_ReturnsForbidden`, which deletes it and fails on `204`.
That execution removes the row again, so the one after it passes.

A run that executes the gate more than once — the normal shape, with a
remediation cycle — should therefore expect the second execution to be red for
reasons that have nothing to do with the change under test.

That is not something to filter away. Narrowing the gate until it is green would
be the dishonest use of ADR 11: the mechanism exists to state which suite the
boundary can host, not to drop tests that fail. The suite needs per-test
isolation, which is the repository's to fix.

## The integration suite cannot start its host inside the boundary

The sixteen non-browser tests are not unit tests. Each one builds an in-process
ASP.NET host through `WebApplicationFactory<Program>`, and under the process
sandbox that host never finishes building:

```
System.InvalidOperationException : Timed out waiting for the entry point to
build the IHost after 00:05:00
   at Microsoft.AspNetCore.Mvc.Testing.WebApplicationFactory`1.CreateHost(...)
   at InterviewCleanApi.Tests.ProductsControllerTests..ctor(...)
```

Five minutes per test, sixteen tests across two parallel classes: roughly forty
minutes, which is exactly the 2400s the gate spent before giving up. What looked
like a hang at fifty percent CPU was this, repeated.

Confirmed outside the test runner, which is the measurement that settles it: the
same application, launched directly, prints its startup log immediately on the
host and emits **nothing at all** in forty seconds under the sandbox.

So with the four Selenium tests already excluded, this repository has no test
that runs under the process boundary. Raising the timeout does not help.

### Three hypotheses this cost, all refuted by measurement

Recorded because each one was plausible and each one was wrong, and because the
refutations were cheaper than the belief would have been.

- **Roslyn's shared compilation server.** MSBuild sat blocked in
  `WaitForMultipleObjects` with `VBCSCompiler` idle on the other end — the same
  shape as the MSBuild node-reuse socket failure fixed earlier. Adding
  `-p:UseSharedCompilation=false` changed nothing; the run timed out again.
  The flag stays in the profile because the reasoning holds for node reuse's
  sibling, but it was not this.
- **The scratch `home` and `tmp` directories.** The only green sandbox run
  predated creating them, and every failure followed it — a clean correlation.
  Removing them again reproduced the failure exactly.
- **A missing database schema.** `Products` did not exist. The table is
  `products`; MySQL is case-sensitive here and the query was wrong, not the
  schema.

A fourth was self-inflicted: the error string was printed truncated to 300
characters, cutting `2390` into `239`, which invented a phantom 2160 seconds of
pre-command work and sent three measurements chasing it.
