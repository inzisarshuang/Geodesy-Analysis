"""Transactional execution of one GAMMA baseline-selection plan."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from geodesy_analysis.common.command import SubprocessCommandRunner
from geodesy_analysis.common.progress import emit_progress
from geodesy_analysis.common.reuse import ReuseState, classify_analysis_output
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


def _project_path(plan: GammaBaselinePlan, path: Path) -> str:
    """Return one resolved project-confined path in portable POSIX form."""

    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(plan.case.project_root).as_posix()
    except ValueError as error:
        raise ValueError(f"baseline path leaves project root: {resolved}") from error


def _portable_command(plan: GammaBaselinePlan) -> list[str]:
    command: list[str] = []
    for value in plan.base_calc_command:
        path = Path(value)
        command.append(_project_path(plan, path) if path.is_absolute() else value)
    return command


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
    reuse = classify_analysis_output(
        plan.case.output_dir, "baseline_manifest.json", signature
    )
    if reuse.state is ReuseState.COMPLETE:
        manifest = reuse.manifest or {}
        expected_identity = {
            "backend": {"name": "gamma"},
            "case_id": plan.case.case_id,
            "network_type": plan.case.network_type,
            "image_pairs_path": f"image_pairs_{plan.case.network_type}",
            "network_path": f"baseline_select_{plan.case.network_type}",
            "polarization": plan.case.polarization,
            "registered_stack_project_path": _project_path(
                plan, plan.case.registered_stack
            ),
            "stack_digest": plan.stack.source_digest,
        }
        inconsistent = [
            key
            for key, value in expected_identity.items()
            if manifest.get(key) != value
        ]
        network = plan.case.output_dir / f"baseline_select_{plan.case.network_type}"
        pair_count = sum(
            1
            for line in network.read_text(
                encoding="utf-8", errors="replace"
            ).splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
        if manifest.get("pair_count") != pair_count:
            inconsistent.append("pair_count")
        if inconsistent:
            raise RuntimeError(
                "baseline manifest identity is inconsistent: "
                + ", ".join(inconsistent)
                + f". Existing science was not modified: {plan.case.output_dir}"
            )
        _event(
            progress_sink,
            event="batch_finished",
            status="skipped",
            total=2,
            stage="reuse",
        )
        return BaselineRunSummary(
            status="skipped",
            pair_count=int(manifest.get("pair_count", 0)),
            output_dir=plan.case.output_dir,
        )
    if reuse.state is not ReuseState.ABSENT:
        raise RuntimeError(reuse.guidance)
    log_dir = (
        plan.case.paths.processing_root / "LOG/ANALYSIS/BASELINE"
        if plan.case.paths.processing_root is not None
        else plan.case.case_root / "LOG/ANALYSIS/BASELINE_SELECTION/GAMMA"
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

            registered_stack_project_path = _project_path(
                plan, plan.case.registered_stack
            )
            provenance = {
                "backend": {"name": "gamma"},
                "case_id": plan.case.case_id,
                "command": _portable_command(plan),
                "input_signature": signature,
                "logs": {
                    "stderr_project_path": _project_path(plan, stderr_log),
                    "stdout_project_path": _project_path(plan, stdout_log),
                },
                "parameters": {
                    "max_perpendicular_baseline": plan.case.max_perpendicular_baseline,
                    "max_temporal_baseline": plan.case.max_temporal_baseline,
                    "network_type": plan.case.network_type,
                    "polarization": plan.case.polarization,
                },
                "registered_stack_project_path": registered_stack_project_path,
                "registered_stack_sha256": plan.stack.source_digest,
                "schema_version": 2,
            }
            (staging / "provenance.json").write_text(
                json.dumps(provenance, ensure_ascii=False, sort_keys=True, indent=2)
                + "\n",
                encoding="utf-8",
            )
            manifest = {
                "backend": {"name": "gamma"},
                "case_id": plan.case.case_id,
                "image_pairs_path": image_pairs.name,
                "network_path": network.name,
                "network_type": plan.case.network_type,
                "pair_count": len(records),
                "polarization": plan.case.polarization,
                "provenance_path": "provenance.json",
                "reference_date": plan.stack.reference_date,
                "registered_stack_project_path": registered_stack_project_path,
                "input_signature": signature,
                "required_products": [
                    "images",
                    image_pairs.name,
                    network.name,
                    "provenance.json",
                ],
                "figures": [],
                "schema_version": 2,
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
