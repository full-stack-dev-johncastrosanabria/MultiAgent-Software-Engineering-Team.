# Evaluation

`evaluation/` contains the executable evaluation surface and its evidence. It is separate from the application package and from `docs/`.

| Need | Location |
|---|---|
| Run the standard scenario suite | `scripts/run_evaluation.py` |
| Shared scenario definitions | `scenarios.py` |
| Run a multistack trial | `benchmarks/multistack/run_trial.py` |
| Inspect benchmark inputs and fixtures | `benchmarks/README.md` |
| Review selected report snapshots | `reports/curated/` |
| Inspect reports from individual runs | `reports/runs/` |
| Find generated traces and transient output | `reports/generated/` |
| Review preserved historical evidence | `evidence/archived/` |

Benchmark Markdown files, JSON baselines and compose fixtures are executable inputs. Reports and evidence describe executions; they do not define runtime behavior. Verify claims against code and tests before treating a report as current.
