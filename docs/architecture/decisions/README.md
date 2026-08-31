# Architecture decision records

Decisions that shape the system, in the order they were taken. These are
tracked in git deliberately: `PROJECT_STATE.md` and the handoff files are
ephemeral working state, and anything recorded only there is lost when a session
rotates it out.

| # | Decision | Status |
|---|---|---|
| [1](0001-target-multiple-language-ecosystems.md) | Target multiple language ecosystems | accepted |
| [2](0002-container-runner.md) | Execute target-project commands in a container | accepted |
| [3](0003-split-quality-mcp.md) | Split QualityMCP into quality, runner, and stack profile | accepted |
| [4](0004-profile-per-component.md) | A profile describes a component, not a repository | accepted |
| [5](0005-services-per-run.md) | A project's services live for the run, on a network that reaches nothing else | accepted |
| [6](0006-github-origin-pull-request-delivery.md) | GitHub is an origin, and a pull request is how work is delivered | accepted |
| [7](0007-declared-coverage-decides-remediation.md) | A stage declares what it could not see, and the router believes the count | accepted |

A decision here outranks the same claim made anywhere untracked. When they
disagree, this directory is right and the other file is stale.

For where the product is going rather than why it is as it is, see
[../roadmap.md](../roadmap.md).
