"""CLI for single-pair GAMMA DInSAR."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from geodesy_analysis.common.progress import ConsoleProgress

from .config import load_gamma_dinsar_config
from .plan import build_gamma_dinsar_plan
from .runner import run_gamma_dinsar


def _summary(plan) -> dict[str, object]:
    return {
        "atmosphere_manifest": str(plan.inputs.atmosphere_manifest),
        "case": plan.case.name,
        "case_id": plan.case.case_id,
        "deformation_quantity": "cumulative_displacement",
        "figure_dir": str(plan.case.figure_dir),
        "grid": {"lines": plan.inputs.lines, "width": plan.inputs.width},
        "log_dir": str(plan.case.log_dir),
        "method": "gamma_dinsar",
        "output_dir": str(plan.case.output_dir),
        "pair": plan.pair.name,
    }


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="geodesy-analysis-gamma-dinsar")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--case")
    parser.add_argument("--dry-run", action="store_true")
    options = parser.parse_args(arguments)
    try:
        plans = tuple(
            build_gamma_dinsar_plan(case)
            for case in load_gamma_dinsar_config(options.config, case_name=options.case)
        )
    except (FileNotFoundError, OSError, TypeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    if options.dry_run:
        payload = _summary(plans[0]) if len(plans) == 1 else [_summary(plan) for plan in plans]
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    try:
        sink = print if os.environ.get("GEODESY_PROGRESS_PROTOCOL") == "1" else ConsoleProgress()
        for plan in plans:
            run_gamma_dinsar(plan, progress_sink=sink)
    except KeyboardInterrupt:
        return 130
    except (FileNotFoundError, FileExistsError, OSError, RuntimeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
