"""Validate upstream lineage and build a side-effect-free atmosphere plan."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import numpy as np

from geodesy_analysis.common.case_paths import resolve_project_or_absolute_path
from geodesy_analysis.insar.filtering.publication import gamma_parameter

from .models import (
    GammaAtmosphereCase,
    GammaAtmosphereCommands,
    GammaAtmospherePair,
    GammaAtmospherePlan,
)

_PAIR = re.compile(r"(\d{8})-(\d{8})\Z")
_FILTERING_METHODS = {"nl_insar", "gamma_bm3d", "gamma_adf"}


def _digest(payload: dict[str, object], raw: bytes) -> str:
    supplied = payload.get("scientific_manifest_digest")
    if supplied is None:
        return hashlib.sha256(raw).hexdigest()
    if not isinstance(supplied, str) or re.fullmatch(r"[0-9a-f]{64}", supplied) is None:
        raise ValueError("manifest scientific_manifest_digest is invalid")
    return supplied


def _manifest(path: Path, label: str) -> tuple[dict[str, object], str]:
    source = Path(path)
    if source.is_symlink():
        raise ValueError(f"{label} must not be a symlink: {source}")
    if not source.is_file() or source.stat().st_size < 1:
        raise FileNotFoundError(f"{label} is missing or empty: {source}")
    raw = source.read_bytes()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid {label} JSON {source}: {error}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return payload, _digest(payload, raw)


def _complete(
    payload: dict[str, object], *, label: str, case_id: str, method: str | set[str]
) -> None:
    if payload.get("schema_version") != 2 or payload.get("status") != "complete":
        raise ValueError(f"{label} must be complete schema version 2")
    if payload.get("case_id") != case_id:
        raise ValueError(f"{label} case_id does not match configured case")
    accepted = {method} if isinstance(method, str) else method
    if payload.get("method") not in accepted:
        raise ValueError(f"{label} method is inconsistent")


def _local_product(base: Path, value: object, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"manifest {label} path is required")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"manifest {label} path is unsafe")
    target = base / relative
    if target.is_symlink():
        raise ValueError(f"{label} must not be a symlink: {target}")
    resolved = target.resolve()
    try:
        resolved.relative_to(base.resolve())
    except ValueError as error:
        raise ValueError(f"manifest {label} leaves its product directory") from error
    if not resolved.is_file() or resolved.stat().st_size < 1:
        raise FileNotFoundError(f"{label} is missing or empty: {resolved}")
    return resolved


def _project_product(
    case: GammaAtmosphereCase, value: object, label: str
) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"manifest {label} project path is required")
    raw = Path(value).expanduser()
    candidate = raw if raw.is_absolute() else case.project_root / raw
    if candidate.is_symlink():
        raise ValueError(f"{label} must not be a symlink: {candidate}")
    target = resolve_project_or_absolute_path(case.paths, value, label)
    if not target.is_file() or target.stat().st_size < 1:
        raise FileNotFoundError(f"{label} is missing or empty: {target}")
    return target


def _grid(payload: dict[str, object], label: str) -> tuple[int, int]:
    grid = payload.get("grid")
    if not isinstance(grid, dict):
        raise ValueError(f"{label} grid is required")
    width, lines = grid.get("width"), grid.get("lines")
    if (
        not isinstance(width, int)
        or not isinstance(lines, int)
        or width <= 0
        or lines <= 0
    ):
        raise ValueError(f"{label} grid dimensions are invalid")
    return width, lines


def _float_raster(path: Path, expected_size: int, label: str) -> Path:
    if path.stat().st_size != expected_size:
        raise ValueError(f"{label} byte size mismatch: {path}")
    values = np.memmap(path, dtype=">f4", mode="r")
    finite = bool(np.all(np.isfinite(values)))
    del values
    if not finite:
        raise ValueError(f"{label} contains non-finite values: {path}")
    return path


def _coherence(path: Path, expected_size: int) -> Path:
    _float_raster(path, expected_size, "filtered coherence")
    values = np.memmap(path, dtype=">f4", mode="r")
    valid = bool(np.all((values >= 0.0) & (values <= 1.0)))
    del values
    if not valid:
        raise ValueError(f"filtered coherence values are outside [0,1]: {path}")
    return path


def _manifest_reference(
    case: GammaAtmosphereCase,
    payload: dict[str, object],
    path_key: str,
    digest_key: str,
    label: str,
) -> tuple[Path, dict[str, object], str]:
    path = _project_product(case, payload.get(path_key), label)
    source, digest = _manifest(path, label)
    if payload.get(digest_key) != digest:
        raise ValueError(f"{label} digest does not match source")
    return path, source, digest


def _pair_names(payload: dict[str, object], label: str) -> tuple[str, ...]:
    records = payload.get("pairs")
    if not isinstance(records, list) or payload.get("pair_count") != len(records):
        raise ValueError(f"{label} pair inventory is incomplete")
    names: list[str] = []
    for item in records:
        if not isinstance(item, dict):
            raise ValueError(f"{label} pair item is invalid")
        name = item.get("pair")
        if not isinstance(name, str) or _PAIR.fullmatch(name) is None:
            raise ValueError(f"{label} pair name is invalid")
        if name in names:
            raise ValueError(f"{label} contains duplicate pair: {name}")
        names.append(name)
    if not names:
        raise ValueError(f"{label} contains no pairs")
    return tuple(names)


def _overlaps(first: Path, second: Path) -> bool:
    left, right = first.resolve(), second.resolve()
    return left == right or left in right.parents or right in left.parents


def build_gamma_atmosphere_plan(case: GammaAtmosphereCase) -> GammaAtmospherePlan:
    """Resolve and validate the full detrending-to-interferogram lineage."""

    if not isinstance(case, GammaAtmosphereCase):
        raise TypeError("case must be GammaAtmosphereCase")
    detrending, detrending_digest = _manifest(
        case.detrending_manifest, "detrending manifest"
    )
    _complete(
        detrending,
        label="detrending manifest",
        case_id=case.case_id,
        method="gamma_quad_detrending",
    )
    width, lines = _grid(detrending, "detrending manifest")
    expected_size = width * lines * 4

    unwrap_path, unwrapping, unwrap_digest = _manifest_reference(
        case,
        detrending,
        "unwrapping_manifest_project_path",
        "unwrapping_manifest_digest",
        "unwrapping manifest",
    )
    _complete(
        unwrapping,
        label="unwrapping manifest",
        case_id=case.case_id,
        method="gamma_mcf",
    )
    if _grid(unwrapping, "unwrapping manifest") != (width, lines):
        raise ValueError("detrending and unwrapping grid dimensions differ")

    filter_path, filtering, filter_digest = _manifest_reference(
        case,
        detrending,
        "filtering_manifest_project_path",
        "filtering_manifest_digest",
        "filtering manifest",
    )
    _complete(
        filtering,
        label="filtering manifest",
        case_id=case.case_id,
        method=_FILTERING_METHODS,
    )
    if _grid(filtering, "filtering manifest") != (width, lines):
        raise ValueError("detrending and filtering grid dimensions differ")
    if (
        _project_product(
            case,
            unwrapping.get("filtering_manifest_project_path"),
            "unwrapping filtering manifest",
        )
        != filter_path
        or unwrapping.get("filtering_manifest_digest") != filter_digest
    ):
        raise ValueError("unwrapping filtering lineage or digest is inconsistent")

    ifg_path, interferogram, ifg_digest = _manifest_reference(
        case,
        detrending,
        "interferogram_manifest_project_path",
        "interferogram_manifest_digest",
        "interferogram manifest",
    )
    if (
        interferogram.get("schema_version") != 2
        or interferogram.get("status") != "complete"
        or interferogram.get("case_id") != case.case_id
    ):
        raise ValueError(
            "interferogram manifest must be complete schema version 2 for the case"
        )
    if (
        _project_product(
            case,
            filtering.get("interferogram_manifest_project_path"),
            "filtering interferogram manifest",
        )
        != ifg_path
        or filtering.get("interferogram_manifest_digest") != ifg_digest
    ):
        raise ValueError("filtering interferogram lineage or digest is inconsistent")

    raw_mli = interferogram.get("mli_assets")
    if not isinstance(raw_mli, list) or not raw_mli:
        raise ValueError("interferogram manifest MLI inventory is missing")
    mli_by_date: dict[str, tuple[Path, Path]] = {}
    for item in raw_mli:
        if not isinstance(item, dict):
            raise ValueError("interferogram MLI item is invalid")
        date = item.get("date")
        if not isinstance(date, str) or re.fullmatch(r"\d{8}", date) is None:
            raise ValueError("interferogram MLI date is invalid")
        if date in mli_by_date:
            raise ValueError(f"interferogram manifest has duplicate MLI date: {date}")
        data = _local_product(ifg_path.parent, item.get("data_path"), "MLI")
        parameter = _local_product(
            ifg_path.parent, item.get("parameter_path"), "MLI parameter"
        )
        if (
            gamma_parameter(parameter, "range_samples") != width
            or gamma_parameter(parameter, "azimuth_lines") != lines
        ):
            raise ValueError(f"MLI parameter grid differs from atmosphere grid: {date}")
        _float_raster(data, expected_size, "MLI")
        mli_by_date[date] = (data, parameter)

    radar = _project_product(
        case, interferogram.get("radar_height_project_path"), "radar height"
    )
    _float_raster(radar, expected_size, "radar height")

    filtering_names = _pair_names(filtering, "filtering manifest")
    coherence_by_pair: dict[str, Path] = {}
    for item in filtering["pairs"]:  # type: ignore[index]
        products = item.get("products")
        if not isinstance(products, dict):
            raise ValueError("filtering manifest pair products are invalid")
        coherence_by_pair[item["pair"]] = _coherence(
            _local_product(
                filter_path.parent,
                products.get("filtered_coherence"),
                "filtered coherence",
            ),
            expected_size,
        )

    unwrapping_names = _pair_names(unwrapping, "unwrapping manifest")
    if not set(unwrapping_names).issubset(filtering_names):
        raise ValueError("unwrapping pair inventory is not a filtering subset")
    interferogram_pairs = interferogram.get("pairs")
    if not isinstance(interferogram_pairs, list):
        raise ValueError("interferogram manifest pair inventory is missing")
    ifg_names = [
        item.get("pair") for item in interferogram_pairs if isinstance(item, dict)
    ]
    if len(ifg_names) != len(interferogram_pairs) or len(set(ifg_names)) != len(ifg_names):
        raise ValueError("interferogram pair inventory is invalid")
    if not set(filtering_names).issubset(ifg_names):
        raise ValueError("filtering pair inventory is not an interferogram subset")

    mask = unwrapping.get("mask")
    if not isinstance(mask, dict):
        raise ValueError("unwrapping manifest MCF mask identity is required")
    auto_mask = _local_product(
        unwrap_path.parent, mask.get("final_mask_path"), "MCF final mask"
    )

    detrending_names = _pair_names(detrending, "detrending manifest")
    if not set(detrending_names).issubset(unwrapping_names):
        raise ValueError("detrending pair inventory is not an unwrapping subset")
    pairs: list[GammaAtmospherePair] = []
    for item in detrending["pairs"]:  # type: ignore[index]
        name = item["pair"]
        match = _PAIR.fullmatch(name)
        assert match is not None
        products = item.get("products")
        if not isinstance(products, dict):
            raise ValueError("detrending manifest pair products are invalid")
        phase = _float_raster(
            _local_product(
                case.detrending_manifest.parent,
                products.get("detrended_unwrapped"),
                "detrended unwrapped phase",
            ),
            expected_size,
            "detrended unwrapped phase",
        )
        master_assets = mli_by_date.get(match.group(1))
        if master_assets is None:
            raise ValueError(f"master MLI is missing for atmosphere pair: {name}")
        pairs.append(
            GammaAtmospherePair(
                master=match.group(1),
                slave=match.group(2),
                detrended_phase=phase,
                coherence=coherence_by_pair[name],
                master_mli=master_assets[0],
                master_mli_parameter=master_assets[1],
            )
        )

    polygon_digest = None
    if case.method == "gamma_atm_mod_2d_polygon":
        polygon = case.polygon_file
        if polygon is None or polygon.is_symlink() or not polygon.is_file():
            raise ValueError("polygon method requires a regular polygon file")
        raw_polygon = polygon.read_bytes()
        if not raw_polygon:
            raise ValueError("polygon file must not be empty")
        polygon_digest = hashlib.sha256(raw_polygon).hexdigest()
    elif case.polygon_file is not None:
        raise ValueError("polygon file is only valid for polygon atmosphere method")

    protected = (
        case.detrending_manifest,
        unwrap_path,
        filter_path,
        ifg_path,
        auto_mask,
        radar,
        *((case.polygon_file,) if case.polygon_file is not None else ()),
        *(
            source
            for pair in pairs
            for source in (
                pair.detrended_phase,
                pair.coherence,
                pair.master_mli,
                pair.master_mli_parameter,
            )
        ),
    )
    destinations = (case.output_dir, case.figure_dir, case.log_dir)
    for index, left in enumerate(destinations):
        if left.is_symlink():
            raise ValueError(f"atmosphere destination must not be a symlink: {left}")
        for right in destinations[index + 1 :]:
            if _overlaps(left, right):
                raise ValueError("atmosphere output, figure, and log paths overlap")
        for source in protected:
            if _overlaps(left, source):
                raise ValueError(
                    f"atmosphere destination overlaps an input: {left} overlaps {source}"
                )

    return GammaAtmospherePlan(
        case=case,
        pairs=tuple(pairs),
        width=width,
        lines=lines,
        available_pair_count=len(pairs),
        auto_mask=auto_mask,
        radar_height=radar,
        detrending_manifest_digest=detrending_digest,
        unwrapping_manifest=unwrap_path,
        unwrapping_manifest_digest=unwrap_digest,
        filtering_manifest=filter_path,
        filtering_manifest_digest=filter_digest,
        interferogram_manifest=ifg_path,
        interferogram_manifest_digest=ifg_digest,
        polygon_digest=polygon_digest,
        commands=GammaAtmosphereCommands(),
    )


__all__ = ["build_gamma_atmosphere_plan"]
