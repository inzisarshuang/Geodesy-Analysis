"""Transactional GAMMA MCF execution and publication."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from geodesy_analysis.common.command import SubprocessCommandRunner
from geodesy_analysis.common.progress import emit_progress
from geodesy_analysis.io import atomic_output_directory

from .mask import ReferencePoint, build_unwrapping_mask, resolve_reference_point
from .models import GammaMcfPlan, UnwrappingPair
from .publication import unwrapping_input_signature

_TASK = "ANALYSIS_GAMMA_MCF"


@dataclass(frozen=True)
class GammaMcfRunSummary:
    status: str
    pair_count: int
    output_dir: Path


def mcf_command(
    pair: UnwrappingPair,
    plan: GammaMcfPlan,
    mask: Path,
    reference: ReferencePoint,
    output: Path,
) -> tuple[str, ...]:
    return (
        "mcf",
        str(pair.filtered_interferogram),
        str(pair.filtered_coherence),
        str(mask),
        str(output),
        str(plan.width),
        str(plan.case.mcf_mode),
        "0",
        "0",
        "-",
        "-",
        "1",
        "1",
        "-",
        str(reference.command_range),
        str(reference.command_azimuth),
    )


def _event(sink: Callable[[str], object], **values: object) -> None:
    sink(emit_progress(task=_TASK, **values))


def _project_path(plan: GammaMcfPlan, path: Path) -> str:
    return Path(path).resolve().relative_to(plan.case.project_root).as_posix()


def _next_failed(active: Path) -> Path:
    index = 1
    while True:
        candidate = active.with_name(f"{active.name}.failed-logs-{index}")
        if not candidate.exists():
            return candidate
        index += 1


def _begin_logs(active: Path) -> None:
    active.parent.mkdir(parents=True, exist_ok=True)
    if active.exists():
        os.replace(active, _next_failed(active))
    active.mkdir()


def _preserve_logs(active: Path) -> Path:
    failed = _next_failed(active)
    if active.exists():
        os.replace(active, failed)
    return failed


def _output_asset(output: Path, value: object, expected: int) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError("unwrapping product path is required")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("unwrapping product path is unsafe")
    path = output / relative
    if not path.is_file() or path.stat().st_size != expected:
        raise ValueError("unwrapping product is missing or has wrong byte size")
    return path


def _read_existing(plan: GammaMcfPlan, signature: str) -> GammaMcfRunSummary | None:
    output = plan.case.output_dir
    if not output.exists():
        return None
    try:
        manifest = json.loads((output / "unwrapping_manifest.json").read_text(encoding="utf-8"))
        provenance = json.loads((output / "provenance.json").read_text(encoding="utf-8"))
        if manifest.get("input_signature") != signature or provenance.get("input_signature") != signature:
            raise FileExistsError(f"unwrapping output was produced from different inputs: {output}")
        if manifest.get("schema_version") != 2 or manifest.get("status") != "complete":
            raise ValueError("unwrapping manifest is incomplete")
        if manifest.get("case_id") != plan.case.case_id or manifest.get("method") != "gamma_mcf":
            raise ValueError("unwrapping manifest identity is inconsistent")
        pairs = manifest.get("pairs")
        if not isinstance(pairs, list) or len(pairs) != len(plan.pairs):
            raise ValueError("unwrapping manifest pair inventory is incomplete")
        expected_size = plan.width * plan.lines * 4
        for expected, item in zip(plan.pairs, pairs):
            if not isinstance(item, dict) or item.get("pair") != expected.name:
                raise ValueError("unwrapping manifest pair inventory is inconsistent")
            _output_asset(output, item.get("unwrapped_path"), expected_size)
        mask = manifest.get("mask")
        if not isinstance(mask, dict) or not (output / mask.get("final_mask_path", "")).is_file():
            raise ValueError("unwrapping manifest mask is missing")
        return GammaMcfRunSummary("skipped", len(pairs), output)
    except FileExistsError:
        raise
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise FileExistsError(f"unwrapping output is incomplete or invalid: {output}") from error


def run_gamma_mcf(
    plan: GammaMcfPlan,
    *,
    command_runner: object | None = None,
    progress_sink: Callable[[str], object] | None = None,
) -> GammaMcfRunSummary:
    if not isinstance(plan, GammaMcfPlan):
        raise TypeError("plan must be GammaMcfPlan")
    sink = progress_sink or print
    signature = unwrapping_input_signature(plan)
    existing = _read_existing(plan, signature)
    if existing is not None:
        _event(sink, event="batch_finished", status="skipped", stage="publish", total=existing.pair_count)
        return existing
    delegate = command_runner or SubprocessCommandRunner()
    log_dir = plan.case.case_root / "LOG/ANALYSIS/UNWRAPPING/GAMMA_MCF"
    _begin_logs(log_dir)
    total = len(plan.pairs) + 1
    _event(sink, event="batch_started", status="start", stage="prepare", total=total)
    try:
        with atomic_output_directory(plan.case.output_dir) as staging:
            mask = build_unwrapping_mask(plan, staging)
            reference = resolve_reference_point(plan, mask)
            pairs_dir = staging / "pairs"
            pairs_dir.mkdir()
            products: list[tuple[UnwrappingPair, Path, int]] = []
            expected_size = plan.width * plan.lines * 4
            for index, pair in enumerate(plan.pairs, start=1):
                _event(sink, event="item_started", status="start", item=pair.name, index=index, total=total, stage="unwrap")
                pair_dir = pairs_dir / pair.name
                pair_dir.mkdir()
                output = pair_dir / "pair.tflt.filt.unw"
                delegate.run(
                    mcf_command(pair, plan, mask.final_mask, reference, output),
                    cwd=pair_dir,
                    stdin_text=None,
                    stdout_path=log_dir / f"{pair.name}.mcf.stdout.log",
                    stderr_path=log_dir / f"{pair.name}.mcf.stderr.log",
                )
                if not output.is_file() or output.stat().st_size != expected_size:
                    raise ValueError(f"MCF unwrapped raster byte size mismatch: {output}")
                values = np.memmap(output, dtype=">f4", mode="r")
                finite_count = int(np.count_nonzero(np.isfinite(values)))
                del values
                if finite_count == 0:
                    raise ValueError(f"MCF unwrapped raster contains no finite values: {output}")
                products.append((pair, output, finite_count))
                _event(sink, event="item_finished", status="complete", item=pair.name, index=index, total=total, stage="unwrap")
            reference_payload = {
                "azimuth_index": reference.azimuth_index,
                "coherence": reference.coherence,
                "command_azimuth": reference.command_azimuth,
                "command_range": reference.command_range,
                "mode": reference.mode,
                "range_index": reference.range_index,
            }
            provenance = {
                "case_id": plan.case.case_id,
                "filtering_manifest_project_path": _project_path(plan, plan.filtering.source_path),
                "filtering_manifest_digest": plan.filtering.source_digest,
                "filtering_method": plan.filtering.method,
                "input_signature": signature,
                "log_dir_project_path": _project_path(plan, log_dir),
                "mcf_mode": plan.case.mcf_mode,
                "reference": reference_payload,
                "schema_version": 2,
            }
            (staging / "provenance.json").write_text(json.dumps(provenance, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            manifest = {
                "case_id": plan.case.case_id,
                "filtering_manifest_digest": plan.filtering.source_digest,
                "filtering_manifest_project_path": _project_path(plan, plan.filtering.source_path),
                "filtering_method": plan.filtering.method,
                "grid": {"lines": plan.lines, "width": plan.width},
                "input_signature": signature,
                "mask": {
                    "binary_mask_path": mask.binary_mask.relative_to(staging).as_posix(),
                    "final_mask_path": mask.final_mask.relative_to(staging).as_posix(),
                    "metadata_path": mask.metadata.relative_to(staging).as_posix(),
                    "valid_count": mask.valid_count,
                    "valid_ratio": mask.valid_ratio,
                },
                "mcf_mode": plan.case.mcf_mode,
                "method": "gamma_mcf",
                "pair_count": len(products),
                "pairs": [
                    {"finite_count": finite, "pair": pair.name, "unwrapped_path": output.relative_to(staging).as_posix()}
                    for pair, output, finite in products
                ],
                "provenance_path": "provenance.json",
                "reference": reference_payload,
                "schema_version": 2,
                "status": "complete",
            }
            (staging / "unwrapping_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        _event(sink, event="batch_finished", status="complete", stage="publish", index=total, total=total)
        return GammaMcfRunSummary("complete", len(plan.pairs), plan.case.output_dir)
    except BaseException:
        failed = _preserve_logs(log_dir)
        _event(sink, event="batch_finished", status="failed", stage="failed", total=total, failure_logs=str(failed))
        raise


__all__ = ["GammaMcfRunSummary", "mcf_command", "run_gamma_mcf"]
