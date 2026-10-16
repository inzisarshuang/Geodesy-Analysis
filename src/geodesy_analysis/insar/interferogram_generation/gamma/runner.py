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
from geodesy_analysis.insar.common.gamma_quicklooks import (
    coherence_quicklook_command,
    mli_quicklook_command,
    require_nonempty_quicklook,
    wrapped_phase_quicklook_command,
)
from geodesy_analysis.io import atomic_output_directory, atomic_output_path

from .models import GammaInterferogramPlan, InterferogramPair
from .publication import (
    ensure_nonempty,
    gamma_parameter,
    interferogram_input_signature,
    legacy_interferogram_input_signature,
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


@dataclass(frozen=True)
class _ExistingInterferogram:
    summary: InterferogramRunSummary
    manifest: dict[str, object]
    provenance: dict[str, object]


def _event(sink: Callable[[str], None], **values: object) -> None:
    sink(emit_progress(task=_TASK, **values))


def _published_asset(output: Path, value: object, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"interferogram manifest {label} path is required")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"interferogram manifest {label} path is unsafe")
    target = (output / relative).resolve()
    try:
        target.relative_to(output.resolve())
    except ValueError as error:
        raise ValueError(f"interferogram manifest {label} leaves output directory") from error
    return ensure_nonempty(target, label)


def _project_path(plan: GammaInterferogramPlan, path: Path) -> str:
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(plan.case.project_root).as_posix()
    except ValueError as error:
        raise ValueError(f"interferogram path leaves project root: {resolved}") from error


