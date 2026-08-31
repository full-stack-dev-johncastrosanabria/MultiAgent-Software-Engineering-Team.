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
| 12 | high | Configuration never reaches the MCP server that acts on it | **fixed** — the runner and image travel as explicit arguments; the SDK forwards only five environment variables and a test now says so |
| 11 | high | The ephemeral environment imposes the operator's Python on the project | **fixed** — the container image follows the interpreter derived from the project's pins, verified against FlaskApiProduct: 32 seconds, Python 3.12, every dependency from a wheel, 62 tests passing. Previously **partly fixed** — the failure now says so: an install that fell back to a source build is reported as INFRASTRUCTURE_ERROR naming the interpreter, instead of a wall of ninja output read as a code defect. Declared requirements are read where a project states one. Actually *providing* a different interpreter still needs a version-matched container image |
| 10 | critical | The ephemeral environment installs only projects that ship a pyproject.toml | **fixed** — a project that declares its dependencies in requirements.txt gets them, and the installable manifests are tied to the ones detection recognises |
| 9 | critical | The cloud-context guardrail blocks any project that reads environment variables | **fixed** — `.env` is matched as a file reference and not as a substring of `os.environ` |
| 8 | high | Architecture designs from four files and cannot ask for a fifth | **fixed** — a byte budget replaced the file count, and the prompt now states how much evidence was withheld |

## Two things worth remembering

**Findings 9 and 10 were both invisible to the whole test suite, and both were
found in the same run.** They share a shape: the system refused or failed for a
reason that had nothing to do with the work, and reported it as though it did.
Nine blocked the Developer with a message about secrets over a comment; ten let
the tests run without the project's dependencies and called the resulting
ModuleNotFoundError a code defect, looping the Developer three times over it.

**Finding 9 was invisible to the whole test suite.** Every fixture in this
project is written by this project, and none of them reads configuration from the
environment in the text that travels to a provider. It took pointing the system at
somebody else's repository, for real, to find that the Developer stage could not
run at all against most Python projects.

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
