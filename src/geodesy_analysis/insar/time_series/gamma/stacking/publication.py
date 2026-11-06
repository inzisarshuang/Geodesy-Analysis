"""Deterministic identity for GAMMA stacking."""

from __future__ import annotations

import hashlib
import json

from geodesy_analysis.insar.time_series.gamma.common import (
    gamma_time_series_asset_identities,
)

from .models import GammaStackingPlan

COMMAND_CONTRACT = ("stacking", "dispmap", "geocode_back", "rasdt_pwr")


def gamma_stacking_input_signature(plan: GammaStackingPlan) -> str:
    payload = {
        "atmosphere_manifest_digest": plan.inputs.atmosphere_manifest_digest,
        "auxiliary_assets": gamma_time_series_asset_identities(plan.inputs),
        "baseline_manifest_digest": plan.inputs.baseline_manifest_digest,
        "case_id": plan.case.case_id,
        "colormap": plan.case.colormap,
        "display": [plan.case.display_min, plan.case.display_max],
        "grid": [plan.inputs.width, plan.inputs.lines],
        "map_grid": [plan.inputs.map_width, plan.inputs.map_lines],
        "pair_list_digest": plan.inputs.pair_list_digest,
        "pairs": [
            [pair.name, pair.perpendicular_baseline, pair.temporal_baseline_days]
            for pair in plan.inputs.pairs
        ],
        "reference_window": [
            plan.case.reference_range,
            plan.case.reference_azimuth,
            plan.case.reference_width,
            plan.case.reference_height,
        ],
        "command_contract": COMMAND_CONTRACT,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


__all__ = ["gamma_stacking_input_signature"]
