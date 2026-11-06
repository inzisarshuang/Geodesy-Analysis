"""Build validated GAMMA mb plans."""

from __future__ import annotations

from geodesy_analysis.insar.time_series.gamma.common import load_gamma_time_series_inputs

from .models import GammaMbCase, GammaMbPlan


def build_gamma_mb_plan(case: GammaMbCase) -> GammaMbPlan:
    if not isinstance(case, GammaMbCase):
        raise TypeError("case must be GammaMbCase")
    inputs = load_gamma_time_series_inputs(
        project_root=case.project_root,
        atmosphere_manifest=case.atmosphere_manifest,
        pair_list=case.pair_list,
        lookup_table=case.lookup_table,
        map_dem=case.map_dem,
        map_dem_parameter=case.map_dem_parameter,
    )
    if inputs.case_id != case.case_id:
        raise ValueError("atmosphere case_id does not match GAMMA mb case")
    if inputs.final_mask is None:
        raise ValueError("GAMMA mb requires the MCF binary final mask")
    if (
        case.reference_range + case.reference_width > inputs.width
        or case.reference_azimuth + case.reference_height > inputs.lines
    ):
        raise ValueError("GAMMA mb reference window leaves the radar grid")
    return GammaMbPlan(case, inputs)


__all__ = ["build_gamma_mb_plan"]
