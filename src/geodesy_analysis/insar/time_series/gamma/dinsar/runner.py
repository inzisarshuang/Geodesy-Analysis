"""Transactional single-pair GAMMA DInSAR execution."""

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
from geodesy_analysis.io import atomic_output_directories

from .models import GammaDinsarPlan
from .publication import gamma_dinsar_input_signature

_TASK = "ANALYSIS_GAMMA_DINSAR"


@dataclass(frozen=True)
class GammaDinsarRunSummary:
    status: str
    pair: str
    output_dir: Path


def _portable(plan: GammaDinsarPlan, path: Path) -> str:
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


def _render(
    plan: GammaDinsarPlan,
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
        (
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
        ),
        cwd=output.parent,
        log_dir=plan.case.log_dir,
        stem=stem,
    )
    require_nonempty_quicklook(output, stem)


def run_gamma_dinsar(
    plan: GammaDinsarPlan,
    *,
    command_runner=None,
    progress_sink: Callable[[str], object] | None = None,
) -> GammaDinsarRunSummary:
    if not isinstance(plan, GammaDinsarPlan):
        raise TypeError("plan must be GammaDinsarPlan")
    sink = progress_sink or print
    delegate = command_runner or SubprocessCommandRunner()
    signature = gamma_dinsar_input_signature(plan)
    reference_mli = next(
        asset for asset in plan.inputs.mli_assets if asset.date == plan.inputs.reference_date
    )
    radar_name = "cumulative_los_displacement"
    geo_name = "cumulative_los_displacement.geo"
    reference_geo_name = "reference_mli.geo"
    radar_figure = plan.case.figure_dir / f"{radar_name}.radar.bmp"
    geo_figure = plan.case.figure_dir / f"{radar_name}.geo.bmp"
    reuse = classify_analysis_output(
        plan.case.output_dir,
        "timeseries_manifest.json",
        signature,
        project_root=plan.case.project_root,
    )
    if reuse.science_reusable:
        manifest = reuse.manifest or {}
        if (
            manifest.get("method") != "gamma_dinsar"
            or manifest.get("case_id") != plan.case.case_id
            or manifest.get("pair") != plan.pair.name
        ):
            raise RuntimeError("DInSAR manifest identity is inconsistent")
        if reuse.state is ReuseState.FIGURES_MISSING:
            _begin_logs(plan.case.log_dir)
            if not radar_figure.is_file():
                _render(
                    plan,
                    data=plan.case.output_dir / radar_name,
                    background=reference_mli.data,
                    width=plan.inputs.width,
                    output=radar_figure,
                    delegate=delegate,
                    stem="cumulative.radar",
                )
            if not geo_figure.is_file():
                _render(
                    plan,
                    data=plan.case.output_dir / geo_name,
                    background=plan.case.output_dir / reference_geo_name,
                    width=plan.inputs.map_width,
                    output=geo_figure,
                    delegate=delegate,
                    stem="cumulative.geo",
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
                total=1,
            )
        )
        return GammaDinsarRunSummary(status, plan.pair.name, plan.case.output_dir)
    if reuse.state is not ReuseState.ABSENT:
        raise RuntimeError(reuse.guidance)
    if plan.case.figure_dir.exists() or plan.case.figure_dir.is_symlink():
        raise RuntimeError("DInSAR science is absent but figure output already exists")
    _begin_logs(plan.case.log_dir)
    try:
        with atomic_output_directories(
            plan.case.figure_dir, plan.case.output_dir
        ) as (figure_staging, staging):
            radar = staging / radar_name
            geocoded = staging / geo_name
            reference_geo = staging / reference_geo_name
            _call(
                delegate,
                (
                    "dispmap",
                    str(plan.pair.corrected_phase),
                    str(plan.inputs.radar_height),
                    str(reference_mli.parameter),
                    "-",
                    str(radar),
                    "0",
                    "0",
                ),
                cwd=staging,
                log_dir=plan.case.log_dir,
                stem="dispmap",
            )
            _validate(radar, plan.inputs.width * plan.inputs.lines, "cumulative LOS displacement")
            for source, output, stem in (
                (reference_mli.data, reference_geo, "reference_mli"),
                (radar, geocoded, "cumulative_displacement"),
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
                data=radar,
                background=reference_mli.data,
                width=plan.inputs.width,
                output=figure_staging / radar_figure.name,
                delegate=delegate,
                stem="cumulative.radar",
            )
            _render(
                plan,
                data=geocoded,
                background=reference_geo,
                width=plan.inputs.map_width,
                output=figure_staging / geo_figure.name,
                delegate=delegate,
                stem="cumulative.geo",
            )
            products = {
                "radar": {
                    "path": radar.name,
                    "quantity": "cumulative_los_displacement",
                    "units": "meter",
                },
                "geocoded": {
                    "path": geocoded.name,
                    "quantity": "cumulative_los_displacement",
                    "units": "meter",
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
                "deformation_quantity": "cumulative_displacement",
                "figures_dir_project_path": _portable(plan, plan.case.figure_dir),
                "grid": {"lines": plan.inputs.lines, "width": plan.inputs.width},
                "input_signature": signature,
                "map_grid": {
                    "lines": plan.inputs.map_lines,
                    "width": plan.inputs.map_width,
                },
                "method": "gamma_dinsar",
                "pair": plan.pair.name,
                "perpendicular_baseline": plan.pair.perpendicular_baseline,
                "products": products,
                "provenance_path": "provenance.json",
                "schema_version": 2,
                "status": "complete",
                "temporal_baseline_days": plan.pair.temporal_baseline_days,
            }
            manifest["scientific_manifest_digest"] = hashlib.sha256(
                (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
            ).hexdigest()
            manifest["required_products"] = [
                *[item["path"] for item in products.values()],
                "provenance.json",
            ]
            manifest["figures"] = [
                Path(os.path.relpath(path, start=plan.case.output_dir)).as_posix()
                for path in (radar_figure, geo_figure)
            ]
            provenance = {
                "case_id": plan.case.case_id,
                "command_contract": ["dispmap", "geocode_back", "rasdt_pwr"],
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
                total=1,
            )
        )
        return GammaDinsarRunSummary("complete", plan.pair.name, plan.case.output_dir)
    except BaseException:
        failed = _failed(plan.case.log_dir)
        if plan.case.log_dir.exists() or plan.case.log_dir.is_symlink():
            os.replace(plan.case.log_dir, failed)
        raise


__all__ = ["GammaDinsarRunSummary", "run_gamma_dinsar"]
