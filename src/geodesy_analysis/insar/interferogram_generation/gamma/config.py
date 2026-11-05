"""Strict project configuration for GAMMA interferogram generation."""

from __future__ import annotations

import configparser
import math
import re
from collections.abc import Sequence
from pathlib import Path

from geodesy_analysis.common.case_paths import (
    AnalysisCasePaths,
    bind_analysis_case,
    resolve_case_input,
    resolve_output_path,
    resolve_project_input,
)
from geodesy_analysis.common.product_layout import AnalysisProductLayout

from .models import GammaGeocodingConfig, GammaInterferogramCase

_CASE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
_POLARIZATION = re.compile(r"[A-Z][A-Z0-9]*\Z")
_VALUE_KEYS = {
    "project",
    "case_root",
    "processing_root",
    "registered_stack",
    "baseline_manifest",
    "geocoding_config",
    "polarization",
    "range_looks",
    "azimuth_looks",
    "spectral_filter",
    "create_offset_range_start",
    "create_offset_azimuth_start",
    "create_offset_range_window",
    "create_offset_azimuth_window",
    "create_offset_range_search",
    "create_offset_azimuth_search",
    "create_offset_correlation_threshold",
    "coherence_range_window",
    "coherence_azimuth_window",
    "coherence_estimator",
    "output_dir",
    "visualization_dir",
    "figure_dir",
}
_DEFAULT_KEYS = _VALUE_KEYS - {"project", "case_root", "processing_root"}
_BUILTIN_DEFAULTS = {
    "spectral_filter": "auto",
    "create_offset_range_start": "0",
    "create_offset_azimuth_start": "0",
    "create_offset_range_window": "32",
    "create_offset_azimuth_window": "32",
    "create_offset_range_search": "64",
    "create_offset_azimuth_search": "64",
    "create_offset_correlation_threshold": "0.35",
    "coherence_range_window": "5",
    "coherence_azimuth_window": "5",
    "coherence_estimator": "2",
}


def _unknown(
    section: configparser.SectionProxy,
    source: Path,
    allowed: set[str] = _VALUE_KEYS,
) -> None:
    unknown = sorted(set(section) - allowed)
    if unknown:
        raise ValueError(f"{source}: unknown key in [{section.name}]: {unknown[0]}")


def _integer(value: str, key: str, source: Path) -> int:
    try:
        return int(value)
    except ValueError as error:
        raise ValueError(f"{source}: {key} must be an integer") from error


def _positive_integer(value: str, key: str, source: Path) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise ValueError(f"{source}: {key} must be a positive integer") from error
    if parsed <= 0:
        raise ValueError(f"{source}: {key} must be a positive integer")
    return parsed


def _closed_unit_float(value: str, key: str, source: Path) -> float:
    try:
        parsed = float(value)
    except ValueError as error:
        raise ValueError(f"{source}: {key} must be within [0, 1]") from error
    if not math.isfinite(parsed) or not 0 <= parsed <= 1:
        raise ValueError(f"{source}: {key} must be within [0, 1]")
    return parsed


def _overlaps(first: Path, second: Path) -> bool:
    left = first.resolve()
    right = second.resolve()
    return left == right or left in right.parents or right in left.parents


