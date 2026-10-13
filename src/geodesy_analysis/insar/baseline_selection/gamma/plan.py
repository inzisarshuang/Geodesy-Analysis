"""Side-effect-free GAMMA baseline plan construction."""

from __future__ import annotations

from geodesy_analysis.insar.common.registered_stack import read_registered_stack

from .models import GammaBaselineCase, GammaBaselinePlan


def _number(value: float) -> str:
    return str(int(value)) if value.is_integer() else format(value, ".15g")


def _base_calc_command(
    case: GammaBaselineCase, reference_parameter: str
) -> tuple[str, ...]:
    common = (
        "base_calc",
        "SLC_tab",
        reference_parameter,
        "Berp_SC",
        "itab_SC",
    )
    if case.network_type == "DSI":
        return common + ("1", "1", "-", "10000", "-", "10000", "-")
    if case.network_type == "SBAS":
        return common + (
            "1",
            "1",
            "-",
            _number(case.max_perpendicular_baseline),
            "-",
            _number(case.max_temporal_baseline),
            "-",
        )
    return common + ("0", "1", "-", "-", "-", "-", "-")


def build_gamma_baseline_plan(case: GammaBaselineCase) -> GammaBaselinePlan:
    """Validate a registered stack and build one deterministic execution plan."""

    if not isinstance(case, GammaBaselineCase):
        raise TypeError("case must be GammaBaselineCase")
    stack = read_registered_stack(
        case.registered_stack,
        project_root=case.project_root,
        polarization=case.polarization,
    )
    by_date = {asset.date: asset for asset in stack.assets}
    reference_parameter = by_date[stack.reference_date].parameter_path
    images_text = "".join(f"{date}\n" for date in stack.dates)
    slc_tab_text = "".join(
        f"{by_date[date].data_path} {by_date[date].parameter_path}\n"
        for date in stack.dates
    )
    return GammaBaselinePlan(
        case=case,
        stack=stack,
        base_calc_command=_base_calc_command(case, str(reference_parameter)),
        expected_network_name=f"baseline_select_{case.network_type}",
        images_text=images_text,
        slc_tab_text=slc_tab_text,
    )


__all__ = ["build_gamma_baseline_plan"]
