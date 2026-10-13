"""Transactional execution of one GAMMA baseline-selection plan."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from geodesy_analysis.common.command import SubprocessCommandRunner
from geodesy_analysis.common.progress import emit_progress
from geodesy_analysis.insar.baseline import plot_baseline_network
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
    warnings: tuple[str, ...] = ()


def _event(sink: Callable[[str], None], **values: object) -> None:
    sink(emit_progress(task=_TASK, **values))


def _read_existing(plan: GammaBaselinePlan, signature: str) -> BaselineRunSummary | None:
    output = plan.case.output_dir
    if not output.exists():
        return None
    manifest_path = output / "baseline_manifest.json"
    provenance_path = output / "provenance.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        if provenance.get("input_signature") != signature:
            raise FileExistsError(
                f"baseline output was produced from different inputs: {output}"
            )
        for key in ("network_path", "image_pairs_path", "provenance_path"):
            path = output / manifest[key]
            if not path.is_file() or path.stat().st_size == 0:
                raise ValueError(f"complete baseline output is missing {key}: {path}")
        images = output / "images"
        if not images.is_file() or images.stat().st_size == 0:
            raise ValueError(f"complete baseline output is missing images: {images}")
        return BaselineRunSummary(
            status="skipped",
            pair_count=int(manifest["pair_count"]),
            output_dir=output,
            warnings=tuple(manifest.get("warnings", ())),
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
    plotter=plot_baseline_network,
) -> BaselineRunSummary:
    """Execute `base_calc`, publish its network, and automatically draw the plot."""

    if not isinstance(plan, GammaBaselinePlan):
        raise TypeError("plan must be GammaBaselinePlan")
    signature = baseline_input_signature(plan)
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

    log_dir = (
        plan.case.project_root
        / "LOG/ANALYSIS/GAMMA/BASELINE"
        / plan.case.name
    )
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout_log = log_dir / "base_calc.stdout.log"
    stderr_log = log_dir / "base_calc.stderr.log"
    delegate = command_runner or SubprocessCommandRunner()
    warnings: list[str] = []
    _event(
        progress_sink,
        event="batch_started",
        status="start",
        total=3,
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
                total=3,
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
                total=3,
                stage="base_calc",
            )

            plot_name = f"{network.name}.png"
            try:
                plotter(
                    baseline_file=str(network),
                    master_date=int(plan.stack.reference_date),
                    out_file=str(staging / plot_name),
                )
                plot_path: str | None = plot_name
                _event(
                    progress_sink,
                    event="item_finished",
                    status="complete",
                    item=plot_name,
                    index=2,
                    total=3,
                    stage="plot",
                )
            except Exception as error:
                warning = f"baseline plot failed: {error}"
                warnings.append(warning)
                plot_path = None
                _event(
                    progress_sink,
                    event="item_finished",
                    status="warning",
                    item=plot_name,
                    index=2,
                    total=3,
                    stage="plot",
                    message=warning,
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
                "plot_path": plot_path,
                "polarization": plan.case.polarization,
                "provenance_path": "provenance.json",
                "reference_date": plan.stack.reference_date,
                "schema_version": 1,
                "stack_digest": plan.stack.source_digest,
                "status": "complete",
                "warnings": warnings,
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
            index=3,
            total=3,
            stage="publish",
        )
        return BaselineRunSummary(
            status="complete",
            pair_count=len(records),
            output_dir=plan.case.output_dir,
            warnings=tuple(warnings),
        )
    except BaseException:
        _event(
            progress_sink,
            event="batch_finished",
            status="failed",
            total=3,
            stage="failed",
            failure_logs=str(log_dir),
        )
        raise


__all__ = ["BaselineRunSummary", "run_gamma_baseline"]
