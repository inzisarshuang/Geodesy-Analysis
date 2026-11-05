"""Transactional execution and publication for GAMMA quad phase detrending."""

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
    require_nonempty_quicklook,
    unwrapped_phase_quicklook_command,
)
from geodesy_analysis.insar.masking import coherence_mask, write_mask
from geodesy_analysis.io import atomic_output_directories

from .models import GammaQuadDetrendPlan, GammaQuadPair
from .publication import quad_detrend_input_signature

_TASK = "ANALYSIS_GAMMA_QUAD_DETREND"


@dataclass(frozen=True)
class GammaQuadDetrendRunSummary:
    status: str
    pair_count: int
    output_dir: Path


def _project_path(plan: GammaQuadDetrendPlan, path: Path) -> str:
    resolved = Path(path).resolve()
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
    if active.exists():
        os.replace(active, _failed_log_directory(active))
    active.mkdir()


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


def _create_diff_par_command(pair: GammaQuadPair, output: Path) -> tuple[str, ...]:
    return (
        "create_diff_par",
        str(pair.master_mli_parameter),
        "-",
        str(output),
        "1",
        "0",
    )


def _quad_fit_command(
    pair: GammaQuadPair,
    diff_par: Path,
    mask: Path,
    plot_data: Path,
    trend_model: int,
) -> tuple[str, ...]:
    return (
        "quad_fit",
        str(pair.unwrapped),
        str(diff_par),
        "-",
        "-",
        str(mask),
        str(plot_data),
        str(trend_model),
    )


def _quad_sub_command(pair: GammaQuadPair, diff_par: Path, output: Path) -> tuple[str, ...]:
    return ("quad_sub", str(pair.unwrapped), str(diff_par), str(output), "0", "0")


def _validate_raster(path: Path, expected_size: int, label: str) -> int:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"{label} is missing: {path}")
    if path.stat().st_size != expected_size:
        raise ValueError(f"{label} byte size mismatch: {path}")
    values = np.memmap(path, dtype=">f4", mode="r")
    finite_count = int(np.count_nonzero(np.isfinite(values)))
    del values
    if finite_count == 0:
        raise ValueError(f"{label} contains no finite values: {path}")
    return finite_count


def _render_quicklook(
    plan: GammaQuadDetrendPlan,
    pair: GammaQuadPair,
    unwrapped: Path,
    *,
    destination: Path,
    delegate: object,
    log_dir: Path,
) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    quicklook = destination / f"{pair.name}.quad.unw.bmp"
    if quicklook.is_symlink():
        quicklook.unlink()
    if quicklook.is_file() and quicklook.stat().st_size:
        return quicklook
    _call(
        delegate,
        unwrapped_phase_quicklook_command(
            unwrapped,
            plan.width,
            quicklook,
            background=pair.master_mli if plan.case.intensity_background else None,
        ),
        cwd=destination,
        log_dir=log_dir,
        stem=f"{pair.name}.quicklook",
    )
    require_nonempty_quicklook(
        quicklook, f"detrended phase quicklook for {pair.name}"
    )
    return quicklook


