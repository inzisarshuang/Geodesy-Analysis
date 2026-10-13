"""Standalone baseline-network plotting without rerunning GAMMA."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from geodesy_analysis.common.paths import validate_within_root
from geodesy_analysis.insar.baseline import default_baseline_output, plot_baseline_network

from .plot_config import (
    BaselinePlotCase,
    load_baseline_plot_config,
    select_baseline_plot_case,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="geodesy-analysis-baseline-plot",
        description="Plot a temporal-perpendicular baseline network without GAMMA.",
    )
    parser.add_argument("baseline", nargs="?", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--case")
    parser.add_argument("--master-date", type=int)
    parser.add_argument("--orbit")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--title")
    parser.add_argument("--dpi", type=int)
    parser.add_argument("--figsize", nargs=2, type=float, metavar=("WIDTH", "HEIGHT"))
    parser.add_argument("--y-top-extra", type=float)
    parser.add_argument("--y-bottom-extra", type=float)
    parser.add_argument("--font-family")
    return parser


def _direct(options: argparse.Namespace) -> BaselinePlotCase:
    if options.baseline is None:
        raise ValueError("baseline is required when --config is not supplied")
    baseline = options.baseline.expanduser().resolve(strict=True)
    root = baseline.parent
    out_dir = (
        validate_within_root(options.out_dir, root, "plot output directory")
        if options.out_dir is not None
        else root
    )
    output = (
        validate_within_root(options.out, root, "plot output")
        if options.out is not None
        else Path(
            default_baseline_output(
                str(baseline), orbit=options.orbit or "", out_dir=str(out_dir)
            )
        ).resolve()
    )
    return BaselinePlotCase(
        name="direct",
        project_root=root,
        baseline=baseline,
        master_date=options.master_date,
        orbit=options.orbit or "",
        output=output,
        title=options.title or "Perpendicular Baselines History",
        dpi=options.dpi or 300,
        figsize=tuple(options.figsize or (10.5, 6.2)),
        y_top_extra=50.0 if options.y_top_extra is None else options.y_top_extra,
        y_bottom_extra=0.0 if options.y_bottom_extra is None else options.y_bottom_extra,
        font_family=options.font_family or "TeX Gyre Heros",
    )


def _configured(options: argparse.Namespace) -> BaselinePlotCase:
    case = select_baseline_plot_case(
        load_baseline_plot_config(options.config), options.case
    )
    baseline = (
        validate_within_root(
            options.baseline.expanduser().resolve(strict=True),
            case.project_root,
            "baseline",
        )
        if options.baseline is not None
        else case.baseline
    )
    out_dir = (
        validate_within_root(options.out_dir, case.project_root, "plot output directory")
        if options.out_dir is not None
        else case.output.parent
    )
    if options.out is not None:
        candidate = options.out.expanduser()
        output = validate_within_root(
            candidate if candidate.is_absolute() else out_dir / candidate,
            case.project_root,
            "plot output",
        )
    elif options.baseline is not None or options.orbit is not None or options.out_dir is not None:
        output = Path(
            default_baseline_output(
                str(baseline), orbit=options.orbit or case.orbit, out_dir=str(out_dir)
            )
        ).resolve()
    else:
        output = case.output
    return replace(
        case,
        baseline=baseline,
        master_date=options.master_date or case.master_date,
        orbit=case.orbit if options.orbit is None else options.orbit,
        output=output,
        title=case.title if options.title is None else options.title,
        dpi=case.dpi if options.dpi is None else options.dpi,
        figsize=case.figsize if options.figsize is None else tuple(options.figsize),
        y_top_extra=(
            case.y_top_extra if options.y_top_extra is None else options.y_top_extra
        ),
        y_bottom_extra=(
            case.y_bottom_extra
            if options.y_bottom_extra is None
            else options.y_bottom_extra
        ),
        font_family=(
            case.font_family if options.font_family is None else options.font_family
        ),
    )


def main(arguments: Sequence[str] | None = None) -> int:
    """Resolve one plot request and write its PNG."""

    options = _parser().parse_args(arguments)
    try:
        case = _configured(options) if options.config is not None else _direct(options)
        output = plot_baseline_network(
            baseline_file=str(case.baseline),
            master_date=case.master_date,
            out_file=str(case.output),
            title=case.title,
            dpi=case.dpi,
            figsize=case.figsize,
            y_top_extra=case.y_top_extra,
            y_bottom_extra=case.y_bottom_extra,
            font_family=case.font_family,
        )
    except (FileNotFoundError, OSError, TypeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    print(f"[baselineplot] wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
