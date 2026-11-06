"""Strict method-centric CFG loader for GAMMA stacking."""

from __future__ import annotations

import configparser
import math
import re
from pathlib import Path

from geodesy_analysis.common.case_paths import (
    bind_analysis_case,
    resolve_project_or_absolute_path,
)
from geodesy_analysis.common.product_layout import AnalysisProductLayout

from .models import GammaStackingCase

_CASE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
_DEFAULTS = {
    "reference_width": "15",
    "reference_height": "15",
    "display_min": "-0.06",
    "display_max": "0.06",
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
    "output_dir",
    "figure_dir",
    "log_dir",
}


def _unknown(section, source: Path, allowed: set[str]) -> None:
    unknown = sorted(set(section) - allowed)
    if unknown:
        raise ValueError(f"{source}: unknown key in [{section.name}]: {unknown[0]}")


def _path(paths, value: str, label: str, *, required: bool) -> Path | None:
    if not value:
        return None
    raw = Path(value).expanduser()
    candidate = raw if raw.is_absolute() else paths.project_root / raw
    if candidate.is_symlink():
        raise ValueError(f"{label} must not be a symlink: {candidate}")
    resolved = resolve_project_or_absolute_path(paths, value, label)
    if required and (not resolved.is_file() or resolved.stat().st_size < 1):
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


def load_gamma_stacking_config(
    path: Path, *, case_name: str | None = None
) -> tuple[GammaStackingCase, ...]:
    source = Path(path).expanduser().resolve(strict=True)
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    try:
        with source.open("r", encoding="utf-8") as stream:
            parser.read_file(stream)
    except configparser.Error as error:
        raise ValueError(f"invalid GAMMA stacking configuration {source}: {error}") from error
    if not parser.has_section("project"):
        raise ValueError(f"{source}: missing [project] section")
    _unknown(parser["project"], source, {"root"})
    root_value = parser["project"].get("root", "").strip()
    if not root_value:
        raise ValueError(f"{source}: [project] root is required")
    raw_root = Path(root_value).expanduser()
    root = (raw_root if raw_root.is_absolute() else source.parent / raw_root).resolve(
        strict=True
    )
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
    cases: list[GammaStackingCase] = []
    for section_name in sections:
        name = section_name.removeprefix("case:").strip()
        if not _CASE.fullmatch(name):
            raise ValueError(f"{source}: unsafe case name: {name!r}")
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
            )
            if not values.get(key)
        ]
        if not project_value:
            missing.append("project/case_root")
        if missing:
            raise ValueError(f"{source}: [{section_name}] missing keys: {', '.join(missing)}")
        paths = bind_analysis_case(root, name, project_value, values["processing_root"])
        layout = AnalysisProductLayout(paths)
        atmosphere = _path(paths, values["atmosphere_manifest"], "atmosphere manifest", required=True)
        assert atmosphere is not None
        pair_list = _path(paths, values.get("pair_list", ""), "pair list", required=True)
        lookup = _path(paths, values.get("lookup_table", ""), "lookup table", required=True)
        dem = _path(paths, values.get("map_dem", ""), "map DEM", required=True)
        dem_parameter = _path(
            paths, values.get("map_dem_parameter", ""), "map DEM parameter", required=True
        )
        reference_range = _integer(source, "reference_range", values["reference_range"], positive=False)
        reference_azimuth = _integer(source, "reference_azimuth", values["reference_azimuth"], positive=False)
        reference_width = _integer(source, "reference_width", values["reference_width"], positive=True)
        reference_height = _integer(source, "reference_height", values["reference_height"], positive=True)
        try:
            display_min = float(values["display_min"])
            display_max = float(values["display_max"])
        except ValueError as error:
            raise ValueError(f"{source}: display limits must be finite numbers") from error
        if not all(math.isfinite(value) for value in (display_min, display_max)) or display_min >= display_max:
            raise ValueError(f"{source}: display_min must be smaller than display_max")
        colormap = values["colormap"]
        if not _TOKEN.fullmatch(colormap):
            raise ValueError(f"{source}: colormap is unsafe")
        output = _path(
            paths,
            values.get("output_dir", "") or layout.serialize(layout.product("TIMESERIES", "STACKING")),
            "stacking output",
            required=False,
        )
        figures = _path(
            paths,
            values.get("figure_dir", "") or layout.serialize(layout.figures("TIMESERIES", "STACKING")),
            "stacking figures",
            required=False,
        )
        logs = _path(
            paths,
            values.get("log_dir", "") or layout.serialize(layout.logs("TIMESERIES", "STACKING")),
            "stacking logs",
            required=False,
        )
        assert output is not None and figures is not None and logs is not None
        inputs = tuple(
            value
            for value in (atmosphere, pair_list, lookup, dem, dem_parameter)
            if value is not None
        )
        layout.require_disjoint(science=output, figures=figures, logs=logs, inputs=inputs)
        cases.append(
            GammaStackingCase(
                paths,
                atmosphere,
                pair_list,
                lookup,
                dem,
                dem_parameter,
                reference_range,
                reference_azimuth,
                reference_width,
                reference_height,
                display_min,
                display_max,
                colormap,
                output,
                figures,
                logs,
            )
        )
    if not cases:
        raise ValueError(f"{source}: at least one [case:name] is required")
    return tuple(cases)


__all__ = ["load_gamma_stacking_config"]