def run_gamma_quad_detrend(
    plan: GammaQuadDetrendPlan,
    *,
    command_runner: object | None = None,
    progress_sink: Callable[[str], object] | None = None,
) -> GammaQuadDetrendRunSummary:
    if not isinstance(plan, GammaQuadDetrendPlan):
        raise TypeError("plan must be GammaQuadDetrendPlan")
    sink = progress_sink or print
    delegate = command_runner or SubprocessCommandRunner()
    signature = quad_detrend_input_signature(plan)
    log_dir = (
        plan.case.paths.processing_root / "LOG/ANALYSIS/DETRENDING/GAMMA_QUAD"
        if plan.case.paths.processing_root is not None
        else plan.case.case_root / "LOG/ANALYSIS/DETRENDING/GAMMA_QUAD"
    )
    reuse = classify_analysis_output(
        plan.case.output_dir, "detrending_manifest.json", signature
    )
    if reuse.science_reusable:
        manifest = reuse.manifest or {}
        expected_identity = {
            "case_id": plan.case.case_id,
            "method": "gamma_quad_detrending",
            "pair_count": len(plan.pairs),
            "unwrapping_manifest_digest": plan.unwrapping_manifest_digest,
        }
        if any(manifest.get(key) != value for key, value in expected_identity.items()):
            raise RuntimeError(
                f"detrending manifest identity is inconsistent; existing science was not modified: {plan.case.output_dir}"
            )
        if reuse.state is ReuseState.FIGURES_MISSING:
            _begin_logs(log_dir)
            for pair in plan.pairs:
                _render_quicklook(
                    plan,
                    pair,
                    plan.case.output_dir / "pairs" / pair.name / "pair.quad.unw",
                    destination=plan.case.visualization_dir,
                    delegate=delegate,
                    log_dir=log_dir,
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
                total=len(plan.pairs),
            )
        )
        return GammaQuadDetrendRunSummary(status, len(plan.pairs), plan.case.output_dir)
    if reuse.state is not ReuseState.ABSENT:
        raise RuntimeError(reuse.guidance)
    if plan.case.visualization_dir.exists() or plan.case.visualization_dir.is_symlink():
        raise RuntimeError(
            "detrending science is absent but figure output already exists; inspect and delete the incomplete output group"
        )
    _begin_logs(log_dir)
    total = len(plan.pairs)
    _event = lambda **values: sink(
        emit_progress(task=_TASK, **values)
    )
    expected_size = plan.width * plan.lines * 4
    try:
        with atomic_output_directories(
            plan.case.visualization_dir, plan.case.output_dir
        ) as (visual_staging, staging):
            pairs_dir = staging / "pairs"
            pairs_dir.mkdir()
            products: list[dict[str, object]] = []
            visual_staging.mkdir(exist_ok=True)
            for index, pair in enumerate(plan.pairs, start=1):
                _event(
                    event="item_started",
                    status="start",
                    item=pair.name,
                    index=index,
                    total=total,
                    stage="detrend",
                )
                pair_dir = pairs_dir / pair.name
                pair_dir.mkdir()
                diff_par = pair_dir / "pair.diff.quad.par"
                plot_data = pair_dir / "pair.plot_data"
                mask_path = pair_dir / "pair.coherence_mask.bmp"
                output = pair_dir / "pair.quad.unw"
                coherence = np.fromfile(pair.coherence, dtype=">f4").reshape(
                    plan.lines, plan.width
                )
                if not np.all(np.isfinite(coherence)) or np.any(
                    (coherence < 0.0) | (coherence > 1.0)
                ):
                    raise ValueError(
                        f"filtered coherence must be finite and within [0, 1]: {pair.name}"
                    )
                mask = coherence_mask(coherence, plan.case.coherence_threshold)
                valid_count = int(np.count_nonzero(mask))
                if valid_count == 0:
                    raise ValueError(
                        f"coherence threshold leaves no pixels for quad_fit: {pair.name}"
                    )
                write_mask(mask, str(mask_path))

                _call(
                    delegate,
                    _create_diff_par_command(pair, diff_par),
                    cwd=pair_dir,
                    log_dir=log_dir,
                    stem=f"{pair.name}.create_diff_par",
                )
                if not diff_par.is_file() or diff_par.stat().st_size == 0:
                    raise RuntimeError(f"create_diff_par did not produce {diff_par}")
                _call(
                    delegate,
                    _quad_fit_command(
                        pair, diff_par, mask_path, plot_data, plan.case.trend_model
                    ),
                    cwd=pair_dir,
                    log_dir=log_dir,
                    stem=f"{pair.name}.quad_fit",
                )
                if not plot_data.is_file() or plot_data.stat().st_size == 0:
                    raise RuntimeError(f"quad_fit did not produce {plot_data}")
                _call(
                    delegate,
                    _quad_sub_command(pair, diff_par, output),
                    cwd=pair_dir,
                    log_dir=log_dir,
                    stem=f"{pair.name}.quad_sub",
                )
                finite_count = _validate_raster(
                    output, expected_size, "detrended unwrapped phase"
                )
                quicklook = _render_quicklook(
                    plan,
                    pair,
                    output,
                    destination=visual_staging,
                    delegate=delegate,
                    log_dir=log_dir,
                )
                products.append(
                    {
                        "coherence_project_path": _project_path(plan, pair.coherence),
                        "finite_count": finite_count,
                        "master_mli_project_path": _project_path(plan, pair.master_mli),
                        "pair": pair.name,
                        "products": {
                            "coherence_mask": mask_path.relative_to(staging).as_posix(),
                            "diff_parameter": diff_par.relative_to(staging).as_posix(),
                            "plot_data": plot_data.relative_to(staging).as_posix(),
                            "detrended_unwrapped": output.relative_to(staging).as_posix(),
                        },
                        "quicklook_project_path": _project_path(
                            plan, plan.case.visualization_dir / quicklook.name
                        ),
                        "unwrapped_source_project_path": _project_path(
                            plan, pair.unwrapped
                        ),
                        "valid_mask_count": valid_count,
                    }
                )
                _event(
                    event="item_finished",
                    status="complete",
                    item=pair.name,
                    index=index,
                    total=total,
                    stage="detrend",
                )

            pair_selection = {
                "available_pair_count": plan.available_pair_count,
                "mode": "all" if plan.case.pair_list is None else "list",
                "pair_list_project_path": (
                    None
                    if plan.case.pair_list is None
                    else _project_path(plan, plan.case.pair_list)
                ),
                "pair_list_sha256": plan.pair_list_digest,
                "selected_pairs": [pair.name for pair in plan.pairs],
            }
            manifest: dict[str, object] = {
                "case_id": plan.case.case_id,
                "coherence_threshold": plan.case.coherence_threshold,
                "filtering_manifest_digest": plan.filtering_manifest_digest,
                "filtering_manifest_project_path": _project_path(
                    plan, plan.filtering_manifest
                ),
                "grid": {"lines": plan.lines, "width": plan.width},
                "input_signature": signature,
                "interferogram_manifest_digest": plan.interferogram_manifest_digest,
                "interferogram_manifest_project_path": _project_path(
                    plan, plan.interferogram_manifest
                ),
                "method": "gamma_quad_detrending",
                "pair_count": len(products),
                "pair_selection": pair_selection,
                "pairs": products,
                "provenance_path": "provenance.json",
                "schema_version": 2,
                "status": "complete",
                "trend_model": plan.case.trend_model,
                "intensity_background": plan.case.intensity_background,
                "unwrapping_manifest_digest": plan.unwrapping_manifest_digest,
                "unwrapping_manifest_project_path": _project_path(
                    plan, plan.case.unwrapping_manifest
                ),
                "visualization_dir_project_path": _project_path(
                    plan, plan.case.visualization_dir
                ),
            }
            manifest["scientific_manifest_digest"] = hashlib.sha256(
                (
                    json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2)
                    + "\n"
                ).encode("utf-8")
            ).hexdigest()
            manifest["required_products"] = [
                *[
                    relative
                    for item in manifest["pairs"]  # type: ignore[index]
                    for relative in item["products"].values()
                ],
                "provenance.json",
            ]
            manifest["figures"] = [
                Path(
                    os.path.relpath(
                        plan.case.visualization_dir / f"{pair.name}.quad.unw.bmp",
                        start=plan.case.output_dir,
                    )
                ).as_posix()
                for pair in plan.pairs
            ]
            provenance: dict[str, object] = {
                "case_id": plan.case.case_id,
                "commands": {
                    "create_diff_par": ["create_diff_par", "master.mli.par", "-", "pair.diff.quad.par", "1", "0"],
                    "quad_fit": ["quad_fit", "unwrapped", "diff_parameter", "-", "-", "coherence_mask", "plot_data", str(plan.case.trend_model)],
                    "quad_sub": ["quad_sub", "unwrapped", "diff_parameter", "detrended_unwrapped", "0", "0"],
                    "quicklook": {
                        "background": (
                            "master MLI"
                            if plan.case.intensity_background
                            else None
                        ),
                        "color_map": "rmg.cm",
                        "command": "rasdt_pwr",
                    },
                },
                "coherence_threshold": plan.case.coherence_threshold,
                "input_signature": signature,
                "log_dir_project_path": _project_path(plan, log_dir),
                "pair_selection": pair_selection,
                "schema_version": 2,
                "trend_model": plan.case.trend_model,
                "intensity_background": plan.case.intensity_background,
            }
            (staging / "provenance.json").write_text(
                json.dumps(provenance, ensure_ascii=False, sort_keys=True, indent=2)
                + "\n",
                encoding="utf-8",
            )
            (staging / "detrending_manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2)
                + "\n",
                encoding="utf-8",
            )
        _event(
            event="batch_finished",
            status="complete",
            stage="publish",
            index=total,
            total=total,
        )
        return GammaQuadDetrendRunSummary("complete", total, plan.case.output_dir)
    except BaseException:
        failure_logs = _failed_log_directory(log_dir)
        if log_dir.exists():
            os.replace(log_dir, failure_logs)
        _event(
            event="batch_finished",
            status="failed",
            stage="failed",
            total=total,
            failure_logs=str(failure_logs),
        )
        raise


__all__ = [
    "GammaQuadDetrendRunSummary",
    "run_gamma_quad_detrend",
]
