"""Deterministic identity helpers for GAMMA MCF publication."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .models import GammaMcfPlan


def unwrapping_input_signature(plan: GammaMcfPlan) -> str:
    root = plan.case.project_root

    def relative(path: Path) -> str:
        return Path(path).resolve().relative_to(root).as_posix()

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
        "pairs": [pair.name for pair in plan.pairs],
        "reference": {
            "azimuth": plan.case.reference_azimuth,
            "mode": plan.case.reference_mode,
            "range": plan.case.reference_range,
        },
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


__all__ = ["unwrapping_input_signature"]
