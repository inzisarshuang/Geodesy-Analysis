"""Validate filtering lineage and build a side-effect-free GAMMA MCF plan."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from geodesy_analysis.common.case_paths import resolve_case_input, resolve_project_input
from geodesy_analysis.insar.filtering.publication import ensure_nonempty, gamma_parameter

from .models import FilteringManifest, GammaMcfCase, GammaMcfPlan, UnwrappingPair

_PAIR = re.compile(r"(\d{8})-(\d{8})\Z")


def _asset(base: Path, value: object, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"manifest {label} path is required")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"manifest {label} path is unsafe")
    target = (base / relative).resolve()
    try:
        target.relative_to(base.resolve())
    except ValueError as error:
        raise ValueError(f"manifest {label} leaves its product directory") from error
    return ensure_nonempty(target, label)


def _size(path: Path, expected: int, label: str) -> None:
    if path.stat().st_size != expected:
        raise ValueError(f"{label} byte size mismatch: {path.stat().st_size} != {expected}")


def build_gamma_mcf_plan(case: GammaMcfCase) -> GammaMcfPlan:
    if not isinstance(case, GammaMcfCase):
        raise TypeError("case must be GammaMcfCase")
    source = ensure_nonempty(case.filtering_manifest, "filtering manifest")
    raw = source.read_bytes()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid filtering manifest JSON {source}: {error}") from error
    if not isinstance(payload, dict) or payload.get("schema_version") != 2:
        raise ValueError("filtering manifest schema_version must be 2")
    if payload.get("status") != "complete":
        raise ValueError("filtering manifest status must be complete")
    if payload.get("case_id") != case.case_id:
        raise ValueError("filtering manifest case_id does not match configured case")
    method = payload.get("method")
    if method not in {"nl_insar", "gamma_bm3d", "gamma_adf"}:
        raise ValueError("filtering manifest method is invalid")
    grid = payload.get("grid")
    if not isinstance(grid, dict):
        raise ValueError("filtering manifest grid is required")
    width, lines = grid.get("width"), grid.get("lines")
    if not isinstance(width, int) or not isinstance(lines, int) or width <= 0 or lines <= 0:
        raise ValueError("filtering manifest grid dimensions are invalid")
    float_size, complex_size = width * lines * 4, width * lines * 8
    mean = _asset(source.parent, payload.get("mean_coherence_path"), "mean coherence")
    _size(mean, float_size, "mean coherence")
    upstream_value = payload.get("interferogram_manifest_project_path")
    if not isinstance(upstream_value, str):
        raise ValueError("filtering manifest interferogram identity is required")
    upstream = resolve_project_input(case.paths, upstream_value)
    upstream_raw = upstream.read_bytes()
    upstream_digest = hashlib.sha256(upstream_raw).hexdigest()
    if payload.get("interferogram_manifest_digest") != upstream_digest:
        raise ValueError("filtering manifest interferogram digest does not match its source")
    try:
        upstream_payload = json.loads(upstream_raw)
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid interferogram manifest JSON {upstream}: {error}") from error
    if not isinstance(upstream_payload, dict) or upstream_payload.get("schema_version") not in {1, 2}:
        raise ValueError("interferogram manifest schema_version must be 1 or 2")
    if upstream_payload.get("status") != "complete":
        raise ValueError("interferogram manifest status must be complete")
    if upstream_payload.get("schema_version") == 2 and upstream_payload.get("case_id") != case.case_id:
        raise ValueError("interferogram manifest case_id is inconsistent")

    raw_mli = upstream_payload.get("mli_assets")
    if not isinstance(raw_mli, list) or not raw_mli:
        raise ValueError("interferogram manifest MLI inventory is missing")
    mli_assets: list[Path] = []
    shape: tuple[int, int] | None = None
    for item in raw_mli:
        if not isinstance(item, dict):
            raise ValueError("interferogram manifest MLI item is invalid")
        data = _asset(upstream.parent, item.get("data_path"), "MLI")
        parameter = _asset(upstream.parent, item.get("parameter_path"), "MLI parameter")
        current = (gamma_parameter(parameter, "range_samples"), gamma_parameter(parameter, "azimuth_lines"))
        if shape is None:
            shape = current
        elif current != shape:
            raise ValueError("interferogram MLI shapes do not match")
        _size(data, float_size, "MLI")
        mli_assets.append(data)
    if shape != (width, lines):
        raise ValueError("filtering grid does not match interferogram MLI grid")

    if upstream_payload.get("schema_version") == 2:
        radar = resolve_project_input(case.paths, upstream_payload.get("radar_height_project_path", ""))
    else:
        radar_info = upstream_payload.get("radar_height")
        if not isinstance(radar_info, dict) or not isinstance(radar_info.get("path"), str):
            raise ValueError("interferogram manifest radar height is required")
        radar = resolve_case_input(case.paths, radar_info["path"])
    _size(ensure_nonempty(radar, "radar height"), float_size, "radar height")

    upstream_pairs = upstream_payload.get("pairs")
    if not isinstance(upstream_pairs, list):
        raise ValueError("interferogram manifest pair inventory is missing")
    upstream_names = [item.get("pair") for item in upstream_pairs if isinstance(item, dict)]
    raw_pairs = payload.get("pairs")
    if not isinstance(raw_pairs, list) or payload.get("pair_count") != len(raw_pairs):
        raise ValueError("filtering manifest pair inventory is incomplete")
    pairs: list[UnwrappingPair] = []
    for item in raw_pairs:
        if not isinstance(item, dict) or not isinstance(item.get("products"), dict):
            raise ValueError("filtering manifest pair item is invalid")
        name = item.get("pair")
        match = _PAIR.fullmatch(name) if isinstance(name, str) else None
        if match is None:
            raise ValueError("filtering manifest pair name is invalid")
        products = item["products"]
        filtered = _asset(source.parent, products.get("filtered_interferogram"), "filtered interferogram")
        coherence = _asset(source.parent, products.get("filtered_coherence"), "filtered coherence")
        _size(filtered, complex_size, "filtered interferogram")
        _size(coherence, float_size, "filtered coherence")
        pairs.append(UnwrappingPair(match.group(1), match.group(2), filtered, coherence))
    pairs.sort(key=lambda item: item.name)
    if [pair.name for pair in pairs] != sorted(upstream_names):
        raise ValueError("filtering and interferogram pair inventory is inconsistent")
    filtering = FilteringManifest(
        source_path=source,
        source_digest=hashlib.sha256(raw).hexdigest(),
        method=method,
        interferogram_manifest=upstream,
        interferogram_digest=upstream_digest,
        mean_coherence=mean,
    )
    return GammaMcfPlan(case, filtering, tuple(pairs), width, lines, mean, tuple(mli_assets), radar)


__all__ = ["build_gamma_mcf_plan"]
