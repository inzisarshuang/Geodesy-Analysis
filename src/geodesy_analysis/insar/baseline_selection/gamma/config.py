"""Strict project configuration for GAMMA baseline selection."""

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

from .models import GammaBaselineCase

_CASE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
_POLARIZATION = re.compile(r"[A-Z][A-Z0-9]*\Z")
_VALUE_KEYS = {
    "case_root",
    "registered_stack",
    "polarization",
    "network_type",
    "max_perpendicular_baseline",
    "max_temporal_baseline",
    "output_dir",
}
_DEFAULT_KEYS = _VALUE_KEYS - {"case_root"}
_BUILTIN_DEFAULTS = {
    "network_type": "SBAS",
    "max_perpendicular_baseline": "300",
    "max_temporal_baseline": "100",
}


def _unknown(
    section: configparser.SectionProxy,
    source: Path,
    allowed: set[str] = _VALUE_KEYS,
) -> None:
    unknown = sorted(set(section) - allowed)
    if unknown:
        raise ValueError(f"{source}: unknown key in [{section.name}]: {unknown[0]}")


def _positive_float(value: str, key: str, source: Path) -> float:
    try:
        parsed = float(value)
    except ValueError as error:
        raise ValueError(f"{source}: {key} must be a positive finite number") from error
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError(f"{source}: {key} must be a positive finite number")
    return parsed


def load_gamma_baseline_config(path: Path) -> tuple[GammaBaselineCase, ...]:
    """Read ordered GAMMA baseline cases from one strict project CFG."""

    source = Path(path).expanduser().resolve(strict=True)
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    try:
        with source.open("r", encoding="utf-8") as stream:
            parser.read_file(stream)
    except configparser.Error as error:
        raise ValueError(f"invalid GAMMA baseline configuration {source}: {error}") from error
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
        defaults.update(
            (key, value.strip()) for key, value in parser["defaults"].items()
        )

    cases: list[GammaBaselineCase] = []
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
        required = ("case_root", "registered_stack", "polarization", "output_dir")
        missing = [key for key in required if not values.get(key)]
        if missing:
            raise ValueError(
                f"{source}: [{section_name}] missing keys: {', '.join(missing)}"
            )

        polarization = values["polarization"].upper()
        if not _POLARIZATION.fullmatch(polarization):
            raise ValueError(f"{source}: polarization must be an uppercase label")
        network_type = values["network_type"].upper()
        if network_type not in {"DSI", "SBAS", "PSI"}:
            raise ValueError(f"{source}: network_type must be DSI, SBAS, or PSI")
        paths = bind_analysis_case(root, name, values["case_root"])
        registered_stack = resolve_case_input(
            paths, values["registered_stack"]
        )
        expected_stack = (
            paths.case_root
            / "PRE"
            / "GAMMA"
            / "RSLC_SUBSET"
            / "registered_stack.json"
        ).resolve()
        if registered_stack != expected_stack:
            raise ValueError(
                f"{source}: registered_stack must be the canonical case PRE input: "
                f"{expected_stack}"
            )
        output_dir = resolve_case_output(paths, values["output_dir"])
        expected_output = (
            paths.case_root / "ANALYSIS" / "BASELINE_SELECTION" / "GAMMA"
        ).resolve()
        if output_dir != expected_output:
            raise ValueError(
                f"{source}: output_dir must be the canonical baseline output: "
                f"{expected_output}"
            )
        cases.append(
            GammaBaselineCase(
                paths=paths,
                registered_stack=registered_stack,
                polarization=polarization,
                network_type=network_type,
                max_perpendicular_baseline=_positive_float(
                    values["max_perpendicular_baseline"],
                    "max_perpendicular_baseline",
                    source,
                ),
                max_temporal_baseline=_positive_float(
                    values["max_temporal_baseline"],
                    "max_temporal_baseline",
                    source,
                ),
                output_dir=output_dir,
            )
        )
    if not cases:
        raise ValueError(f"{source}: at least one [case:name] section is required")
    return tuple(cases)


def select_gamma_baseline_case(
    cases: Sequence[GammaBaselineCase], name: str | None
) -> GammaBaselineCase:
    """Select one named case, allowing omission only for a single-case CFG."""

    if name is None:
        if len(cases) != 1:
            raise ValueError("--case is required when configuration has multiple cases")
        return cases[0]
    for case in cases:
        if case.name == name:
            return case
    raise ValueError(f"unknown case: {name}")


__all__ = ["load_gamma_baseline_config", "select_gamma_baseline_case"]
