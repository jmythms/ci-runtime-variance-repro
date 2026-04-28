#!/usr/bin/env python3
"""Synthetic long-running workload inspired by Scout's run.py.

This file intentionally mimics the *shape* of a data-heavy integration run:
large nested market dictionaries, numpy arrays, repeated copies, tabular
aggregation, compression, pickle/json I/O, and deterministic result output.
It does not import, clone, or execute Scout.
"""

from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import json
import pickle
import shutil
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class WorkloadPreset:
    measures: int
    segments: int
    years: int
    width: int
    copy_rounds: int
    competition_rounds: int
    io_rounds: int


PRESETS: dict[str, WorkloadPreset] = {
    "smoke": WorkloadPreset(
        measures=8,
        segments=3,
        years=8,
        width=32,
        copy_rounds=1,
        competition_rounds=2,
        io_rounds=1,
    ),
    "ci": WorkloadPreset(
        measures=120,
        segments=10,
        years=32,
        width=96,
        copy_rounds=4,
        competition_rounds=12,
        io_rounds=2,
    ),
}

ADOPTION_SCHEMES = ("technical_potential", "max_adoption_potential")
METRICS = ("stock", "energy", "carbon", "cost")


def _rng(seed: int) -> np.random.Generator:
    return np.random.default_rng(seed)


def _build_market_tree(preset: WorkloadPreset, seed: int) -> dict[str, Any]:
    rng = _rng(seed)
    tree: dict[str, Any] = {}
    year_labels = [str(2024 + i) for i in range(preset.years)]

    for measure_idx in range(preset.measures):
        measure_name = f"measure_{measure_idx:04d}"
        tree[measure_name] = {}
        base = rng.random((preset.years, preset.width), dtype=np.float64)

        for scheme_idx, scheme in enumerate(ADOPTION_SCHEMES):
            scheme_scale = 1.0 + (scheme_idx * 0.15)
            scheme_data: dict[str, Any] = {}

            for segment_idx in range(preset.segments):
                segment_name = f"segment_{segment_idx:02d}"
                segment_scale = 1.0 + (segment_idx / max(1, preset.segments))
                segment_data: dict[str, Any] = {}

                for metric_idx, metric in enumerate(METRICS):
                    metric_scale = 1.0 + (metric_idx * 0.2)
                    noise = rng.normal(
                        loc=0.0,
                        scale=0.005,
                        size=(preset.years, preset.width),
                    )
                    values = np.abs(base * scheme_scale * segment_scale * metric_scale + noise)
                    segment_data[metric] = {
                        "baseline": values,
                        "efficient": values * (0.72 + metric_idx * 0.03),
                        "years": year_labels,
                    }

                scheme_data[segment_name] = segment_data

            tree[measure_name][scheme] = scheme_data

    return tree


def _clone_markets(markets: dict[str, Any]) -> dict[str, Any]:
    """Baseline clone implementation intentionally uses general deepcopy."""
    return copy.deepcopy(markets)


def _iter_metric_arrays(markets: dict[str, Any]):
    for measure_data in markets.values():
        for scheme_data in measure_data.values():
            for segment_data in scheme_data.values():
                for metric_data in segment_data.values():
                    yield metric_data["baseline"], metric_data["efficient"]


def _competition_pass(markets: dict[str, Any], rounds: int) -> dict[str, float]:
    totals = {
        "baseline": 0.0,
        "efficient": 0.0,
        "savings": 0.0,
        "checksum": 0.0,
    }

    for round_idx in range(rounds):
        round_weight = 1.0 / (round_idx + 1)
        for baseline, efficient in _iter_metric_arrays(markets):
            adjusted = np.minimum(baseline, efficient * (1.0 + round_weight * 0.015))
            savings = baseline - adjusted
            totals["baseline"] += float(np.sum(baseline[:, :16]))
            totals["efficient"] += float(np.sum(adjusted[:, :16]))
            totals["savings"] += float(np.sum(savings[:, :16]))
            totals["checksum"] += float(np.linalg.norm(adjusted[:8, :16]))

    return totals


