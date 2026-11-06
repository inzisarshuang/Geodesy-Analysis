"""Immutable models for single-pair GAMMA DInSAR."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from geodesy_analysis.common.case_paths import AnalysisCasePaths
from geodesy_analysis.insar.time_series.gamma.common import (
    GammaTimeSeriesInputs,
    GammaTimeSeriesPair,
)


@dataclass(frozen=True)
class GammaDinsarCase:
    paths: AnalysisCasePaths
    atmosphere_manifest: Path
    pair: str
    lookup_table: Path | None
    map_dem: Path | None
    map_dem_parameter: Path | None
    display_min: float
    display_max: float
    colormap: str
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
class GammaDinsarPlan:
    case: GammaDinsarCase
    inputs: GammaTimeSeriesInputs
    pair: GammaTimeSeriesPair


__all__ = ["GammaDinsarCase", "GammaDinsarPlan"]
