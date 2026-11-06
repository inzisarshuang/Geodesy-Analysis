"""Deterministic identity for single-pair GAMMA DInSAR."""

from __future__ import annotations

import hashlib
import json

from geodesy_analysis.insar.time_series.gamma.common import (
    gamma_time_series_asset_identities,
)

from .models import GammaDinsarPlan

COMMAND_CONTRACT = ("dispmap", "geocode_back", "rasdt_pwr")


def gamma_dinsar_input_signature(plan: GammaDinsarPlan) -> str:
    payload = {
        "atmosphere_manifest_digest": plan.inputs.atmosphere_manifest_digest,
        "auxiliary_assets": gamma_time_series_asset_identities(plan.inputs),
        "case_id": plan.case.case_id,
        "colormap": plan.case.colormap,
        "display": [plan.case.display_min, plan.case.display_max],
        "grid": [plan.inputs.width, plan.inputs.lines],
        "map_grid": [plan.inputs.map_width, plan.inputs.map_lines],
        "pair": [
            plan.pair.name,
            plan.pair.perpendicular_baseline,
            plan.pair.temporal_baseline_days,
        ],
        "command_contract": COMMAND_CONTRACT,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


__all__ = ["gamma_dinsar_input_signature"]
