"""Deterministic identity helpers for GAMMA atmosphere correction."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .models import GammaAtmospherePlan


def _portable(plan: GammaAtmospherePlan, path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(plan.case.project_root).as_posix()
    except ValueError:
        return resolved.as_posix()


def gamma_atmosphere_input_signature(plan: GammaAtmospherePlan) -> str:
    """Hash scientific lineage and every method-controlled parameter."""

    payload = {
        "case_id": plan.case.case_id,
        "detrending_manifest_digest": plan.detrending_manifest_digest,
        "filtering_manifest_digest": plan.filtering_manifest_digest,
        "fit": {
            "height_correlation_threshold": (
                plan.case.height_correlation_threshold
            ),
            "step_azimuth": plan.case.fit_step_azimuth,
            "step_range": plan.case.fit_step_range,
            "window_azimuth": plan.case.fit_window_azimuth,
            "window_range": plan.case.fit_window_range,
        },
        "fspf": {
            "mode": plan.case.fspf_mode,
            "overlap": plan.case.fspf_overlap,
            "window_size": plan.case.fspf_window_size,
        },
        "grid": {"lines": plan.lines, "width": plan.width},
        "intensity_background": plan.case.intensity_background,
        "interferogram_manifest_digest": plan.interferogram_manifest_digest,
        "method": plan.case.method,
        "pairs": [
            {
                "coherence": _portable(plan, pair.coherence),
                "detrended_phase": _portable(plan, pair.detrended_phase),
                "master_mli": _portable(plan, pair.master_mli),
                "name": pair.name,
            }
            for pair in plan.pairs
        ],
        "polygon": (
            None
            if plan.case.polygon_file is None
            else {
                "path": _portable(plan, plan.case.polygon_file),
                "sha256": plan.polygon_digest,
            }
        ),
        "radar_height": _portable(plan, plan.radar_height),
        "unwrapping_manifest_digest": plan.unwrapping_manifest_digest,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


__all__ = ["gamma_atmosphere_input_signature"]
