"""Validation and deterministic identity helpers for filtering products."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .models import FilteringPlan


def ensure_nonempty(path: Path, label: str) -> Path:
    target = Path(path)
    if not target.is_file():
        raise FileNotFoundError(f"{label} not found: {target}")
    if target.stat().st_size == 0:
        raise ValueError(f"{label} is empty: {target}")
    return target


def gamma_parameter(path: Path, key: str) -> int:
    source = ensure_nonempty(path, "GAMMA parameter file")
    for raw in source.read_text(encoding="utf-8", errors="replace").splitlines():
        fields = raw.replace(":", " ").split()
        if len(fields) >= 2 and fields[0] == key:
            try:
                value = int(fields[1])
            except ValueError as error:
                raise ValueError(f"invalid {key} in GAMMA parameter file: {source}") from error
            if value <= 0:
                raise ValueError(f"invalid {key} in GAMMA parameter file: {source}")
            return value
    raise ValueError(f"missing {key} in GAMMA parameter file: {source}")


def _method_parameters(plan: FilteringPlan) -> dict[str, object]:
    case = plan.case
    if case.method.value == "nl_insar":
        return {
            "coherence_window": case.coherence_window,
            "filter_threshold": case.filter_threshold,
            "likelihood_h": case.likelihood_h,
            "minimum_looks": case.minimum_looks,
            "patch_size": case.patch_size,
            "point_threshold": case.point_threshold,
            "search_window": case.search_window,
            "seed": case.seed,
            "tile_size": case.tile_size,
        }
    if case.method.value == "gamma_bm3d":
        return {
            "block_size": case.bm3d_block_size,
            "block_step": case.bm3d_block_step,
            "group_size": case.bm3d_group_size,
            "mode": case.bm3d_mode,
            "search_window": case.bm3d_search_window,
            "sigma": case.bm3d_sigma,
            "transform": case.bm3d_transform,
        }
    return {
        "alpha": case.adf_alpha,
        "first_window": case.adf_first_window,
        "second_window": case.adf_second_window,
        "steps": case.adf_steps,
    }


def filtering_input_signature(plan: FilteringPlan) -> str:
    root = plan.case.project_root

    def relative(path: Path) -> str:
        return Path(path).resolve().relative_to(root).as_posix()

    payload = {
        "case_id": plan.case.case_id,
        "grid": {"lines": plan.lines, "width": plan.width},
        "interferogram_manifest": relative(plan.manifest.source_path),
        "interferogram_manifest_digest": plan.manifest.source_digest,
        "method": plan.case.method.value,
        "parameters": _method_parameters(plan),
        "pairs": [
            {
                "interferogram": relative(pair.interferogram),
                "master_mli": relative(pair.master_mli),
                "name": pair.name,
                "slave_mli": relative(pair.slave_mli),
            }
            for pair in plan.pairs
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


__all__ = ["ensure_nonempty", "filtering_input_signature", "gamma_parameter"]
