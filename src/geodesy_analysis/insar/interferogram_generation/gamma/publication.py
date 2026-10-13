"""Validation and deterministic identity helpers for interferogram products."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .models import GammaInterferogramPlan


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def ensure_nonempty(path: Path, label: str) -> Path:
    """Require one command output to exist and contain data."""

    target = Path(path)
    if not target.is_file():
        raise ValueError(f"GAMMA did not create {label}: {target}")
    if target.stat().st_size == 0:
        raise ValueError(f"GAMMA created empty {label}: {target}")
    return target


def gamma_parameter(path: Path, key: str) -> int:
    """Read one positive integer from a GAMMA text parameter file."""

    source = ensure_nonempty(path, "parameter file")
    for raw in source.read_text(encoding="utf-8", errors="replace").splitlines():
        fields = raw.replace(":", " ").split()
        if len(fields) >= 2 and fields[0] == key:
            try:
                value = int(fields[1])
            except ValueError as error:
                raise ValueError(f"invalid {key} in GAMMA parameter file: {source}") from error
            if value <= 0:
                raise ValueError(f"invalid {key} in GAMMA parameter file: {source}")
            return value
    raise ValueError(f"missing {key} in GAMMA parameter file: {source}")


def interferogram_input_signature(plan: GammaInterferogramPlan) -> str:
    """Hash every scientific input and user-controlled execution parameter."""

    case = plan.case
    payload = {
        "azimuth_looks": case.azimuth_looks,
        "baseline_manifest": str(plan.baseline.source_path),
        "coherence": {
            "azimuth_window": case.coherence_azimuth_window,
            "estimator": case.coherence_estimator,
            "range_window": case.coherence_range_window,
        },
        "create_offset": {
            "azimuth_search": case.create_offset_azimuth_search,
            "azimuth_start": case.create_offset_azimuth_start,
            "azimuth_window": case.create_offset_azimuth_window,
            "correlation_threshold": case.create_offset_correlation_threshold,
            "range_search": case.create_offset_range_search,
            "range_start": case.create_offset_range_start,
            "range_window": case.create_offset_range_window,
        },
        "filter_flags": [plan.spectral_filter_range, plan.spectral_filter_azimuth],
        "pairs": [pair.name for pair in plan.pairs],
        "polarization": case.polarization,
        "radar_height": {
            "path": str(case.radar_height),
            "sha256": _sha256_file(case.radar_height),
        },
        "range_looks": case.range_looks,
        "reference_date": plan.stack.reference_date,
        "stack_digest": plan.stack.source_digest,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


__all__ = ["ensure_nonempty", "gamma_parameter", "interferogram_input_signature"]