def _read_existing(
    plan: GammaInterferogramPlan, signature: str
) -> _ExistingInterferogram | None:
    output = plan.case.output_dir
    if not output.exists():
        return None
    try:
        manifest = json.loads(
            (output / "interferogram_manifest.json").read_text(encoding="utf-8")
        )
        provenance = json.loads((output / "provenance.json").read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or not isinstance(provenance, dict):
            raise ValueError("interferogram manifest and provenance must be JSON objects")
        schema_version = manifest.get("schema_version")
        if schema_version not in {1, 2} or manifest.get("status") != "complete":
            raise ValueError("interferogram manifest is not a supported complete schema")
        expected_signature = (
            legacy_interferogram_input_signature(plan)
            if schema_version == 1
            else signature
        )
        if provenance.get("input_signature") != expected_signature:
            raise FileExistsError(
                f"interferogram output was produced from different inputs: {output}"
            )
        if schema_version == 2:
            identities = {
                "registered_stack_project_path": _project_path(
                    plan, plan.case.registered_stack
                ),
                "baseline_manifest_project_path": _project_path(
                    plan, plan.case.baseline_manifest
                ),
                "radar_height_project_path": _project_path(
                    plan, plan.case.radar_height
                ),
            }
            if manifest.get("case_id") != plan.case.case_id:
                raise ValueError("interferogram manifest case identity is inconsistent")
            if manifest.get("backend") != {"name": "gamma"}:
                raise ValueError("interferogram manifest backend is inconsistent")
            if provenance.get("schema_version") != 2:
                raise ValueError("interferogram provenance schema is inconsistent")
            if provenance.get("case_id") != plan.case.case_id:
                raise ValueError("interferogram provenance case identity is inconsistent")
            if provenance.get("backend") != {"name": "gamma"}:
                raise ValueError("interferogram provenance backend is inconsistent")
            for key, expected in identities.items():
                if manifest.get(key) != expected:
                    raise ValueError(f"interferogram manifest {key} is inconsistent")
                if provenance.get(key) != expected:
                    raise ValueError(f"interferogram provenance {key} is inconsistent")
        if manifest.get("stack_digest") != plan.stack.source_digest:
            raise ValueError("interferogram manifest stack digest is inconsistent")
        if manifest.get("polarization") != plan.case.polarization:
            raise ValueError("interferogram manifest polarization is inconsistent")
        if manifest.get("reference_date") != plan.stack.reference_date:
            raise ValueError("interferogram manifest reference date is inconsistent")
        if manifest.get("looks") != {
            "azimuth": plan.case.azimuth_looks,
            "range": plan.case.range_looks,
        }:
            raise ValueError("interferogram manifest looks are inconsistent")
        if manifest.get("filter_flags") != {
            "azimuth": plan.spectral_filter_azimuth,
            "range": plan.spectral_filter_range,
        }:
            raise ValueError("interferogram manifest filter flags are inconsistent")
        _published_asset(output, manifest.get("average_mli_path"), "average MLI")
        raw_mli = manifest.get("mli_assets")
        raw_pairs = manifest.get("pairs")
        if not isinstance(raw_mli, list) or len(raw_mli) != len(plan.stack.assets):
            raise ValueError("interferogram manifest has an incomplete MLI inventory")
        if not isinstance(raw_pairs, list) or len(raw_pairs) != len(plan.pairs):
            raise ValueError("interferogram manifest has an incomplete pair inventory")
        for expected_date, item in zip(plan.stack.dates, raw_mli):
            if not isinstance(item, dict):
                raise ValueError("interferogram manifest MLI item must be an object")
            if item.get("date") != expected_date:
                raise ValueError("interferogram manifest MLI date inventory is inconsistent")
            _published_asset(output, item.get("data_path"), "MLI")
            _published_asset(output, item.get("parameter_path"), "MLI parameters")
        for expected_pair, item in zip(plan.pairs, raw_pairs):
            if not isinstance(item, dict) or not isinstance(item.get("products"), dict):
                raise ValueError("interferogram manifest pair item is invalid")
            if item.get("pair") != expected_pair.name:
                raise ValueError("interferogram manifest pair inventory is inconsistent")
            required_products = {
                "baseline",
                "coherence",
                "differential_interferogram",
                "differential_parameters",
                "flattened_interferogram",
                "interferogram",
                "offset",
                "simulated_topographic_phase",
            }
            if set(item["products"]) != required_products:
                raise ValueError("interferogram manifest pair products are incomplete")
            for name, path in item["products"].items():
                _published_asset(output, path, f"pair product {name}")
        return _ExistingInterferogram(
            summary=InterferogramRunSummary(
                status="skipped",
                acquisition_count=len(raw_mli),
                pair_count=len(raw_pairs),
                output_dir=output,
                warnings=tuple(manifest.get("warnings", ())),
            ),
            manifest=manifest,
            provenance=provenance,
        )
    except FileExistsError:
        raise
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise FileExistsError(
            f"interferogram output is incomplete or invalid: {output}"
        ) from error


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
            str(plan.case.radar_height),
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


def _quicklook_names(plan: GammaInterferogramPlan) -> set[str]:
    return {
        *(f"{date}.mli.bmp" for date in plan.stack.dates),
        "ave_mli.bmp",
        *(f"{pair.name}.tflt.bmp" for pair in plan.pairs),
        *(f"{pair.name}.cc.bmp" for pair in plan.pairs),
    }


def _validate_visualization_inventory(plan: GammaInterferogramPlan) -> None:
    directory = plan.case.visualization_dir
    if not directory.exists():
        return
    if not directory.is_dir() or directory.is_symlink():
        raise FileExistsError(f"visualization output is not a directory: {directory}")
    expected = _quicklook_names(plan)
    unexpected = sorted(path.name for path in directory.iterdir() if path.name not in expected)
    if unexpected:
        raise FileExistsError(
            f"visualization directory has unexpected entry: {directory / unexpected[0]}"
        )


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
                plan, directory / f"{pair.name}.cc.bmp"
            ),
            "phase_project_path": _project_path(
                plan, directory / f"{pair.name}.tflt.bmp"
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


def _quicklooks_complete(
    plan: GammaInterferogramPlan, manifest: dict[str, object]
) -> bool:
    directory, average, mli, pairs = _quicklook_metadata(plan)
    if manifest.get("visualization_dir_project_path") != directory:
        return False
    if manifest.get("average_mli_quicklook_project_path") != average:
        return False
    raw_mli = manifest.get("mli_assets")
    raw_pairs = manifest.get("pairs")
    if not isinstance(raw_mli, list) or not isinstance(raw_pairs, list):
        return False
    if any(
        not isinstance(item, dict)
        or item.get("quicklook_project_path") != mli.get(item.get("date"))
        for item in raw_mli
    ):
        return False
    if any(
        not isinstance(item, dict)
        or item.get("quicklooks") != pairs.get(item.get("pair"))
        for item in raw_pairs
    ):
        return False
    try:
        for name in _quicklook_names(plan):
            require_nonempty_quicklook(plan.case.visualization_dir / name, name)
    except (OSError, RuntimeError):
        return False
    return True


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
            lambda output, data=products["differential_interferogram"]: (
                wrapped_phase_quicklook_command(data, width, output)
            ),
            destination / f"{pair.name}.tflt.bmp",
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
            destination / f"{pair.name}.cc.bmp",
            cwd=destination,
            log_dir=log_dir,
            log_stem=f"quicklook_{pair.name}_coherence",
            label=f"coherence quicklook for {pair.name}",
            atomic=atomic_files,
        )


def _existing_science_assets(
    plan: GammaInterferogramPlan, manifest: dict[str, object]
) -> tuple[
    dict[str, tuple[Path, Path]],
    Path,
    list[tuple[InterferogramPair, dict[str, Path]]],
    int,
]:
    output = plan.case.output_dir
    raw_mli = manifest["mli_assets"]
    raw_pairs = manifest["pairs"]
    mli_assets = {
        item["date"]: (
            _published_asset(output, item["data_path"], "MLI"),
            _published_asset(output, item["parameter_path"], "MLI parameters"),
        )
        for item in raw_mli  # type: ignore[union-attr]
    }
    average = _published_asset(output, manifest["average_mli_path"], "average MLI")
    pair_by_name = {item["pair"]: item for item in raw_pairs}  # type: ignore[union-attr]
    pair_products = [
        (
            pair,
            {
                name: _published_asset(output, value, f"pair product {name}")
                for name, value in pair_by_name[pair.name]["products"].items()
            },
        )
        for pair in plan.pairs
    ]
    width = gamma_parameter(mli_assets[plan.stack.dates[0]][1], "range_samples")
    return mli_assets, average, pair_products, width


