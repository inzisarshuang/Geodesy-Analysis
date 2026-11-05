"""CFG-driven CLI for GAMMA quad phase detrending."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from geodesy_analysis.common.progress import ConsoleProgress

from .config import load_gamma_quad_detrend_config
from .plan import build_gamma_quad_detrend_plan
from .runner import run_gamma_quad_detrend


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="geodesy-analysis-gamma-quad-detrend",
        description="Remove spatial phase trends from GAMMA MCF products.",
    )
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--case", help="run one [case:name]; omit to run all cases")
    parser.add_argument("--dry-run", action="store_true", help="validate and print plans only")
    return parser


def _summary(plan) -> dict[str, object]:
    return {
        "available_pair_count": plan.available_pair_count,
        "case": plan.case.name,
        "case_id": plan.case.case_id,
        "coherence_threshold": plan.case.coherence_threshold,
        "filtering_manifest": str(plan.filtering_manifest),
        "grid": {"lines": plan.lines, "width": plan.width},
        "intensity_background": plan.case.intensity_background,
        "method": "gamma_quad_detrending",
        "output_dir": str(plan.case.output_dir),
        "pair_count": len(plan.pairs),
        "pair_list": None if plan.case.pair_list is None else str(plan.case.pair_list),
        "pairs": [pair.name for pair in plan.pairs],
        "trend_model": plan.case.trend_model,
        "unwrapping_manifest": str(plan.case.unwrapping_manifest),
        "visualization_dir": str(plan.case.visualization_dir),
    }


def main(arguments: Sequence[str] | None = None) -> int:
    options = _parser().parse_args(arguments)
    try:
        cases = load_gamma_quad_detrend_config(options.config, case_name=options.case)
        plans = tuple(build_gamma_quad_detrend_plan(case) for case in cases)
    except (FileNotFoundError, OSError, TypeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    if options.dry_run:
        payload: object = (
            _summary(plans[0]) if len(plans) == 1 else [_summary(plan) for plan in plans]
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    try:
        sink = print if os.environ.get("GEODESY_PROGRESS_PROTOCOL") == "1" else ConsoleProgress()
        for plan in plans:
            run_gamma_quad_detrend(plan, progress_sink=sink)
    except KeyboardInterrupt:
        print("ERROR: GAMMA quad detrending interrupted", file=sys.stderr)
        return 130
    except (FileNotFoundError, FileExistsError, OSError, RuntimeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
