"""Immutable models for GAMMA MCF unwrapping."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from geodesy_analysis.common.case_paths import AnalysisCasePaths


@dataclass(frozen=True)
class GammaMcfCase:
    paths: AnalysisCasePaths
    filtering_manifest: Path
    mcf_mode: int
    reference_mode: Literal["auto", "manual"]
    reference_range: int | None
    reference_azimuth: int | None
    coherence_threshold: float
    external_mask: Path | None
    mask_operation: Literal["and", "or", "xor"]
    output_dir: Path
    visualization_dir: Path

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
class FilteringManifest:
    source_path: Path
    source_digest: str
    method: str
    interferogram_manifest: Path
    interferogram_digest: str
    mean_coherence: Path


@dataclass(frozen=True)
class UnwrappingPair:
    master: str
    slave: str
    filtered_interferogram: Path
    filtered_coherence: Path

    @property
    def name(self) -> str:
        return f"{self.master}-{self.slave}"


@dataclass(frozen=True)
class GammaMcfPlan:
    case: GammaMcfCase
    filtering: FilteringManifest
    pairs: tuple[UnwrappingPair, ...]
    width: int
    lines: int
    mean_coherence: Path
    mli_assets: tuple[Path, ...]
    radar_height: Path


__all__ = ["FilteringManifest", "GammaMcfCase", "GammaMcfPlan", "UnwrappingPair"]
