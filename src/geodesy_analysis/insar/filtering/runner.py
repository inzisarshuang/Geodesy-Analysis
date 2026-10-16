"""Transactional execution and normalized publication for InSAR filtering."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from geodesy_analysis.common.command import SubprocessCommandRunner
from geodesy_analysis.common.progress import emit_progress
from geodesy_analysis.io import atomic_output_directory

from .methods.gamma.adf import adf_commands
from .methods.gamma.bm3d import bm3d_commands
from .methods.nl_insar import run_nl_insar_pair
from .models import FilteringMethod, FilteringPlan
from .publication import ensure_nonempty, filtering_input_signature

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
    except ValueError as error:
        raise ValueError(f"filtering path leaves project root: {resolved}") from error


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


def _published(output: Path, value: object, label: str, size: int) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"filtering manifest {label} path is required")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"filtering manifest {label} path is unsafe")
    path = ensure_nonempty(output / relative, label)
    if path.stat().st_size != size:
        raise ValueError(f"filtering manifest {label} byte size mismatch")
    return path


def _read_existing(plan: FilteringPlan, signature: str) -> FilteringRunSummary | None:
    output = plan.case.output_dir
    if not output.exists():
        return None
    try:
        manifest = json.loads((output / "filtering_manifest.json").read_text(encoding="utf-8"))
        provenance = json.loads((output / "provenance.json").read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or not isinstance(provenance, dict):
            raise ValueError("filtering manifest and provenance must be objects")
        if provenance.get("input_signature") != signature or manifest.get("input_signature") != signature:
            raise FileExistsError(f"filtering output was produced from different inputs: {output}")
        if manifest.get("schema_version") != 2 or manifest.get("status") != "complete":
            raise ValueError("filtering manifest is not complete schema v2")
        if manifest.get("case_id") != plan.case.case_id or manifest.get("method") != plan.case.method.value:
            raise ValueError("filtering manifest identity is inconsistent")
        pairs = manifest.get("pairs")
        if not isinstance(pairs, list) or len(pairs) != len(plan.pairs):
            raise ValueError("filtering manifest pair inventory is incomplete")
        complex_size = plan.width * plan.lines * 8
        float_size = plan.width * plan.lines * 4
        for expected, item in zip(plan.pairs, pairs):
            if not isinstance(item, dict) or item.get("pair") != expected.name:
                raise ValueError("filtering manifest pair inventory is inconsistent")
            products = item.get("products")
            if not isinstance(products, dict):
                raise ValueError("filtering manifest pair products are invalid")
            _published(output, products.get("filtered_interferogram"), "filtered interferogram", complex_size)
            _published(output, products.get("filtered_coherence"), "filtered coherence", float_size)
        _published(output, manifest.get("mean_coherence_path"), "mean coherence", float_size)
        return FilteringRunSummary("skipped", plan.case.method.value, len(pairs), output)
    except FileExistsError:
        raise
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise FileExistsError(f"filtering output is incomplete or invalid: {output}") from error


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
    existing = _read_existing(plan, signature)
    if existing is not None:
        _event(sink, event="batch_finished", status="skipped", stage="publish", total=existing.pair_count)
        return existing
    delegate = command_runner or SubprocessCommandRunner()
    method_dir = plan.case.method.directory_name
    log_dir = plan.case.case_root / "LOG" / "ANALYSIS" / "FILTERING" / method_dir
    _begin_logs(log_dir)
    total = len(plan.pairs) + 1
    _event(sink, event="batch_started", status="start", stage="prepare", total=total)
    try:
        with atomic_output_directory(plan.case.output_dir) as staging:
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
            provenance = {
                "case_id": plan.case.case_id,
                "input_signature": signature,
                "interferogram_manifest_project_path": source_path,
                "log_dir_project_path": _project_path(plan, log_dir),
                "method": plan.case.method.value,
                "schema_version": 2,
            }
            (staging / "provenance.json").write_text(json.dumps(provenance, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            manifest = {
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
            (staging / "filtering_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        _event(sink, event="batch_finished", status="complete", stage="publish", index=total, total=total)
        return FilteringRunSummary("complete", plan.case.method.value, len(plan.pairs), plan.case.output_dir)
    except BaseException:
        failed = _preserve_failed_logs(log_dir)
        _event(sink, event="batch_finished", status="failed", stage="failed", total=total, failure_logs=str(failed))
        raise


__all__ = ["FilteringRunSummary", "run_filtering"]