def _make_summary_frame(markets: dict[str, Any]) -> pd.DataFrame:
    records = []
    for measure_name, measure_data in markets.items():
        for scheme_name, scheme_data in measure_data.items():
            for segment_name, segment_data in scheme_data.items():
                for metric_name, metric_data in segment_data.items():
                    baseline = metric_data["baseline"]
                    efficient = metric_data["efficient"]
                    records.append(
                        {
                            "measure": measure_name,
                            "scheme": scheme_name,
                            "segment": segment_name,
                            "metric": metric_name,
                            "baseline": float(np.sum(baseline)),
                            "efficient": float(np.sum(efficient)),
                            "savings": float(np.sum(baseline - efficient)),
                        }
                    )

    frame = pd.DataFrame.from_records(records)
    return (
        frame.groupby(["scheme", "segment", "metric"], as_index=False)
        .agg(
            baseline=("baseline", "sum"),
            efficient=("efficient", "sum"),
            savings=("savings", "sum"),
        )
        .sort_values(["scheme", "segment", "metric"])
        .reset_index(drop=True)
    )


def _write_outputs(
    output_dir: Path,
    markets: dict[str, Any],
    summary: pd.DataFrame,
    metrics: dict[str, float],
    preset: WorkloadPreset,
    io_rounds: int,
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    data_dir = output_dir / "generated"
    data_dir.mkdir(parents=True, exist_ok=True)

    summary_path = output_dir / "summary.csv"
    summary.to_csv(summary_path, index=False)

    metrics_path = output_dir / "metrics.json"
    metrics_payload = {
        "preset": asdict(preset),
        "metrics": metrics,
        "row_count": int(len(summary)),
    }
    metrics_path.write_text(json.dumps(metrics_payload, indent=2, sort_keys=True), encoding="utf-8")

    last_gzip_path = data_dir / "markets.pkl.gz"
    for round_idx in range(io_rounds):
        gzip_path = data_dir / f"markets_{round_idx:02d}.pkl.gz"
        with gzip.open(gzip_path, "wb", compresslevel=5) as fh:
            pickle.dump(markets, fh, protocol=pickle.HIGHEST_PROTOCOL)
        last_gzip_path = gzip_path

    digest = hashlib.sha256()
    digest.update(summary_path.read_bytes())
    digest.update(metrics_path.read_bytes())
    digest.update(last_gzip_path.read_bytes()[: 1024 * 1024])
    digest_path = output_dir / "digest.txt"
    digest_path.write_text(digest.hexdigest() + "\n", encoding="utf-8")

    return {
        "summary_csv": str(summary_path),
        "metrics_json": str(metrics_path),
        "market_pickle_gzip": str(last_gzip_path),
        "digest": digest.hexdigest(),
    }


def run_workload(
    preset_name: str,
    output_dir: Path,
    seed: int,
    keep_workdir: bool = False,
) -> dict[str, Any]:
    preset = PRESETS[preset_name]
    start = time.perf_counter()

    workdir = Path(tempfile.mkdtemp(prefix="runtime-repro-"))
    try:
        markets = _build_market_tree(preset, seed)
        clone_metrics = []

        for copy_round in range(preset.copy_rounds):
            cloned = _clone_markets(markets)
            totals = _competition_pass(cloned, preset.competition_rounds)
            totals["copy_round"] = float(copy_round)
            clone_metrics.append(totals)

        final_clone = _clone_markets(markets)
        summary = _make_summary_frame(final_clone)
        merged_metrics = {
            key: float(sum(round_metrics[key] for round_metrics in clone_metrics))
            for key in ("baseline", "efficient", "savings", "checksum")
        }
        merged_metrics["copy_rounds"] = float(preset.copy_rounds)

        outputs = _write_outputs(
            output_dir=output_dir,
            markets=final_clone,
            summary=summary,
            metrics=merged_metrics,
            preset=preset,
            io_rounds=preset.io_rounds,
        )

        elapsed = time.perf_counter() - start
        return {
            "preset": preset_name,
            "preset_config": asdict(preset),
            "seed": seed,
            "elapsed_seconds": elapsed,
            "metrics": merged_metrics,
            "outputs": outputs,
            "workdir": str(workdir),
        }
    finally:
        if keep_workdir:
            (output_dir / "workdir.txt").write_text(str(workdir) + "\n", encoding="utf-8")
        else:
            shutil.rmtree(workdir, ignore_errors=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a synthetic Scout-shaped workload")
    parser.add_argument("--preset", choices=sorted(PRESETS), default="ci")
    parser.add_argument("--output-dir", type=Path, default=Path("results"))
    parser.add_argument("--seed", type=int, default=618)
    parser.add_argument("--keep-workdir", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> dict[str, Any]:
    args = parse_args(argv)
    result = run_workload(
        preset_name=args.preset,
        output_dir=args.output_dir,
        seed=args.seed,
        keep_workdir=args.keep_workdir,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return result


if __name__ == "__main__":
    main()
