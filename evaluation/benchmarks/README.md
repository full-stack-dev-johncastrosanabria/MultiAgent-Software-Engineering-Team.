# Benchmarks

Benchmark runners and their inputs live under this directory. The multistack runner supports the cases `ingresos`, `interview` and `northgate`.

```sh
python3 evaluation/benchmarks/multistack/run_trial.py --help
```

Case specifications are in `multistack/cases/`. Stable baselines, provider probes and the `multinetwork` compose fixture remain beside the runner because they are benchmark inputs. Do not move or edit them as ordinary documentation; changes alter an evaluation contract and require the benchmark tests to be reviewed.
