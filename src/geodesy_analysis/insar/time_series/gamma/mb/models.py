"""Immutable models for GAMMA mb SBAS/ISBAS processing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from geodesy_analysis.common.case_paths import AnalysisCasePaths
from geodesy_analysis.insar.time_series.gamma.common import GammaTimeSeriesInputs


@dataclass(frozen=True)
class GammaMbCase:
    paths: AnalysisCasePaths
    atmosphere_manifest: Path
    pair_list: Path | None
    lookup_table: Path | None
    map_dem: Path | None
    map_dem_parameter: Path | None
    mb_mode: int
    reference_range: int
    reference_azimuth: int
    reference_width: int
    reference_height: int
    gamma: float
    dtmax: float
    generate_mean_geocoded: bool
    generate_displacement: bool
    generate_geocoded_displacement: bool
    display_min: float
    display_max: float
    colormap: str
    visdt_pwr: Path | None
    output_dir: Path
    figure_dir: Path
    log_dir: Path

    @property
    def name(self) -> str:
        return self.paths.label

    @property
    def case_id(self) -> str:
        return self.paths.case_id

    @property
    def project_root(self) -> Path:
        return self.paths.project_root


@dataclass(frozen=True)
class GammaMbPlan:
    case: GammaMbCase
    inputs: GammaTimeSeriesInputs

    @property
    def intermediate_dir(self) -> Path:
        return self.case.output_dir / "INTERMEDIATE"

    @property
    def displacement_dir(self) -> Path:
        return self.case.output_dir / "DISPLACEMENT"

    @property
    def geocoded_displacement_dir(self) -> Path:
        return self.case.output_dir / "DISPLACEMENT_GEO"


__all__ = ["GammaMbCase", "GammaMbPlan"]
