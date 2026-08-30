# Findings

Defects in how the agents behave, as opposed to defects in a line of code. The
record is [agent-architecture-audit.json](agent-architecture-audit.json); this
index says where each one stands.

| # | Severity | Finding | Status |
|---|---|---|---|
| 1 | critical | Reviewer approves without the coverage evidence it requires | **fixed** — `e6f9319` |
| 2 | critical | Architecture is not grounded in the repository it inspected | **fixed** — `dd36bf1`, `f14e7b6`, `95cc463` |
| 3 | high | Project dependencies install into the shared interpreter | **superseded** — `aa69fb1`, `b20ad86` landed the ephemeral environment and the process sandbox; the two races still open against it dissolve under [ADR 2](../decisions/0002-container-runner.md) rather than being fixed |
| 4 | high | Repository MCP indexes ignored artefacts without limit | **fixed** — `6fe08e4` |
| 5 | medium | Telemetry confuses primary execution with fallback | **open** — confirmed live in run-8e101cac (`fallback_used: true`, `fallback_reason: CLOUD_FIRST` on the primary path) |
| 6 | medium | Visible history reconstructs past decisions from the latest revision | **open** — untouched |
| 7 | critical | The Developer can empty files and cannot see what it wrote | **open** — recorded `210b125` |
| 8 | high | Architecture designs from four files and cannot ask for a fifth | **open** — recorded `47642e7` |

## Two things worth remembering

**Finding 3 is the reason ADR 2 exists.** Four rounds of review against the
process sandbox each closed a gap and revealed another. The decision to move to a
container was not a preference; it came from the shape of what kept being wrong.

**Finding 7 is why counts are not evidence.** The rewrite it describes deleted
four tests and added five, so the total rose from 18 to 19. Anything checking
test counts would have reported an improvement. Only comparing symbols showed the
fifteen that vanished.
