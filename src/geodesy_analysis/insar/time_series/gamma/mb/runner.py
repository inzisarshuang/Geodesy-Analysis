"""Transactional GAMMA mb SBAS/ISBAS execution."""

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
from geodesy_analysis.insar.common.gamma_quicklooks import require_nonempty_quicklook
from geodesy_analysis.insar.time_series.gamma.common import (
    write_gamma_diff_tab,
    write_gamma_itab,
    write_gamma_rmli_tab,
)
from geodesy_analysis.io import atomic_replace_output_directories

from .models import GammaMbPlan
from .publication import COMMAND_CONTRACT, gamma_mb_input_signature

_TASK = "ANALYSIS_GAMMA_MB"


@dataclass(frozen=True)
class GammaMbRunSummary:
    status: str
    pair_count: int
    epoch_count: int
    output_dir: Path


def _portable(plan: GammaMbPlan, path: Path) -> str:
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


def _validate_float(path: Path, count: int, label: str) -> None:
    if path.is_symlink() or not path.is_file() or path.stat().st_size != count * 4:
        raise ValueError(f"{label} is missing or has the wrong byte size: {path}")
    values = np.memmap(path, dtype=">f4", mode="r")
    valid = bool(np.all(np.isfinite(values)))
    del values
    if not valid:
        raise ValueError(f"{label} contains non-finite values: {path}")


def _table_products(
    table: Path,
    *,
    root: Path,
    expected: int,
    count: int,
    label: str,
) -> tuple[Path, ...]:
    if table.is_symlink() or not table.is_file() or table.stat().st_size < 1:
        raise ValueError(f"{label} table is missing: {table}")
    products: list[Path] = []
    for line_number, raw in enumerate(table.read_text().splitlines(), 1):
        value = raw.split()
        if not value:
            continue
        path = Path(value[0])
        if not path.is_absolute():
            path = table.parent / path
        path = path.resolve()
        try:
            path.relative_to(root.resolve())
        except ValueError as error:
            raise ValueError(f"{label} table entry leaves output on line {line_number}") from error
        _validate_float(path, count, f"{label} epoch")
        products.append(path)
    if len(products) != expected or len(set(products)) != len(products):
        raise ValueError(f"{label} epoch count is inconsistent")
    return tuple(products)


