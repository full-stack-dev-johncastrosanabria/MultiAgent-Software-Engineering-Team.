# Evaluation

`evaluation/` contains the executable evaluation surface and its evidence. It is separate from the application package and from `docs/`.

| Need | Location |
|---|---|
| Run the standard scenario suite | `scripts/run_evaluation.py` |
| Shared scenario definitions | `scenarios.py` |
| Run a multistack trial | `benchmarks/multistack/run_trial.py` |
| Measure the full GitHub cycle against real repositories | `benchmarks/ghcycle/run_cycle.py` (scored results in `results/`, raw reports in the git-ignored `results/raw/`) |
| Verify decisions 14, 16, 17 and 18 against a real Docker daemon | `benchmarks/adr14/`, `benchmarks/adr16/`, `benchmarks/adr17/`, `benchmarks/adr18/` |
| Inspect benchmark inputs and fixtures | `benchmarks/README.md` |
| Review selected report snapshots | `reports/curated/` |
| Inspect reports from individual runs | `reports/runs/` |
| Find generated traces and transient output | `reports/generated/` |
| Review preserved historical evidence | `evidence/archived/` |

Benchmark Markdown files, JSON baselines and compose fixtures are executable inputs. Reports and evidence describe executions; they do not define runtime behavior. Verify claims against code and tests before treating a report as current.
