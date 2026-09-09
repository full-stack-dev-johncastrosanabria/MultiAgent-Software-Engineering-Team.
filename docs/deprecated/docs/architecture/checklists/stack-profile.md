# Adding a stack profile

A profile teaches the system to work in one language ecosystem: which image, and
which commands to install, lint, test and build. It is done when every item below
holds.

## The image

- [ ] **Pinned by digest**, not a tag. A tag is a different image tomorrow, and a
      run that cannot be reproduced is not evidence.
- [ ] Built on the base the ecosystem's official images use, so profiles share
      layers instead of each pulling its own world.
- [ ] Its architecture is checked against the host. SQL Server publishes
      linux/amd64 only; on Apple Silicon that is emulation, and it is slow enough
      to matter for something that starts every run.
- [ ] Carries the toolchain. The runner supplies the boundary, never the compiler.

## The commands

- [ ] Install, lint, test and build are each named for this ecosystem, and none
      of them is assumed to exist because the Python one did.
- [ ] **Every tool's configuration is scoped to the project.** Ruff resolves
      config by walking up the directory tree, so in a nested project it read the
      parent's `pyproject.toml`, died with "Operation not permitted" outside the
      sandbox, and both demos were rejected for a defect that did not exist. Any
      tool that searches upward has to be pinned downward.
- [ ] Network is declared, and the declaration is honest. Python installs from a
      hashed lock and tests offline. Maven, dotnet and npm resolve while they
      build, so their test phase is granted network and says so through
      `test_needs_network`. Do not claim a restore phase makes them offline
      without measuring it: `dependency:go-offline` completes and a following
      offline `mvn test` still fails.
- [ ] **Toolchain caches live on the environment volume.** Each command is a
      fresh container running as the host user, whose HOME it cannot write, so a
      cache left at its default location is both unwritable and gone before the
      next phase starts.
- [ ] Commands are argv, never a shell string, so nothing in a project's name or
      path is interpreted.

## The evidence

- [ ] `run_tests` means the same thing it means everywhere else: behaviour really
      executed and a status really reported. The gates read MCP operation names,
      not tool binaries, so a profile satisfies the existing contract rather than
      extending it.
- [ ] Failures are attributed. A compilation error, a failing assertion and a
      service that never started are three different facts, and reporting them as
      one is how [finding 7](../findings/README.md) produced a headline that
      pointed at the wrong thing.
- [ ] Coverage dimensions map to something real in this ecosystem, or the profile
      says plainly that they do not. "No evidence" and "not applicable" are
      different, and conflating them is [finding 1](../findings/README.md).

## Proof

- [ ] The stack is detectable *and* runnable. A manifest that detection knows
      about with no profile behind it produces a component nothing can build;
      a test derives one set from the other rather than restating it.
- [ ] Services the project declares are started before its tests, and a service
      that never becomes ready is reported as infrastructure rather than as a
      failing test.
- [ ] Verified against a real repository, not a fixture. The six in
      [../roadmap.md](../roadmap.md) exist for this.
- [ ] The suite passes on a machine with no container runtime and no images
      pulled. Integration tests gate on what is actually present; a profile that
      makes the suite require Docker has broken everyone who does not have it.
- [ ] A deliberately broken change is rejected. A profile that only ever passes
      has not been shown to be a gate.
