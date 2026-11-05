"""Immutable models for GAMMA quadratic phase-trend removal."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from geodesy_analysis.common.case_paths import AnalysisCasePaths


@dataclass(frozen=True)
class GammaQuadDetrendCase:
    paths: AnalysisCasePaths
    unwrapping_manifest: Path
    coherence_threshold: float
    trend_model: int
    output_dir: Path
    visualization_dir: Path
    pair_list: Path | None = None
    intensity_background: bool = True

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
class GammaQuadPair:
    master: str
    slave: str
    unwrapped: Path
    coherence: Path
    master_mli: Path
    master_mli_parameter: Path

    @property
    def name(self) -> str:
        return f"{self.master}-{self.slave}"


@dataclass(frozen=True)
class GammaQuadDetrendPlan:
    case: GammaQuadDetrendCase
    pairs: tuple[GammaQuadPair, ...]
    width: int
    lines: int
    available_pair_count: int
    unwrapping_manifest_digest: str
    filtering_manifest: Path
    filtering_manifest_digest: str
    interferogram_manifest: Path
    interferogram_manifest_digest: str
    pair_list_digest: str | None


__all__ = [
    "GammaQuadDetrendCase",
    "GammaQuadDetrendPlan",
    "GammaQuadPair",
]
