# CI Runtime Variance Repro

This repository is a local-first, synthetic reproduction harness for a common CI
performance question:

> A commit appears slower in CI. A later revert makes the source match the
> earlier baseline again, but the CI runtime is still slower. Is that possible?

Yes. Hosted CI runners can vary enough that one run per commit is weak evidence.
This repo demonstrates that behavior without cloning, modifying, or interacting
with `scout-bto/scout`.

## What It Measures

The benchmark is inspired by the workload shape of Scout's `run.py`, but it is
not Scout code. It performs deterministic data-heavy work:

- builds large nested market dictionaries;
- copies dictionaries containing NumPy arrays;
- runs repeated competition-style array calculations;
- aggregates results with pandas;
- writes JSON, CSV, gzip, and pickle artifacts;
- captures `cProfile`, wall time, process time, Python/package versions, and
  runner metadata.

## Local Smoke Test

```powershell
python -m pip install -r requirements.txt
python profile_run.py --preset smoke --sample-id local-1 --output-dir artifacts/local-smoke/sample-1
python summarize_results.py artifacts/local-smoke --output artifacts/local-smoke/summary.md
```

Generated local artifacts are ignored by git.

## CI Design

The GitHub Actions workflow runs up to 10 repeated matrix samples for each
commit. Ten samples are the default because comparing distributions is more
useful than comparing one timing number.

The intended demonstration sequence is:

1. Commit A: baseline synthetic benchmark.
2. Commit B: harmless-looking refactor/perf-style change.
3. Commit C: `git revert` of commit B, returning the source to commit A.

If commit C is source-equivalent to commit A but the observed timing is still
different, the likely explanation is CI variance rather than a code difference.

## Interpreting Results

Download workflow artifacts and run:

```powershell
python summarize_results.py path\to\downloaded\artifacts --output docs\report.md
```

Look at min, median, max, standard deviation, and spread percentage. Avoid
treating a single slow hosted-runner sample as proof of a regression.

## Practical Recommendations

- Rerun the same SHA several times before blaming a commit.
- Compare medians and spread, not one workflow run.
- Measure the target script separately from setup/install/job overhead.
- Upload profiler output and runner metadata for every run.
- Pin Python and dependencies.
- Use larger or self-hosted runners when strict performance gates matter.
- Define a regression threshold only after observing baseline CI variance.
