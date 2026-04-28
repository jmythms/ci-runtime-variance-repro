#!/usr/bin/env python3
"""Summarize timing artifacts from local runs or GitHub Actions downloads."""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any


def _find_timing_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_file() and path.name == "timing.json":
            files.append(path)
        elif path.is_dir():
            files.extend(path.rglob("timing.json"))
    return sorted(files)


def _load_timing(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    data["_path"] = str(path)
    return data


def _fmt(value: float) -> str:
    return f"{value:.2f}"


def summarize(paths: list[Path]) -> str:
    timing_files = _find_timing_files(paths)
    if not timing_files:
        raise SystemExit("No timing.json files found")

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for timing_file in timing_files:
        timing = _load_timing(timing_file)
        groups[timing.get("commit_sha", "unknown")].append(timing)

    lines = [
        "# Runtime Summary",
        "",
        f"Found {len(timing_files)} timing artifact(s).",
        "",
        "| Commit | Samples | Min s | Median s | Mean s | Stddev s | Max s | Spread % |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for commit, entries in sorted(groups.items()):
        values = sorted(float(entry["wall_seconds"]) for entry in entries)
        mean = statistics.fmean(values)
        median = statistics.median(values)
        stddev = statistics.stdev(values) if len(values) > 1 else 0.0
        spread = ((max(values) - min(values)) / median * 100.0) if median else 0.0
        lines.append(
            "| {commit} | {samples} | {min_s} | {median_s} | {mean_s} | {stddev_s} | {max_s} | {spread} |".format(
                commit=commit[:12],
                samples=len(values),
                min_s=_fmt(min(values)),
                median_s=_fmt(median),
                mean_s=_fmt(mean),
                stddev_s=_fmt(stddev),
                max_s=_fmt(max(values)),
                spread=_fmt(spread),
            )
        )

    lines.extend(["", "## Raw Samples", ""])

    for commit, entries in sorted(groups.items()):
        lines.append(f"### {commit}")
        lines.append("")
        lines.append("| Sample | Wall s | Process s | Runner | Artifact |")
        lines.append("|---|---:|---:|---|---|")
        for entry in sorted(entries, key=lambda item: str(item.get("sample_id", ""))):
            runner = entry.get("runner_os") or entry.get("platform", {}).get("system", "")
            lines.append(
                "| {sample} | {wall} | {process} | {runner} | {artifact} |".format(
                    sample=entry.get("sample_id", ""),
                    wall=_fmt(float(entry["wall_seconds"])),
                    process=_fmt(float(entry["process_seconds"])),
                    runner=runner,
                    artifact=entry.get("_path", ""),
                )
            )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize runtime timing artifacts")
    parser.add_argument("paths", nargs="+", type=Path, help="Artifact directories or timing.json files")
    parser.add_argument("--output", type=Path, help="Optional Markdown output path")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> str:
    args = parse_args(argv)
    markdown = summarize(args.paths)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(markdown, encoding="utf-8")
    print(markdown)
    return markdown


if __name__ == "__main__":
    main()
