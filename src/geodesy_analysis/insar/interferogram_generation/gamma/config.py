"""Strict project configuration for GAMMA interferogram generation."""

from __future__ import annotations

import configparser
import math
import re
from collections.abc import Sequence
from pathlib import Path

from geodesy_analysis.common.case_paths import (
    bind_analysis_case,
    resolve_case_input,
    resolve_case_output,
)

from .models import GammaInterferogramCase

_CASE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
_POLARIZATION = re.compile(r"[A-Z][A-Z0-9]*\Z")
_VALUE_KEYS = {
    "case_root",
    "registered_stack",
    "baseline_manifest",
    "polarization",
    "range_looks",
    "azimuth_looks",
    "radar_height",
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
}
_DEFAULT_KEYS = _VALUE_KEYS - {"case_root"}
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


def load_gamma_interferogram_config(path: Path) -> tuple[GammaInterferogramCase, ...]:
    """Read ordered, project-confined GAMMA interferogram cases."""

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

    cases: list[GammaInterferogramCase] = []
    required = (
        "case_root",
        "registered_stack",
        "baseline_manifest",
        "polarization",
        "range_looks",
        "azimuth_looks",
        "radar_height",
        "output_dir",
    )
    for section_name in parser.sections():
        if section_name in {"project", "defaults"}:
            continue
        if not section_name.startswith("case:"):
            raise ValueError(f"{source}: unsupported section [{section_name}]")
        name = section_name.removeprefix("case:").strip()
        if not _CASE_NAME.fullmatch(name):
            raise ValueError(f"{source}: unsafe or empty case name: {name!r}")
        section = parser[section_name]
        _unknown(section, source)
        values = dict(defaults)
        values.update((key, value.strip()) for key, value in section.items())
        missing = [key for key in required if not values.get(key)]
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

        paths = bind_analysis_case(root, name, values["case_root"])
        registered_stack = resolve_case_input(paths, values["registered_stack"])
        expected_stack = (
            paths.case_root
            / "PRE/GAMMA/RSLC_SUBSET/registered_stack.json"
        ).resolve()
        if registered_stack != expected_stack:
            raise ValueError(
                f"{source}: registered_stack must be the canonical case PRE input: "
                f"{expected_stack}"
            )
        baseline_manifest = resolve_case_input(paths, values["baseline_manifest"])
        expected_baseline = (
            paths.case_root / "ANALYSIS/GAMMA/BASELINE/baseline_manifest.json"
        ).resolve()
        if baseline_manifest != expected_baseline:
            raise ValueError(
                f"{source}: baseline_manifest must be the canonical baseline input: "
                f"{expected_baseline}"
            )
        radar_height = resolve_case_input(paths, values["radar_height"])
        geometry_root = (paths.case_root / "PRE/GAMMA/GEOMETRY").resolve()
        try:
            radar_height.relative_to(geometry_root)
        except ValueError as error:
            raise ValueError(
                f"{source}: radar_height must be below case PRE/GAMMA/GEOMETRY"
            ) from error
        output_dir = resolve_case_output(paths, values["output_dir"])
        expected_output = (
            paths.case_root / "ANALYSIS/GAMMA/INTERFEROGRAM"
        ).resolve()
        if output_dir != expected_output:
            raise ValueError(
                f"{source}: output_dir must be the canonical interferogram output: "
                f"{expected_output}"
            )

        cases.append(
            GammaInterferogramCase(
                paths=paths,
                registered_stack=registered_stack,
                baseline_manifest=baseline_manifest,
                polarization=polarization,
                range_looks=_positive_integer(values["range_looks"], "range_looks", source),
                azimuth_looks=_positive_integer(values["azimuth_looks"], "azimuth_looks", source),
                radar_height=radar_height,
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
