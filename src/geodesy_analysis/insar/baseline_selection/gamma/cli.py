"""CFG-driven command-line entry for GAMMA baseline selection."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from geodesy_analysis.common.progress import ConsoleProgress

from .config import load_gamma_baseline_config, select_gamma_baseline_case
from .plan import build_gamma_baseline_plan
from .runner import run_gamma_baseline


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="geodesy-analysis-gamma-baseline",
        description="Build a GAMMA DSI, SBAS, or PSI baseline network.",
    )
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--case")
    parser.add_argument(
        "--dry-run", action="store_true", help="validate and print the plan only"
    )
    return parser


def main(arguments: Sequence[str] | None = None) -> int:
    """Validate or execute one configured GAMMA baseline case."""

    options = _parser().parse_args(arguments)
    try:
        case = select_gamma_baseline_case(
            load_gamma_baseline_config(options.config), options.case
        )
        plan = build_gamma_baseline_plan(case)
    except (FileNotFoundError, OSError, TypeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    if options.dry_run:
        print(
            json.dumps(
                {
                    "case": case.name,
                    "expected_network": plan.expected_network_name,
                    "max_perpendicular_baseline_m": case.max_perpendicular_baseline,
                    "max_temporal_baseline_days": case.max_temporal_baseline,
                    "network_type": case.network_type,
                    "output_dir": str(case.output_dir),
                    "polarization": case.polarization,
                    "reference_date": plan.stack.reference_date,
                    "registered_stack": str(case.registered_stack),
                    "scene_count": len(plan.stack.assets),
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    try:
        sink = print if os.environ.get("GEODESY_PROGRESS_PROTOCOL") == "1" else ConsoleProgress()
        run_gamma_baseline(plan, progress_sink=sink)
    except KeyboardInterrupt:
        print("ERROR: GAMMA baseline selection interrupted", file=sys.stderr)
        return 130
    except (FileNotFoundError, FileExistsError, OSError, RuntimeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
