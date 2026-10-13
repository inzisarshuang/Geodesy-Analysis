"""Immutable configuration and plan models for GAMMA baseline selection."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from geodesy_analysis.insar.common.registered_stack import RegisteredStack


@dataclass(frozen=True)
class GammaBaselineCase:
    """One resolved project case for a single polarization and network type."""

    name: str
    project_root: Path
    registered_stack: Path
    polarization: str
    network_type: Literal["DSI", "SBAS", "PSI"]
    max_perpendicular_baseline: float
    max_temporal_baseline: float
    output_dir: Path


@dataclass(frozen=True)
class GammaBaselinePlan:
    """Validated, side-effect-free plan for one GAMMA baseline calculation."""

    case: GammaBaselineCase
    stack: RegisteredStack
    base_calc_command: tuple[str, ...]
    expected_network_name: str
    images_text: str
    slc_tab_text: str


__all__ = ["GammaBaselineCase", "GammaBaselinePlan"]
