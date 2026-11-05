"""Exact two-pass legacy GAMMA ADF command construction."""

from __future__ import annotations

from pathlib import Path

from ...models import FilteringPair, FilteringPlan


def _number(value: float) -> str:
    return str(int(value)) if value.is_integer() else format(value, ".15g")


def adf_commands(
    pair: FilteringPair, plan: FilteringPlan, output_dir: Path
) -> tuple[tuple[str, ...], ...]:
    target = Path(output_dir)
    first_interferogram = target / ".first-pass.tflt"
    first_coherence = target / ".first-pass.coh"
    filtered = target / "pair.tflt.filt"
    coherence = target / "pair.coh.filt"
    case = plan.case
    common = (str(plan.width), _number(case.adf_alpha))
    return (
        (
            "adf",
            str(pair.interferogram),
            str(first_interferogram),
            str(first_coherence),
            *common,
            str(case.adf_first_window),
            str(case.adf_steps),
        ),
        (
            "adf",
            str(first_interferogram),
            str(filtered),
            str(coherence),
            *common,
            str(case.adf_second_window),
            str(case.adf_steps),
        ),
    )


__all__ = ["adf_commands"]
