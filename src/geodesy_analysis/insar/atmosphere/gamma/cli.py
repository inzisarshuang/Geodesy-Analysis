"""CFG-driven CLI for GAMMA atmospheric phase correction."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from geodesy_analysis.common.progress import ConsoleProgress

from .config import load_gamma_atmosphere_config
from .plan import build_gamma_atmosphere_plan
from .runner import run_gamma_atmosphere


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="geodesy-analysis-gamma-atmosphere",
        description="Apply a manifest-driven GAMMA atmosphere method.",
    )
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--case", help="run one [case:name]; omit to run all")
    parser.add_argument(
        "--dry-run", action="store_true", help="validate and print plans only"
    )
    return parser


def _summary(plan) -> dict[str, object]:
    return {
        "auto_mask": str(plan.auto_mask),
        "case": plan.case.name,
        "case_id": plan.case.case_id,
        "detrending_manifest": str(plan.case.detrending_manifest),
        "figure_dir": str(plan.case.figure_dir),
        "filtering_manifest": str(plan.filtering_manifest),
        "grid": {"lines": plan.lines, "width": plan.width},
        "interferogram_manifest": str(plan.interferogram_manifest),
        "log_dir": str(plan.case.log_dir),
        "method": plan.case.method,
        "output_dir": str(plan.case.output_dir),
        "pair_count": len(plan.pairs),
        "pairs": [pair.name for pair in plan.pairs],
        "polygon_file": (
            None
            if plan.case.polygon_file is None
            else str(plan.case.polygon_file)
        ),
        "radar_height": str(plan.radar_height),
        "unwrapping_manifest": str(plan.unwrapping_manifest),
    }


def main(arguments: Sequence[str] | None = None) -> int:
    options = _parser().parse_args(arguments)
    try:
        cases = load_gamma_atmosphere_config(
            options.config, case_name=options.case
        )
        plans = tuple(build_gamma_atmosphere_plan(case) for case in cases)
    except (FileNotFoundError, OSError, TypeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    if options.dry_run:
        payload: object = (
            _summary(plans[0])
            if len(plans) == 1
            else [_summary(plan) for plan in plans]
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    try:
        sink = (
            print
            if os.environ.get("GEODESY_PROGRESS_PROTOCOL") == "1"
            else ConsoleProgress()
        )
        for plan in plans:
            run_gamma_atmosphere(plan, progress_sink=sink)
    except KeyboardInterrupt:
        print("ERROR: GAMMA atmosphere correction interrupted", file=sys.stderr)
        return 130
    except (
        FileNotFoundError,
        FileExistsError,
        OSError,
        RuntimeError,
        ValueError,
    ) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
