"""Transactional GAMMA interferogram execution with project-local logs."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from geodesy_analysis.common.command import SubprocessCommandRunner
from geodesy_analysis.common.progress import emit_progress
from geodesy_analysis.io import atomic_output_directory

from .models import GammaInterferogramPlan, InterferogramPair
from .publication import ensure_nonempty, gamma_parameter, interferogram_input_signature

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


def _read_existing(
    plan: GammaInterferogramPlan, signature: str
) -> InterferogramRunSummary | None:
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
        if provenance.get("input_signature") != signature:
            raise FileExistsError(
                f"interferogram output was produced from different inputs: {output}"
            )
        if manifest.get("schema_version") != 1 or manifest.get("status") != "complete":
            raise ValueError("interferogram manifest is not complete schema version 1")
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
        return InterferogramRunSummary(
            status="skipped",
            acquisition_count=len(raw_mli),
            pair_count=len(raw_pairs),
            output_dir=output,
            warnings=tuple(manifest.get("warnings", ())),
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
    mli_dir = staging / "mli"
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
    signature = interferogram_input_signature(plan)
    existing = _read_existing(plan, signature)
    if existing is not None:
        _event(
            progress_sink,
            event="batch_finished",
            status="skipped",
            total=existing.pair_count,
            stage="publish",
        )
        return existing
    delegate = command_runner or SubprocessCommandRunner()
    log_dir = plan.case.project_root / "LOG/ANALYSIS/GAMMA/INTERFEROGRAM" / plan.case.name
    _begin_logs(log_dir)
    warnings: list[str] = []
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
            pairs_dir = staging / "pairs"
            pairs_dir.mkdir()
            quicklook_dir = staging / "quicklooks"
            quicklook_dir.mkdir()
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
                if quicklook_renderer is not None:
                    try:
                        quicklook_renderer(
                            pair=pair.name,
                            pair_dir=pair_dir,
                            width=width,
                            output_dir=quicklook_dir,
                        )
                    except Exception as error:
                        warnings.append(f"quicklook failed for {pair.name}: {error}")
                _event(
                    progress_sink,
                    event="item_finished",
                    status="complete",
                    item=pair.name,
                    index=offset,
                    total=total,
                    stage="interferogram",
                )

            provenance = {
                "baseline_manifest": str(plan.baseline.source_path),
                "input_signature": signature,
                "logs": str(log_dir),
                "radar_height": {
                    "path": str(plan.case.radar_height),
                    "size_bytes": actual_height_size,
                },
                "resolved_filter_flags": {
                    "azimuth": plan.spectral_filter_azimuth,
                    "range": plan.spectral_filter_range,
                },
            }
            (staging / "provenance.json").write_text(
                json.dumps(provenance, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
            manifest = {
                "average_mli_path": "mli/ave_mli",
                "baseline_manifest": str(plan.baseline.source_path),
                "filter_flags": {
                    "azimuth": plan.spectral_filter_azimuth,
                    "range": plan.spectral_filter_range,
                },
                "logs": str(log_dir),
                "looks": {"azimuth": plan.case.azimuth_looks, "range": plan.case.range_looks},
                "mli_assets": [
                    {
                        "data_path": f"mli/{date}.mli",
                        "date": date,
                        "parameter_path": f"mli/{date}.mli.par",
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
                "radar_height": {
                    "path": str(plan.case.radar_height),
                    "size_bytes": actual_height_size,
                },
                "reference_date": plan.stack.reference_date,
                "schema_version": 1,
                "stack_digest": plan.stack.source_digest,
                "status": "complete",
                "warnings": warnings,
            }
            (staging / "interferogram_manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
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
            warnings=tuple(warnings),
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
