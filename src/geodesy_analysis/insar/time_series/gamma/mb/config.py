"""Strict method-centric CFG loader for GAMMA mb."""

from __future__ import annotations

import configparser
import math
import os
import re
from pathlib import Path

from geodesy_analysis.common.case_paths import (
    bind_analysis_case,
    resolve_project_or_absolute_path,
)
from geodesy_analysis.common.product_layout import AnalysisProductLayout

from .models import GammaMbCase

_CASE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
_DEFAULTS = {
    "mb_mode": "1",
    "gamma": "0.5",
    "dtmax": "70",
    "generate_mean_geocoded": "true",
    "generate_displacement": "true",
    "generate_geocoded_displacement": "true",
    "display_min": "-0.05",
    "display_max": "0.05",
    "colormap": "hls.cm",
}
_KEYS = set(_DEFAULTS) | {
    "project",
    "case_root",
    "processing_root",
    "atmosphere_manifest",
    "pair_list",
    "lookup_table",
    "map_dem",
    "map_dem_parameter",
    "reference_range",
    "reference_azimuth",
    "reference_width",
    "reference_height",
    "visdt_pwr",
    "output_dir",
    "figure_dir",
    "log_dir",
}


def _unknown(section, source: Path, allowed: set[str]) -> None:
    unknown = sorted(set(section) - allowed)
    if unknown:
        raise ValueError(f"{source}: unknown key in [{section.name}]: {unknown[0]}")


def _path(paths, value: str, label: str, *, input_file: bool) -> Path | None:
    if not value:
        return None
    raw = Path(value).expanduser()
    candidate = raw if raw.is_absolute() else paths.project_root / raw
    if candidate.is_symlink():
        raise ValueError(f"{label} must not be a symlink: {candidate}")
    resolved = resolve_project_or_absolute_path(paths, value, label)
    if input_file and (not resolved.is_file() or resolved.stat().st_size < 1):
        raise FileNotFoundError(f"{label} is missing or empty: {resolved}")
    return resolved


def _integer(source: Path, key: str, value: str, *, positive: bool) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        requirement = "positive" if positive else "non-negative"
        raise ValueError(f"{source}: {key} must be a {requirement} integer") from error
    if (positive and parsed <= 0) or (not positive and parsed < 0):
        requirement = "positive" if positive else "non-negative"
        raise ValueError(f"{source}: {key} must be a {requirement} integer")
    return parsed


