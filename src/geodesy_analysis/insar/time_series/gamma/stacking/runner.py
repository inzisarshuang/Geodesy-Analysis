"""Transactional GAMMA stacking execution."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from geodesy_analysis.common.command import SubprocessCommandRunner
from geodesy_analysis.common.progress import emit_progress
from geodesy_analysis.common.reuse import ReuseState, classify_analysis_output
from geodesy_analysis.insar.common.gamma_quicklooks import require_nonempty_quicklook
from geodesy_analysis.insar.time_series.gamma.common import write_gamma_diff_tab
from geodesy_analysis.io import atomic_output_directories

from .models import GammaStackingPlan
from .publication import COMMAND_CONTRACT, gamma_stacking_input_signature

_TASK = "ANALYSIS_GAMMA_STACKING"


@dataclass(frozen=True)
class GammaStackingRunSummary:
    status: str
    pair_count: int
    output_dir: Path


def _portable(plan: GammaStackingPlan, path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(plan.case.project_root).as_posix()
    except ValueError:
        return resolved.as_posix()


def _failed(active: Path) -> Path:
    index = 1
    while True:
        candidate = active.with_name(f"{active.name}.failed-logs-{index}")
        if not candidate.exists():
            return candidate
        index += 1


def _begin_logs(active: Path) -> None:
    active.parent.mkdir(parents=True, exist_ok=True)
    if active.exists() or active.is_symlink():
        os.replace(active, _failed(active))
    active.mkdir()


def _call(delegate, command, *, cwd: Path, log_dir: Path, stem: str) -> None:
    delegate.run(
        command,
        cwd=cwd,
        stdin_text=None,
        stdout_path=log_dir / f"{stem}.stdout.log",
        stderr_path=log_dir / f"{stem}.stderr.log",
    )


def _validate(path: Path, count: int, label: str) -> None:
    if path.is_symlink() or not path.is_file() or path.stat().st_size != count * 4:
        raise ValueError(f"{label} is missing or has the wrong byte size: {path}")
    values = np.memmap(path, dtype=">f4", mode="r")
    valid = bool(np.all(np.isfinite(values)))
    del values
    if not valid:
        raise ValueError(f"{label} contains non-finite values: {path}")


def _quicklook_command(
    plan: GammaStackingPlan,
    data: Path,
    background: Path,
    width: int,
    output: Path,
) -> tuple[str, ...]:
    return (
        "rasdt_pwr",
        str(data),
        str(background),
        str(width),
        "-",
        "-",
        "-",
        "-",
        f"{plan.case.display_min:g}",
        f"{plan.case.display_max:g}",
        "0",
        plan.case.colormap,
        str(output),
    )


def _render(
    plan: GammaStackingPlan,
    *,
    data: Path,
    background: Path,
    width: int,
    output: Path,
    delegate,
    stem: str,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    _call(
        delegate,
        _quicklook_command(plan, data, background, width, output),
        cwd=output.parent,
        log_dir=plan.case.log_dir,
        stem=stem,
    )
    require_nonempty_quicklook(output, stem)


def run_gamma_stacking(
    plan: GammaStackingPlan,
    *,
    command_runner=None,
    progress_sink: Callable[[str], object] | None = None,
) -> GammaStackingRunSummary:
    if not isinstance(plan, GammaStackingPlan):
        raise TypeError("plan must be GammaStackingPlan")
    sink = progress_sink or print
    delegate = command_runner or SubprocessCommandRunner()
    signature = gamma_stacking_input_signature(plan)
    reuse = classify_analysis_output(
        plan.case.output_dir,
        "timeseries_manifest.json",
        signature,
        project_root=plan.case.project_root,
    )
    reference_mli = next(
        asset for asset in plan.inputs.mli_assets if asset.date == plan.inputs.reference_date
    )
    radar_figure = plan.case.figure_dir / "mean_los_velocity.radar.bmp"
    geo_figure = plan.case.figure_dir / "mean_los_velocity.geo.bmp"
    if reuse.science_reusable:
        manifest = reuse.manifest or {}
        if (
            manifest.get("method") != "gamma_stacking"
            or manifest.get("case_id") != plan.case.case_id
            or manifest.get("atmosphere_manifest_digest")
            != plan.inputs.atmosphere_manifest_digest
        ):
            raise RuntimeError("stacking manifest identity is inconsistent")
        if reuse.state is ReuseState.FIGURES_MISSING:
            _begin_logs(plan.case.log_dir)
            if not radar_figure.is_file():
                _render(
                    plan,
                    data=plan.case.output_dir / "mean_los_velocity",
                    background=reference_mli.data,
                    width=plan.inputs.width,
                    output=radar_figure,
                    delegate=delegate,
                    stem="mean_velocity.radar",
                )
            if not geo_figure.is_file():
                _render(
                    plan,
                    data=plan.case.output_dir / "mean_los_velocity.geo",
                    background=plan.case.output_dir / "reference_mli.geo",
                    width=plan.inputs.map_width,
                    output=geo_figure,
                    delegate=delegate,
                    stem="mean_velocity.geo",
                )
            status = "figures_repaired"
        else:
            status = "skipped"
        sink(
            emit_progress(
                task=_TASK,
                event="batch_finished",
                status=status,
                stage="reuse",
                total=len(plan.inputs.pairs),
            )
        )
        return GammaStackingRunSummary(status, len(plan.inputs.pairs), plan.case.output_dir)
    if reuse.state is not ReuseState.ABSENT:
        raise RuntimeError(reuse.guidance)
    if plan.case.figure_dir.exists() or plan.case.figure_dir.is_symlink():
        raise RuntimeError("stacking science is absent but figure output already exists")
    _begin_logs(plan.case.log_dir)
    try:
        with atomic_output_directories(
            plan.case.figure_dir, plan.case.output_dir
        ) as (figure_staging, staging):
            diff_tab = write_gamma_diff_tab(plan.inputs, staging / "diff_tab")
            mean_phase = staging / "mean_phase_rate"
            sigma_rate = staging / "sigma_phase_rate"
            sigma_phase = staging / "sigma_phase"
            mean_velocity = staging / "mean_los_velocity"
            reference_geo = staging / "reference_mli.geo"
            velocity_geo = staging / "mean_los_velocity.geo"
            _call(
                delegate,
                (
                    "stacking",
                    str(diff_tab),
                    str(plan.inputs.width),
                    str(mean_phase),
                    str(sigma_rate),
                    str(sigma_phase),
                    str(plan.case.reference_range),
                    str(plan.case.reference_azimuth),
                    str(plan.case.reference_width),
                    str(plan.case.reference_height),
                    "-",
                    "1",
                ),
                cwd=staging,
                log_dir=plan.case.log_dir,
                stem="stacking",
            )
            for path, label in (
                (mean_phase, "mean phase rate"),
                (sigma_rate, "phase-rate uncertainty"),
                (sigma_phase, "phase uncertainty"),
            ):
                _validate(path, plan.inputs.width * plan.inputs.lines, label)
            _call(
                delegate,
                (
                    "dispmap",
                    str(mean_phase),
                    str(plan.inputs.radar_height),
                    str(reference_mli.parameter),
                    "-",
                    str(mean_velocity),
                    "0",
                    "0",
                ),
                cwd=staging,
                log_dir=plan.case.log_dir,
                stem="dispmap",
            )
            _validate(
                mean_velocity,
                plan.inputs.width * plan.inputs.lines,
                "mean LOS velocity",
            )
            for source, output, stem in (
                (reference_mli.data, reference_geo, "reference_mli"),
                (mean_velocity, velocity_geo, "mean_velocity"),
            ):
                _call(
                    delegate,
                    (
                        "geocode_back",
                        str(source),
                        str(plan.inputs.width),
                        str(plan.inputs.lookup_table),
                        str(output),
                        str(plan.inputs.map_width),
                        "0",
                        "1",
                        "0",
                        "1",
                        "1",
                        "5",
                    ),
                    cwd=staging,
                    log_dir=plan.case.log_dir,
                    stem=f"geocode.{stem}",
                )
                _validate(
                    output,
                    plan.inputs.map_width * plan.inputs.map_lines,
                    f"geocoded {stem}",
                )
            _render(
                plan,
                data=mean_velocity,
                background=reference_mli.data,
                width=plan.inputs.width,
                output=figure_staging / radar_figure.name,
                delegate=delegate,
                stem="mean_velocity.radar",
            )
            _render(
                plan,
                data=velocity_geo,
                background=reference_geo,
                width=plan.inputs.map_width,
                output=figure_staging / geo_figure.name,
                delegate=delegate,
                stem="mean_velocity.geo",
            )
            products = {
                "mean_phase_rate": {
                    "path": mean_phase.name,
                    "quantity": "phase_rate",
                    "units": "radian/day",
                },
                "phase_rate_uncertainty": {
                    "path": sigma_rate.name,
                    "quantity": "phase_rate_uncertainty",
                    "units": "radian/day",
                },
                "phase_uncertainty": {
                    "path": sigma_phase.name,
                    "quantity": "phase_uncertainty",
                    "units": "radian",
                },
                "mean_los_velocity": {
                    "path": mean_velocity.name,
                    "quantity": "los_velocity",
                    "units": "meter/day",
                },
                "mean_los_velocity_geocoded": {
                    "path": velocity_geo.name,
                    "quantity": "los_velocity",
                    "units": "meter/day",
                },
                "reference_mli_geocoded": {
                    "path": reference_geo.name,
                    "quantity": "intensity",
                    "units": "power",
                },
            }
            manifest: dict[str, object] = {
                "atmosphere_manifest_digest": plan.inputs.atmosphere_manifest_digest,
                "atmosphere_manifest_project_path": _portable(
                    plan, plan.inputs.atmosphere_manifest
                ),
                "case_id": plan.case.case_id,
                "figures_dir_project_path": _portable(plan, plan.case.figure_dir),
                "grid": {"lines": plan.inputs.lines, "width": plan.inputs.width},
                "input_signature": signature,
                "map_grid": {
                    "lines": plan.inputs.map_lines,
                    "width": plan.inputs.map_width,
                },
                "method": "gamma_stacking",
                "pair_count": len(plan.inputs.pairs),
                "pairs": [
                    {
                        "pair": pair.name,
                        "perpendicular_baseline": pair.perpendicular_baseline,
                        "temporal_baseline_days": pair.temporal_baseline_days,
                    }
                    for pair in plan.inputs.pairs
                ],
                "products": products,
                "provenance_path": "provenance.json",
                "reference_window": {
                    "range": plan.case.reference_range,
                    "azimuth": plan.case.reference_azimuth,
                    "width": plan.case.reference_width,
                    "height": plan.case.reference_height,
                },
                "schema_version": 2,
                "status": "complete",
            }
            manifest["scientific_manifest_digest"] = hashlib.sha256(
                (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
            ).hexdigest()
            manifest["required_products"] = [
                "diff_tab",
                *[value["path"] for value in products.values()],
                "provenance.json",
            ]
            manifest["figures"] = [
                Path(os.path.relpath(path, start=plan.case.output_dir)).as_posix()
                for path in (radar_figure, geo_figure)
            ]
            provenance = {
                "case_id": plan.case.case_id,
                "commands": list(COMMAND_CONTRACT),
                "input_signature": signature,
                "log_dir_project_path": _portable(plan, plan.case.log_dir),
                "schema_version": 2,
            }
            (staging / "provenance.json").write_text(
                json.dumps(provenance, sort_keys=True, indent=2) + "\n"
            )
            (staging / "timeseries_manifest.json").write_text(
                json.dumps(manifest, sort_keys=True, indent=2) + "\n"
            )
        sink(
            emit_progress(
                task=_TASK,
                event="batch_finished",
                status="complete",
                stage="publish",
                total=len(plan.inputs.pairs),
            )
        )
        return GammaStackingRunSummary(
            "complete", len(plan.inputs.pairs), plan.case.output_dir
        )
    except BaseException:
        failed = _failed(plan.case.log_dir)
        if plan.case.log_dir.exists() or plan.case.log_dir.is_symlink():
            os.replace(plan.case.log_dir, failed)
        raise


__all__ = ["GammaStackingRunSummary", "run_gamma_stacking"]
