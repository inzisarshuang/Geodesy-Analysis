"""Immutable inputs and plans for GAMMA atmospheric phase correction."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from geodesy_analysis.common.case_paths import AnalysisCasePaths

GammaAtmosphereMethod = Literal[
    "none",
    "gamma_atm_mod_2d_auto",
    "gamma_atm_mod_2d_polygon",
    "gamma_fspf_atm_mod_2d",
]


@dataclass(frozen=True)
class GammaAtmosphereCase:
    paths: AnalysisCasePaths
    detrending_manifest: Path
    method: GammaAtmosphereMethod
    output_dir: Path
    figure_dir: Path
    log_dir: Path
    intensity_background: bool
    fit_window_range: int
    fit_window_azimuth: int
    fit_step_range: int
    fit_step_azimuth: int
    height_correlation_threshold: float
    polygon_file: Path | None
    fspf_mode: int
    fspf_window_size: int
    fspf_overlap: int

    @property
    def name(self) -> str:
        return self.paths.label

    @property
    def case_id(self) -> str:
        return self.paths.case_id

    @property
    def project_root(self) -> Path:
        return self.paths.project_root

    @property
    def case_root(self) -> Path:
        return self.paths.case_root


@dataclass(frozen=True)
class GammaAtmospherePair:
    master: str
    slave: str
    detrended_phase: Path
    coherence: Path
    master_mli: Path
    master_mli_parameter: Path

    @property
    def name(self) -> str:
        return f"{self.master}-{self.slave}"


@dataclass(frozen=True)
class GammaAtmosphereCommands:
    create_diff_par: str = "create_diff_par"
    atm_mod_2d: str = "atm_mod_2d"
    atm_sim_2d: str = "atm_sim_2d"
    sub_phase: str = "sub_phase"
    poly_mask: str = "poly_mask"
    float_math: str = "float_math"
    fspf: str = "fspf"


@dataclass(frozen=True)
class GammaAtmospherePlan:
    case: GammaAtmosphereCase
    pairs: tuple[GammaAtmospherePair, ...]
    width: int
    lines: int
    available_pair_count: int
    auto_mask: Path
    radar_height: Path
    detrending_manifest_digest: str
    unwrapping_manifest: Path
    unwrapping_manifest_digest: str
    filtering_manifest: Path
    filtering_manifest_digest: str
    interferogram_manifest: Path
    interferogram_manifest_digest: str
    polygon_digest: str | None
    commands: GammaAtmosphereCommands


__all__ = [
    "GammaAtmosphereCase",
    "GammaAtmosphereCommands",
    "GammaAtmosphereMethod",
    "GammaAtmospherePair",
    "GammaAtmospherePlan",
]
