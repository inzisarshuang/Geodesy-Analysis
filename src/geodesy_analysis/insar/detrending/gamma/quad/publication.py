"""Deterministic identity helpers for GAMMA quad detrending."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .models import GammaQuadDetrendPlan


def _portable(plan: GammaQuadDetrendPlan, path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(plan.case.project_root).as_posix()
    except ValueError:
        return resolved.as_posix()


def quad_detrend_input_signature(plan: GammaQuadDetrendPlan) -> str:
    payload = {
        "case_id": plan.case.case_id,
        "coherence_threshold": plan.case.coherence_threshold,
        "filtering_manifest_digest": plan.filtering_manifest_digest,
        "interferogram_manifest_digest": plan.interferogram_manifest_digest,
        "pair_list": (
            None
            if plan.case.pair_list is None
            else {
                "path": _portable(plan, plan.case.pair_list),
                "sha256": plan.pair_list_digest,
            }
        ),
        "pairs": [
            {
                "coherence": _portable(plan, pair.coherence),
                "master_mli_parameter": _portable(plan, pair.master_mli_parameter),
                "name": pair.name,
                "unwrapped": _portable(plan, pair.unwrapped),
            }
            for pair in plan.pairs
        ],
        "trend_model": plan.case.trend_model,
        "unwrapping_manifest_digest": plan.unwrapping_manifest_digest,
        "grid": {"lines": plan.lines, "width": plan.width},
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


__all__ = ["quad_detrend_input_signature"]
