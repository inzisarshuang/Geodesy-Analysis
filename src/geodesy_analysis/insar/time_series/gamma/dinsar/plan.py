"""Build one validated single-pair GAMMA DInSAR plan."""

from __future__ import annotations

from geodesy_analysis.insar.time_series.gamma.common import load_gamma_time_series_inputs

from .models import GammaDinsarCase, GammaDinsarPlan


def build_gamma_dinsar_plan(case: GammaDinsarCase) -> GammaDinsarPlan:
    if not isinstance(case, GammaDinsarCase):
        raise TypeError("case must be GammaDinsarCase")
    inputs = load_gamma_time_series_inputs(
        project_root=case.project_root,
        atmosphere_manifest=case.atmosphere_manifest,
        pair_list=None,
        lookup_table=case.lookup_table,
        map_dem=case.map_dem,
        map_dem_parameter=case.map_dem_parameter,
    )
    if inputs.case_id != case.case_id:
        raise ValueError("atmosphere case_id does not match DInSAR case")
    selected = next((pair for pair in inputs.pairs if pair.name == case.pair), None)
    if selected is None:
        raise ValueError(f"selected pair is unavailable: {case.pair}")
    return GammaDinsarPlan(case, inputs, selected)


__all__ = ["build_gamma_dinsar_plan"]