def _render(
    plan: GammaMbPlan,
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


def _rel(root: Path, paths: tuple[Path, ...] | list[Path]) -> list[str]:
    return [path.relative_to(root).as_posix() for path in paths]


def run_gamma_mb(
    plan: GammaMbPlan,
    *,
    command_runner=None,
    progress_sink: Callable[[str], object] | None = None,
) -> GammaMbRunSummary:
    if not isinstance(plan, GammaMbPlan):
        raise TypeError("plan must be GammaMbPlan")
    sink = progress_sink or print
    environment = None
    if plan.case.visdt_pwr is not None:
        environment = dict(os.environ)
        current_path = environment.get("PATH", "")
        environment["PATH"] = os.pathsep.join(
            value
            for value in (str(plan.case.visdt_pwr.parent), current_path)
            if value
        )
    delegate = command_runner or SubprocessCommandRunner(environment=environment)
    signature = gamma_mb_input_signature(plan)
    reference_mli = next(
        asset for asset in plan.inputs.mli_assets if asset.date == plan.inputs.reference_date
    )
    radar_figure = plan.case.figure_dir / "mean_los_velocity.radar.bmp"
    geo_figure = plan.case.figure_dir / "mean_los_velocity.geo.bmp"
    _begin_logs(plan.case.log_dir)
    try:
        with atomic_replace_output_directories(
            plan.case.figure_dir, plan.case.output_dir
        ) as (figure_staging, staging):
            intermediate = staging / "INTERMEDIATE"
            intermediate.mkdir()
            diff_tab = write_gamma_diff_tab(plan.inputs, staging / "diff_tab")
            rmli_tab = write_gamma_rmli_tab(plan.inputs, staging / "RMLI_tab")
            itab = write_gamma_itab(plan.inputs, staging / "itab")
            itab_ts = intermediate / "itab_ts"
            ts_prefix = intermediate / "TS"
            std_ts = intermediate / "STD_ts"
            hgt_res = staging / "height_residual"
            _call(
                delegate,
                (
                    "mb",
                    str(diff_tab),
                    str(rmli_tab),
                    str(itab),
                    "-",
                    str(itab_ts),
                    str(ts_prefix),
                    "1",
                    str(std_ts),
                    "1",
                    str(hgt_res),
                    str(plan.case.reference_range),
                    str(plan.case.reference_azimuth),
                    str(plan.case.reference_width),
                    str(plan.case.reference_height),
                    f"{plan.case.gamma:g}",
                    str(reference_mli.parameter),
                    "-",
                    str(plan.case.mb_mode),
                ),
                cwd=staging,
                log_dir=plan.case.log_dir,
                stem="mb",
            )
            if not itab_ts.is_file() or itab_ts.stat().st_size < 1:
                raise ValueError("mb did not create itab_ts")
            ts_tab = Path(f"{ts_prefix}.tab")
            ts_products = _table_products(
                ts_tab,
                root=staging,
                expected=len(plan.inputs.acquisition_dates),
                count=plan.inputs.width * plan.inputs.lines,
                label="mb time series",
            )
            _validate_float(std_ts, plan.inputs.width * plan.inputs.lines, "mb uncertainty")
            _validate_float(hgt_res, plan.inputs.width * plan.inputs.lines, "height residual")

            tpf_prefix = intermediate / "TS_tpf"
            tpf_tab = intermediate / "TS_tpf.tab"
            _call(
                delegate,
                (
                    "tpf_2d",
                    str(ts_tab),
                    str(rmli_tab),
                    str(itab_ts),
                    str(tpf_prefix),
                    str(tpf_tab),
                    "2",
                    f"{plan.case.dtmax:g}",
                    "2",
                ),
                cwd=staging,
                log_dir=plan.case.log_dir,
                stem="tpf_2d",
            )
            tpf_products = _table_products(
                tpf_tab,
                root=staging,
                expected=len(plan.inputs.acquisition_dates),
                count=plan.inputs.width * plan.inputs.lines,
                label="TPF time series",
            )
            mean_phase = staging / "mean_phase_rate"
            std_rate = intermediate / "STD_ts2"
            _call(
                delegate,
                (
                    "ts_rate",
                    str(tpf_tab),
                    str(rmli_tab),
                    str(itab_ts),
                    "-",
                    str(mean_phase),
                    "const",
                    str(std_rate),
                ),
                cwd=staging,
                log_dir=plan.case.log_dir,
                stem="ts_rate",
            )
            _validate_float(mean_phase, plan.inputs.width * plan.inputs.lines, "mean phase rate")
            _validate_float(std_rate, plan.inputs.width * plan.inputs.lines, "mean rate uncertainty")
            mean_velocity = staging / "mean_los_velocity"
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
            _validate_float(mean_velocity, plan.inputs.width * plan.inputs.lines, "mean LOS velocity")

            assert plan.inputs.final_mask is not None
            mask_float = staging / "final_mask.f32"
            mask_geo = staging / "final_mask.geo"
            _call(
                delegate,
                (
                    "uchar2float",
                    str(plan.inputs.final_mask),
                    str(mask_float),
                    "1.0",
                    "1.0",
                ),
                cwd=staging,
                log_dir=plan.case.log_dir,
                stem="mask.uchar2float",
            )
            _validate_float(mask_float, plan.inputs.width * plan.inputs.lines, "float final mask")
            _call(
                delegate,
                (
                    "geocode_back",
                    str(mask_float),
                    str(plan.inputs.width),
                    str(plan.inputs.lookup_table),
                    str(mask_geo),
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
                stem="mask.geocode",
            )
            _validate_float(mask_geo, plan.inputs.map_width * plan.inputs.map_lines, "geocoded final mask")

            reference_geo = staging / "reference_mli.geo"
            velocity_geo = staging / "mean_los_velocity.geo"
            if plan.case.generate_mean_geocoded:
                for source, output, stem in (
                    (reference_mli.data, reference_geo, "reference_mli"),
                    (mean_velocity, velocity_geo, "mean_velocity"),
                    (hgt_res, staging / "height_residual.geo", "height_residual"),
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
                        stem=f"mean.geocode.{stem}",
                    )
                    _validate_float(
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
            if plan.case.generate_mean_geocoded:
                _render(
                    plan,
                    data=velocity_geo,
                    background=reference_geo,
                    width=plan.inputs.map_width,
                    output=figure_staging / geo_figure.name,
                    delegate=delegate,
                    stem="mean_velocity.geo",
                )

            displacement_products: tuple[Path, ...] = ()
            geo_displacement_products: tuple[Path, ...] = ()
            displacement_tab: Path | None = None
            geo_displacement_tab: Path | None = None
            if plan.case.generate_displacement:
                displacement_dir = staging / "DISPLACEMENT"
                displacement_tab = displacement_dir / "displacement_tab"
                _call(
                    delegate,
                    (
                        "mk_dispmap_2d",
                        str(tpf_tab),
                        str(reference_mli.data),
                        str(reference_mli.parameter),
                        str(displacement_dir),
                        f"{plan.case.display_min:g}",
                        f"{plan.case.display_max:g}",
                        str(displacement_tab),
                        "0",
                        "-s",
                        "1",
                        "-e",
                        "0.4",
                        "-m",
                        plan.case.colormap,
                        "-z",
                        "1000",
                        "-D",
                        "0",
                        "-u",
                    ),
                    cwd=staging,
                    log_dir=plan.case.log_dir,
                    stem="mk_dispmap_2d",
                )
                displacement_products = _table_products(
                    displacement_tab,
                    root=staging,
                    expected=len(plan.inputs.acquisition_dates),
                    count=plan.inputs.width * plan.inputs.lines,
                    label="cumulative displacement",
                )
            if plan.case.generate_geocoded_displacement:
                assert displacement_tab is not None
                geo_dir = staging / "DISPLACEMENT_GEO"
                _call(
                    delegate,
                    (
                        "mk_geo_data_all",
                        str(reference_mli.parameter),
                        str(plan.inputs.map_dem_parameter),
                        str(plan.inputs.lookup_table),
                        str(displacement_tab),
                        str(geo_dir),
                        "1",
                        "0",
                        "-b",
                        f"{plan.case.display_min:g},{plan.case.display_max:g}",
                        "-s",
                        "1",
                        "-e",
                        "0.4",
                        "-c",
                        plan.case.colormap,
                        "-u",
                    ),
                    cwd=staging,
                    log_dir=plan.case.log_dir,
                    stem="mk_geo_data_all",
                )
                geo_displacement_products = tuple(
                    geo_dir / f"{source.stem}_geo{source.suffix}"
                    for source in displacement_products
                )
                for product in geo_displacement_products:
                    _validate_float(
                        product,
                        plan.inputs.map_width * plan.inputs.map_lines,
                        "geocoded cumulative displacement",
                    )
                geo_displacement_tab = geo_dir / "displacement_geo_tab"
                geo_displacement_tab.write_text(
                    "".join(f"{path.name}\n" for path in geo_displacement_products),
                    encoding="utf-8",
                )

            # GAMMA reads the original table during processing. Publish it with
            # paths relative to the table so the staging directory can be renamed.
            if displacement_tab is not None:
                records = (
                    line.split(maxsplit=1)
                    for line in displacement_tab.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                )
                displacement_tab.write_text(
                    "".join(
                        " ".join((os.path.relpath(path, displacement_tab.parent), *fields[1:]))
                        + "\n"
                        for path, fields in zip(displacement_products, records, strict=True)
                    ),
                    encoding="utf-8",
                )
            (staging / "images").write_text(
                "".join(f"{date}\n" for date in plan.inputs.acquisition_dates),
                encoding="utf-8",
            )

            mean_products = {
                "mean_phase_rate": {
                    "path": mean_phase.name,
                    "quantity": "phase_rate",
                    "units": "radian/year",
                },
                "mean_los_velocity": {
                    "path": mean_velocity.name,
                    "quantity": "los_velocity",
                    "units": "meter/year",
                },
                "height_residual": {
                    "path": hgt_res.name,
                    "quantity": "height_residual",
                    "units": "meter",
                },
                "final_mask_geocoded": {
                    "path": mask_geo.name,
                    "quantity": "valid_data_mask",
                    "units": "1",
                },
            }
            if plan.case.generate_mean_geocoded:
                mean_products["mean_los_velocity_geocoded"] = {
                    "path": velocity_geo.name,
                    "quantity": "los_velocity",
                    "units": "meter/year",
                }
                mean_products["reference_mli_geocoded"] = {
                    "path": reference_geo.name,
                    "quantity": "intensity",
                    "units": "power",
                }
                mean_products["height_residual_geocoded"] = {
                    "path": "height_residual.geo",
                    "quantity": "height_residual",
                    "units": "meter",
                }
            manifest: dict[str, object] = {
                "atmosphere_manifest_digest": plan.inputs.atmosphere_manifest_digest,
                "atmosphere_manifest_project_path": _portable(
                    plan, plan.inputs.atmosphere_manifest
                ),
                "case_id": plan.case.case_id,
                "displacement": {
                    "enabled": plan.case.generate_displacement,
                    "geocoded_enabled": plan.case.generate_geocoded_displacement,
                    "quantity": "cumulative_los_displacement",
                    "units": "meter",
                    "paths": _rel(staging, displacement_products),
                    "geocoded_paths": _rel(staging, geo_displacement_products),
                },
                "epoch_count": len(plan.inputs.acquisition_dates),
                "epochs": list(plan.inputs.acquisition_dates),
                "grid": {"lines": plan.inputs.lines, "width": plan.inputs.width},
                "input_signature": signature,
                "intermediate": {
                    "mb_paths": _rel(staging, ts_products),
                    "tpf_paths": _rel(staging, tpf_products),
                },
                "map_grid": {
                    "lines": plan.inputs.map_lines,
                    "width": plan.inputs.map_width,
                },
                "method": "gamma_mb",
                "pair_count": len(plan.inputs.pairs),
                "pairs": [pair.name for pair in plan.inputs.pairs],
                "products": mean_products,
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
            required = [
                "images",
                "diff_tab",
                "RMLI_tab",
                "itab",
                itab_ts.relative_to(staging).as_posix(),
                ts_tab.relative_to(staging).as_posix(),
                tpf_tab.relative_to(staging).as_posix(),
                std_ts.relative_to(staging).as_posix(),
                std_rate.relative_to(staging).as_posix(),
                *_rel(staging, ts_products),
                *_rel(staging, tpf_products),
                *[value["path"] for value in mean_products.values()],
                "provenance.json",
            ]
            if displacement_tab is not None:
                required.append(displacement_tab.relative_to(staging).as_posix())
            required.extend(_rel(staging, displacement_products))
            if geo_displacement_tab is not None:
                required.append(geo_displacement_tab.relative_to(staging).as_posix())
            required.extend(_rel(staging, geo_displacement_products))
            manifest["required_products"] = required
            figure_paths = [radar_figure]
            if plan.case.generate_mean_geocoded:
                figure_paths.append(geo_figure)
            manifest["figures"] = [
                Path(os.path.relpath(path, start=plan.case.output_dir)).as_posix()
                for path in figure_paths
            ]
            provenance = {
                "case_id": plan.case.case_id,
                "command_contract": list(COMMAND_CONTRACT),
                "input_signature": signature,
                "log_dir_project_path": _portable(plan, plan.case.log_dir),
                "schema_version": 2,
                "visdt_pwr": (
                    None
                    if plan.case.visdt_pwr is None
                    else _portable(plan, plan.case.visdt_pwr)
                ),
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
        return GammaMbRunSummary(
            "complete",
            len(plan.inputs.pairs),
            len(plan.inputs.acquisition_dates),
            plan.case.output_dir,
        )
    except BaseException:
        failed = _failed(plan.case.log_dir)
        if plan.case.log_dir.exists() or plan.case.log_dir.is_symlink():
            os.replace(plan.case.log_dir, failed)
        raise


__all__ = ["GammaMbRunSummary", "run_gamma_mb"]
