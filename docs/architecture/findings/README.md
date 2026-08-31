# Findings

Defects in how the agents behave, as opposed to defects in a line of code. The
record is [agent-architecture-audit.json](agent-architecture-audit.json); this
index says where each one stands.

| # | Severity | Finding | Status |
|---|---|---|---|
| 1 | critical | Reviewer approves without the coverage evidence it requires | **fixed** — `e6f9319` |
| 2 | critical | Architecture is not grounded in the repository it inspected | **fixed** — `dd36bf1`, `f14e7b6`, `95cc463` |
| 3 | high | Project dependencies install into the shared interpreter | **fixed** — nothing runs the operator's interpreter any more; each QualityMCP provisions its own environment from `sys._base_executable`, and a test asserts no command reaches `sys.executable`. The two races that review found against the *sandbox* are a different question, and they dissolve under [ADR 2](../decisions/0002-container-runner.md), whose container runner is now implemented and verified |
| 4 | high | Repository MCP indexes ignored artefacts without limit | **fixed** — `6fe08e4` |
| 5 | medium | Telemetry confuses primary execution with fallback | **fixed** — the cloud runtime reports a fallback only when it is one, and the local runtime records the reason it is given instead of accepting and dropping it |
| 6 | medium | Visible history reconstructs past decisions from the latest revision | **fixed** — the state records every reviewer decision, and the report shows each cycle its own; where no history exists it says nothing rather than borrowing |
| 7 | critical | The Developer can empty files and cannot see what it wrote | **fixed** — the projection now carries `implementation`, and the prompt renders the previously authored code, because a projected value alone is collapsed to "present" |
| 8 | high | Architecture designs from four files and cannot ask for a fifth | **fixed** — a byte budget replaced the file count, and the prompt now states how much evidence was withheld |

## Two things worth remembering

**Finding 5 was found because the record contradicted itself.** The trace beside
each cloud attempt already said "primary" or "fallback" correctly; only the
`ModelExecutionInfo` was wrong. A single source would have hidden it.

**Finding 6 could not be fixed by reading harder.** The state kept only the
latest reviewer decision, so the data to show what an earlier cycle decided did
not exist. The fix had to record it. Where an older run has no history, the
report now shows nothing for that cycle instead of the terminal decision — saying
nothing beats saying something untrue.

**Finding 3 is the reason ADR 2 exists.** Four rounds of review against the
process sandbox each closed a gap and revealed another. The decision to move to a
container was not a preference; it came from the shape of what kept being wrong.

**Finding 7 was not where the audit said it was.** The audit blamed the missing
`implementation` in the Developer's projection. That is real, but fixing it alone
changes nothing: `build_role_prompts` collapses every projected value except
`run_id` and `requirement` to "present"/"absent". The mechanism is that the graph
writes to the workspace only for `ActionMode.APPLIED`, so after a `PROPOSED` pass
the Developer re-reads the original files and sees no trace of its own work.

**Finding 7 is why counts are not evidence.** The rewrite it describes deleted
four tests and added five, so the total rose from 18 to 19. Anything checking
test counts would have reported an improvement. Only comparing symbols showed the
fifteen that vanished.