def _load_geocoding_config(
    path: Path,
    *,
    paths: AnalysisCasePaths,
    case_name: str,
) -> GammaGeocodingConfig:
    source = resolve_project_input(paths, path)
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    try:
        with source.open("r", encoding="utf-8") as stream:
            parser.read_file(stream)
    except configparser.Error as error:
        raise ValueError(f"invalid GAMMA geocoding configuration {source}: {error}") from error
    if not parser.has_section("project"):
        raise ValueError(f"{source}: missing [project] section")
    _unknown(parser["project"], source, {"root"})
    root_text = parser["project"].get("root", "").strip()
    if not root_text:
        raise ValueError(f"{source}: [project] root is required")
    declared_root = Path(root_text).expanduser()
    if not declared_root.is_absolute():
        declared_root = source.parent / declared_root
    if declared_root.resolve(strict=True) != paths.project_root:
        raise ValueError(
            f"{source}: geocoding project root does not match interferogram project"
        )

    defaults = {
        "correlation_threshold": "0.2",
        "polynomial_parameters": "1",
        "range_window": "128",
        "azimuth_window": "128",
        "area_factor": "1.0",
    }
    allowed = {
        "dem",
        "dem_par",
        "output_dir",
        *defaults,
    }
    if parser.has_section("defaults"):
        _unknown(parser["defaults"], source, allowed)
        defaults.update(
            (key, value.strip())
            for key, value in parser["defaults"].items()
            if key in defaults
        )
    section_name = f"case:{case_name}"
    if not parser.has_section(section_name):
        raise ValueError(f"{source}: missing [{section_name}] section")
    section = parser[section_name]
    _unknown(section, source, allowed)
    values = dict(defaults)
    values.update((key, value.strip()) for key, value in section.items())
    missing = [key for key in ("dem", "dem_par") if not values.get(key)]
    if not values.get("output_dir") and paths.processing_root is None:
        missing.append("output_dir")
    if missing:
        raise ValueError(
            f"{source}: [{section_name}] missing keys: {', '.join(missing)}"
        )

    dem = resolve_project_input(paths, values["dem"])
    dem_par = resolve_project_input(paths, values["dem_par"])
    if not dem.is_file() or dem.stat().st_size == 0:
        raise ValueError(f"{source}: DEM must be a non-empty file: {dem}")
    if not dem_par.is_file() or dem_par.stat().st_size == 0:
        raise ValueError(f"{source}: DEM parameter must be a non-empty file: {dem_par}")
    if dem_par.name != f"{dem.name}.par":
        raise ValueError(f"{source}: DEM and DEM parameter filenames must be paired")

    try:
        area_factor = float(values["area_factor"])
    except ValueError as error:
        raise ValueError(f"{source}: area_factor must be positive and finite") from error
    if not math.isfinite(area_factor) or area_factor <= 0:
        raise ValueError(f"{source}: area_factor must be positive and finite")
    polynomial = _positive_integer(
        values["polynomial_parameters"], "polynomial_parameters", source
    )
    if polynomial not in {1, 3, 4, 6}:
        raise ValueError(f"{source}: polynomial_parameters must be 1, 3, 4 or 6")

    layout = (
        AnalysisProductLayout(paths) if paths.processing_root is not None else None
    )
    geocoding_output = (
        resolve_output_path(paths, values["output_dir"])
        if values.get("output_dir", "").strip()
        else layout.product("GEOCODING")  # type: ignore[union-attr]
    )
    return GammaGeocodingConfig(
        config_path=source,
        dem=dem,
        dem_par=dem_par,
        output_dir=geocoding_output,
        correlation_threshold=_closed_unit_float(
            values["correlation_threshold"], "correlation_threshold", source
        ),
        polynomial_parameters=polynomial,
        range_window=_positive_integer(values["range_window"], "range_window", source),
        azimuth_window=_positive_integer(
            values["azimuth_window"], "azimuth_window", source
        ),
        area_factor=area_factor,
    )


