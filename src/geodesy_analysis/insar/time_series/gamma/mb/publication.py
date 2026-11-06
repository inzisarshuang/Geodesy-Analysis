"""Deterministic identity for GAMMA mb."""

from __future__ import annotations

import hashlib
import json

from .models import GammaMbPlan


def gamma_mb_input_signature(plan: GammaMbPlan) -> str:
    payload = {
        "atmosphere_manifest_digest": plan.inputs.atmosphere_manifest_digest,
        "case_id": plan.case.case_id,
        "dtmax": plan.case.dtmax,
        "flags": [
            plan.case.generate_mean_geocoded,
            plan.case.generate_displacement,
            plan.case.generate_geocoded_displacement,
        ],
        "gamma": plan.case.gamma,
        "grid": [plan.inputs.width, plan.inputs.lines],
        "map_grid": [plan.inputs.map_width, plan.inputs.map_lines],
        "mb_mode": plan.case.mb_mode,
        "pair_list_digest": plan.inputs.pair_list_digest,
        "pairs": [
            [pair.name, pair.temporal_baseline_days] for pair in plan.inputs.pairs
        ],
        "reference": [
            plan.case.reference_range,
            plan.case.reference_azimuth,
            plan.case.reference_width,
            plan.case.reference_height,
        ],
        "display": [
            plan.case.display_min,
            plan.case.display_max,
            plan.case.colormap,
        ],
        "visdt_pwr": None if plan.case.visdt_pwr is None else str(plan.case.visdt_pwr),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


__all__ = ["gamma_mb_input_signature"]
