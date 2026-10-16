"""Immutable configuration and planning models for InSAR filtering."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from geodesy_analysis.common.case_paths import AnalysisCasePaths


class FilteringMethod(str, Enum):
    NL_INSAR = "nl_insar"
    GAMMA_BM3D = "gamma_bm3d"
    GAMMA_ADF = "gamma_adf"

    @property
    def directory_name(self) -> str:
        return self.value.upper()


@dataclass(frozen=True)
class FilteringCase:
    paths: AnalysisCasePaths
    interferogram_manifest: Path
    method: FilteringMethod
    output_dir: Path
    visualization_dir: Path
    search_window: int = 13
    patch_size: int = 3
    minimum_looks: int = 80
    likelihood_h: float | None = None
    coherence_window: int = 11
    filter_threshold: float = 0.3
    tile_size: int = 96
    point_threshold: float = 0.3
    seed: int = 20260717
    bm3d_mode: int = 1
    bm3d_sigma: int = 6
    bm3d_search_window: int = 10
    bm3d_block_size: int = 8
    bm3d_block_step: int = 16
    bm3d_group_size: int = 3
    bm3d_transform: int = 0
    adf_alpha: float = 0.4
    adf_first_window: int = 64
    adf_second_window: int = 16
    adf_steps: int = 5

    @property
    def name(self) -> str:
        return self.paths.label

    @property
    def project_root(self) -> Path:
        return self.paths.project_root

    @property
    def case_root(self) -> Path:
        return self.paths.case_root

    @property
    def case_id(self) -> str:
        return self.paths.case_id


@dataclass(frozen=True)
class MLIAsset:
    date: str
    data_path: Path
    parameter_path: Path


@dataclass(frozen=True)
class FilteringPair:
    master: str
    slave: str
    interferogram: Path
    master_mli: Path
    slave_mli: Path

    @property
    def name(self) -> str:
        return f"{self.master}-{self.slave}"


@dataclass(frozen=True)
class InterferogramManifest:
    source_path: Path
    schema_version: int
    case_id: str | None
    mli_assets: tuple[MLIAsset, ...]
    average_mli: Path
    source_digest: str


@dataclass(frozen=True)
class FilteringPlan:
    case: FilteringCase
    manifest: InterferogramManifest
    pairs: tuple[FilteringPair, ...]
    width: int
    lines: int


__all__ = [
    "FilteringCase",
    "FilteringMethod",
    "FilteringPair",
    "FilteringPlan",
    "InterferogramManifest",
    "MLIAsset",
]
