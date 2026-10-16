"""CFG-driven command-line entry for manifest-driven InSAR filtering."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from geodesy_analysis.common.progress import ConsoleProgress

from .config import load_filtering_config, select_filtering_case
from .plan import build_filtering_plan
from .runner import run_filtering


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="geodesy-analysis-filtering",
        description="Filter manifest-declared interferograms with NL-InSAR, GAMMA BM3D, or GAMMA ADF.",
    )
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--case", help="run one [case:name]; omit to run all configured cases")
    parser.add_argument("--dry-run", action="store_true", help="validate and print plans only")
    return parser


def _summary(plan) -> dict[str, object]:
    return {
        "case": plan.case.name,
        "case_id": plan.case.case_id,
        "grid": {"lines": plan.lines, "width": plan.width},
        "interferogram_manifest": str(plan.manifest.source_path),
        "method": plan.case.method.value,
        "output_dir": str(plan.case.output_dir),
        "pair_count": len(plan.pairs),
    }


def main(arguments: Sequence[str] | None = None) -> int:
    options = _parser().parse_args(arguments)
    try:
        configured = load_filtering_config(options.config)
        selected = (
            (select_filtering_case(configured, options.case),)
            if options.case is not None
            else configured
        )
        plans = tuple(build_filtering_plan(case) for case in selected)
    except (FileNotFoundError, OSError, TypeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    if options.dry_run:
        payload: object = _summary(plans[0]) if len(plans) == 1 else [_summary(plan) for plan in plans]
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    try:
        sink = print if os.environ.get("GEODESY_PROGRESS_PROTOCOL") == "1" else ConsoleProgress()
        for plan in plans:
            run_filtering(plan, progress_sink=sink)
    except KeyboardInterrupt:
        print("ERROR: filtering interrupted", file=sys.stderr)
        return 130
    except (FileNotFoundError, FileExistsError, OSError, RuntimeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
