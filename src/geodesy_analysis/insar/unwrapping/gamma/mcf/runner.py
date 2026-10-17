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
from geodesy_analysis.insar.common.gamma_quicklooks import (
    require_nonempty_quicklook,
    unwrapped_phase_quicklook_command,
)
from geodesy_analysis.io import (
    atomic_output_directories,
    atomic_output_directory,
    atomic_output_path,
)

from .mask import ReferencePoint, build_unwrapping_mask, resolve_reference_point
from .models import GammaMcfPlan, UnwrappingPair
from .publication import unwrapping_input_signature

_TASK = "ANALYSIS_GAMMA_MCF"


@dataclass(frozen=True)
class GammaMcfRunSummary:
    status: str
    pair_count: int
    output_dir: Path


@dataclass(frozen=True)
class _ExistingMcf:
    summary: GammaMcfRunSummary
    manifest: dict[str, object]
    provenance: dict[str, object]


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


def _read_existing(plan: GammaMcfPlan, signature: str) -> _ExistingMcf | None:
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
        return _ExistingMcf(
            GammaMcfRunSummary("skipped", len(pairs), output),
            manifest,
            provenance,
        )
    except FileExistsError:
        raise
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise FileExistsError(f"unwrapping output is incomplete or invalid: {output}") from error


def _quicklook_names(plan: GammaMcfPlan) -> set[str]:
    return {f"{pair.name}.tflt.filt.unw.bmp" for pair in plan.pairs}


def _validate_visualization_inventory(plan: GammaMcfPlan) -> None:
    directory = plan.case.visualization_dir
    if not directory.exists():
        return
    if not directory.is_dir() or directory.is_symlink():
        raise FileExistsError(f"visualization output is not a directory: {directory}")
    expected = _quicklook_names(plan)
    unexpected = sorted(
        path.name
        for path in directory.iterdir()
        if path.name not in expected or path.is_symlink() or not path.is_file()
    )
    if unexpected:
        raise FileExistsError(
            f"visualization directory has unexpected entry: {directory / unexpected[0]}"
        )


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


def _quicklooks_complete(plan: GammaMcfPlan, manifest: dict[str, object]) -> bool:
    if manifest.get("visualization_dir_project_path") != _project_path(
        plan, plan.case.visualization_dir
    ):
        return False
    pairs = manifest.get("pairs")
    if not isinstance(pairs, list) or any(
        not isinstance(item, dict)
        or item.get("quicklook_project_path") != _quicklook_path(plan, item.get("pair"))
        for item in pairs
    ):
        return False
    try:
        for name in _quicklook_names(plan):
            require_nonempty_quicklook(plan.case.visualization_dir / name, name)
    except (OSError, RuntimeError):
        return False
    return True


def _run_quicklook(
    plan: GammaMcfPlan,
    pair: UnwrappingPair,
    unwrapped: Path,
    *,
    destination: Path,
    delegate,
    log_dir: Path,
    atomic: bool,
) -> None:
    target = destination / f"{pair.name}.tflt.filt.unw.bmp"
    if target.is_file() and target.stat().st_size:
        return

    def execute(output: Path) -> None:
        delegate.run(
            unwrapped_phase_quicklook_command(unwrapped, plan.width, output),
            cwd=destination,
            stdin_text=None,
            stdout_path=log_dir / f"{pair.name}.quicklook.stdout.log",
            stderr_path=log_dir / f"{pair.name}.quicklook.stderr.log",
        )
        require_nonempty_quicklook(output, f"unwrapped phase quicklook for {pair.name}")

    if atomic:
        with atomic_output_path(target) as temporary:
            execute(temporary)
    else:
        execute(target)


def _existing_products(
    plan: GammaMcfPlan, manifest: dict[str, object]
) -> list[tuple[UnwrappingPair, Path]]:
    by_name = {item["pair"]: item for item in manifest["pairs"]}  # type: ignore[union-attr]
    expected_size = plan.width * plan.lines * 4
    return [
        (
            pair,
            _output_asset(
                plan.case.output_dir,
                by_name[pair.name]["unwrapped_path"],
                expected_size,
            ),
        )
        for pair in plan.pairs
    ]


def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    with atomic_output_path(path) as temporary:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )


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
        _validate_visualization_inventory(plan)
        if _quicklooks_complete(plan, existing.manifest):
            _event(
                sink,
                event="batch_finished",
                status="skipped",
                stage="publish",
                total=existing.summary.pair_count,
            )
            return existing.summary
        delegate = command_runner or SubprocessCommandRunner()
        log_dir = plan.case.case_root / "LOG/ANALYSIS/UNWRAPPING/GAMMA_MCF"
        _begin_logs(log_dir)
        try:
            products = _existing_products(plan, existing.manifest)
            if plan.case.visualization_dir.exists():
                for pair, unwrapped in products:
                    _run_quicklook(
                        plan,
                        pair,
                        unwrapped,
                        destination=plan.case.visualization_dir,
                        delegate=delegate,
                        log_dir=log_dir,
                        atomic=True,
                    )
            else:
                with atomic_output_directory(plan.case.visualization_dir) as visual_staging:
                    for pair, unwrapped in products:
                        _run_quicklook(
                            plan,
                            pair,
                            unwrapped,
                            destination=visual_staging,
                            delegate=delegate,
                            log_dir=log_dir,
                            atomic=False,
                        )
            _add_quicklook_metadata(plan, existing.manifest, existing.provenance)
            _write_json_atomic(plan.case.output_dir / "provenance.json", existing.provenance)
            _write_json_atomic(
                plan.case.output_dir / "unwrapping_manifest.json", existing.manifest
            )
        except BaseException:
            failed = _preserve_logs(log_dir)
            _event(
                sink,
                event="batch_finished",
                status="failed",
                stage="failed",
                total=existing.summary.pair_count,
                failure_logs=str(failed),
            )
            raise
        _event(
            sink,
            event="batch_finished",
            status="repaired",
            stage="publish",
            total=existing.summary.pair_count,
        )
        return GammaMcfRunSummary(
            "repaired", existing.summary.pair_count, existing.summary.output_dir
        )
    delegate = command_runner or SubprocessCommandRunner()
    log_dir = plan.case.case_root / "LOG/ANALYSIS/UNWRAPPING/GAMMA_MCF"
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
                    atomic=False,
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
            provenance: dict[str, object] = {
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
                "mcf_mode": plan.case.mcf_mode,
                "method": "gamma_mcf",
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
