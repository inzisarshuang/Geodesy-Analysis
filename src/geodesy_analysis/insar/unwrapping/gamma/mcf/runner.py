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
from geodesy_analysis.common.reuse import ReuseState, classify_analysis_output
from geodesy_analysis.insar.common.gamma_quicklooks import (
    require_nonempty_quicklook,
    unwrapped_phase_quicklook_command,
)
from geodesy_analysis.io import atomic_output_directories

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
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(plan.case.project_root).as_posix()
    except ValueError:
        return resolved.as_posix()


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


def _quicklook_path(plan: GammaMcfPlan, pair_name: str) -> str:
    return _project_path(
        plan, plan.case.visualization_dir / f"{pair_name}.tflt.filt.unw.bmp"
    )


def _add_quicklook_metadata(
    plan: GammaMcfPlan,
    manifest: dict[str, object],
    provenance: dict[str, object],
) -> None:
    directory = _project_path(plan, plan.case.visualization_dir)
    manifest["visualization_dir_project_path"] = directory
    for item in manifest["pairs"]:  # type: ignore[index]
        item["quicklook_project_path"] = _quicklook_path(plan, item["pair"])
    provenance["visualization_dir_project_path"] = directory
    provenance["quicklook_commands"] = {
        "unwrapped_phase": {"command": "rasdt_pwr", "color_map": "rmg.cm"}
    }


def _run_quicklook(
    plan: GammaMcfPlan,
    pair: UnwrappingPair,
    unwrapped: Path,
    *,
    destination: Path,
    delegate,
    log_dir: Path,
) -> None:
    target = destination / f"{pair.name}.tflt.filt.unw.bmp"
    if target.is_symlink():
        target.unlink()
    if target.is_file() and target.stat().st_size:
        return
    delegate.run(
        unwrapped_phase_quicklook_command(unwrapped, plan.width, target),
        cwd=destination,
        stdin_text=None,
        stdout_path=log_dir / f"{pair.name}.quicklook.stdout.log",
        stderr_path=log_dir / f"{pair.name}.quicklook.stderr.log",
    )
    require_nonempty_quicklook(target, f"unwrapped phase quicklook for {pair.name}")


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
    delegate = command_runner or SubprocessCommandRunner()
    log_dir = (
        plan.case.paths.processing_root / "LOG/ANALYSIS/UNW/GAMMA_MCF"
        if plan.case.paths.processing_root is not None
        else plan.case.case_root / "LOG/ANALYSIS/UNWRAPPING/GAMMA_MCF"
    )
    reuse = classify_analysis_output(
        plan.case.output_dir, "unwrapping_manifest.json", signature
    )
    if reuse.science_reusable:
        manifest = reuse.manifest or {}
        expected_identity = {
            "case_id": plan.case.case_id,
            "filtering_manifest_digest": plan.filtering.source_digest,
            "method": "gamma_mcf",
            "pair_count": len(plan.pairs),
        }
        if any(manifest.get(key) != value for key, value in expected_identity.items()):
            raise RuntimeError(
                f"unwrapping manifest identity is inconsistent; existing science was not modified: {plan.case.output_dir}"
            )
        if reuse.state is ReuseState.FIGURES_MISSING:
            _begin_logs(log_dir)
            plan.case.visualization_dir.mkdir(parents=True, exist_ok=True)
            for pair in plan.pairs:
                _run_quicklook(
                    plan,
                    pair,
                    plan.case.output_dir / "pairs" / pair.name / "pair.tflt.filt.unw",
                    destination=plan.case.visualization_dir,
                    delegate=delegate,
                    log_dir=log_dir,
                )
            status = "figures_repaired"
        else:
            status = "skipped"
        _event(sink, event="batch_finished", status=status, stage="reuse", total=len(plan.pairs) + 1)
        return GammaMcfRunSummary(status, len(plan.pairs), plan.case.output_dir)
    if reuse.state is not ReuseState.ABSENT:
        raise RuntimeError(reuse.guidance)
    if plan.case.visualization_dir.exists() or plan.case.visualization_dir.is_symlink():
        raise RuntimeError(
            "unwrapping science is absent but figure output already exists; inspect and delete the incomplete output group"
        )
    _begin_logs(log_dir)
    total = len(plan.pairs) + 1
    _event(sink, event="batch_started", status="start", stage="prepare", total=total)
    try:
        with atomic_output_directories(
            plan.case.visualization_dir, plan.case.output_dir
        ) as (visual_staging, staging):
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
                _run_quicklook(
                    plan,
                    pair,
                    output,
                    destination=visual_staging,
                    delegate=delegate,
                    log_dir=log_dir,
                )
                _event(sink, event="item_finished", status="complete", item=pair.name, index=index, total=total, stage="unwrap")
            reference_payload = {
                "azimuth_index": reference.azimuth_index,
                "coherence": reference.coherence,
                "command_azimuth": reference.command_azimuth,
                "command_range": reference.command_range,
                "mode": reference.mode,
                "range_index": reference.range_index,
            }
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
            provenance: dict[str, object] = {
                "case_id": plan.case.case_id,
                "filtering_manifest_project_path": _project_path(plan, plan.filtering.source_path),
                "filtering_manifest_digest": plan.filtering.source_digest,
                "filtering_method": plan.filtering.method,
                "input_signature": signature,
                "log_dir_project_path": _project_path(plan, log_dir),
                "mask_coherence_scope": "all_filtering_pairs",
                "mcf_mode": plan.case.mcf_mode,
                "pair_selection": pair_selection,
                "reference": reference_payload,
                "schema_version": 2,
            }
            manifest: dict[str, object] = {
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
                "mask_coherence_scope": "all_filtering_pairs",
                "mcf_mode": plan.case.mcf_mode,
                "method": "gamma_mcf",
                "pair_selection": pair_selection,
                "pair_count": len(products),
                "pairs": [
                    {
                        "finite_count": finite,
                        "pair": pair.name,
                        "unwrapped_path": output.relative_to(staging).as_posix(),
                    }
                    for pair, output, finite in products
                ],
                "provenance_path": "provenance.json",
                "reference": reference_payload,
                "schema_version": 2,
                "status": "complete",
            }
            _add_quicklook_metadata(plan, manifest, provenance)
            manifest["required_products"] = [
                manifest["mask"]["binary_mask_path"],  # type: ignore[index]
                manifest["mask"]["final_mask_path"],  # type: ignore[index]
                manifest["mask"]["metadata_path"],  # type: ignore[index]
                *[item["unwrapped_path"] for item in manifest["pairs"]],  # type: ignore[index]
                "provenance.json",
            ]
            manifest["figures"] = [
                Path(
                    os.path.relpath(
                        plan.case.visualization_dir
                        / f"{pair.name}.tflt.filt.unw.bmp",
                        start=plan.case.output_dir,
                    )
                ).as_posix()
                for pair in plan.pairs
            ]
            (staging / "provenance.json").write_text(
                json.dumps(provenance, ensure_ascii=False, sort_keys=True, indent=2)
                + "\n",
                encoding="utf-8",
            )
            (staging / "unwrapping_manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2)
                + "\n",
                encoding="utf-8",
            )
        _event(sink, event="batch_finished", status="complete", stage="publish", index=total, total=total)
        return GammaMcfRunSummary("complete", len(plan.pairs), plan.case.output_dir)
    except BaseException:
        failed = _preserve_logs(log_dir)
        _event(sink, event="batch_finished", status="failed", stage="failed", total=total, failure_logs=str(failed))
        raise


__all__ = ["GammaMcfRunSummary", "mcf_command", "run_gamma_mcf"]
