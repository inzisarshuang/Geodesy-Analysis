"""CFG-driven command-line entry for GAMMA interferogram generation."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from geodesy_analysis.common.progress import ConsoleProgress

from .config import load_gamma_interferogram_config, select_gamma_interferogram_case
from .plan import build_gamma_interferogram_plan
from .runner import run_gamma_interferograms


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="geodesy-analysis-gamma-interferogram",
        description="Generate GAMMA MLI, differential interferograms, and coherence.",
    )
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--case")
    parser.add_argument(
        "--dry-run", action="store_true", help="validate and print the plan only"
    )
    return parser


def main(arguments: Sequence[str] | None = None) -> int:
    """Validate or execute one configured GAMMA interferogram case."""

    options = _parser().parse_args(arguments)
    try:
        case = select_gamma_interferogram_case(
            load_gamma_interferogram_config(options.config), options.case
        )
        plan = build_gamma_interferogram_plan(case)
    except (FileNotFoundError, OSError, TypeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    if options.dry_run:
        print(
            json.dumps(
                {
                    "baseline_manifest": str(case.baseline_manifest),
                    "case": case.name,
                    "case_id": case.case_id,
                    "looks": {"azimuth": case.azimuth_looks, "range": case.range_looks},
                    "output_dir": str(case.output_dir),
                    "pair_count": len(plan.pairs),
                    "polarization": case.polarization,
                    "radar_height": str(case.radar_height),
                    "reference_date": plan.stack.reference_date,
                    "registered_stack": str(case.registered_stack),
                    "resolved_filter_flags": {
                        "azimuth": plan.spectral_filter_azimuth,
                        "range": plan.spectral_filter_range,
                    },
                    "scene_count": len(plan.stack.assets),
                    "spectral_filter": case.spectral_filter,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    try:
        sink = print if os.environ.get("GEODESY_PROGRESS_PROTOCOL") == "1" else ConsoleProgress()
        run_gamma_interferograms(plan, progress_sink=sink)
    except KeyboardInterrupt:
        print("ERROR: GAMMA interferogram generation interrupted", file=sys.stderr)
        return 130
    except (FileNotFoundError, FileExistsError, OSError, RuntimeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
