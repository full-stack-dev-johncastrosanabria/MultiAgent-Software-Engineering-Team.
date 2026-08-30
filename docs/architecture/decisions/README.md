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

A decision here outranks the same claim made anywhere untracked. When they
disagree, this directory is right and the other file is stale.

For where the product is going rather than why it is as it is, see
[../roadmap.md](../roadmap.md).
