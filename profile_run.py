#!/usr/bin/env python3
"""Profile the synthetic run.py workload and write CI-friendly artifacts."""

from __future__ import annotations

import argparse
import cProfile
import importlib.metadata
import io
import json
import os
import platform
import pstats
import subprocess
import sys
import time
import tracemalloc
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import run


def _package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "not-installed"


def _git_value(args: list[str], default: str = "unknown") -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return default
    value = completed.stdout.strip()
    return value or default


def _metadata(sample_id: str, preset: str, seed: int) -> dict[str, Any]:
    return {
        "sample_id": sample_id,
        "preset": preset,
        "seed": seed,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "commit_sha": os.environ.get("GITHUB_SHA") or _git_value(["rev-parse", "HEAD"]),
        "git_branch": os.environ.get("GITHUB_REF_NAME") or _git_value(["branch", "--show-current"]),
        "github_run_id": os.environ.get("GITHUB_RUN_ID", ""),
        "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", ""),
        "runner_name": os.environ.get("RUNNER_NAME", ""),
        "runner_os": os.environ.get("RUNNER_OS", platform.system()),
        "runner_arch": os.environ.get("RUNNER_ARCH", platform.machine()),
        "python": {
            "version": sys.version,
            "executable": sys.executable,
            "implementation": platform.python_implementation(),
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "processor": platform.processor(),
        },
        "packages": {
            "numpy": _package_version("numpy"),
            "pandas": _package_version("pandas"),
        },
    }


def profile_workload(args: argparse.Namespace) -> dict[str, Any]:
    args.output_dir.mkdir(parents=True, exist_ok=True)

    profiler = cProfile.Profile()
    tracemalloc.start()
    wall_start = time.perf_counter()
    process_start = time.process_time()
    started_utc = datetime.now(timezone.utc)

    profiler.enable()
    workload_result = run.run_workload(
        preset_name=args.preset,
        output_dir=args.output_dir / "workload",
        seed=args.seed,
        keep_workdir=args.keep_workdir,
    )
    profiler.disable()

    process_seconds = time.process_time() - process_start
    wall_seconds = time.perf_counter() - wall_start
    current_bytes, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    finished_utc = datetime.now(timezone.utc)

    stats_stream = io.StringIO()
    stats = pstats.Stats(profiler, stream=stats_stream).strip_dirs().sort_stats("cumulative")
    stats.print_stats(args.profile_limit)

    profile_txt = args.output_dir / "profile.txt"
    profile_txt.write_text(stats_stream.getvalue(), encoding="utf-8")
    profile_pstats = args.output_dir / "profile.pstats"
    profiler.dump_stats(str(profile_pstats))

    timing = {
        **_metadata(args.sample_id, args.preset, args.seed),
        "started_utc": started_utc.isoformat(),
        "finished_utc": finished_utc.isoformat(),
        "wall_seconds": wall_seconds,
        "process_seconds": process_seconds,
        "tracemalloc_current_mb": current_bytes / (1024 * 1024),
        "tracemalloc_peak_mb": peak_bytes / (1024 * 1024),
        "workload": workload_result,
        "artifacts": {
            "profile_txt": str(profile_txt),
            "profile_pstats": str(profile_pstats),
        },
    }

    timing_path = args.output_dir / "timing.json"
    timing_path.write_text(json.dumps(timing, indent=2, sort_keys=True), encoding="utf-8")

    print(json.dumps(timing, indent=2, sort_keys=True))
    return timing


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Profile synthetic run.py workload")
    parser.add_argument("--preset", choices=sorted(run.PRESETS), default="ci")
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts") / "sample-1")
    parser.add_argument("--sample-id", default=os.environ.get("GITHUB_RUN_NUMBER", "local-1"))
    parser.add_argument("--seed", type=int, default=618)
    parser.add_argument("--profile-limit", type=int, default=60)
    parser.add_argument("--keep-workdir", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> dict[str, Any]:
    return profile_workload(parse_args(argv))


if __name__ == "__main__":
    main()
