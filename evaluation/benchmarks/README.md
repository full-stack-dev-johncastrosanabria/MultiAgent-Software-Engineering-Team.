# Benchmarks

Benchmark runners and their inputs live under this directory. The multistack runner supports the cases `ingresos`, `interview` and `northgate`.

```sh
python3 evaluation/benchmarks/multistack/run_trial.py --help
```

Other runners: `ghcycle/run_cycle.py` measures the full GitHub cycle against real repositories and `ghcycle/probe_shallow_push.py` probes a push from a shallow clone. Scored results go to `ghcycle/results/`; raw reports go to the git-ignored `ghcycle/results/raw/`. A scored result does not record the ASET commit, specification or model chain, and dry runs score `infrastructure` and `delivery` as passed without exercising them (see `docs/audit160926/02-evidencia-y-metricas.md`). `adr14/`, `adr16/`, `adr17/` and `adr18/` verify those decisions against a real Docker daemon; decisions 16–18 write their evidence to `results/`, while the decision 14 trial reports live in `../reports/runs/adr14-trial-*`.

Case specifications are in `multistack/cases/`. Stable baselines, provider probes and the `multinetwork` compose fixture remain beside the runner because they are benchmark inputs. Do not move or edit them as ordinary documentation; changes alter an evaluation contract and require the benchmark tests to be reviewed.