def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    with atomic_output_path(path) as temporary:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
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
    existing = _read_existing(plan, signature)
    if existing is not None:
        _validate_visualization_inventory(plan)
        if _quicklooks_complete(plan, existing.manifest):
            _event(
                progress_sink,
                event="batch_finished",
                status="skipped",
                total=existing.summary.pair_count,
                stage="publish",
            )
            return existing.summary
        delegate = command_runner or SubprocessCommandRunner()
        log_dir = plan.case.case_root / "LOG/ANALYSIS/INTERFEROGRAM_GENERATION/GAMMA"
        _begin_logs(log_dir)
        try:
            manifest_path = plan.case.output_dir / "interferogram_manifest.json"
            existing.manifest.setdefault(
                "scientific_manifest_digest",
                hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            )
            mli_assets, average_mli, pair_products, width = _existing_science_assets(
                plan, existing.manifest
            )
            if plan.case.visualization_dir.exists():
                _render_quicklooks(
                    plan,
                    mli_assets=mli_assets,
                    average_mli=average_mli,
                    pair_products=pair_products,
                    width=width,
                    destination=plan.case.visualization_dir,
                    delegate=delegate,
                    log_dir=log_dir,
                    atomic_files=True,
                )
            else:
                with atomic_output_directory(plan.case.visualization_dir) as visual_staging:
                    _render_quicklooks(
                        plan,
                        mli_assets=mli_assets,
                        average_mli=average_mli,
                        pair_products=pair_products,
                        width=width,
                        destination=visual_staging,
                        delegate=delegate,
                        log_dir=log_dir,
                        atomic_files=False,
                    )
            _add_quicklook_metadata(plan, existing.manifest, existing.provenance)
            _write_json_atomic(
                plan.case.output_dir / "provenance.json", existing.provenance
            )
            _write_json_atomic(
                manifest_path, existing.manifest
            )
        except BaseException:
            failed_logs = _preserve_failed_logs(log_dir)
            _event(
                progress_sink,
                event="batch_finished",
                status="failed",
                total=existing.summary.pair_count,
                stage="failed",
                failure_logs=str(failed_logs),
            )
            raise
        _event(
            progress_sink,
            event="batch_finished",
            status="repaired",
            total=existing.summary.pair_count,
            stage="publish",
        )
        return InterferogramRunSummary(
            status="repaired",
            acquisition_count=existing.summary.acquisition_count,
            pair_count=existing.summary.pair_count,
            output_dir=existing.summary.output_dir,
            warnings=existing.summary.warnings,
        )
    delegate = command_runner or SubprocessCommandRunner()
    log_dir = plan.case.case_root / "LOG/ANALYSIS/INTERFEROGRAM_GENERATION/GAMMA"
    _begin_logs(log_dir)
    total = len(plan.stack.assets) + len(plan.pairs) + 2
    _event(progress_sink, event="batch_started", status="start", total=total, stage="prepare")
    try:
        with atomic_output_directory(plan.case.output_dir) as staging:
            mli_assets, width, lines = _mli_commands(
                plan,
                staging=staging,
                delegate=delegate,
                log_dir=log_dir,
                progress_sink=progress_sink,
                total=total,
            )
            expected_height_size = width * lines * 4
            actual_height_size = plan.case.radar_height.stat().st_size
            if actual_height_size != expected_height_size:
                raise ValueError(
                    "radar height grid size mismatch: expected "
                    f"{expected_height_size} bytes from MLI {width}x{lines}, got "
                    f"{actual_height_size} bytes"
                )
            pairs_dir = staging / "PAIRS"
            pairs_dir.mkdir()
            pair_products: list[tuple[InterferogramPair, dict[str, Path]]] = []
            for offset, pair in enumerate(plan.pairs, start=len(plan.stack.assets) + 1):
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
            radar_height_project_path = _project_path(plan, plan.case.radar_height)
            provenance: dict[str, object] = {
                "backend": {"name": "gamma"},
                "baseline_manifest_project_path": baseline_manifest_project_path,
                "case_id": plan.case.case_id,
                "input_signature": signature,
                "log_dir_project_path": _project_path(plan, log_dir),
                "radar_height_project_path": radar_height_project_path,
                "radar_height_size_bytes": actual_height_size,
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
                "looks": {"azimuth": plan.case.azimuth_looks, "range": plan.case.range_looks},
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
                "registered_stack_project_path": registered_stack_project_path,
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
            with atomic_output_directory(plan.case.visualization_dir) as visual_staging:
                _render_quicklooks(
                    plan,
                    mli_assets=mli_assets,
                    average_mli=staging / "MLI/ave_mli",
                    pair_products=pair_products,
                    width=width,
                    destination=visual_staging,
                    delegate=delegate,
                    log_dir=log_dir,
                    atomic_files=False,
                )
                _add_quicklook_metadata(plan, manifest, provenance)
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
