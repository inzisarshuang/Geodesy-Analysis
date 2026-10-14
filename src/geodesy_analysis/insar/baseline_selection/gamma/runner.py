"""Transactional execution of one GAMMA baseline-selection plan."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from geodesy_analysis.common.command import SubprocessCommandRunner
from geodesy_analysis.common.progress import emit_progress
from geodesy_analysis.io import atomic_output_directory

from .models import GammaBaselinePlan
from .publication import (
    baseline_input_signature,
    parse_berp_sc,
    write_network_files,
)

_TASK = "ANALYSIS_GAMMA_BASELINE"


@dataclass(frozen=True)
class BaselineRunSummary:
    """Final baseline-stage state returned to CLI and workflows."""

    status: str
    pair_count: int
    output_dir: Path


def _event(sink: Callable[[str], None], **values: object) -> None:
    sink(emit_progress(task=_TASK, **values))


def _published_asset(output: Path, value: object, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"baseline manifest {label} path is required")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"baseline manifest {label} path is unsafe")
    target = (output / relative).resolve()
    try:
        target.relative_to(output.resolve())
    except ValueError as error:
        raise ValueError(f"baseline manifest {label} leaves output directory") from error
    if not target.is_file() or target.stat().st_size == 0:
        raise ValueError(f"complete baseline output is missing {label}: {target}")
    return target


def _nonempty_lines(path: Path) -> tuple[str, ...]:
    return tuple(
        line.strip()
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )


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


def _read_existing(plan: GammaBaselinePlan, signature: str) -> BaselineRunSummary | None:
    output = plan.case.output_dir
    if not output.exists():
        return None
    manifest_path = output / "baseline_manifest.json"
    provenance_path = output / "provenance.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or not isinstance(provenance, dict):
            raise ValueError("baseline manifest and provenance must be JSON objects")
        if provenance.get("input_signature") != signature:
            raise FileExistsError(
                f"baseline output was produced from different inputs: {output}"
            )
        if manifest.get("schema_version") != 1 or manifest.get("status") != "complete":
            raise ValueError("baseline manifest is not complete schema version 1")
        if manifest.get("stack_digest") != plan.stack.source_digest:
            raise ValueError("baseline manifest stack digest is inconsistent")
        if manifest.get("reference_date") != plan.stack.reference_date:
            raise ValueError("baseline manifest reference date is inconsistent")
        if manifest.get("polarization") != plan.case.polarization:
            raise ValueError("baseline manifest polarization is inconsistent")
        if manifest.get("network_type") != plan.case.network_type:
            raise ValueError("baseline manifest network type is inconsistent")
        network = _published_asset(output, manifest.get("network_path"), "network")
        image_pairs = _published_asset(
            output, manifest.get("image_pairs_path"), "image pairs"
        )
        _published_asset(output, manifest.get("provenance_path"), "provenance")
        images = _published_asset(output, "images", "images")
        pair_count = manifest.get("pair_count")
        if not isinstance(pair_count, int) or isinstance(pair_count, bool) or pair_count <= 0:
            raise ValueError("baseline manifest pair_count must be a positive integer")
        if len(_nonempty_lines(network)) != pair_count:
            raise ValueError("baseline manifest pair_count does not match network")
        if len(_nonempty_lines(image_pairs)) != pair_count:
            raise ValueError("baseline manifest pair_count does not match image pairs")
        if tuple(
            "-".join(line.split()[:2]) for line in _nonempty_lines(network)
        ) != _nonempty_lines(image_pairs):
            raise ValueError("baseline network and image-pair inventories disagree")
        if _nonempty_lines(images) != plan.stack.dates:
            raise ValueError("baseline images inventory is inconsistent")
        return BaselineRunSummary(
            status="skipped",
            pair_count=pair_count,
            output_dir=output,
        )
    except FileExistsError:
        raise
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise FileExistsError(f"baseline output is incomplete or invalid: {output}") from error


def run_gamma_baseline(
    plan: GammaBaselinePlan,
    *,
    command_runner=None,
    progress_sink: Callable[[str], None] = print,
) -> BaselineRunSummary:
    """Execute ``base_calc`` and publish its scientific baseline products."""

    if not isinstance(plan, GammaBaselinePlan):
        raise TypeError("plan must be GammaBaselinePlan")
    signature = baseline_input_signature(plan)
    existing = _read_existing(plan, signature)
    if existing is not None:
        _event(
            progress_sink,
            event="batch_finished",
            status="skipped",
            index=2,
            total=2,
            stage="publish",
        )
        return existing

    log_dir = (
        plan.case.project_root
        / "LOG/ANALYSIS/GAMMA/BASELINE"
        / plan.case.name
    )
    _begin_logs(log_dir)
    stdout_log = log_dir / "base_calc.stdout.log"
    stderr_log = log_dir / "base_calc.stderr.log"
    delegate = command_runner or SubprocessCommandRunner()
    _event(
        progress_sink,
        event="batch_started",
        status="start",
        total=2,
        stage="prepare",
    )
    try:
        with atomic_output_directory(plan.case.output_dir) as staging:
            (staging / "images").write_text(plan.images_text, encoding="utf-8")
            (staging / "SLC_tab").write_text(plan.slc_tab_text, encoding="utf-8")
            _event(
                progress_sink,
                event="item_started",
                status="start",
                item=plan.case.network_type,
                index=1,
                total=2,
                stage="base_calc",
            )
            delegate.run(
                plan.base_calc_command,
                cwd=staging,
                stdin_text=None,
                stdout_path=stdout_log,
                stderr_path=stderr_log,
            )
            berp = staging / "Berp_SC"
            itab = staging / "itab_SC"
            if not berp.is_file() or berp.stat().st_size == 0:
                raise ValueError(f"base_calc did not create non-empty Berp_SC: {berp}")
            if not itab.is_file() or itab.stat().st_size == 0:
                raise ValueError(f"base_calc did not create non-empty itab_SC: {itab}")
            records = parse_berp_sc(berp)
            image_pairs, network = write_network_files(
                staging, plan.case.network_type, records
            )
            _event(
                progress_sink,
                event="item_finished",
                status="complete",
                item=plan.case.network_type,
                index=1,
                total=2,
                stage="base_calc",
            )

            provenance = {
                "command": list(plan.base_calc_command),
                "input_signature": signature,
                "logs": {
                    "stderr": str(stderr_log),
                    "stdout": str(stdout_log),
                },
                "parameters": {
                    "max_perpendicular_baseline": plan.case.max_perpendicular_baseline,
                    "max_temporal_baseline": plan.case.max_temporal_baseline,
                    "network_type": plan.case.network_type,
                    "polarization": plan.case.polarization,
                },
                "registered_stack": {
                    "path": str(plan.stack.source_path),
                    "sha256": plan.stack.source_digest,
                },
            }
            (staging / "provenance.json").write_text(
                json.dumps(provenance, ensure_ascii=False, sort_keys=True, indent=2)
                + "\n",
                encoding="utf-8",
            )
            manifest = {
                "image_pairs_path": image_pairs.name,
                "network_path": network.name,
                "network_type": plan.case.network_type,
                "pair_count": len(records),
                "polarization": plan.case.polarization,
                "provenance_path": "provenance.json",
                "reference_date": plan.stack.reference_date,
                "schema_version": 1,
                "stack_digest": plan.stack.source_digest,
                "status": "complete",
            }
            (staging / "baseline_manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2)
                + "\n",
                encoding="utf-8",
            )
            for temporary in (berp, itab, staging / "SLC_tab"):
                temporary.unlink(missing_ok=True)
        _event(
            progress_sink,
            event="batch_finished",
            status="complete",
            index=2,
            total=2,
            stage="publish",
        )
        return BaselineRunSummary(
            status="complete",
            pair_count=len(records),
            output_dir=plan.case.output_dir,
        )
    except BaseException:
        failed_logs = _preserve_failed_logs(log_dir)
        _event(
            progress_sink,
            event="batch_finished",
            status="failed",
            total=2,
            stage="failed",
            failure_logs=str(failed_logs),
        )
        raise


__all__ = ["BaselineRunSummary", "run_gamma_baseline"]