def _positive_float(source: Path, key: str, value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as error:
        raise ValueError(f"{source}: {key} must be positive") from error
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError(f"{source}: {key} must be positive")
    return parsed


def _boolean(source: Path, key: str, value: str) -> bool:
    normalized = value.casefold()
    if normalized not in {"true", "false"}:
        raise ValueError(f"{source}: {key} must be true or false")
    return normalized == "true"


def load_gamma_mb_config(
    path: Path, *, case_name: str | None = None
) -> tuple[GammaMbCase, ...]:
    source = Path(path).expanduser().resolve(strict=True)
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    try:
        with source.open("r", encoding="utf-8") as stream:
            parser.read_file(stream)
    except configparser.Error as error:
        raise ValueError(f"invalid GAMMA mb configuration {source}: {error}") from error
    if not parser.has_section("project"):
        raise ValueError(f"{source}: missing [project] section")
    _unknown(parser["project"], source, {"root"})
    root_value = parser["project"].get("root", "").strip()
    if not root_value:
        raise ValueError(f"{source}: project root is required")
    raw_root = Path(root_value).expanduser()
    root = (raw_root if raw_root.is_absolute() else source.parent / raw_root).resolve(strict=True)
    defaults = dict(_DEFAULTS)
    if parser.has_section("defaults"):
        _unknown(parser["defaults"], source, set(_DEFAULTS))
        defaults.update((key, value.strip()) for key, value in parser["defaults"].items())
    sections = [name for name in parser.sections() if name not in {"project", "defaults"}]
    if any(not name.startswith("case:") for name in sections):
        raise ValueError(f"{source}: unsupported section")
    if case_name is not None:
        selected = f"case:{case_name}"
        if selected not in sections:
            raise ValueError(f"unknown case: {case_name}")
        sections = [selected]
    cases: list[GammaMbCase] = []
    for section_name in sections:
        name = section_name.removeprefix("case:").strip()
        if not _CASE.fullmatch(name):
            raise ValueError(f"{source}: unsafe case name")
        section = parser[section_name]
        _unknown(section, source, _KEYS)
        values = dict(defaults)
        values.update((key, value.strip()) for key, value in section.items())
        project_value = values.get("project", "") or values.get("case_root", "")
        missing = [
            key
            for key in (
                "processing_root",
                "atmosphere_manifest",
                "reference_range",
                "reference_azimuth",
                "reference_width",
                "reference_height",
            )
            if not values.get(key)
        ]
        if not project_value:
            missing.append("project/case_root")
        if missing:
            raise ValueError(f"{source}: [{section_name}] missing keys: {', '.join(missing)}")
        paths = bind_analysis_case(root, name, project_value, values["processing_root"])
        layout = AnalysisProductLayout(paths)
        atmosphere = _path(paths, values["atmosphere_manifest"], "atmosphere manifest", input_file=True)
        assert atmosphere is not None
        pair_list = _path(paths, values.get("pair_list", ""), "pair list", input_file=True)
        lookup = _path(paths, values.get("lookup_table", ""), "lookup table", input_file=True)
        dem = _path(paths, values.get("map_dem", ""), "map DEM", input_file=True)
        dem_parameter = _path(paths, values.get("map_dem_parameter", ""), "map DEM parameter", input_file=True)
        mb_mode = _integer(source, "mb_mode", values["mb_mode"], positive=True)
        if mb_mode not in {1, 2}:
            raise ValueError(f"{source}: mb_mode must be 1 or 2")
        reference_range = _integer(source, "reference_range", values["reference_range"], positive=False)
        reference_azimuth = _integer(source, "reference_azimuth", values["reference_azimuth"], positive=False)
        reference_width = _integer(source, "reference_width", values["reference_width"], positive=True)
        reference_height = _integer(source, "reference_height", values["reference_height"], positive=True)
        gamma = _positive_float(source, "gamma", values["gamma"])
        dtmax = _positive_float(source, "dtmax", values["dtmax"])
        mean_geo = _boolean(source, "generate_mean_geocoded", values["generate_mean_geocoded"])
        displacement = _boolean(source, "generate_displacement", values["generate_displacement"])
        displacement_geo = _boolean(
            source,
            "generate_geocoded_displacement",
            values["generate_geocoded_displacement"],
        )
        if displacement_geo and not displacement:
            raise ValueError("generate_geocoded_displacement requires generate_displacement")
        try:
            display_min = float(values["display_min"])
            display_max = float(values["display_max"])
        except ValueError as error:
            raise ValueError(f"{source}: display limits must be finite") from error
        if not all(math.isfinite(value) for value in (display_min, display_max)) or display_min >= display_max:
            raise ValueError(f"{source}: display_min must be smaller than display_max")
        colormap = values["colormap"]
        if not _TOKEN.fullmatch(colormap):
            raise ValueError(f"{source}: unsafe colormap")
        visdt = _path(paths, values.get("visdt_pwr", ""), "visdt_pwr", input_file=True)
        if visdt is not None and visdt.name != "visdt_pwr.py":
            raise ValueError(f"visdt_pwr must name the executable visdt_pwr.py: {visdt}")
        if visdt is not None and not os.access(visdt, os.X_OK):
            raise ValueError(f"visdt_pwr must be executable: {visdt}")
        output = _path(
            paths,
            values.get("output_dir", "") or layout.serialize(layout.product("TIMESERIES", "GAMMA_MB")),
            "GAMMA mb output",
            input_file=False,
        )
        figures = _path(
            paths,
            values.get("figure_dir", "") or layout.serialize(layout.figures("TIMESERIES", "GAMMA_MB")),
            "GAMMA mb figures",
            input_file=False,
        )
        logs = _path(
            paths,
            values.get("log_dir", "") or layout.serialize(layout.logs("TIMESERIES", "GAMMA_MB")),
            "GAMMA mb logs",
            input_file=False,
        )
        assert output is not None and figures is not None and logs is not None
        protected = tuple(
            value
            for value in (atmosphere, pair_list, lookup, dem, dem_parameter, visdt)
            if value is not None
        )
        layout.require_disjoint(science=output, figures=figures, logs=logs, inputs=protected)
        cases.append(
            GammaMbCase(
                paths,
                atmosphere,
                pair_list,
                lookup,
                dem,
                dem_parameter,
                mb_mode,
                reference_range,
                reference_azimuth,
                reference_width,
                reference_height,
                gamma,
                dtmax,
                mean_geo,
                displacement,
                displacement_geo,
                display_min,
                display_max,
                colormap,
                visdt,
                output,
                figures,
                logs,
            )
        )
    if not cases:
        raise ValueError(f"{source}: at least one [case:name] is required")
    return tuple(cases)


__all__ = ["load_gamma_mb_config"]