def load_gamma_interferogram_config(
    path: Path, *, case_name: str | None = None
) -> tuple[GammaInterferogramCase, ...]:
    """Read ordered cases, optionally validating only the requested case."""

    source = Path(path).expanduser().resolve(strict=True)
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    try:
        with source.open("r", encoding="utf-8") as stream:
            parser.read_file(stream)
    except configparser.Error as error:
        raise ValueError(
            f"invalid GAMMA interferogram configuration {source}: {error}"
        ) from error
    if not parser.has_section("project"):
        raise ValueError(f"{source}: missing [project] section")
    project = parser["project"]
    unknown_project = sorted(set(project) - {"root"})
    if unknown_project:
        raise ValueError(f"{source}: unknown key in [project]: {unknown_project[0]}")
    root_text = project.get("root", "").strip()
    if not root_text:
        raise ValueError(f"{source}: [project] root is required")
    root_value = Path(root_text).expanduser()
    root = (root_value if root_value.is_absolute() else source.parent / root_value).resolve(
        strict=True
    )
    if not root.is_dir():
        raise ValueError(f"{source}: project root is not a directory: {root}")

    defaults = dict(_BUILTIN_DEFAULTS)
    if parser.has_section("defaults"):
        _unknown(parser["defaults"], source, _DEFAULT_KEYS)
        defaults.update((key, value.strip()) for key, value in parser["defaults"].items())

    case_sections = [
        section_name
        for section_name in parser.sections()
        if section_name.startswith("case:")
    ]
    if case_name is not None:
        selected_section = next(
            (
                section_name
                for section_name in case_sections
                if section_name.removeprefix("case:").strip() == case_name
            ),
            None,
        )
        if selected_section is None:
            raise ValueError(f"unknown case: {case_name}")
        case_sections = [selected_section]

    cases: list[GammaInterferogramCase] = []
    required = (
        "registered_stack",
        "baseline_manifest",
        "geocoding_config",
        "polarization",
        "range_looks",
        "azimuth_looks",
    )
    for section_name in parser.sections():
        if section_name in {"project", "defaults"}:
            continue
        if not section_name.startswith("case:"):
            raise ValueError(f"{source}: unsupported section [{section_name}]")
        if section_name not in case_sections:
            continue
        name = section_name.removeprefix("case:").strip()
        if not _CASE_NAME.fullmatch(name):
            raise ValueError(f"{source}: unsafe or empty case name: {name!r}")
        section = parser[section_name]
        _unknown(section, source)
        values = dict(defaults)
        values.update((key, value.strip()) for key, value in section.items())
        missing = [key for key in required if not values.get(key)]
        project_value = values.get("project", "") or values.get("case_root", "")
        if not project_value:
            missing.append("project/case_root")
        if not values.get("output_dir") and not values.get("processing_root"):
            missing.append("output_dir")
        if missing:
            raise ValueError(
                f"{source}: [{section_name}] missing keys: {', '.join(missing)}"
            )

        polarization = values["polarization"].upper()
        if not _POLARIZATION.fullmatch(polarization):
            raise ValueError(f"{source}: polarization must be an uppercase label")
        spectral_filter = values["spectral_filter"].lower()
        if spectral_filter not in {"auto", "on", "off"}:
            raise ValueError(f"{source}: spectral_filter must be auto, on, or off")

        processing_value = values.get("processing_root", "").strip() or None
        paths = bind_analysis_case(root, name, project_value, processing_value)
        layout = AnalysisProductLayout(paths) if processing_value is not None else None
        registered_stack = resolve_case_input(paths, values["registered_stack"])
        expected_stacks = (
            {
                layout.product("RSLC", "registered_stack.json").resolve(),
                layout.product("RSLC", "SUBSET", "registered_stack.json").resolve(),
            }
            if layout is not None
            else {
                (paths.case_root / "PRE/GAMMA/RSLC/registered_stack.json").resolve(),
                (paths.case_root / "PRE/GAMMA/RSLC_SUBSET/registered_stack.json").resolve(),
            }
        )
        if registered_stack not in expected_stacks:
            raise ValueError(
                f"{source}: registered_stack must be a canonical case PRE input: "
                f"{', '.join(str(path) for path in sorted(expected_stacks))}"
            )
        baseline_manifest = resolve_case_input(paths, values["baseline_manifest"])
        expected_baseline = (
            layout.product("BASELINE", "baseline_manifest.json").resolve()
            if layout is not None
            else (
                paths.case_root
                / "ANALYSIS/BASELINE_SELECTION/GAMMA/baseline_manifest.json"
            ).resolve()
        )
        if baseline_manifest != expected_baseline:
            raise ValueError(
                f"{source}: baseline_manifest must be the canonical baseline input: "
                f"{expected_baseline}"
            )
        geocoding = _load_geocoding_config(
            resolve_project_input(paths, values["geocoding_config"]),
            paths=paths,
            case_name=name,
        )
        output_dir = (
            resolve_output_path(paths, values["output_dir"])
            if values.get("output_dir", "").strip()
            else layout.product("INTF")  # type: ignore[union-attr]
        )
        figure_value = (
            values.get("figure_dir", "").strip()
            or values.get("visualization_dir", "").strip()
        )
        visualization_dir = resolve_output_path(
            paths,
            figure_value
            or (
                layout.serialize(layout.figures("INTF"))
                if layout is not None
                else f"{paths.case_id}/VISUALIZATION/INTERFEROGRAM_GENERATION/GAMMA"
            ),
        )
        protected_inputs = (
            registered_stack,
            baseline_manifest,
            geocoding.dem,
            geocoding.dem_par,
            geocoding.config_path,
        )
        for output in (output_dir, geocoding.output_dir, visualization_dir):
            for input_path in protected_inputs:
                if _overlaps(output, input_path):
                    raise ValueError(
                        f"output directory overlaps an input/configuration file: "
                        f"{output} overlaps {input_path}"
                    )
        if _overlaps(output_dir, geocoding.output_dir):
            raise ValueError("interferogram and geocoding output directories overlap")
        if _overlaps(output_dir, visualization_dir):
            raise ValueError("interferogram and visualization output directories overlap")
        if _overlaps(geocoding.output_dir, visualization_dir):
            raise ValueError("geocoding and visualization output directories overlap")

        cases.append(
            GammaInterferogramCase(
                paths=paths,
                registered_stack=registered_stack,
                baseline_manifest=baseline_manifest,
                geocoding=geocoding,
                polarization=polarization,
                range_looks=_positive_integer(values["range_looks"], "range_looks", source),
                azimuth_looks=_positive_integer(values["azimuth_looks"], "azimuth_looks", source),
                spectral_filter=spectral_filter,
                create_offset_range_start=_integer(
                    values["create_offset_range_start"], "create_offset_range_start", source
                ),
                create_offset_azimuth_start=_integer(
                    values["create_offset_azimuth_start"], "create_offset_azimuth_start", source
                ),
                create_offset_range_window=_positive_integer(
                    values["create_offset_range_window"], "create_offset_range_window", source
                ),
                create_offset_azimuth_window=_positive_integer(
                    values["create_offset_azimuth_window"], "create_offset_azimuth_window", source
                ),
                create_offset_range_search=_positive_integer(
                    values["create_offset_range_search"], "create_offset_range_search", source
                ),
                create_offset_azimuth_search=_positive_integer(
                    values["create_offset_azimuth_search"], "create_offset_azimuth_search", source
                ),
                create_offset_correlation_threshold=_closed_unit_float(
                    values["create_offset_correlation_threshold"],
                    "create_offset_correlation_threshold",
                    source,
                ),
                coherence_range_window=_positive_integer(
                    values["coherence_range_window"], "coherence_range_window", source
                ),
                coherence_azimuth_window=_positive_integer(
                    values["coherence_azimuth_window"], "coherence_azimuth_window", source
                ),
                coherence_estimator=_positive_integer(
                    values["coherence_estimator"], "coherence_estimator", source
                ),
                output_dir=output_dir,
                visualization_dir=visualization_dir,
            )
        )
    if not cases:
        raise ValueError(f"{source}: at least one [case:name] section is required")
    return tuple(cases)


def select_gamma_interferogram_case(
    cases: Sequence[GammaInterferogramCase], name: str | None
) -> GammaInterferogramCase:
    """Select one named case, allowing omission for a single-case CFG."""

    if name is None:
        if len(cases) != 1:
            raise ValueError("--case is required when configuration has multiple cases")
        return cases[0]
    for case in cases:
        if case.name == name:
            return case
    raise ValueError(f"unknown case: {name}")


__all__ = ["load_gamma_interferogram_config", "select_gamma_interferogram_case"]
