"""Transactional GAMMA interferogram execution with project-local logs."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from geodesy_analysis.common.command import SubprocessCommandRunner
from geodesy_analysis.common.progress import emit_progress
from geodesy_analysis.common.reuse import ReuseState, classify_analysis_output
from geodesy_analysis.insar.common.gamma_quicklooks import (
    coherence_quicklook_command,
    mli_quicklook_command,
    require_nonempty_quicklook,
    wrapped_phase_quicklook_command,
)
from geodesy_analysis.io import (
    atomic_output_directories,
    atomic_output_path,
)

from .models import GammaInterferogramPlan, InterferogramPair
from .publication import (
    ensure_nonempty,
    gamma_parameter,
    interferogram_input_signature,
)

_TASK = "ANALYSIS_GAMMA_INTERFEROGRAM"


@dataclass(frozen=True)
class InterferogramRunSummary:
    """Final interferogram-stage state returned to callers."""

    status: str
    acquisition_count: int
    pair_count: int
    output_dir: Path
    warnings: tuple[str, ...] = ()


def _event(sink: Callable[[str], None], **values: object) -> None:
    sink(emit_progress(task=_TASK, **values))


def _project_path(plan: GammaInterferogramPlan, path: Path) -> str:
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(plan.case.project_root).as_posix()
    except ValueError:
        return resolved.as_posix()


def _next_failed_log_directory(active: Path) -> Path:
    index = 1
    while True:
        candidate = active.with_name(f"{active.name}.failed-logs-{index}")
        if not candidate.exists():
            return candidate
        index += 1


def _begin_logs(active: Path) -> None:
    active.parent.mkdir(parents=True, exist_ok=True)
    if active.exists():
        os.replace(active, _next_failed_log_directory(active))
    active.mkdir()


def _preserve_failed_logs(active: Path) -> Path:
    failed = _next_failed_log_directory(active)
    if active.exists():
        os.replace(active, failed)
    return failed


def _number(value: float) -> str:
    return str(int(value)) if value.is_integer() else format(value, ".15g")


def _run(
    delegate,
    command: Sequence[str],
    *,
    cwd: Path,
    stdin_text: str | None,
    log_dir: Path,
    log_stem: str,
    expected: tuple[tuple[Path, str], ...] = (),
) -> None:
    delegate.run(
        tuple(str(value) for value in command),
        cwd=cwd,
        stdin_text=stdin_text,
        stdout_path=log_dir / f"{log_stem}.stdout.log",
        stderr_path=log_dir / f"{log_stem}.stderr.log",
    )
    for path, label in expected:
        ensure_nonempty(path, label)


def _mli_commands(
    plan: GammaInterferogramPlan,
    *,
    staging: Path,
    delegate,
    log_dir: Path,
    progress_sink: Callable[[str], None],
    total: int,
) -> tuple[dict[str, tuple[Path, Path]], int, int]:
    mli_dir = staging / "MLI"
    mli_dir.mkdir()
    assets: dict[str, tuple[Path, Path]] = {}
    range_samples: int | None = None
    azimuth_lines: int | None = None
    for index, asset in enumerate(plan.stack.assets, start=1):
        mli = mli_dir / f"{asset.date}.mli"
        parameter = mli_dir / f"{asset.date}.mli.par"
        _event(
            progress_sink,
            event="item_started",
            status="start",
            item=asset.date,
            index=index,
            total=total,
            stage="multi_look",
        )
        _run(
            delegate,
            (
                "multi_look",
                str(asset.data_path),
                str(asset.parameter_path),
                str(mli),
                str(parameter),
                str(plan.case.range_looks),
                str(plan.case.azimuth_looks),
            ),
            cwd=mli_dir,
            stdin_text=None,
            log_dir=log_dir,
            log_stem=f"mli_{asset.date}",
            expected=((mli, f"MLI for {asset.date}"), (parameter, f"MLI parameters for {asset.date}")),
        )
        width = gamma_parameter(parameter, "range_samples")
        lines = gamma_parameter(parameter, "azimuth_lines")
        if range_samples is None:
            range_samples, azimuth_lines = width, lines
        elif (width, lines) != (range_samples, azimuth_lines):
            raise ValueError(
                f"MLI grid mismatch for {asset.date}: {(width, lines)} != "
                f"{(range_samples, azimuth_lines)}"
            )
        assets[asset.date] = (mli, parameter)
        _event(
            progress_sink,
            event="item_finished",
            status="complete",
            item=asset.date,
            index=index,
            total=total,
            stage="multi_look",
        )
    assert range_samples is not None and azimuth_lines is not None
    list_path = mli_dir / "avemli_list"
    list_path.write_text(
        "".join(f"{assets[date][0]}\n" for date in plan.stack.dates), encoding="utf-8"
    )
    average = mli_dir / "ave_mli"
    _run(
        delegate,
        ("ave_image", str(list_path), str(range_samples), str(average)),
        cwd=mli_dir,
        stdin_text=None,
        log_dir=log_dir,
        log_stem="ave_mli",
        expected=((average, "average MLI"),),
    )
    list_path.unlink(missing_ok=True)
    return assets, range_samples, azimuth_lines


def _pair_commands(
    plan: GammaInterferogramPlan,
    pair: InterferogramPair,
    *,
    pair_dir: Path,
    mli_assets: dict[str, tuple[Path, Path]],
    radar_height: Path,
    width: int,
    delegate,
    log_dir: Path,
) -> dict[str, Path]:
    by_date = {asset.date: asset for asset in plan.stack.assets}
    master = by_date[pair.master]
    slave = by_date[pair.slave]
    output = {
        "interferogram": pair_dir / "pair.int",
        "offset": pair_dir / "pair.off",
        "baseline": pair_dir / "pair.baseline",
        "flattened_interferogram": pair_dir / "pair.int.flt",
        "differential_parameters": pair_dir / "pair.diff.par",
        "simulated_topographic_phase": pair_dir / "pair.sim.topo.unw",
        "differential_interferogram": pair_dir / "pair.tflt",
        "coherence": pair_dir / "pair.cc",
    }
    stdin = (
        f"{pair.name}\n"
        f"{plan.case.create_offset_range_start} {plan.case.create_offset_azimuth_start}\n"
        f"{plan.case.create_offset_range_window} {plan.case.create_offset_azimuth_window}\n"
        f"{plan.case.create_offset_range_search} {plan.case.create_offset_azimuth_search}\n"
        f"{_number(plan.case.create_offset_correlation_threshold)}\n\n\n"
    )
    common = {"cwd": pair_dir, "log_dir": log_dir}
    _run(
        delegate,
        (
            "create_offset",
            str(master.parameter_path),
            str(slave.parameter_path),
            str(output["offset"]),
            "1",
            str(plan.case.range_looks),
            str(plan.case.azimuth_looks),
        ),
        stdin_text=stdin,
        log_stem=f"{pair.name}_01_create_offset",
        expected=((output["offset"], f"offset parameters for {pair.name}"),),
        **common,
    )
    _run(
        delegate,
        (
            "SLC_intf",
            str(master.data_path),
            str(slave.data_path),
            str(master.parameter_path),
            str(slave.parameter_path),
            str(output["offset"]),
            str(output["interferogram"]),
            str(plan.case.range_looks),
            str(plan.case.azimuth_looks),
            "-",
            "-",
            str(plan.spectral_filter_range),
            str(plan.spectral_filter_azimuth),
        ),
        stdin_text=None,
        log_stem=f"{pair.name}_02_SLC_intf",
        expected=((output["interferogram"], f"interferogram for {pair.name}"),),
        **common,
    )
    _run(
        delegate,
        (
            "base_init",
            str(master.parameter_path),
            str(slave.parameter_path),
            str(output["offset"]),
            str(output["interferogram"]),
            str(output["baseline"]),
            "1",
        ),
        stdin_text=None,
        log_stem=f"{pair.name}_03_base_init",
        expected=((output["baseline"], f"baseline for {pair.name}"),),
        **common,
    )
    _run(
        delegate,
        ("base_perp", str(output["baseline"]), str(master.parameter_path), str(output["offset"])),
        stdin_text=None,
        log_stem=f"{pair.name}_04_base_perp",
        **common,
    )
    _run(
        delegate,
        (
            "ph_slope_base",
            str(output["interferogram"]),
            str(master.parameter_path),
            str(output["offset"]),
            str(output["baseline"]),
            str(output["flattened_interferogram"]),
        ),
        stdin_text=None,
        log_stem=f"{pair.name}_05_ph_slope_base",
        expected=((output["flattened_interferogram"], f"flattened interferogram for {pair.name}"),),
        **common,
    )
    _run(
        delegate,
        (
            "create_diff_par",
            str(output["offset"]),
            str(output["offset"]),
            str(output["differential_parameters"]),
            "0",
            "0",
        ),
        stdin_text=None,
        log_stem=f"{pair.name}_06_create_diff_par",
        expected=(
            (
                output["differential_parameters"],
                f"differential parameters for {pair.name}",
            ),
        ),
        **common,
    )
    _run(
        delegate,
        (
            "phase_sim_orb",
            str(master.parameter_path),
            str(slave.parameter_path),
            str(output["offset"]),
            str(radar_height),
            str(output["simulated_topographic_phase"]),
            "-",
            "-",
            "-",
            "1",
            "1",
        ),
        stdin_text=None,
        log_stem=f"{pair.name}_07_phase_sim_orb",
        expected=((output["simulated_topographic_phase"], f"simulated topographic phase for {pair.name}"),),
        **common,
    )
    _run(
        delegate,
        (
            "sub_phase",
            str(output["interferogram"]),
            str(output["simulated_topographic_phase"]),
            str(output["differential_parameters"]),
            str(output["differential_interferogram"]),
            "1",
        ),
        stdin_text=None,
        log_stem=f"{pair.name}_08_sub_phase",
        expected=((output["differential_interferogram"], f"differential interferogram for {pair.name}"),),
        **common,
    )
    _run(
        delegate,
        (
            "cc_wave",
            str(output["differential_interferogram"]),
            str(mli_assets[pair.master][0]),
            str(mli_assets[pair.slave][0]),
            str(output["coherence"]),
            str(width),
            str(plan.case.coherence_range_window),
            str(plan.case.coherence_azimuth_window),
            str(plan.case.coherence_estimator),
        ),
        stdin_text=None,
        log_stem=f"{pair.name}_09_cc_wave",
        expected=((output["coherence"], f"coherence for {pair.name}"),),
        **common,
    )
    return output


def _geocode_reference(
    plan: GammaInterferogramPlan,
    *,
    mli_assets: dict[str, tuple[Path, Path]],
    width: int,
    lines: int,
    destination: Path,
    delegate,
    log_dir: Path,
    progress_sink: Callable[[str], None],
    index: int,
    total: int,
) -> Path:
    reference_date = plan.stack.reference_date
    reference_mli, reference_parameter = mli_assets[reference_date]
    root_name = f"{reference_date}.{plan.case.polarization}"
    radar_height = destination / f"{root_name}.wgs84.hgt"
    quality = destination / f"{root_name}.geocoding_quality"
    map_dem = destination / "demcrop.dem"
    map_dem_parameter = destination / "demcrop.dem_par"
    settings = plan.case.geocoding
    destination.mkdir(parents=True, exist_ok=True)
    _event(
        progress_sink,
        event="item_started",
        status="start",
        item=reference_date,
        index=index,
        total=total,
        stage="geocoding",
    )
    _run(
        delegate,
        (
            "geocoding.py",
            str(reference_mli),
            str(reference_parameter),
            str(settings.dem),
            str(settings.dem_par),
            root_name,
            "--summary",
            str(quality),
            "--thres",
            _number(settings.correlation_threshold),
            "--npoly",
            str(settings.polynomial_parameters),
            "--rwin",
            str(settings.range_window),
            "--azwin",
            str(settings.azimuth_window),
            "--area_fact",
            _number(settings.area_factor),
            "--seg",
            "demcrop",
            "--out_dir",
            str(destination),
        ),
        cwd=destination,
        stdin_text=None,
        log_dir=log_dir,
        log_stem=f"geocoding_{reference_date}",
        expected=(
            (radar_height, "geocoded WGS84 radar height"),
            (quality, "geocoding quality summary"),
            (map_dem, "cropped map-grid DEM"),
            (map_dem_parameter, "cropped map-grid DEM parameter"),
        ),
    )
    expected_size = width * lines * 4
    if radar_height.stat().st_size != expected_size:
        raise ValueError(
            "geocoded radar height grid size mismatch: expected "
            f"{expected_size} bytes from MLI {width}x{lines}, got "
            f"{radar_height.stat().st_size} bytes"
        )
    map_width = gamma_parameter(map_dem_parameter, "width")
    map_lines = gamma_parameter(map_dem_parameter, "nlines")
    expected_map_dem_size = map_width * map_lines * 4
    if map_dem.stat().st_size != expected_map_dem_size:
        raise ValueError(
            "cropped map-grid DEM size mismatch: expected "
            f"{expected_map_dem_size} bytes from DEM parameter "
            f"{map_width}x{map_lines}, got {map_dem.stat().st_size} bytes"
        )
    _event(
        progress_sink,
        event="item_finished",
        status="complete",
        item=reference_date,
        index=index,
        total=total,
        stage="geocoding",
    )
    return radar_height


def _quicklook_metadata(
    plan: GammaInterferogramPlan,
) -> tuple[str, str, dict[str, str], dict[str, dict[str, str]]]:
    directory = plan.case.visualization_dir
    directory_path = _project_path(plan, directory)
    mli = {
        date: _project_path(plan, directory / f"{date}.mli.bmp")
        for date in plan.stack.dates
    }
    pairs = {
        pair.name: {
            "coherence_project_path": _project_path(
                plan, directory / f"{pair.name}.coherence.bmp"
            ),
            "intensity_project_path": _project_path(
                plan, directory / f"{pair.name}.intensity.bmp"
            ),
            "phase_project_path": _project_path(
                plan, directory / f"{pair.name}.phase.bmp"
            ),
        }
        for pair in plan.pairs
    }
    return (
        directory_path,
        _project_path(plan, directory / "ave_mli.bmp"),
        mli,
        pairs,
    )


def _figure_inventory(plan: GammaInterferogramPlan) -> list[Path]:
    directory = plan.case.visualization_dir
    figures = [
        *(directory / f"{date}.mli.bmp" for date in plan.stack.dates),
        directory / "ave_mli.bmp",
    ]
    for pair in plan.pairs:
        figures.extend(
            (
                directory / f"{pair.name}.intensity.bmp",
                directory / f"{pair.name}.phase.bmp",
                directory / f"{pair.name}.coherence.bmp",
            )
        )
    return figures


def _add_quicklook_metadata(
    plan: GammaInterferogramPlan,
    manifest: dict[str, object],
    provenance: dict[str, object],
) -> None:
    directory, average, mli, pairs = _quicklook_metadata(plan)
    manifest["visualization_dir_project_path"] = directory
    manifest["average_mli_quicklook_project_path"] = average
    for item in manifest["mli_assets"]:  # type: ignore[index]
        item["quicklook_project_path"] = mli[item["date"]]
    for item in manifest["pairs"]:  # type: ignore[index]
        item["quicklooks"] = pairs[item["pair"]]
    provenance["visualization_dir_project_path"] = directory
    provenance["quicklook_commands"] = {
        "coherence": {"command": "rasdt_pwr", "color_map": "cc.cm"},
        "intensity": {"command": "raspwr", "color_map": "gray.cm"},
        "wrapped_phase": {"command": "rasmph", "color_map": "rmg.cm"},
    }


def _run_quicklook(
    delegate,
    command_factory,
    destination: Path,
    *,
    cwd: Path,
    log_dir: Path,
    log_stem: str,
    label: str,
    atomic: bool,
) -> None:
    if destination.is_symlink():
        destination.unlink()
    if destination.is_file() and destination.stat().st_size:
        return
    if atomic:
        with atomic_output_path(destination) as temporary:
            _run(
                delegate,
                command_factory(temporary),
                cwd=cwd,
                stdin_text=None,
                log_dir=log_dir,
                log_stem=log_stem,
            )
            require_nonempty_quicklook(temporary, label)
        return
    _run(
        delegate,
        command_factory(destination),
        cwd=cwd,
        stdin_text=None,
        log_dir=log_dir,
        log_stem=log_stem,
    )
    require_nonempty_quicklook(destination, label)


def _render_quicklooks(
    plan: GammaInterferogramPlan,
    *,
    mli_assets: dict[str, tuple[Path, Path]],
    average_mli: Path,
    pair_products: list[tuple[InterferogramPair, dict[str, Path]]],
    width: int,
    destination: Path,
    delegate,
    log_dir: Path,
    atomic_files: bool,
) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for date in plan.stack.dates:
        target = destination / f"{date}.mli.bmp"
        _run_quicklook(
            delegate,
            lambda output, data=mli_assets[date][0]: mli_quicklook_command(
                data, width, output
            ),
            target,
            cwd=destination,
            log_dir=log_dir,
            log_stem=f"quicklook_{date}_mli",
            label=f"MLI quicklook for {date}",
            atomic=atomic_files,
        )
    _run_quicklook(
        delegate,
        lambda output: mli_quicklook_command(average_mli, width, output),
        destination / "ave_mli.bmp",
        cwd=destination,
        log_dir=log_dir,
        log_stem="quicklook_ave_mli",
        label="average MLI quicklook",
        atomic=atomic_files,
    )
    for pair, products in pair_products:
        _run_quicklook(
            delegate,
            lambda output, data=mli_assets[pair.master][0]: mli_quicklook_command(
                data, width, output
            ),
            destination / f"{pair.name}.intensity.bmp",
            cwd=destination,
            log_dir=log_dir,
            log_stem=f"quicklook_{pair.name}_intensity",
            label=f"intensity quicklook for {pair.name}",
            atomic=atomic_files,
        )
        _run_quicklook(
            delegate,
            lambda output, data=products["differential_interferogram"]: (
                wrapped_phase_quicklook_command(data, width, output)
            ),
            destination / f"{pair.name}.phase.bmp",
            cwd=destination,
            log_dir=log_dir,
            log_stem=f"quicklook_{pair.name}_phase",
            label=f"wrapped phase quicklook for {pair.name}",
            atomic=atomic_files,
        )
        _run_quicklook(
            delegate,
            lambda output, data=products["coherence"]: coherence_quicklook_command(
                data, width, output, background=None
            ),
            destination / f"{pair.name}.coherence.bmp",
            cwd=destination,
            log_dir=log_dir,
            log_stem=f"quicklook_{pair.name}_coherence",
            label=f"coherence quicklook for {pair.name}",
            atomic=atomic_files,
        )


def run_gamma_interferograms(
    plan: GammaInterferogramPlan,
    *,
    command_runner=None,
    progress_sink: Callable[[str], None] = print,
    quicklook_renderer=None,
) -> InterferogramRunSummary:
    """Create MLI and differential interferogram products, then publish once."""

    if not isinstance(plan, GammaInterferogramPlan):
        raise TypeError("plan must be GammaInterferogramPlan")
    _ = quicklook_renderer
    signature = interferogram_input_signature(plan)
    delegate = command_runner or SubprocessCommandRunner()
    log_dir = (
        plan.case.paths.processing_root / "LOG/ANALYSIS/INTF"
        if plan.case.paths.processing_root is not None
        else plan.case.case_root / "LOG/ANALYSIS/INTERFEROGRAM_GENERATION/GAMMA"
    )
    reuse = classify_analysis_output(
        plan.case.output_dir, "interferogram_manifest.json", signature
    )
    if reuse.science_reusable:
        manifest = reuse.manifest or {}
        expected_identity = {
            "backend": {"name": "gamma"},
            "baseline_manifest_project_path": _project_path(
                plan, plan.case.baseline_manifest
            ),
            "case_id": plan.case.case_id,
            "polarization": plan.case.polarization,
            "radar_height_project_path": _project_path(
                plan,
                plan.case.geocoding.output_dir
                / f"{plan.stack.reference_date}.{plan.case.polarization}.wgs84.hgt",
            ),
            "registered_stack_project_path": _project_path(
                plan, plan.case.registered_stack
            ),
            "stack_digest": plan.stack.source_digest,
        }
        inconsistent = [
            key
            for key, value in expected_identity.items()
            if manifest.get(key) != value
        ]
        if [item.get("pair") for item in manifest.get("pairs", [])] != [
            pair.name for pair in plan.pairs
        ]:
            inconsistent.append("pairs")
        if inconsistent:
            raise RuntimeError(
                "interferogram manifest identity is inconsistent: "
                + ", ".join(inconsistent)
                + f". Existing science was not modified: {plan.case.output_dir}"
            )
        required_geometry = (
            plan.case.geocoding.output_dir / str(manifest.get("reference_radar_height_name", "")),
            plan.case.geocoding.output_dir / "demcrop.dem",
            plan.case.geocoding.output_dir / "demcrop.dem_par",
        )
        missing_geometry = [
            path for path in required_geometry if not path.is_file() or path.stat().st_size < 1
        ]
        if missing_geometry:
            raise RuntimeError(
                "science manifest is complete but required GEOCODING products are missing: "
                + ", ".join(str(path) for path in missing_geometry)
                + f". Delete {plan.case.output_dir} and {plan.case.geocoding.output_dir} "
                "after inspection before rerunning"
            )
        if reuse.state is ReuseState.FIGURES_MISSING:
            _begin_logs(log_dir)
            mli_assets = {
                date: (
                    plan.case.output_dir / "MLI" / f"{date}.mli",
                    plan.case.output_dir / "MLI" / f"{date}.mli.par",
                )
                for date in plan.stack.dates
            }
            width = gamma_parameter(mli_assets[plan.stack.reference_date][1], "range_samples")
            pair_products = [
                (
                    pair,
                    {
                        "differential_interferogram": (
                            plan.case.output_dir / "PAIRS" / pair.name / "pair.tflt"
                        ),
                        "coherence": (
                            plan.case.output_dir / "PAIRS" / pair.name / "pair.cc"
                        ),
                    },
                )
                for pair in plan.pairs
            ]
            _render_quicklooks(
                plan,
                mli_assets=mli_assets,
                average_mli=plan.case.output_dir / "MLI/ave_mli",
                pair_products=pair_products,
                width=width,
                destination=plan.case.visualization_dir,
                delegate=delegate,
                log_dir=log_dir,
                atomic_files=True,
            )
            status = "figures_repaired"
        else:
            status = "skipped"
        _event(
            progress_sink,
            event="batch_finished",
            status=status,
            total=len(plan.stack.assets) + len(plan.pairs) + 3,
            stage="reuse",
        )
        return InterferogramRunSummary(
            status=status,
            acquisition_count=len(plan.stack.assets),
            pair_count=len(plan.pairs),
            output_dir=plan.case.output_dir,
            warnings=(),
        )
    if reuse.state is not ReuseState.ABSENT:
        raise RuntimeError(reuse.guidance)
    existing_companions = [
        path
        for path in (
            plan.case.geocoding.output_dir,
            plan.case.visualization_dir,
        )
        if path.exists() or path.is_symlink()
    ]
    if existing_companions:
        raise RuntimeError(
            "interferogram science is absent but companion outputs already exist: "
            + ", ".join(str(path) for path in existing_companions)
            + ". Inspect and delete the incomplete output group before rerunning"
        )
    _begin_logs(log_dir)
    total = len(plan.stack.assets) + len(plan.pairs) + 3
    _event(progress_sink, event="batch_started", status="start", total=total, stage="prepare")
    try:
        with atomic_output_directories(
            plan.case.geocoding.output_dir,
            plan.case.visualization_dir,
            plan.case.output_dir,
        ) as (geocoding_staging, visualization_staging, staging):
            mli_assets, width, lines = _mli_commands(
                plan,
                staging=staging,
                delegate=delegate,
                log_dir=log_dir,
                progress_sink=progress_sink,
                total=total,
            )
            radar_height = _geocode_reference(
                plan,
                mli_assets=mli_assets,
                width=width,
                lines=lines,
                destination=geocoding_staging,
                delegate=delegate,
                log_dir=log_dir,
                progress_sink=progress_sink,
                index=len(plan.stack.assets) + 1,
                total=total,
            )
            expected_height_size = width * lines * 4
            actual_height_size = radar_height.stat().st_size
            if actual_height_size != expected_height_size:
                raise ValueError(
                    "radar height grid size mismatch: expected "
                    f"{expected_height_size} bytes from MLI {width}x{lines}, got "
                    f"{actual_height_size} bytes"
                )
            pairs_dir = staging / "PAIRS"
            pairs_dir.mkdir()
            pair_products: list[tuple[InterferogramPair, dict[str, Path]]] = []
            for offset, pair in enumerate(plan.pairs, start=len(plan.stack.assets) + 2):
                _event(
                    progress_sink,
                    event="item_started",
                    status="start",
                    item=pair.name,
                    index=offset,
                    total=total,
                    stage="interferogram",
                )
                pair_dir = pairs_dir / pair.name
                pair_dir.mkdir()
                products = _pair_commands(
                    plan,
                    pair,
                    pair_dir=pair_dir,
                    mli_assets=mli_assets,
                    radar_height=radar_height,
                    width=width,
                    delegate=delegate,
                    log_dir=log_dir,
                )
                pair_products.append((pair, products))
                _event(
                    progress_sink,
                    event="item_finished",
                    status="complete",
                    item=pair.name,
                    index=offset,
                    total=total,
                    stage="interferogram",
                )

            registered_stack_project_path = _project_path(
                plan, plan.case.registered_stack
            )
            baseline_manifest_project_path = _project_path(
                plan, plan.case.baseline_manifest
            )
            radar_height_project_path = _project_path(
                plan,
                plan.case.geocoding.output_dir / radar_height.name,
            )
            map_dem = geocoding_staging / "demcrop.dem"
            map_dem_parameter = geocoding_staging / "demcrop.dem_par"
            map_dem_width = gamma_parameter(map_dem_parameter, "width")
            map_dem_lines = gamma_parameter(map_dem_parameter, "nlines")
            published_map_dem = plan.case.geocoding.output_dir / map_dem.name
            published_map_dem_parameter = (
                plan.case.geocoding.output_dir / map_dem_parameter.name
            )
            geocoding_output_project_path = _project_path(
                plan, plan.case.geocoding.output_dir
            )
            geocoding_config_project_path = _project_path(
                plan, plan.case.geocoding.config_path
            )
            provenance: dict[str, object] = {
                "backend": {"name": "gamma"},
                "baseline_manifest_project_path": baseline_manifest_project_path,
                "case_id": plan.case.case_id,
                "geocoding": {
                    "area_factor": plan.case.geocoding.area_factor,
                    "azimuth_window": plan.case.geocoding.azimuth_window,
                    "config_path": geocoding_config_project_path,
                    "correlation_threshold": plan.case.geocoding.correlation_threshold,
                    "dem_path": _project_path(plan, plan.case.geocoding.dem),
                    "dem_par_path": _project_path(plan, plan.case.geocoding.dem_par),
                    "dem_segment_parameter_path": _project_path(
                        plan, published_map_dem_parameter
                    ),
                    "dem_segment_path": _project_path(plan, published_map_dem),
                    "dem_segment_root": "demcrop",
                    "output_dir": geocoding_output_project_path,
                    "polynomial_parameters": (
                        plan.case.geocoding.polynomial_parameters
                    ),
                    "range_window": plan.case.geocoding.range_window,
                },
                "input_signature": signature,
                "log_dir_project_path": _project_path(plan, log_dir),
                "radar_height_project_path": radar_height_project_path,
                "radar_height_size_bytes": actual_height_size,
                "reference_radar_height_name": radar_height.name,
                "registered_stack_project_path": registered_stack_project_path,
                "resolved_filter_flags": {
                    "azimuth": plan.spectral_filter_azimuth,
                    "range": plan.spectral_filter_range,
                },
                "schema_version": 2,
            }
            manifest: dict[str, object] = {
                "average_mli_path": "MLI/ave_mli",
                "backend": {"name": "gamma"},
                "baseline_manifest_project_path": baseline_manifest_project_path,
                "case_id": plan.case.case_id,
                "filter_flags": {
                    "azimuth": plan.spectral_filter_azimuth,
                    "range": plan.spectral_filter_range,
                },
                "geocoding_output_dir_project_path": geocoding_output_project_path,
                "looks": {"azimuth": plan.case.azimuth_looks, "range": plan.case.range_looks},
                "map_dem_segment_project_path": _project_path(
                    plan, published_map_dem
                ),
                "map_dem_segment_parameter_project_path": _project_path(
                    plan, published_map_dem_parameter
                ),
                "map_grid": {"lines": map_dem_lines, "width": map_dem_width},
                "mli_assets": [
                    {
                        "data_path": f"MLI/{date}.mli",
                        "date": date,
                        "parameter_path": f"MLI/{date}.mli.par",
                    }
                    for date in plan.stack.dates
                ],
                "network_type": plan.baseline.network_type,
                "pairs": [
                    {
                        "pair": pair.name,
                        "products": {
                            key: str(path.relative_to(staging)) for key, path in products.items()
                        },
                    }
                    for pair, products in pair_products
                ],
                "polarization": plan.case.polarization,
                "provenance_path": "provenance.json",
                "radar_height_project_path": radar_height_project_path,
                "radar_height_size_bytes": actual_height_size,
                "reference_date": plan.stack.reference_date,
                "reference_radar_height_name": radar_height.name,
                "registered_stack_project_path": registered_stack_project_path,
                "input_signature": signature,
                "schema_version": 2,
                "stack_digest": plan.stack.source_digest,
                "status": "complete",
            }
            manifest["scientific_manifest_digest"] = hashlib.sha256(
                (
                    json.dumps(
                        manifest, ensure_ascii=False, sort_keys=True, indent=2
                    )
                    + "\n"
                ).encode("utf-8")
            ).hexdigest()
            _render_quicklooks(
                plan,
                mli_assets=mli_assets,
                average_mli=staging / "MLI/ave_mli",
                pair_products=pair_products,
                width=width,
                destination=visualization_staging,
                delegate=delegate,
                log_dir=log_dir,
                atomic_files=False,
            )
            _add_quicklook_metadata(plan, manifest, provenance)
            manifest["required_products"] = [
                "MLI/ave_mli",
                *[
                    relative
                    for item in manifest["mli_assets"]  # type: ignore[index]
                    for relative in (item["data_path"], item["parameter_path"])
                ],
                *[
                    relative
                    for item in manifest["pairs"]  # type: ignore[index]
                    for relative in item["products"].values()
                ],
                "provenance.json",
            ]
            manifest["figures"] = [
                Path(
                    os.path.relpath(path, start=plan.case.output_dir)
                ).as_posix()
                for path in _figure_inventory(plan)
            ]
            (staging / "provenance.json").write_text(
                json.dumps(provenance, ensure_ascii=False, sort_keys=True, indent=2)
                + "\n",
                encoding="utf-8",
            )
            (staging / "interferogram_manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2)
                + "\n",
                encoding="utf-8",
            )
        _event(
            progress_sink,
            event="batch_finished",
            status="complete",
            index=total,
            total=total,
            stage="publish",
        )
        return InterferogramRunSummary(
            status="complete",
            acquisition_count=len(plan.stack.assets),
            pair_count=len(plan.pairs),
            output_dir=plan.case.output_dir,
            warnings=(),
        )
    except BaseException:
        failed_logs = _preserve_failed_logs(log_dir)
        _event(
            progress_sink,
            event="batch_finished",
            status="failed",
            total=total,
            stage="failed",
            failure_logs=str(failed_logs),
        )
        raise


__all__ = ["InterferogramRunSummary", "run_gamma_interferograms"]
