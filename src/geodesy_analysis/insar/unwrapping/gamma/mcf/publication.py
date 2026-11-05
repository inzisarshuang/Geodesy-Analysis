"""Deterministic identity helpers for GAMMA MCF publication."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .models import GammaMcfPlan


def unwrapping_input_signature(plan: GammaMcfPlan) -> str:
    root = plan.case.project_root

    def relative(path: Path) -> str:
        resolved = Path(path).resolve()
        try:
            return resolved.relative_to(root).as_posix()
        except ValueError:
            return resolved.as_posix()

    external = plan.case.external_mask
    payload = {
        "case_id": plan.case.case_id,
        "coherence_threshold": plan.case.coherence_threshold,
        "external_mask": None if external is None else {"path": relative(external), "sha256": hashlib.sha256(external.read_bytes()).hexdigest()},
        "filtering_manifest": relative(plan.filtering.source_path),
        "filtering_manifest_digest": plan.filtering.source_digest,
        "grid": {"lines": plan.lines, "width": plan.width},
        "mask_operation": plan.case.mask_operation,
        "mcf_mode": plan.case.mcf_mode,
        "pair_list": (
            None
            if plan.case.pair_list is None
            else {
                "path": relative(plan.case.pair_list),
                "sha256": plan.pair_list_digest,
            }
        ),
        "pairs": [pair.name for pair in plan.pairs],
        "reference": {
            "azimuth": plan.case.reference_azimuth,
            "mode": plan.case.reference_mode,
            "range": plan.case.reference_range,
        },
        "radar_height": {
            "path": relative(plan.radar_height),
            "sha256": hashlib.sha256(plan.radar_height.read_bytes()).hexdigest(),
        },
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


__all__ = ["unwrapping_input_signature"]
