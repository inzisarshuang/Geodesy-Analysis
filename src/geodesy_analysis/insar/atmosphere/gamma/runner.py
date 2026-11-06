"""Transactional GAMMA atmosphere execution and schema-v2 publication."""

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
from geodesy_analysis.insar.common.gamma_quicklooks import (
    atmosphere_phase_quicklook_command,
    require_nonempty_quicklook,
)
from geodesy_analysis.io import atomic_output_directories

from .models import GammaAtmospherePair, GammaAtmospherePlan
from .publication import gamma_atmosphere_input_signature

_TASK = "ANALYSIS_GAMMA_ATMOSPHERE"


@dataclass(frozen=True)
class GammaAtmosphereRunSummary:
    status: str
    pair_count: int
    output_dir: Path


def _portable(plan: GammaAtmospherePlan, path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(plan.case.project_root).as_posix()
    except ValueError:
        return resolved.as_posix()


def _failed_log_directory(active: Path) -> Path:
    index = 1
    while True:
        candidate = active.with_name(f"{active.name}.failed-logs-{index}")
        if not candidate.exists():
            return candidate
        index += 1


def _begin_logs(active: Path) -> None:
    active.parent.mkdir(parents=True, exist_ok=True)
    if active.exists() or active.is_symlink():
        os.replace(active, _failed_log_directory(active))
    active.mkdir()


def _preserve_logs(active: Path) -> Path:
    failed = _failed_log_directory(active)
    if active.exists() or active.is_symlink():
        os.replace(active, failed)
    return failed


def _event(sink: Callable[[str], object], **values: object) -> None:
    sink(emit_progress(task=_TASK, **values))


def _call(
    delegate: object,
    command: tuple[str, ...],
    *,
    cwd: Path,
    log_dir: Path,
    stem: str,
) -> None:
    delegate.run(
        command,
        cwd=cwd,
        stdin_text=None,
        stdout_path=log_dir / f"{stem}.stdout.log",
        stderr_path=log_dir / f"{stem}.stderr.log",
    )


def _number(value: float) -> str:
    return f"{value:g}"


def _require_nonempty(path: Path, label: str) -> Path:
    if path.is_symlink() or not path.is_file() or path.stat().st_size < 1:
        raise RuntimeError(f"{label} is missing or empty: {path}")
    return path


def _validate_float(path: Path, expected_size: int, label: str) -> int:
    _require_nonempty(path, label)
    if path.stat().st_size != expected_size:
        raise ValueError(f"{label} byte size mismatch: {path}")
    values = np.memmap(path, dtype=">f4", mode="r")
    finite = int(np.count_nonzero(np.isfinite(values)))
    del values
    if finite == 0:
        raise ValueError(f"{label} contains no finite values: {path}")
    return finite


def _create_diff_par(
    plan: GammaAtmospherePlan, pair: GammaAtmospherePair, output: Path
) -> tuple[str, ...]:
    return (
        plan.commands.create_diff_par,
        str(pair.master_mli_parameter),
        "-",
        str(output),
        "1",
        "0",
    )


def _atm_mod(
    plan: GammaAtmospherePlan,
    source: Path,
    pair: GammaAtmospherePair,
    diff_parameter: Path,
    mask: Path,
    a0: Path,
    a1: Path,
) -> tuple[str, ...]:
    return (
        plan.commands.atm_mod_2d,
        str(source),
        str(plan.radar_height),
        str(pair.coherence),
        str(diff_parameter),
        str(mask),
        "1",
        str(a0),
        str(a1),
        "-",
        "-",
        "-",
        str(plan.case.fit_window_range),
        str(plan.case.fit_window_azimuth),
        str(plan.case.fit_step_range),
        str(plan.case.fit_step_azimuth),
        "-",
        "-",
        _number(plan.case.height_correlation_threshold),
    )


def _render_quicklook(
    plan: GammaAtmospherePlan,
    pair: GammaAtmospherePair,
    data: Path,
    output: Path,
    *,
    delegate: object,
    log_dir: Path,
    label: str,
    background: bool,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    _call(
        delegate,
        atmosphere_phase_quicklook_command(
            data,
            plan.width,
            output,
            background=(
                pair.master_mli
                if background and plan.case.intensity_background
                else None
            ),
        ),
        cwd=output.parent,
        log_dir=log_dir,
        stem=f"{pair.name}.{label}.quicklook",
    )
    require_nonempty_quicklook(output, f"{label} for {pair.name}")


def _quicklook_paths(
    plan: GammaAtmospherePlan, pair: GammaAtmospherePair, directory: Path
) -> dict[str, Path]:
    paths = {"corrected": directory / f"{pair.name}.corrected.bmp"}
    if plan.case.method != "none":
        paths["atmosphere"] = directory / f"{pair.name}.atmosphere.bmp"
    if plan.case.method == "gamma_atm_mod_2d_polygon":
        paths["outside_mask"] = directory / f"{pair.name}.outside.mask.bmp"
    return paths


def _repair_quicklooks(
    plan: GammaAtmospherePlan,
    *,
    manifest: dict[str, object],
    delegate: object,
    log_dir: Path,
) -> None:
    records = {
        item.get("pair"): item
        for item in manifest.get("pairs", [])
        if isinstance(item, dict)
    }
    for pair in plan.pairs:
        record = records.get(pair.name)
        if not isinstance(record, dict):
            raise RuntimeError(f"atmosphere manifest is missing pair: {pair.name}")
        products = record.get("products")
        if not isinstance(products, dict):
            raise RuntimeError(f"atmosphere pair products are invalid: {pair.name}")
        quicklooks = _quicklook_paths(plan, pair, plan.case.figure_dir)
        if not quicklooks["corrected"].is_file():
            corrected_value = record.get("corrected_phase_project_path")
            if not isinstance(corrected_value, str):
                raise RuntimeError(f"corrected phase identity is missing: {pair.name}")
            corrected = Path(corrected_value)
            if not corrected.is_absolute():
                corrected = plan.case.project_root / corrected
            _render_quicklook(
                plan,
                pair,
                corrected,
                quicklooks["corrected"],
                delegate=delegate,
                log_dir=log_dir,
                label="corrected",
                background=True,
            )
        if "atmosphere" in quicklooks and not quicklooks["atmosphere"].is_file():
            atmosphere_value = products.get("atmosphere_phase")
            if not isinstance(atmosphere_value, str):
                raise RuntimeError(f"atmosphere phase identity is missing: {pair.name}")
            _render_quicklook(
                plan,
                pair,
                plan.case.output_dir / atmosphere_value,
                quicklooks["atmosphere"],
                delegate=delegate,
                log_dir=log_dir,
                label="atmosphere",
                background=False,
            )
        if "outside_mask" in quicklooks and not quicklooks["outside_mask"].is_file():
            mask_value = products.get("outside_mask")
            if not isinstance(mask_value, str):
                raise RuntimeError(f"outside mask identity is missing: {pair.name}")
            _render_quicklook(
                plan,
                pair,
                plan.case.output_dir / mask_value,
                quicklooks["outside_mask"],
                delegate=delegate,
                log_dir=log_dir,
                label="outside_mask",
                background=False,
            )


def _run_pair(
    plan: GammaAtmospherePlan,
    pair: GammaAtmospherePair,
    *,
    pair_dir: Path | None,
    figure_dir: Path,
    delegate: object,
    log_dir: Path,
) -> dict[str, object]:
    quicklooks = _quicklook_paths(plan, pair, figure_dir)
    if plan.case.method == "none":
        _render_quicklook(
            plan,
            pair,
            pair.detrended_phase,
            quicklooks["corrected"],
            delegate=delegate,
            log_dir=log_dir,
            label="corrected",
            background=True,
        )
        return {
            "coherence_project_path": _portable(plan, pair.coherence),
            "corrected_phase_path": None,
            "corrected_phase_project_path": _portable(
                plan, pair.detrended_phase
            ),
            "corrected_phase_storage": "external",
            "master_mli_project_path": _portable(plan, pair.master_mli),
            "pair": pair.name,
            "products": {},
            "quicklooks": {
                "corrected_project_path": _portable(
                    plan, plan.case.figure_dir / quicklooks["corrected"].name
                )
            },
            "source_detrended_phase_project_path": _portable(
                plan, pair.detrended_phase
            ),
        }

    assert pair_dir is not None
    pair_dir.mkdir()
    expected_size = plan.width * plan.lines * 4
    diff_parameter = pair_dir / "pair.diff.atm.par"
    a0 = pair_dir / "pair.atm.a0"
    a1 = pair_dir / "pair.atm.a1"
    atmosphere_phase = pair_dir / "pair.atm.phase"
    corrected = pair_dir / "pair.atm.unw"
    source = pair.detrended_phase
    products: dict[str, Path] = {}

    if plan.case.method == "gamma_fspf_atm_mod_2d":
        filtered = pair_dir / "pair.fspf.unw"
        _call(
            delegate,
            (
                plan.commands.fspf,
                str(pair.detrended_phase),
                str(filtered),
                str(plan.width),
                str(plan.case.fspf_mode),
                str(plan.case.fspf_window_size),
                str(plan.case.fspf_overlap),
            ),
            cwd=pair_dir,
            log_dir=log_dir,
            stem=f"{pair.name}.fspf",
        )
        _validate_float(filtered, expected_size, "FSPF phase")
        products["fspf_phase"] = filtered
        source = filtered

    outside_mask_bmp: Path | None = None
    if plan.case.method == "gamma_atm_mod_2d_polygon":
        assert plan.case.polygon_file is not None
        outside_mask = pair_dir / "pair.outside.mask"
        _call(
            delegate,
            (
                plan.commands.poly_mask,
                str(pair.detrended_phase),
                str(outside_mask),
                str(plan.width),
                str(plan.case.polygon_file),
                "1",
                "0",
            ),
            cwd=pair_dir,
            log_dir=log_dir,
            stem=f"{pair.name}.outside_mask",
        )
        _validate_float(outside_mask, expected_size, "polygon outside mask")
        outside_mask_bmp = quicklooks["outside_mask"]
        _render_quicklook(
            plan,
            pair,
            outside_mask,
            outside_mask_bmp,
            delegate=delegate,
            log_dir=log_dir,
            label="outside_mask",
            background=False,
        )
        products["outside_mask"] = outside_mask

    _call(
        delegate,
        _create_diff_par(plan, pair, diff_parameter),
        cwd=pair_dir,
        log_dir=log_dir,
        stem=f"{pair.name}.create_diff_par",
    )
    _require_nonempty(diff_parameter, "atmosphere difference parameter")
    model_mask = outside_mask_bmp or plan.auto_mask
    _call(
        delegate,
        _atm_mod(plan, source, pair, diff_parameter, model_mask, a0, a1),
        cwd=pair_dir,
        log_dir=log_dir,
        stem=f"{pair.name}.atm_mod_2d",
    )
    _require_nonempty(a0, "atmosphere model a0")
    _require_nonempty(a1, "atmosphere model a1")
    sim_tail = (
        (str(plan.auto_mask),)
        if plan.case.method == "gamma_fspf_atm_mod_2d"
        else (("-",) if plan.case.method == "gamma_atm_mod_2d_polygon" else ("-", "-"))
    )
    _call(
        delegate,
        (
            plan.commands.atm_sim_2d,
            str(diff_parameter),
            str(plan.radar_height),
            str(a0),
            str(a1),
            str(atmosphere_phase),
            *sim_tail,
        ),
        cwd=pair_dir,
        log_dir=log_dir,
        stem=f"{pair.name}.atm_sim_2d",
    )
    _validate_float(atmosphere_phase, expected_size, "simulated atmosphere phase")

    if plan.case.method == "gamma_atm_mod_2d_polygon":
        outside_phase = pair_dir / "pair.outside.unw"
        inside_phase = pair_dir / "pair.inside.unw"
        _call(
            delegate,
            (
                plan.commands.sub_phase,
                str(pair.detrended_phase),
                str(atmosphere_phase),
                str(diff_parameter),
                str(outside_phase),
                "0",
                "0",
                "0",
            ),
            cwd=pair_dir,
            log_dir=log_dir,
            stem=f"{pair.name}.outside_sub_phase",
        )
        _validate_float(outside_phase, expected_size, "outside corrected phase")
        assert plan.case.polygon_file is not None
        _call(
            delegate,
            (
                plan.commands.poly_mask,
                str(pair.detrended_phase),
                str(inside_phase),
                str(plan.width),
                str(plan.case.polygon_file),
                "0",
                "0",
            ),
            cwd=pair_dir,
            log_dir=log_dir,
            stem=f"{pair.name}.inside_mask",
        )
        _validate_float(inside_phase, expected_size, "protected inside phase")
        _call(
            delegate,
            (
                plan.commands.float_math,
                str(outside_phase),
                str(inside_phase),
                str(corrected),
                str(plan.width),
                "0",
                "-",
                "-",
                "-",
                "-",
                "-",
                "1",
            ),
            cwd=pair_dir,
            log_dir=log_dir,
            stem=f"{pair.name}.merge",
        )
        products["outside_corrected_phase"] = outside_phase
        products["inside_protected_phase"] = inside_phase
    else:
        _call(
            delegate,
            (
                plan.commands.sub_phase,
                str(source),
                str(atmosphere_phase),
                str(diff_parameter),
                str(corrected),
                "0",
                "0",
            ),
            cwd=pair_dir,
            log_dir=log_dir,
            stem=f"{pair.name}.sub_phase",
        )
    finite_count = _validate_float(corrected, expected_size, "corrected phase")

    _render_quicklook(
        plan,
        pair,
        atmosphere_phase,
        quicklooks["atmosphere"],
        delegate=delegate,
        log_dir=log_dir,
        label="atmosphere",
        background=False,
    )
    _render_quicklook(
        plan,
        pair,
        corrected,
        quicklooks["corrected"],
        delegate=delegate,
        log_dir=log_dir,
        label="corrected",
        background=True,
    )
    products.update(
        {
            "diff_parameter": diff_parameter,
            "model_a0": a0,
            "model_a1": a1,
            "atmosphere_phase": atmosphere_phase,
            "corrected_phase": corrected,
        }
    )
    return {
        "coherence_project_path": _portable(plan, pair.coherence),
        "corrected_finite_count": finite_count,
        "corrected_phase_path": corrected.relative_to(pair_dir.parent.parent).as_posix(),
        "corrected_phase_project_path": _portable(
            plan, plan.case.output_dir / corrected.relative_to(pair_dir.parent.parent)
        ),
        "corrected_phase_storage": "local",
        "master_mli_project_path": _portable(plan, pair.master_mli),
        "pair": pair.name,
        "products": {
            key: value.relative_to(pair_dir.parent.parent).as_posix()
            for key, value in products.items()
        },
        "quicklooks": {
            key + "_project_path": _portable(
                plan, plan.case.figure_dir / value.name
            )
            for key, value in quicklooks.items()
        },
        "source_detrended_phase_project_path": _portable(
            plan, pair.detrended_phase
        ),
    }


def run_gamma_atmosphere(
    plan: GammaAtmospherePlan,
    *,
    command_runner: object | None = None,
    progress_sink: Callable[[str], object] | None = None,
) -> GammaAtmosphereRunSummary:
    """Execute one validated atmosphere plan and publish both trees atomically."""

    if not isinstance(plan, GammaAtmospherePlan):
        raise TypeError("plan must be GammaAtmospherePlan")
    sink = progress_sink or print
    delegate = command_runner or SubprocessCommandRunner()
    signature = gamma_atmosphere_input_signature(plan)
    reuse = classify_analysis_output(
        plan.case.output_dir,
        "atmosphere_manifest.json",
        signature,
        project_root=plan.case.project_root,
    )
    if reuse.science_reusable:
        manifest = reuse.manifest or {}
        identity = {
            "case_id": plan.case.case_id,
            "detrending_manifest_digest": plan.detrending_manifest_digest,
            "method": plan.case.method,
            "pair_count": len(plan.pairs),
        }
        if any(manifest.get(key) != value for key, value in identity.items()) or [
            item.get("pair")
            for item in manifest.get("pairs", [])
            if isinstance(item, dict)
        ] != [pair.name for pair in plan.pairs]:
            raise RuntimeError(
                "atmosphere manifest identity is inconsistent; existing science "
                f"was not modified: {plan.case.output_dir}"
            )
        if reuse.state is ReuseState.FIGURES_MISSING:
            _begin_logs(plan.case.log_dir)
            _repair_quicklooks(
                plan,
                manifest=manifest,
                delegate=delegate,
                log_dir=plan.case.log_dir,
            )
            status = "figures_repaired"
        else:
            status = "skipped"
        _event(
            sink,
            event="batch_finished",
            status=status,
            stage="reuse",
            total=len(plan.pairs),
        )
        return GammaAtmosphereRunSummary(status, len(plan.pairs), plan.case.output_dir)
    if reuse.state is not ReuseState.ABSENT:
        raise RuntimeError(reuse.guidance)
    if plan.case.figure_dir.exists() or plan.case.figure_dir.is_symlink():
        raise RuntimeError(
            "atmosphere science is absent but figure output already exists; inspect "
            "and delete the incomplete output group"
        )

    _begin_logs(plan.case.log_dir)
    total = len(plan.pairs)
    _event(sink, event="batch_started", status="start", stage="prepare", total=total)
    try:
        with atomic_output_directories(
            plan.case.figure_dir, plan.case.output_dir
        ) as (figure_staging, staging):
            pairs_dir = staging / "PAIRS"
            if plan.case.method != "none":
                pairs_dir.mkdir()
            records: list[dict[str, object]] = []
            for index, pair in enumerate(plan.pairs, start=1):
                _event(
                    sink,
                    event="item_started",
                    status="start",
                    item=pair.name,
                    index=index,
                    total=total,
                    stage="atmosphere",
                )
                record = _run_pair(
                    plan,
                    pair,
                    pair_dir=(
                        None
                        if plan.case.method == "none"
                        else pairs_dir / pair.name
                    ),
                    figure_dir=figure_staging,
                    delegate=delegate,
                    log_dir=plan.case.log_dir,
                )
                records.append(record)
                _event(
                    sink,
                    event="item_finished",
                    status="complete",
                    item=pair.name,
                    index=index,
                    total=total,
                    stage="atmosphere",
                )

            method_parameters = {
                "fit_step_azimuth": plan.case.fit_step_azimuth,
                "fit_step_range": plan.case.fit_step_range,
                "fit_window_azimuth": plan.case.fit_window_azimuth,
                "fit_window_range": plan.case.fit_window_range,
                "fspf_mode": plan.case.fspf_mode,
                "fspf_overlap": plan.case.fspf_overlap,
                "fspf_window_size": plan.case.fspf_window_size,
                "height_correlation_threshold": (
                    plan.case.height_correlation_threshold
                ),
                "polygon_sha256": plan.polygon_digest,
            }
            manifest: dict[str, object] = {
                "auto_mask_project_path": _portable(plan, plan.auto_mask),
                "case_id": plan.case.case_id,
                "detrending_manifest_digest": plan.detrending_manifest_digest,
                "detrending_manifest_project_path": _portable(
                    plan, plan.case.detrending_manifest
                ),
                "filtering_manifest_digest": plan.filtering_manifest_digest,
                "filtering_manifest_project_path": _portable(
                    plan, plan.filtering_manifest
                ),
                "grid": {"lines": plan.lines, "width": plan.width},
                "input_signature": signature,
                "interferogram_manifest_digest": plan.interferogram_manifest_digest,
                "interferogram_manifest_project_path": _portable(
                    plan, plan.interferogram_manifest
                ),
                "method": plan.case.method,
                "method_parameters": method_parameters,
                "pair_count": len(records),
                "pairs": records,
                "provenance_path": "provenance.json",
                "radar_height_project_path": _portable(
                    plan, plan.radar_height
                ),
                "schema_version": 2,
                "status": "complete",
                "unwrapping_manifest_digest": plan.unwrapping_manifest_digest,
                "unwrapping_manifest_project_path": _portable(
                    plan, plan.unwrapping_manifest
                ),
                "figure_dir_project_path": _portable(
                    plan, plan.case.figure_dir
                ),
            }
            manifest["scientific_manifest_digest"] = hashlib.sha256(
                (
                    json.dumps(
                        manifest, ensure_ascii=False, sort_keys=True, indent=2
                    )
                    + "\n"
                ).encode("utf-8")
            ).hexdigest()
            manifest["required_products"] = [
                *[
                    value
                    for item in records
                    for value in item["products"].values()  # type: ignore[union-attr]
                ],
                "provenance.json",
            ]
            manifest["required_external_products"] = (
                [
                    item["corrected_phase_project_path"]
                    for item in records
                ]
                if plan.case.method == "none"
                else []
            )
            figures = [
                plan.case.figure_dir / path.name
                for pair in plan.pairs
                for path in _quicklook_paths(plan, pair, figure_staging).values()
            ]
            manifest["figures"] = [
                Path(os.path.relpath(path, start=plan.case.output_dir)).as_posix()
                for path in figures
            ]
            provenance = {
                "case_id": plan.case.case_id,
                "commands": {
                    key: value
                    for key, value in vars(plan.commands).items()
                },
                "input_signature": signature,
                "intensity_background": plan.case.intensity_background,
                "log_dir_project_path": _portable(plan, plan.case.log_dir),
                "method": plan.case.method,
                "method_parameters": method_parameters,
                "polygon_project_path": (
                    None
                    if plan.case.polygon_file is None
                    else _portable(plan, plan.case.polygon_file)
                ),
                "schema_version": 2,
            }
            (staging / "provenance.json").write_text(
                json.dumps(provenance, ensure_ascii=False, sort_keys=True, indent=2)
                + "\n",
                encoding="utf-8",
            )
            (staging / "atmosphere_manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2)
                + "\n",
                encoding="utf-8",
            )
        _event(
            sink,
            event="batch_finished",
            status="complete",
            stage="publish",
            index=total,
            total=total,
        )
        return GammaAtmosphereRunSummary("complete", total, plan.case.output_dir)
    except BaseException:
        failed = _preserve_logs(plan.case.log_dir)
        _event(
            sink,
            event="batch_finished",
            status="failed",
            stage="failed",
            total=total,
            failure_logs=str(failed),
        )
        raise


__all__ = ["GammaAtmosphereRunSummary", "run_gamma_atmosphere"]
