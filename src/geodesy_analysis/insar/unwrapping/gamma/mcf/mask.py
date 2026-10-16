"""Final-mask generation and reference selection for GAMMA MCF."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from insar_data_adapter import read_binary_raster

from geodesy_analysis.insar.masking import (
    coherence_mask,
    combine_masks,
    mask_valid_ratio,
    read_mask,
    write_mask,
)

from .models import GammaMcfPlan


@dataclass(frozen=True)
class MaskProducts:
    mask: np.ndarray
    mean_coherence: np.ndarray
    final_mask: Path
    binary_mask: Path
    metadata: Path
    valid_count: int
    valid_ratio: float


@dataclass(frozen=True)
class ReferencePoint:
    mode: str
    range_index: int
    azimuth_index: int
    coherence: float
    command_range: int
    command_azimuth: int


def build_unwrapping_mask(plan: GammaMcfPlan, output_dir: Path) -> MaskProducts:
    mean = read_binary_raster(
        plan.mean_coherence, (plan.lines, plan.width), dtype="float32", endian="big"
    ).astype(np.float32)
    masks = [coherence_mask(mean, plan.case.coherence_threshold)]
    if plan.case.external_mask is not None:
        masks.append(
            read_mask(str(plan.case.external_mask), plan.lines, plan.width)
        )
    final = (
        masks[0]
        if len(masks) == 1
        else combine_masks(masks, plan.case.mask_operation)
    ).astype(np.uint8)
    valid_count = int(np.count_nonzero(final))
    if valid_count == 0:
        raise ValueError("final unwrapping mask is empty")
    directory = Path(output_dir) / "mask"
    directory.mkdir(parents=True, exist_ok=True)
    final_path = directory / "final.mask.bmp"
    binary_path = directory / "final.mask.bin"
    metadata_path = directory / "mask_metadata.json"
    write_mask(final, str(final_path))
    final.tofile(binary_path)
    ratio = mask_valid_ratio(final)
    metadata = {
        "coherence_threshold": plan.case.coherence_threshold,
        "external_mask_project_path": (
            None
            if plan.case.external_mask is None
            else plan.case.external_mask.relative_to(plan.case.project_root).as_posix()
        ),
        "grid": {"lines": plan.lines, "width": plan.width},
        "mask_operation": plan.case.mask_operation,
        "valid_count": valid_count,
        "valid_ratio": ratio,
    }
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return MaskProducts(
        mask=final,
        mean_coherence=mean,
        final_mask=final_path,
        binary_mask=binary_path,
        metadata=metadata_path,
        valid_count=valid_count,
        valid_ratio=ratio,
    )


def select_reference_point(
    mean_coherence: np.ndarray, mask: np.ndarray
) -> tuple[int, int, float]:
    mean = np.asarray(mean_coherence, dtype=np.float64)
    valid = np.asarray(mask, dtype=bool)
    if mean.shape != valid.shape:
        raise ValueError("reference mask shape does not match mean coherence")
    candidates = valid & np.isfinite(mean)
    if not np.any(candidates):
        raise ValueError("final mask contains no finite reference candidate")
    values = np.where(candidates, mean, -np.inf)
    flat = int(np.argmax(values))
    azimuth, range_index = np.unravel_index(flat, values.shape)
    return int(range_index), int(azimuth), float(values[azimuth, range_index])


def resolve_reference_point(
    plan: GammaMcfPlan, mask_products: MaskProducts
) -> ReferencePoint:
    if plan.case.reference_mode == "auto":
        range_index, azimuth_index, coherence = select_reference_point(
            mask_products.mean_coherence, mask_products.mask
        )
    else:
        assert plan.case.reference_range is not None
        assert plan.case.reference_azimuth is not None
        range_index = plan.case.reference_range
        azimuth_index = plan.case.reference_azimuth
        if not (0 <= range_index < plan.width and 0 <= azimuth_index < plan.lines):
            raise ValueError("manual reference point is outside the raster")
        if not bool(mask_products.mask[azimuth_index, range_index]):
            raise ValueError("manual reference point is masked out")
        coherence = float(mask_products.mean_coherence[azimuth_index, range_index])
        if not np.isfinite(coherence):
            raise ValueError("manual reference point coherence is not finite")
    return ReferencePoint(
        mode=plan.case.reference_mode,
        range_index=range_index,
        azimuth_index=azimuth_index,
        coherence=coherence,
        command_range=range_index,
        command_azimuth=azimuth_index,
    )


__all__ = [
    "MaskProducts",
    "ReferencePoint",
    "build_unwrapping_mask",
    "resolve_reference_point",
    "select_reference_point",
]
