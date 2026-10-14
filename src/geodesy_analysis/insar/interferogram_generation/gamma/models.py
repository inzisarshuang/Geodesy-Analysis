"""Immutable inputs and plans for GAMMA interferogram generation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from geodesy_analysis.common.case_paths import AnalysisCasePaths
from geodesy_analysis.insar.common.registered_stack import RegisteredStack


@dataclass(frozen=True)
class GammaInterferogramCase:
    """One resolved interferogram case and all user-controlled parameters."""

    paths: AnalysisCasePaths
    registered_stack: Path
    baseline_manifest: Path
    polarization: str
    range_looks: int
    azimuth_looks: int
    radar_height: Path
    spectral_filter: Literal["auto", "on", "off"]
    create_offset_range_start: int
    create_offset_azimuth_start: int
    create_offset_range_window: int
    create_offset_azimuth_window: int
    create_offset_range_search: int
    create_offset_azimuth_search: int
    create_offset_correlation_threshold: float
    coherence_range_window: int
    coherence_azimuth_window: int
    coherence_estimator: int
    output_dir: Path

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
class BaselineManifest:
    """Validated identity and ordered network published by baseline selection."""

    source_path: Path
    schema_version: int
    case_id: str | None
    registered_stack: Path | None
    stack_digest: str
    polarization: str
    reference_date: str
    network_type: str
    network_path: Path
    pair_count: int


@dataclass(frozen=True)
class InterferogramPair:
    """One ordered master/slave date pair from the selected network."""

    master: str
    slave: str

    @property
    def name(self) -> str:
        return f"{self.master}-{self.slave}"


@dataclass(frozen=True)
class GammaInterferogramPlan:
    """Validated, side-effect-free plan for an interferogram batch."""

    case: GammaInterferogramCase
    stack: RegisteredStack
    baseline: BaselineManifest
    pairs: tuple[InterferogramPair, ...]
    spectral_filter_range: int
    spectral_filter_azimuth: int


__all__ = [
    "BaselineManifest",
    "GammaInterferogramCase",
    "GammaInterferogramPlan",
    "InterferogramPair",
]
