"""Exact legacy GAMMA BM3D command construction."""

from __future__ import annotations

from pathlib import Path

from ...models import FilteringPair, FilteringPlan


def bm3d_commands(
    pair: FilteringPair, plan: FilteringPlan, output_dir: Path
) -> tuple[tuple[str, ...], ...]:
    target = Path(output_dir)
    filtered = target / "pair.tflt.filt"
    coherence = target / "pair.coh.filt"
    case = plan.case
    return (
        (
            "bm3d",
            str(pair.interferogram),
            str(plan.width),
            str(filtered),
            str(case.bm3d_mode),
            str(case.bm3d_sigma),
            str(case.bm3d_search_window),
            "-",
            str(case.bm3d_block_size),
            str(case.bm3d_block_step),
            str(case.bm3d_group_size),
            str(case.bm3d_transform),
            "-",
            "-",
        ),
        (
            "cc_wave",
            str(pair.interferogram),
            str(pair.master_mli),
            str(pair.slave_mli),
            str(coherence),
            str(plan.width),
        ),
    )


__all__ = ["bm3d_commands"]
