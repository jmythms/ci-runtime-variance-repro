# Runtime Report

This file is a template for the final CI comparison report after artifacts are
downloaded from the personal public repo workflow runs.

## Data Collection

- Repo: `jmythms/ci-runtime-variance-repro`
- Workflow: `runtime-repro`
- Samples per commit: 10
- Benchmark: synthetic Scout-shaped workload, roughly 7-10 minutes per CI sample
- Scout interaction: none

## Commits

| Label | Commit | Purpose |
|---|---|---|
| A | TBD | Baseline synthetic benchmark |
| B | TBD | Harmless-looking refactor/perf-style change |
| C | TBD | Revert of B, expected to match A source |

## Summary

Run this after downloading artifacts:

```powershell
python summarize_results.py path\to\downloaded\artifacts --output docs\report.md
```

## Interpretation Checklist

- Confirm commit C's benchmark source matches commit A.
- Compare medians rather than single samples.
- Check max/min spread for hosted-runner variance.
- Separate script wall time from setup/install/job time.
- Review `profile.txt` artifacts before attributing timing changes to code.
