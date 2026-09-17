# Reports

Reports are organized by lifecycle:

- `curated/` contains selected snapshots used by evidence tests or retained as reference outputs, including the previously versioned text/XML suite summaries.
- `runs/` contains reports produced by CLI, apply, retry and one-off evaluation runs.
- `generated/` contains transient traces and text/XML output. It is ignored for new files.
- `traces/` and the top-level `apply-debugger-flask-writes*.json` predate this layout and are kept as run evidence; new reports go under `runs/`. The `apply-debugger-flask-writes*.json` files are byte-identical copies of `../evidence/archived/flask-low-stock-2026-09-03/`.
- `curated/full-pytest.*` and `curated/e2e-pytest.txt` are 2026-08-25 snapshots from another host (103 tests); they do not describe the current suite. `tests/e2e/test_live_evaluation_evidence.py` and `tests/e2e/test_multimodel_evidence.py` read the curated JSON files.

A report is evidence about one execution, identified by its filename and payload. It is not a source of runtime configuration. Do not place credentials or raw provider payloads in a report. When a report is used by a test, keep that dependency explicit in the test and in this index.
