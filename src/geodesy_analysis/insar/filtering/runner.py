"""Transactional execution and normalized publication for InSAR filtering."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from geodesy_analysis.common.command import SubprocessCommandRunner
from geodesy_analysis.common.progress import emit_progress
from geodesy_analysis.common.reuse import ReuseState, classify_analysis_output
from geodesy_analysis.insar.common.gamma_quicklooks import (
    coherence_quicklook_command,
    require_nonempty_quicklook,
    wrapped_phase_quicklook_command,
)
from geodesy_analysis.io import (
    atomic_output_directories,
)

from .methods.gamma.adf import adf_commands
from .methods.gamma.bm3d import bm3d_commands
from .methods.nl_insar import run_nl_insar_pair
from .models import FilteringMethod, FilteringPlan
from .publication import (
    ensure_nonempty,
    filtering_input_signature,
    filtering_parameters,
)

_TASK = "ANALYSIS_FILTERING"


@dataclass(frozen=True)
class FilteringRunSummary:
    status: str
    method: str
    pair_count: int
    output_dir: Path


def _event(sink: Callable[[str], object], **values: object) -> None:
    sink(emit_progress(task=_TASK, **values))


def _project_path(plan: FilteringPlan, path: Path) -> str:
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


def _run_commands(
    commands: Sequence[Sequence[str]],
    *,
    delegate,
    cwd: Path,
    log_dir: Path,
    pair_name: str,
) -> None:
    for index, command in enumerate(commands, start=1):
        program = command[0]
        delegate.run(
            command,
            cwd=cwd,
            stdin_text=None,
            stdout_path=log_dir / f"{pair_name}.{index:02d}.{program}.stdout.log",
            stderr_path=log_dir / f"{pair_name}.{index:02d}.{program}.stderr.log",
        )


def _validate_pair_products(plan: FilteringPlan, pair_dir: Path) -> dict[str, Path]:
    filtered = ensure_nonempty(pair_dir / "pair.tflt.filt", "filtered interferogram")
    coherence = ensure_nonempty(pair_dir / "pair.coh.filt", "filtered coherence")
    expected_complex = plan.width * plan.lines * 8
    expected_float = plan.width * plan.lines * 4
    if filtered.stat().st_size != expected_complex:
        raise ValueError("filtered interferogram byte size mismatch")
    if coherence.stat().st_size != expected_float:
        raise ValueError("filtered coherence byte size mismatch")
    values = np.fromfile(coherence, dtype=">f4")
    if not np.all(np.isfinite(values)) or np.any((values < 0.0) | (values > 1.0)):
        raise ValueError("filtered coherence must contain finite values between 0 and 1")
    return {"filtered_interferogram": filtered, "filtered_coherence": coherence}


def _mean_coherence(plan: FilteringPlan, products: list[dict[str, Path]], staging: Path) -> np.ndarray:
    total = np.zeros(plan.width * plan.lines, dtype=np.float64)
    for item in products:
        total += np.fromfile(item["filtered_coherence"], dtype=">f4")
    mean = (total / len(products)).astype(np.float32).reshape(plan.lines, plan.width)
    mean.astype(">f4").tofile(staging / "coh_ave.coh")
    return mean


def _write_coherent_points(plan: FilteringPlan, mean: np.ndarray, staging: Path) -> str | None:
    if plan.case.method is not FilteringMethod.NL_INSAR:
        return None
    directory = staging / "coherent_points"
    directory.mkdir()
    rows, columns = np.nonzero(mean > plan.case.point_threshold)
    lines = ["range,azimuth,coherence"]
    lines.extend(f"{column},{row},{mean[row, column]:.8g}" for row, column in zip(rows, columns))
    (directory / "points.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return "coherent_points/points.csv"


def _pair_quicklook_paths(plan: FilteringPlan, pair_name: str) -> dict[str, str]:
    directory = plan.case.visualization_dir
    return {
        "coherence_project_path": _project_path(
            plan, directory / f"{pair_name}.coh.filt.bmp"
        ),
        "phase_project_path": _project_path(
            plan, directory / f"{pair_name}.tflt.filt.bmp"
        ),
    }


def _add_quicklook_metadata(
    plan: FilteringPlan,
    manifest: dict[str, object],
    provenance: dict[str, object],
) -> None:
    directory = _project_path(plan, plan.case.visualization_dir)
    manifest["visualization_dir_project_path"] = directory
    for item in manifest["pairs"]:  # type: ignore[index]
        item["quicklooks"] = _pair_quicklook_paths(plan, item["pair"])
    provenance["visualization_dir_project_path"] = directory
    provenance["quicklook_commands"] = {
        "coherence": {
            "background": (
                None
                if plan.case.method is FilteringMethod.NL_INSAR
                else _project_path(plan, plan.manifest.average_mli)
            ),
            "color_map": "cc.cm",
            "command": "rasdt_pwr",
        },
        "phase": {
            "color_map": "rmg.cm",
            "command": "rasmph",
        },
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
) -> None:
    if destination.is_symlink():
        destination.unlink()
    if destination.is_file() and destination.stat().st_size:
        return
    delegate.run(
        command_factory(destination),
        cwd=cwd,
        stdin_text=None,
        stdout_path=log_dir / f"{log_stem}.stdout.log",
        stderr_path=log_dir / f"{log_stem}.stderr.log",
    )
    require_nonempty_quicklook(destination, label)


def _render_quicklooks(
    plan: FilteringPlan,
    published: list[tuple[object, dict[str, Path]]],
    *,
    destination: Path,
    delegate,
    log_dir: Path,
) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    nonlocal_mode = plan.case.method is FilteringMethod.NL_INSAR
    background = None if nonlocal_mode else plan.manifest.average_mli
    for pair, products in published:
        _run_quicklook(
            delegate,
            lambda output, data=products["filtered_interferogram"]: (
                wrapped_phase_quicklook_command(
                    data,
                    plan.width,
                    output,
                    line_start="0",
                )
            ),
            destination / f"{pair.name}.tflt.filt.bmp",
            cwd=destination,
            log_dir=log_dir,
            log_stem=f"{pair.name}.quicklook.phase",
            label=f"filtered phase quicklook for {pair.name}",
        )
        _run_quicklook(
            delegate,
            lambda output, data=products["filtered_coherence"]: (
                coherence_quicklook_command(
                    data, plan.width, output, background=background
                )
            ),
            destination / f"{pair.name}.coh.filt.bmp",
            cwd=destination,
            log_dir=log_dir,
            log_stem=f"{pair.name}.quicklook.coherence",
            label=f"filtered coherence quicklook for {pair.name}",
        )


def run_filtering(
    plan: FilteringPlan,
    *,
    command_runner: object | None = None,
    progress_sink: Callable[[str], object] | None = None,
) -> FilteringRunSummary:
    if not isinstance(plan, FilteringPlan):
        raise TypeError("plan must be FilteringPlan")
    sink = progress_sink or print
    signature = filtering_input_signature(plan)
    delegate = command_runner or SubprocessCommandRunner()
    method_dir = plan.case.method.directory_name
    log_dir = (
        plan.case.paths.processing_root / "LOG" / "ANALYSIS" / "FILTERING" / method_dir
        if plan.case.paths.processing_root is not None
        else plan.case.case_root / "LOG" / "ANALYSIS" / "FILTERING" / method_dir
    )
    reuse = classify_analysis_output(
        plan.case.output_dir, "filtering_manifest.json", signature
    )
    if reuse.science_reusable:
        manifest = reuse.manifest or {}
        expected_identity = {
            "case_id": plan.case.case_id,
            "interferogram_manifest_digest": plan.manifest.source_digest,
            "method": plan.case.method.value,
            "pair_count": len(plan.pairs),
        }
        if any(manifest.get(key) != value for key, value in expected_identity.items()):
            raise RuntimeError(
                f"filtering manifest identity is inconsistent; existing science was not modified: {plan.case.output_dir}"
            )
        if reuse.state is ReuseState.FIGURES_MISSING:
            _begin_logs(log_dir)
            published = [
                (
                    pair,
                    {
                        "filtered_interferogram": plan.case.output_dir
                        / "pairs"
                        / pair.name
                        / "pair.tflt.filt",
                        "filtered_coherence": plan.case.output_dir
                        / "pairs"
                        / pair.name
                        / "pair.coh.filt",
                    },
                )
                for pair in plan.pairs
            ]
            _render_quicklooks(
                plan,
                published,
                destination=plan.case.visualization_dir,
                delegate=delegate,
                log_dir=log_dir,
            )
            status = "figures_repaired"
        else:
            status = "skipped"
        _event(sink, event="batch_finished", status=status, stage="reuse", total=len(plan.pairs) + 1)
        return FilteringRunSummary(
            status, plan.case.method.value, len(plan.pairs), plan.case.output_dir
        )
    if reuse.state is not ReuseState.ABSENT:
        raise RuntimeError(reuse.guidance)
    if plan.case.visualization_dir.exists() or plan.case.visualization_dir.is_symlink():
        raise RuntimeError(
            "filtering science is absent but figure output already exists; inspect and delete the incomplete output group"
        )
    _begin_logs(log_dir)
    total = len(plan.pairs) + 1
    _event(sink, event="batch_started", status="start", stage="prepare", total=total)
    try:
        with atomic_output_directories(
            plan.case.visualization_dir, plan.case.output_dir
        ) as (visual_staging, staging):
            pairs_dir = staging / "pairs"
            pairs_dir.mkdir()
            published: list[tuple[object, dict[str, Path]]] = []
            for index, pair in enumerate(plan.pairs, start=1):
                _event(sink, event="item_started", status="start", item=pair.name, index=index, total=total, stage="filter")
                pair_dir = pairs_dir / pair.name
                pair_dir.mkdir()
                if plan.case.method is FilteringMethod.NL_INSAR:
                    run_nl_insar_pair(pair, plan, pair_dir)
                elif plan.case.method is FilteringMethod.GAMMA_BM3D:
                    _run_commands(bm3d_commands(pair, plan, pair_dir), delegate=delegate, cwd=pair_dir, log_dir=log_dir, pair_name=pair.name)
                else:
                    commands = adf_commands(pair, plan, pair_dir)
                    _run_commands(commands, delegate=delegate, cwd=pair_dir, log_dir=log_dir, pair_name=pair.name)
                    for temporary in (pair_dir / ".first-pass.tflt", pair_dir / ".first-pass.coh"):
                        temporary.unlink(missing_ok=True)
                products = _validate_pair_products(plan, pair_dir)
                published.append((pair, products))
                _event(sink, event="item_finished", status="complete", item=pair.name, index=index, total=total, stage="filter")
            mean = _mean_coherence(plan, [item for _, item in published], staging)
            coherent_points = _write_coherent_points(plan, mean, staging)
            source_path = _project_path(plan, plan.manifest.source_path)
            provenance: dict[str, object] = {
                "case_id": plan.case.case_id,
                "input_signature": signature,
                "interferogram_manifest_project_path": source_path,
                "log_dir_project_path": _project_path(plan, log_dir),
                "method": plan.case.method.value,
                "parameters": filtering_parameters(plan),
                "schema_version": 2,
            }
            manifest: dict[str, object] = {
                "case_id": plan.case.case_id,
                "coherent_points_path": coherent_points,
                "grid": {"lines": plan.lines, "width": plan.width},
                "input_signature": signature,
                "interferogram_manifest_digest": plan.manifest.source_digest,
                "interferogram_manifest_project_path": source_path,
                "mean_coherence_path": "coh_ave.coh",
                "method": plan.case.method.value,
                "pair_count": len(plan.pairs),
                "pairs": [
                    {
                        "pair": pair.name,
                        "products": {key: path.relative_to(staging).as_posix() for key, path in products.items()},
                    }
                    for pair, products in published
                ],
                "provenance_path": "provenance.json",
                "schema_version": 2,
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
                published,
                destination=visual_staging,
                delegate=delegate,
                log_dir=log_dir,
            )
            _add_quicklook_metadata(plan, manifest, provenance)
            required_products = [
                "coh_ave.coh",
                "provenance.json",
                *(
                    [coherent_points]
                    if coherent_points is not None
                    else []
                ),
                *[
                    relative
                    for item in manifest["pairs"]  # type: ignore[index]
                    for relative in item["products"].values()
                ],
            ]
            manifest["required_products"] = required_products
            manifest["figures"] = [
                Path(
                    os.path.relpath(
                        plan.case.visualization_dir / name,
                        start=plan.case.output_dir,
                    )
                ).as_posix()
                for pair in plan.pairs
                for name in (
                    f"{pair.name}.tflt.filt.bmp",
                    f"{pair.name}.coh.filt.bmp",
                )
            ]
            (staging / "provenance.json").write_text(
                json.dumps(provenance, ensure_ascii=False, sort_keys=True, indent=2)
                + "\n",
                encoding="utf-8",
            )
            (staging / "filtering_manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2)
                + "\n",
                encoding="utf-8",
            )
        _event(sink, event="batch_finished", status="complete", stage="publish", index=total, total=total)
        return FilteringRunSummary("complete", plan.case.method.value, len(plan.pairs), plan.case.output_dir)
    except BaseException:
        failed = _preserve_failed_logs(log_dir)
        _event(sink, event="batch_finished", status="failed", stage="failed", total=total, failure_logs=str(failed))
        raise


__all__ = ["FilteringRunSummary", "run_filtering"]
