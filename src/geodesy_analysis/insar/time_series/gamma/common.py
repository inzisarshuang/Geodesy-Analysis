"""Read-only preparation shared by GAMMA DInSAR, stacking, and mb."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from geodesy_analysis.insar.common.registered_stack import read_registered_stack
from geodesy_analysis.insar.filtering.publication import gamma_parameter
from geodesy_analysis.insar.network import (
    GammaNetworkRecord,
    read_gamma_network_records,
)

_PAIR = re.compile(r"(\d{8})-(\d{8})\Z")


@dataclass(frozen=True)
class GammaMliAsset:
    date: str
    data: Path
    parameter: Path


@dataclass(frozen=True)
class GammaTimeSeriesPair:
    master: str
    slave: str
    perpendicular_baseline: float
    temporal_baseline_days: float
    corrected_phase: Path

    @property
    def name(self) -> str:
        return f"{self.master}-{self.slave}"


@dataclass(frozen=True)
class GammaTimeSeriesInputs:
    project_root: Path
    case_id: str
    atmosphere_method: str
    atmosphere_manifest: Path
    atmosphere_manifest_digest: str
    interferogram_manifest: Path
    interferogram_manifest_digest: str
    baseline_manifest: Path
    baseline_manifest_digest: str
    registered_stack_manifest: Path
    registered_stack_manifest_digest: str
    lineage_manifest_digests: tuple[tuple[str, str], ...]
    pairs: tuple[GammaTimeSeriesPair, ...]
    acquisition_dates: tuple[str, ...]
    reference_date: str
    width: int
    lines: int
    mli_assets: tuple[GammaMliAsset, ...]
    radar_height: Path
    lookup_table: Path
    map_dem: Path
    map_dem_parameter: Path
    map_width: int
    map_lines: int
    pair_list: Path | None
    pair_list_digest: str | None


def _manifest_digest(payload: dict[str, object], raw: bytes) -> str:
    supplied = payload.get("scientific_manifest_digest")
    if supplied is None:
        return hashlib.sha256(raw).hexdigest()
    if not isinstance(supplied, str) or re.fullmatch(r"[0-9a-f]{64}", supplied) is None:
        raise ValueError("manifest scientific_manifest_digest is invalid")
    return supplied


def _manifest(path: Path, label: str) -> tuple[dict[str, object], str]:
    source = Path(path).expanduser()
    if source.is_symlink():
        raise ValueError(f"{label} must not be a symlink: {source}")
    source = source.resolve()
    if not source.is_file() or source.stat().st_size < 1:
        raise FileNotFoundError(f"{label} is missing or empty: {source}")
    raw = source.read_bytes()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid {label} JSON {source}: {error}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return payload, _manifest_digest(payload, raw)


def _path(
    project_root: Path,
    value: object,
    label: str,
    *,
    base: Path | None = None,
) -> Path:
    if not isinstance(value, (str, Path)) or not str(value):
        raise ValueError(f"{label} path is required")
    declared = Path(value).expanduser()
    if not declared.is_absolute():
        if ".." in declared.parts:
            raise ValueError(f"{label} path is unsafe")
        declared = (base or project_root) / declared
    if declared.is_symlink():
        raise ValueError(f"{label} must not be a symlink: {declared}")
    resolved = declared.resolve()
    if not Path(value).is_absolute() and base is None:
        try:
            resolved.relative_to(project_root)
        except ValueError as error:
            raise ValueError(f"{label} leaves project root") from error
    if not resolved.is_file() or resolved.stat().st_size < 1:
        raise FileNotFoundError(f"{label} is missing or empty: {resolved}")
    return resolved


def _complete(
    payload: dict[str, object], label: str, case_id: str | None = None
) -> None:
    if payload.get("schema_version") != 2 or payload.get("status") != "complete":
        raise ValueError(f"{label} must be complete schema version 2")
    if case_id is not None and payload.get("case_id") != case_id:
        raise ValueError(f"{label} case_id is inconsistent")


def _lineage_manifest(
    *,
    project_root: Path,
    atmosphere: dict[str, object],
    prefix: str,
    case_id: str,
) -> tuple[Path, dict[str, object], str]:
    path = _path(
        project_root,
        atmosphere.get(f"{prefix}_manifest_project_path"),
        f"{prefix} manifest",
    )
    payload, digest = _manifest(path, f"{prefix} manifest")
    _complete(payload, f"{prefix} manifest", case_id)
    if atmosphere.get(f"{prefix}_manifest_digest") != digest:
        raise ValueError(f"{prefix} manifest digest does not match source")
    return path, payload, digest


def _float_raster(path: Path, expected_size: int, label: str) -> Path:
    if path.stat().st_size != expected_size:
        raise ValueError(f"{label} byte size mismatch: {path}")
    values = np.memmap(path, dtype=">f4", mode="r")
    finite = bool(np.all(np.isfinite(values)))
    del values
    if not finite:
        raise ValueError(f"{label} contains non-finite values: {path}")
    return path


def _resolve_geometry(
    *,
    project_root: Path,
    manifest: dict[str, object],
    manifest_key: str,
    override: Path | None,
    label: str,
) -> Path:
    declared_value = manifest.get(manifest_key)
    declared = (
        None
        if not isinstance(declared_value, str) or not declared_value
        else _path(project_root, declared_value, label)
    )
    explicit = (
        None
        if override is None
        else _path(project_root, override, f"explicit {label}")
    )
    if declared is None and explicit is None:
        raise ValueError(
            f"{manifest_key} is absent; an explicit {label} override is required"
        )
    if declared is not None and explicit is not None and declared != explicit:
        raise ValueError(f"explicit {label} conflicts with interferogram manifest")
    return declared or explicit  # type: ignore[return-value]


def _pair_list(
    path: Path,
    available: dict[str, tuple[GammaNetworkRecord, Path]],
) -> tuple[tuple[str, ...], str]:
    source = Path(path).expanduser()
    if source.is_symlink():
        raise ValueError(f"pair list must not be a symlink: {source}")
    source = source.resolve()
    if not source.is_file() or source.stat().st_size < 1:
        raise FileNotFoundError(f"pair list is missing or empty: {source}")
    raw = source.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"pair list must be UTF-8 text: {source}") from error
    selected: list[str] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        name = raw_line.split("#", 1)[0].strip()
        if not name:
            continue
        if _PAIR.fullmatch(name) is None:
            raise ValueError(f"invalid selected pair on line {line_number}: {name!r}")
        if name in selected:
            raise ValueError(f"duplicate selected pair on line {line_number}: {name}")
        if name not in available:
            raise ValueError(f"selected pair is unavailable: {name}")
        selected.append(name)
    if not selected:
        raise ValueError(f"pair list contains no selected pairs: {source}")
    return tuple(selected), hashlib.sha256(raw).hexdigest()


def load_gamma_time_series_inputs(
    *,
    project_root: Path,
    atmosphere_manifest: Path,
    pair_list: Path | None,
    lookup_table: Path | None,
    map_dem: Path | None,
    map_dem_parameter: Path | None,
) -> GammaTimeSeriesInputs:
    """Load one complete downstream contract without creating any output."""

    root = Path(project_root).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError(f"project_root is not a directory: {root}")
    atmosphere_path = _path(root, atmosphere_manifest, "atmosphere manifest")
    atmosphere, atmosphere_digest = _manifest(
        atmosphere_path, "atmosphere manifest"
    )
    _complete(atmosphere, "atmosphere manifest")
    case_id = atmosphere.get("case_id")
    method = atmosphere.get("method")
    if not isinstance(case_id, str) or not case_id:
        raise ValueError("atmosphere manifest case_id is required")
    if method not in {
        "none",
        "gamma_atm_mod_2d_auto",
        "gamma_atm_mod_2d_polygon",
        "gamma_fspf_atm_mod_2d",
    }:
        raise ValueError("atmosphere manifest method is invalid")
    grid = atmosphere.get("grid")
    if not isinstance(grid, dict):
        raise ValueError("atmosphere manifest grid is required")
    width, lines = grid.get("width"), grid.get("lines")
    if (
        not isinstance(width, int)
        or not isinstance(lines, int)
        or width <= 0
        or lines <= 0
    ):
        raise ValueError("atmosphere manifest grid is invalid")
    expected_size = width * lines * 4

    lineage: dict[str, tuple[Path, dict[str, object], str]] = {}
    for prefix in ("detrending", "unwrapping", "filtering", "interferogram"):
        lineage[prefix] = _lineage_manifest(
            project_root=root,
            atmosphere=atmosphere,
            prefix=prefix,
            case_id=case_id,
        )
    ifg_path, interferogram, ifg_digest = lineage["interferogram"]

    baseline_path = _path(
        root,
        interferogram.get("baseline_manifest_project_path"),
        "baseline manifest",
    )
    baseline, baseline_digest = _manifest(baseline_path, "baseline manifest")
    _complete(baseline, "baseline manifest", case_id)
    network = _path(
        root,
        baseline.get("network_path"),
        "baseline network",
        base=baseline_path.parent,
    )
    records = read_gamma_network_records(network)
    if baseline.get("pair_count") != len(records):
        raise ValueError("baseline manifest pair inventory is inconsistent")
    for record in records:
        if not math.isfinite(record.temporal_baseline_days) or record.temporal_baseline_days == 0:
            raise ValueError(f"temporal baseline must be finite and non-zero: {record.name}")
    records_by_name = {record.name: record for record in records}

    polarization = baseline.get("polarization")
    if not isinstance(polarization, str) or not polarization:
        raise ValueError("baseline manifest polarization is required")
    stack_path = _path(
        root,
        baseline.get("registered_stack_project_path"),
        "registered stack",
    )
    stack = read_registered_stack(
        stack_path, project_root=root, polarization=polarization
    )
    if baseline.get("stack_digest") != stack.source_digest:
        raise ValueError("baseline registered-stack digest does not match source")
    if interferogram.get("stack_digest") != stack.source_digest:
        raise ValueError("interferogram registered-stack digest does not match source")
    if _path(
        root,
        interferogram.get("registered_stack_project_path"),
        "interferogram registered stack",
    ) != stack.source_path:
        raise ValueError("interferogram registered-stack lineage is inconsistent")
    if interferogram.get("reference_date") != stack.reference_date:
        raise ValueError("interferogram reference date is inconsistent")

    raw_mli = interferogram.get("mli_assets")
    if not isinstance(raw_mli, list) or not raw_mli:
        raise ValueError("interferogram MLI inventory is missing")
    mli_by_date: dict[str, GammaMliAsset] = {}
    for item in raw_mli:
        if not isinstance(item, dict):
            raise ValueError("interferogram MLI item is invalid")
        date = item.get("date")
        if not isinstance(date, str) or date not in stack.dates or date in mli_by_date:
            raise ValueError("interferogram MLI date is invalid or duplicate")
        data = _path(
            root, item.get("data_path"), "MLI", base=ifg_path.parent
        )
        parameter = _path(
            root,
            item.get("parameter_path"),
            "MLI parameter",
            base=ifg_path.parent,
        )
        if (
            gamma_parameter(parameter, "range_samples") != width
            or gamma_parameter(parameter, "azimuth_lines") != lines
        ):
            raise ValueError(f"MLI grid differs from atmosphere grid: {date}")
        _float_raster(data, expected_size, "MLI")
        mli_by_date[date] = GammaMliAsset(date, data, parameter)
    if tuple(mli_by_date) != stack.dates:
        raise ValueError("interferogram MLI acquisition inventory is incomplete")

    radar = _float_raster(
        _path(
            root,
            interferogram.get("radar_height_project_path"),
            "radar height",
        ),
        expected_size,
        "radar height",
    )
    lookup = _resolve_geometry(
        project_root=root,
        manifest=interferogram,
        manifest_key="lookup_table_project_path",
        override=lookup_table,
        label="lookup_table",
    )
    resolved_map_dem = _resolve_geometry(
        project_root=root,
        manifest=interferogram,
        manifest_key="map_dem_segment_project_path",
        override=map_dem,
        label="map_dem",
    )
    resolved_map_parameter = _resolve_geometry(
        project_root=root,
        manifest=interferogram,
        manifest_key="map_dem_segment_parameter_project_path",
        override=map_dem_parameter,
        label="map_dem_parameter",
    )
    map_width = gamma_parameter(resolved_map_parameter, "width")
    map_lines = gamma_parameter(resolved_map_parameter, "nlines")
    _float_raster(
        resolved_map_dem, map_width * map_lines * 4, "map-grid DEM"
    )

    ifg_pairs = interferogram.get("pairs")
    if not isinstance(ifg_pairs, list):
        raise ValueError("interferogram pair inventory is missing")
    ifg_names = [
        item.get("pair") for item in ifg_pairs if isinstance(item, dict)
    ]
    if (
        len(ifg_names) != len(ifg_pairs)
        or len(set(ifg_names)) != len(ifg_names)
        or set(ifg_names) != set(records_by_name)
    ):
        raise ValueError("interferogram and baseline pair inventories differ")

    atmosphere_pairs = atmosphere.get("pairs")
    if not isinstance(atmosphere_pairs, list) or atmosphere.get("pair_count") != len(
        atmosphere_pairs
    ):
        raise ValueError("atmosphere pair inventory is incomplete")
    available: dict[str, tuple[GammaNetworkRecord, Path]] = {}
    atmosphere_order: list[str] = []
    for item in atmosphere_pairs:
        if not isinstance(item, dict):
            raise ValueError("atmosphere pair item is invalid")
        name = item.get("pair")
        if not isinstance(name, str) or _PAIR.fullmatch(name) is None:
            raise ValueError("atmosphere pair name is invalid")
        if name in available:
            raise ValueError(f"atmosphere manifest contains duplicate pair: {name}")
        record = records_by_name.get(name)
        if record is None:
            raise ValueError(f"atmosphere pair is absent from baseline network: {name}")
        corrected = _float_raster(
            _path(
                root,
                item.get("corrected_phase_project_path"),
                "corrected phase",
            ),
            expected_size,
            "corrected phase",
        )
        available[name] = (record, corrected)
        atmosphere_order.append(name)
    if not available:
        raise ValueError("atmosphere manifest contains no pairs")

    pair_list_digest = None
    pair_list_path = None
    if pair_list is None:
        selected_names = tuple(atmosphere_order)
    else:
        selected_names, pair_list_digest = _pair_list(pair_list, available)
        pair_list_path = Path(pair_list).expanduser().resolve()
    selected = tuple(
        GammaTimeSeriesPair(
            master=available[name][0].master,
            slave=available[name][0].slave,
            perpendicular_baseline=available[name][0].perpendicular_baseline,
            temporal_baseline_days=available[name][0].temporal_baseline_days,
            corrected_phase=available[name][1],
        )
        for name in selected_names
    )

    return GammaTimeSeriesInputs(
        project_root=root,
        case_id=case_id,
        atmosphere_method=method,
        atmosphere_manifest=atmosphere_path,
        atmosphere_manifest_digest=atmosphere_digest,
        interferogram_manifest=ifg_path,
        interferogram_manifest_digest=ifg_digest,
        baseline_manifest=baseline_path,
        baseline_manifest_digest=baseline_digest,
        registered_stack_manifest=stack.source_path,
        registered_stack_manifest_digest=stack.source_digest,
        lineage_manifest_digests=tuple(
            (name, value[2]) for name, value in lineage.items()
        ),
        pairs=selected,
        acquisition_dates=stack.dates,
        reference_date=stack.reference_date,
        width=width,
        lines=lines,
        mli_assets=tuple(mli_by_date[date] for date in stack.dates),
        radar_height=radar,
        lookup_table=lookup,
        map_dem=resolved_map_dem,
        map_dem_parameter=resolved_map_parameter,
        map_width=map_width,
        map_lines=map_lines,
        pair_list=pair_list_path,
        pair_list_digest=pair_list_digest,
    )


def _destination(path: Path, label: str) -> Path:
    target = Path(path)
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"{label} already exists: {target}")
    if not target.parent.is_dir():
        raise FileNotFoundError(
            f"{label} parent staging directory does not exist: {target.parent}"
        )
    return target


def write_gamma_diff_tab(
    inputs: GammaTimeSeriesInputs, destination: Path
) -> Path:
    """Write corrected phase and temporal-baseline rows in selected order."""

    target = _destination(destination, "diff_tab")
    target.write_text(
        "".join(
            f"{pair.corrected_phase} {pair.temporal_baseline_days:g}\n"
            for pair in inputs.pairs
        ),
        encoding="utf-8",
    )
    return target


def write_gamma_rmli_tab(
    inputs: GammaTimeSeriesInputs, destination: Path
) -> Path:
    """Write the complete ordered reference MLI inventory."""

    target = _destination(destination, "RMLI_tab")
    target.write_text(
        "".join(f"{asset.data} {asset.parameter}\n" for asset in inputs.mli_assets),
        encoding="utf-8",
    )
    return target


def write_gamma_itab(inputs: GammaTimeSeriesInputs, destination: Path) -> Path:
    """Map selected date pairs to one-based acquisition indices."""

    target = _destination(destination, "itab")
    indices = {date: index for index, date in enumerate(inputs.acquisition_dates, 1)}
    target.write_text(
        "".join(
            f"{indices[pair.master]} {indices[pair.slave]} {row} 1\n"
            for row, pair in enumerate(inputs.pairs, 1)
        ),
        encoding="utf-8",
    )
    return target


__all__ = [
    "GammaMliAsset",
    "GammaTimeSeriesInputs",
    "GammaTimeSeriesPair",
    "load_gamma_time_series_inputs",
    "write_gamma_diff_tab",
    "write_gamma_itab",
    "write_gamma_rmli_tab",
]
