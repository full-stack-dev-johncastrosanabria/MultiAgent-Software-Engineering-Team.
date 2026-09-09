# Reports

Reports are organized by lifecycle:

- `curated/` contains selected snapshots used by evidence tests or retained as reference outputs, including the previously versioned text/XML suite summaries.
- `runs/` contains reports produced by CLI, apply, retry and one-off evaluation runs.
- `generated/` contains transient traces and text/XML output. It is ignored for new files.

A report is evidence about one execution, identified by its filename and payload. It is not a source of runtime configuration. Do not place credentials or raw provider payloads in a report. When a report is used by a test, keep that dependency explicit in the test and in this index.
